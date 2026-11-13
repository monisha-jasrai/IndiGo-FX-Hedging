"""USD/INR forward and option pricing.

Forwards come from covered interest parity. Options use Garman-Kohlhagen (Black-Scholes
for currencies) written on the forward, so the only inputs are the forward, strike,
volatility, time and the INR discount rate.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm


def cont(rate: float) -> float:
    """Annually compounded rate -> continuously compounded rate."""
    return math.log1p(rate)


def forward(spot: float, rd: float, rf: float, t):
    """Covered interest parity. rd, rf are continuous INR and USD rates."""
    return spot * np.exp((rd - rf) * np.asarray(t, dtype=float))


def _d1d2(fwd, strike, vol, t):
    sd = vol * np.sqrt(t)
    d1 = (np.log(fwd / strike) + 0.5 * sd * sd) / sd
    return d1, d1 - sd


def call(fwd, strike, vol, t, rd):
    """Price today (INR per USD) of a European USD call / INR put."""
    d1, d2 = _d1d2(fwd, strike, vol, t)
    return np.exp(-rd * t) * (fwd * norm.cdf(d1) - strike * norm.cdf(d2))


def put(fwd, strike, vol, t, rd):
    d1, d2 = _d1d2(fwd, strike, vol, t)
    return np.exp(-rd * t) * (strike * norm.cdf(-d2) - fwd * norm.cdf(-d1))


def delta_call(fwd, strike, vol, t, rd, rf):
    """Spot delta of the USD call (USD per USD of notional)."""
    d1, _ = _d1d2(fwd, strike, vol, t)
    return math.exp(-rf * t) * norm.cdf(d1)


def solve_put_strike(fwd: float, target: float, vol: float, t: float, rd: float) -> float:
    """Strike of a put whose premium equals `target` (used to build zero-cost structures)."""
    if target <= 0:
        return 0.0
    return brentq(lambda k: put(fwd, k, vol, t, rd) - target, fwd * 0.5, fwd, xtol=1e-10)


def ferr_charge(fwd, rd: float, t, reserve: float, passthrough: float):
    """Extra INR per USD an importer pays when its bank must park `reserve` of the INR notional
    with RBI at no interest for the life of the hedge (RBI Foreign Exchange Risk Reserve, Oct 2026)."""
    return passthrough * reserve * np.asarray(fwd) * (np.exp(rd * np.asarray(t)) - 1.0)
