"""Exposure map, hedge instruments and strategy payoffs for IndiGo's USD/INR risk."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import yaml

from . import pricing as px

ROOT = Path(__file__).resolve().parent.parent
STRATEGIES = ["Unhedged", "Forward 100%", "Forward 50%", "USD call (ATM forward)", "Zero-cost collar",
              "Seagull", "Layered policy"]


def load_config(path: Path | None = None) -> dict:
    with open(path or ROOT / "config" / "indigo.yaml") as f:
        return yaml.safe_load(f)


# ----------------------------------------------------------------------------------- exposure
def exposure(cfg: dict) -> dict:
    """Annual USD flows ($ mn) and the 12-month net payable, settled in equal monthly amounts."""
    c, spot = cfg["company"], cfg["market"]["spot"]
    to_usd = 10.0 / spot                                   # ₹ crore -> $ mn
    fuel = c["fuel_inr"] * c["fuel_usd_linked"] * to_usd
    fx_rev = c["revenue_inr"] * c["international_share"] * c["fx_collected_share"] * to_usd
    gross = fuel + c["lease_maint_usd"] + c["other_usd"]
    net = gross - fx_rev
    n = cfg["horizon_months"]
    return {
        "fuel_usd": fuel, "lease_maint_usd": c["lease_maint_usd"], "other_usd": c["other_usd"],
        "gross_usd": gross, "fx_revenue_usd": fx_rev, "net_usd": net,
        "natural_hedge": fx_rev / gross, "monthly_usd": np.full(n, net / 12),
        "net_inr_at_spot": net * spot / 10.0,
    }


# ----------------------------------------------------------------------------------- pricing
@dataclass
class Book:
    """Per-tenor market and instrument terms (one entry per monthly settlement)."""
    t: np.ndarray
    fwd: np.ndarray
    ferr: np.ndarray
    fwd_all_in: np.ndarray
    call_atm: np.ndarray          # premium today, ₹ per $
    collar_call_k: np.ndarray
    collar_put_k: np.ndarray
    collar_call_prem: np.ndarray
    seagull_k1: np.ndarray
    seagull_k2: np.ndarray
    seagull_put_k: np.ndarray
    rd: float
    rf: float
    vol: float
    extra: dict = field(default_factory=dict)


def price_book(cfg: dict, spot: float | None = None, vol: float | None = None, rd_ann: float | None = None,
               rf_ann: float | None = None, months: int | None = None, ferr: bool = True) -> Book:
    m = cfg["market"]
    s = cfg["strategies"]
    spot = m["spot"] if spot is None else spot
    vol = m["vol"] if vol is None else vol
    rd = px.cont(m["inr_rate"] if rd_ann is None else rd_ann)
    rf = px.cont(m["usd_rate"] if rf_ann is None else rf_ann)
    n = months or cfg["horizon_months"]
    t = np.arange(1, n + 1) / 12.0
    fwd = px.forward(spot, rd, rf, t)
    charge = px.ferr_charge(fwd, rd, t, m["ferr_reserve"], m["ferr_passthrough"]) if ferr else np.zeros(n)
    call_atm = px.call(fwd, fwd, vol, t, rd)

    kc = fwd * s["collar_call_moneyness"]
    cprem = px.call(fwd, kc, vol, t, rd)
    kp = np.array([px.solve_put_strike(f, c, vol, tt, rd) for f, c, tt in zip(fwd, cprem, t)])

    k1, k2 = fwd.copy(), fwd * s["seagull_upper"]
    spread = px.call(fwd, k1, vol, t, rd) - px.call(fwd, k2, vol, t, rd)
    sp = np.array([px.solve_put_strike(f, c, vol, tt, rd) for f, c, tt in zip(fwd, spread, t)])
    return Book(t, fwd, charge, fwd + charge, call_atm, kc, kp, cprem, k1, k2, sp, rd, rf, vol)


# ----------------------------------------------------------------------------------- payoffs
def unit_costs(book: Book, s_t: np.ndarray, cfg: dict) -> dict[str, np.ndarray]:
    """INR paid per USD of exposure at each settlement, for each strategy.

    s_t: USD/INR at settlement, shape (..., months). Option premiums are paid today and carried
    to settlement at the INR rate, so every strategy is compared in settlement-date rupees.
    """
    carry = np.exp(book.rd * book.t)
    fe, fx = book.fwd_all_in, book.ferr
    unhedged = s_t
    fwd100 = np.broadcast_to(fe, s_t.shape)
    fwd50 = 0.5 * fe + 0.5 * s_t
    call = np.minimum(s_t, book.fwd) + book.call_atm * carry + fx
    collar = np.clip(s_t, book.collar_put_k, book.collar_call_k) + fx
    seagull = (np.maximum(s_t, book.seagull_put_k) - np.maximum(s_t - book.seagull_k1, 0)
               + np.maximum(s_t - book.seagull_k2, 0) + fx)

    lay = cfg["strategies"]["layered"]
    q = np.minimum(np.arange(len(book.t)) * 4 // len(book.t), 3) if len(book.t) >= 4 else np.zeros(len(book.t), int)
    h = np.asarray(lay["ratios"])[q]
    fs = lay["forward_share"]
    layered = h * fs * fe + h * (1 - fs) * collar + (1 - h) * s_t
    return dict(zip(STRATEGIES, [unhedged, np.asarray(fwd100), fwd50, call, collar, seagull, layered]))


def total_cost_inr(unit: np.ndarray, monthly_usd: np.ndarray) -> np.ndarray:
    """₹ crore for the whole 12-month strip ($ mn x ₹/$ / 10)."""
    return (unit * monthly_usd).sum(axis=-1) / 10.0


# ----------------------------------------------------------------------------------- translation
def translation(cfg: dict, moves=(-5, -2.5, -1, 1, 2.5, 5, 10)) -> dict:
    """Mark-to-market loss on USD liabilities for a move in USD/INR at a reporting date."""
    c = cfg["company"]
    per_rupee = c["net_usd_liabilities"] / 10.0          # ₹ crore per ₹1 move
    hedged = c["hedge_book_usd"] / 10.0
    rows = []
    for mv in moves:
        gross = per_rupee * mv
        offset = -hedged * mv
        net = gross + offset
        rows.append({"move": mv, "gross_loss": gross, "hedge_offset": offset, "net_loss": net,
                     "after_tax": net * (1 - c["tax_rate"])})
    return {"per_rupee": per_rupee, "per_rupee_net_of_hedges": per_rupee - hedged, "rows": rows,
            "q2fy26_check": {"move": 3.18, "reported_loss": 2900, "implied_usd_bn": 2900 / 3.18 / 100}}
