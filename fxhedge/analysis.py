"""Monte Carlo, deterministic scenarios and the 2026 back-test."""
from __future__ import annotations

import numpy as np
import pandas as pd

from . import pricing as px
from .model import ROOT, STRATEGIES, exposure, price_book, total_cost_inr, unit_costs


def simulate_paths(spot: float, drift: float, vol: float, months: int, paths: int, seed: int) -> np.ndarray:
    """Monthly USD/INR fixings under geometric Brownian motion. Shape (paths, months)."""
    rng = np.random.default_rng(seed)
    dt = 1 / 12
    z = rng.standard_normal((paths, months))
    steps = (drift - 0.5 * vol ** 2) * dt + vol * np.sqrt(dt) * z
    return spot * np.exp(np.cumsum(steps, axis=1))


def risk_table(costs: dict[str, np.ndarray], budget: float) -> pd.DataFrame:
    base = costs["Unhedged"]
    rows = []
    for k, v in costs.items():
        v = np.asarray(v)
        if v.ndim == 0 or v.std() == 0:
            v = np.broadcast_to(v, base.shape)
        rows.append({
            "Strategy": k, "Expected cost": v.mean(), "vs budget": v.mean() - budget, "Std dev": v.std(),
            "P5": np.percentile(v, 5), "P50": np.percentile(v, 50), "P95": np.percentile(v, 95),
            "P99": np.percentile(v, 99), "Cost-at-risk (P95 - mean)": np.percentile(v, 95) - v.mean(),
            "Worst": v.max(), "Variance reduction": 1 - v.var() / base.var(),
        })
    return pd.DataFrame(rows).set_index("Strategy")


def monte_carlo(cfg: dict) -> dict:
    ex = exposure(cfg)
    book = price_book(cfg)
    sim = cfg["simulation"]
    budget = total_cost_inr(book.fwd, ex["monthly_usd"])        # what the strip costs at today's forwards
    out = {}
    for name, sc in sim["scenarios"].items():
        drift = book.rd - book.rf if sc["drift"] == "forward" else sc["drift"]
        paths = simulate_paths(cfg["market"]["spot"], drift, sc["vol"], len(book.t), sim["paths"], sim["seed"])
        unit = unit_costs(book, paths, cfg)
        costs = {k: total_cost_inr(v, ex["monthly_usd"]) for k, v in unit.items()}
        out[name] = {"label": sc["label"], "table": risk_table(costs, budget), "costs": costs,
                     "drift": drift, "vol": sc["vol"], "final_rate": paths[:, -1]}
    return {"budget": budget, "scenarios": out}


def scenario_grid(cfg: dict) -> pd.DataFrame:
    """Total 12-month cost (₹ crore) if USD/INR sits at a flat level at every settlement."""
    ex = exposure(cfg)
    book = price_book(cfg)
    rows = {}
    for lvl in cfg["scenario_levels"]:
        s_t = np.full(len(book.t), float(lvl))
        unit = unit_costs(book, s_t, cfg)
        rows[lvl] = {k: float(total_cost_inr(v, ex["monthly_usd"])) for k, v in unit.items()}
    return pd.DataFrame(rows).T[STRATEGIES]


def effective_rates(cfg: dict, s_t: np.ndarray, month: int = 12) -> dict[str, np.ndarray]:
    """Effective INR per USD for one settlement month across a range of outcomes (payoff chart)."""
    book = price_book(cfg)
    i = month - 1
    grid = np.repeat(s_t[:, None], len(book.t), axis=1)
    return {k: (np.broadcast_to(v, grid.shape))[:, i] for k, v in unit_costs(book, grid, cfg).items()}


def load_rates() -> pd.Series:
    df = pd.read_csv(ROOT / "data" / "usdinr_2026_boe.csv", parse_dates=["date"])
    return df.set_index("date")["usdinr"]


def realised_vol(rates: pd.Series, window: int | None = None) -> float:
    r = np.log(rates).diff().dropna()
    if window:
        r = r.iloc[-window:]
    return float(r.std() * np.sqrt(252))


def backtest(cfg: dict) -> dict:
    """Hedge the Jan-Oct 2026 payments on 2 Jan 2026 and settle at each month's last fixing."""
    bt = cfg["backtest"]
    rates = load_rates()
    start = pd.Timestamp(bt["start"])
    s0 = float(rates.loc[start])
    n = bt["months"]
    settle = rates.groupby(rates.index.to_period("M")).last().iloc[:n]
    rd = px.cont(cfg["market"]["inr_rate"])
    prem = px.cont(bt["forward_premium"])
    # Re-price the same instruments as of 2 Jan 2026: the forward premium replaces the rate differential.
    rf = rd - prem
    book = price_book(cfg, spot=s0, vol=bt["vol"], rd_ann=np.expm1(rd), rf_ann=np.expm1(rf), months=n, ferr=False)
    monthly = exposure(cfg)["monthly_usd"][:n]
    unit = unit_costs(book, settle.values, cfg)
    totals = {k: float(total_cost_inr(np.broadcast_to(v, settle.shape), monthly)) for k, v in unit.items()}
    avg_rate = {k: float(np.average(np.broadcast_to(v, settle.shape), weights=monthly)) for k, v in unit.items()}
    return {"start_rate": s0, "settle": settle, "forwards": book.fwd, "totals": totals, "avg_rate": avg_rate,
            "saving_vs_unhedged": {k: totals["Unhedged"] - v for k, v in totals.items()},
            "collar_put_k": book.collar_put_k, "collar_call_k": book.collar_call_k}


def stress_rates(cfg: dict) -> pd.DataFrame:
    """Forward and option costs at different implied volatilities and FERR pass-through."""
    rows = []
    for vol in (0.04, 0.05, 0.06, 0.08, 0.10):
        b = price_book(cfg, vol=vol)
        rows.append({"vol": vol, "1y forward": b.fwd[-1], "1y ATM call premium": b.call_atm[-1],
                     "1y ATM call % of spot": b.call_atm[-1] / cfg["market"]["spot"],
                     "Collar put strike (1y)": b.collar_put_k[-1]})
    return pd.DataFrame(rows).set_index("vol")
