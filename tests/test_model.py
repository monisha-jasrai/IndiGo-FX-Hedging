import copy

import numpy as np
import pytest

from fxhedge import pricing as px
from fxhedge.analysis import backtest, monte_carlo, scenario_grid, simulate_paths
from fxhedge.model import STRATEGIES, exposure, load_config, price_book, total_cost_inr, translation, unit_costs

CFG = load_config()


def test_exposure_adds_up():
    ex = exposure(CFG)
    c, s = CFG["company"], CFG["market"]["spot"]
    assert ex["fuel_usd"] == pytest.approx(c["fuel_inr"] * c["fuel_usd_linked"] * 10 / s)
    assert ex["net_usd"] == pytest.approx(ex["fuel_usd"] + c["lease_maint_usd"] + c["other_usd"] - ex["fx_revenue_usd"])
    assert ex["monthly_usd"].sum() == pytest.approx(ex["net_usd"])
    assert 0 < ex["natural_hedge"] < 1


def test_zero_cost_structures():
    b = price_book(CFG)
    for i in range(len(b.t)):
        put = px.put(b.fwd[i], b.collar_put_k[i], b.vol, b.t[i], b.rd)
        assert put == pytest.approx(b.collar_call_prem[i], abs=1e-9)
        spread = px.call(b.fwd[i], b.seagull_k1[i], b.vol, b.t[i], b.rd) - px.call(b.fwd[i], b.seagull_k2[i], b.vol, b.t[i], b.rd)
        assert px.put(b.fwd[i], b.seagull_put_k[i], b.vol, b.t[i], b.rd) == pytest.approx(spread, abs=1e-9)
    assert np.all(b.collar_put_k < b.fwd) and np.all(b.fwd < b.collar_call_k)


def test_payoff_shapes():
    b = price_book(CFG)
    s = np.array([80.0] * 12), np.array([120.0] * 12)
    lo, hi = unit_costs(b, s[0], CFG), unit_costs(b, s[1], CFG)
    assert np.allclose(lo["Zero-cost collar"], b.collar_put_k + b.ferr)       # floor binds
    assert np.allclose(hi["Zero-cost collar"], b.collar_call_k + b.ferr)      # cap binds
    assert np.allclose(lo["Forward 100%"], hi["Forward 100%"])                # forward ignores the rate
    # Seagull: protection stops above the upper strike, so cost rises again
    assert np.all(hi["Seagull"] > b.seagull_k1 + b.ferr)
    carry = np.exp(b.rd * b.t)
    assert np.allclose(hi["USD call (ATM forward)"], b.fwd + b.call_atm * carry + b.ferr)


def test_layered_policy_weights():
    b = price_book(CFG)
    s_t = np.full(12, 100.0)
    u = unit_costs(b, s_t, CFG)
    lay = CFG["strategies"]["layered"]
    h = np.repeat(lay["ratios"], 3)
    fs = lay["forward_share"]
    expected = h * fs * b.fwd_all_in + h * (1 - fs) * u["Zero-cost collar"] + (1 - h) * s_t
    assert np.allclose(u["Layered policy"], expected)


def test_forward_cost_is_certain_and_matches_grid():
    g = scenario_grid(CFG)
    assert g["Forward 100%"].nunique() == 1
    b = price_book(CFG)
    assert g["Forward 100%"].iloc[0] == pytest.approx(float(total_cost_inr(b.fwd_all_in, exposure(CFG)["monthly_usd"])))


def test_market_implied_mc_is_unbiased():
    # Under the forward drift, the expected unhedged cost equals the cost at today's forwards
    mc = monte_carlo(CFG)
    t = mc["scenarios"]["base"]["table"]
    se = t.loc["Unhedged", "Std dev"] / np.sqrt(CFG["simulation"]["paths"])
    assert abs(t.loc["Unhedged", "Expected cost"] - mc["budget"]) < 4 * se
    assert t.loc["Forward 100%", "Std dev"] == pytest.approx(0, abs=1e-6)
    for k in STRATEGIES[1:]:
        assert t.loc[k, "Std dev"] < t.loc["Unhedged", "Std dev"]


def test_simulated_paths_mean():
    p = simulate_paths(95.0, 0.03, 0.06, 12, 200000, 1)
    assert p[:, -1].mean() == pytest.approx(95.0 * np.exp(0.03), rel=2e-3)


def test_no_ferr_means_plain_forward():
    c = copy.deepcopy(CFG)
    c["market"]["ferr_passthrough"] = 0.0
    b = price_book(c)
    assert np.allclose(b.fwd_all_in, b.fwd)


def test_translation_per_rupee():
    tr = translation(CFG)
    assert tr["per_rupee"] == pytest.approx(CFG["company"]["net_usd_liabilities"] / 10)
    assert tr["q2fy26_check"]["implied_usd_bn"] == pytest.approx(9.12, abs=0.01)


def test_backtest_forward_matches_hand_calc():
    bt = backtest(CFG)
    s0, prem = bt["start_rate"], CFG["backtest"]["forward_premium"]
    t = np.arange(1, CFG["backtest"]["months"] + 1) / 12
    fwd = s0 * (1 + prem) ** t
    monthly = exposure(CFG)["monthly_usd"][: len(t)]
    assert bt["totals"]["Forward 100%"] == pytest.approx((fwd * monthly).sum() / 10, rel=1e-9)
    assert bt["totals"]["Unhedged"] == pytest.approx((bt["settle"].values * monthly).sum() / 10, rel=1e-9)
