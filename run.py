#!/usr/bin/env python3
"""Run the IndiGo FX hedging analysis.

    python run.py                 # tables to the console, outputs to output/, charts to docs/img/
    python run.py --no-charts
    python run.py --out results/  # write outputs elsewhere (charts stay out of docs/img)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from fxhedge.analysis import backtest, load_rates, monte_carlo, realised_vol, scenario_grid, stress_rates
from fxhedge.model import ROOT, exposure, load_config, price_book, translation


def summarise(cfg) -> dict:
    ex = exposure(cfg)
    book = price_book(cfg)
    mc = monte_carlo(cfg)
    grid = scenario_grid(cfg)
    bt = backtest(cfg)
    tr = translation(cfg)
    rates = load_rates()
    return dict(ex=ex, book=book, mc=mc, grid=grid, bt=bt, tr=tr, rates=rates,
                vols={"ytd": realised_vol(rates), "60d": realised_vol(rates, 60), "20d": realised_vol(rates, 20)},
                stress=stress_rates(cfg))


def to_json(r: dict) -> dict:
    b = r["book"]
    base = r["mc"]["scenarios"]["base"]["table"]
    return {
        "exposure_usd_mn": {k: float(v) for k, v in r["ex"].items() if np.isscalar(v)},
        "forward_12m": float(b.fwd[-1]), "forward_premium_12m": float(b.fwd[-1] / r["rates"].iloc[-1] - 1),
        "ferr_charge_12m": float(b.ferr[-1]), "atm_call_12m": float(b.call_atm[-1]),
        "collar_12m": [float(b.collar_put_k[-1]), float(b.collar_call_k[-1])],
        "budget_inr_cr": float(r["mc"]["budget"]),
        "risk_base": base.round(1).to_dict(orient="index"),
        "risk_stress": r["mc"]["scenarios"]["stress"]["table"].round(1).to_dict(orient="index"),
        "risk_relief": r["mc"]["scenarios"]["relief"]["table"].round(1).to_dict(orient="index"),
        "scenario_grid": {str(k): v for k, v in r["grid"].round(1).to_dict(orient="index").items()},
        "backtest": {"start_rate": r["bt"]["start_rate"], "totals": r["bt"]["totals"], "avg_rate": r["bt"]["avg_rate"],
                     "saving_vs_unhedged": r["bt"]["saving_vs_unhedged"]},
        "translation": {k: v for k, v in r["tr"].items() if k != "rows"},
        "realised_vol": r["vols"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-charts", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "output")
    a = ap.parse_args()
    cfg = load_config()
    r = summarise(cfg)
    pd.set_option("display.width", 160, "display.max_columns", 12)

    ex = r["ex"]
    print(f"Net 12-month USD payable: ${ex['net_usd']:,.0f} mn (≈ ₹{ex['net_inr_at_spot']:,.0f} crore); "
          f"natural hedge {ex['natural_hedge']:.0%}")
    print(f"12m forward {r['book'].fwd[-1]:.2f}; RBI reserve cost +₹{r['book'].ferr[-1]:.2f}; "
          f"ATM call {r['book'].call_atm[-1]:.2f}; collar {r['book'].collar_put_k[-1]:.2f}-{r['book'].collar_call_k[-1]:.2f}")
    print("\nMonte Carlo, market-implied (₹ crore):")
    print(r["mc"]["scenarios"]["base"]["table"][["Expected cost", "vs budget", "Std dev", "P95", "Cost-at-risk (P95 - mean)"]].round(0))
    print("\nFlat-rate scenarios (₹ crore):")
    print(r["grid"].round(0))
    print("\n2026 back-test, saving vs unhedged (₹ crore):", {k: round(v) for k, v in r["bt"]["saving_vs_unhedged"].items()})
    print(f"Translation: ₹{r['tr']['per_rupee']:,.0f} crore per ₹1 move")

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "summary.json").write_text(json.dumps(to_json(r), indent=1, default=float))
    r["grid"].to_csv(a.out / "scenario_grid.csv")
    r["mc"]["scenarios"]["base"]["table"].to_csv(a.out / "risk_base.csv")
    if not a.no_charts:
        from fxhedge.charts import make_all
        img = ROOT / "docs" / "img" if a.out.resolve() == (ROOT / "output").resolve() else a.out / "img"
        make_all(cfg, r["mc"], r["bt"], r["tr"], img)


if __name__ == "__main__":
    main()
