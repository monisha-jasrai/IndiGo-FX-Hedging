import math

import numpy as np
import pytest

from fxhedge import pricing as px

F, T, VOL, RD = 97.0, 0.75, 0.06, math.log(1.0649)


def test_forward_is_interest_parity():
    s, rd, rf = 94.8378, math.log(1.0649), math.log(1.03875)
    assert px.forward(s, rd, rf, 1.0) == pytest.approx(s * 1.0649 / 1.03875, rel=1e-12)


@pytest.mark.parametrize("k", [90.0, 95.0, 97.0, 100.0, 105.0])
def test_put_call_parity(k):
    lhs = px.call(F, k, VOL, T, RD) - px.put(F, k, VOL, T, RD)
    assert lhs == pytest.approx(math.exp(-RD * T) * (F - k), abs=1e-10)


def test_atm_forward_call_equals_put():
    assert px.call(F, F, VOL, T, RD) == pytest.approx(px.put(F, F, VOL, T, RD), abs=1e-12)


def test_atm_call_rule_of_thumb():
    # ATM-forward premium ~ 0.4 x F x vol x sqrt(t), discounted
    approx = 0.3989 * F * VOL * math.sqrt(T) * math.exp(-RD * T)
    assert px.call(F, F, VOL, T, RD) == pytest.approx(approx, rel=2e-3)


def test_premium_rises_with_vol_and_time():
    assert px.call(F, F, 0.08, T, RD) > px.call(F, F, 0.06, T, RD)
    assert px.call(F, F, VOL, 1.0, RD) > px.call(F, F, VOL, 0.5, RD)


def test_solved_put_strike_gives_target_premium():
    target = px.call(F, 1.02 * F, VOL, T, RD)
    k = px.solve_put_strike(F, target, VOL, T, RD)
    assert px.put(F, k, VOL, T, RD) == pytest.approx(target, abs=1e-9)
    assert k < F


def test_ferr_charge():
    # 20% of notional parked for a year at 6.49%, half passed on
    c = px.ferr_charge(100.0, math.log(1.0649), 1.0, 0.20, 0.5)
    assert c == pytest.approx(0.5 * 0.20 * 100 * 0.0649, rel=1e-9)
    assert px.ferr_charge(100.0, RD, 1.0, 0.20, 0.0) == 0


def test_delta_between_zero_and_one():
    d = px.delta_call(F, F, VOL, T, RD, math.log(1.03875))
    assert 0.4 < d < 0.6
    assert np.isfinite(d)
