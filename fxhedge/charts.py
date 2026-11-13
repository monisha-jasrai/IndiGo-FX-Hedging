"""Charts for the README and the workbook."""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .analysis import effective_rates, load_rates  # noqa: E402
from .model import STRATEGIES, exposure, price_book  # noqa: E402

NAVY, BLUE, LBLUE, GREY, RED, GREEN, AMBER = "#1F3864", "#2E75B6", "#9DC3E6", "#8C8C8C", "#C0504D", "#4E8542", "#C9A227"
COLORS = dict(zip(STRATEGIES, [GREY, NAVY, LBLUE, GREEN, BLUE, AMBER, RED]))
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.titleweight": "bold", "axes.titlesize": 10, "figure.dpi": 150,
                     "savefig.bbox": "tight", "legend.frameon": False})


def exposure_chart(cfg, out: Path):
    ex = exposure(cfg)
    items = [("Fuel\n(USD-linked)", ex["fuel_usd"]), ("Leases and\nmaintenance", ex["lease_maint_usd"]),
             ("Other USD\ncosts", ex["other_usd"]), ("USD revenue\n(natural hedge)", -ex["fx_revenue_usd"])]
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    run = 0
    for i, (lab, v) in enumerate(items):
        bottom = run if v > 0 else run + v
        ax.bar(i, abs(v), bottom=bottom, color=NAVY if v > 0 else GREEN, width=0.6)
        ax.text(i, bottom + abs(v) + 60, f"{v:+,.0f}" if i else f"{v:,.0f}", ha="center", fontsize=8.5)
        run += v
    ax.bar(len(items), run, color=RED, width=0.6)
    ax.text(len(items), run + 60, f"{run:,.0f}", ha="center", fontsize=9, fontweight="bold")
    ax.set_xticks(range(len(items) + 1))
    ax.set_xticklabels([i[0] for i in items] + ["Net USD\npayable"])
    ax.set_ylabel("$ million, next 12 months")
    ax.set_title(f"IndiGo's 12-month USD exposure: ${run/1000:.1f} bn net, about ₹{ex['net_inr_at_spot']:,.0f} crore", loc="left")
    fig.savefig(out / "exposure.png")
    plt.close(fig)


def rupee_chart(cfg, out: Path):
    s = load_rates()
    vol = np.log(s).diff().rolling(30).std() * np.sqrt(252) * 100
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(7.5, 4.4), sharex=True, gridspec_kw=dict(height_ratios=[2.2, 1]))
    a1.plot(s.index, s.values, color=NAVY, lw=1.4)
    for d, lab in [("2026-05-20", "Peak 96.83 (20 May) "), ("2026-10-07", "RBI hike + FX curbs ")]:
        a1.axvline(pd.Timestamp(d), color=GREY, lw=0.8, ls="--")
        a1.text(pd.Timestamp(d), 90.2, lab, fontsize=7.5, color=GREY, ha="right", va="bottom")
    a1.set_ylabel("₹ per $")
    a1.set_title(f"USD/INR in 2026: {s.iloc[0]:.2f} to {s.iloc[-1]:.2f} (+{s.iloc[-1]/s.iloc[0]-1:.1%})", loc="left")
    a2.plot(vol.index, vol.values, color=RED, lw=1.2)
    a2.set_ylabel("30-day vol, %")
    a2.axhline(cfg["market"]["vol"] * 100, color=BLUE, lw=0.9, ls=":")
    a2.text(s.index[5], cfg["market"]["vol"] * 100 + 0.3, f"pricing vol {cfg['market']['vol']:.0%}", fontsize=7.5, color=BLUE)
    import matplotlib.dates as mdates
    a2.xaxis.set_major_locator(mdates.MonthLocator())
    a2.xaxis.set_major_formatter(mdates.DateFormatter("%b"))
    fig.savefig(out / "rupee_2026.png")
    plt.close(fig)


def forward_chart(cfg, out: Path):
    b = price_book(cfg)
    m = np.arange(0, len(b.t) + 1)
    spot = cfg["market"]["spot"]
    fig, ax = plt.subplots(figsize=(7.5, 3.4))
    ax.fill_between(m[1:], b.collar_put_k, b.collar_call_k, color=LBLUE, alpha=0.35, label="Zero-cost collar range")
    ax.plot(m, np.r_[spot, b.fwd], color=NAVY, marker="o", ms=3, label="Forward (interest parity)")
    ax.plot(m[1:], b.fwd_all_in, color=RED, ls="--", lw=1.2, label="Forward incl. RBI reserve cost")
    ax.set_xlabel("Months to settlement")
    ax.set_ylabel("₹ per $")
    ax.set_title(f"Hedge rates: 12-month forward {b.fwd[-1]:.2f} ({b.fwd[-1]/spot-1:.1%} premium); "
                 f"+₹{b.ferr[-1]:.2f} for the RBI reserve", loc="left")
    ax.legend(loc="upper left")
    fig.savefig(out / "forward_curve.png")
    plt.close(fig)


def payoff_chart(cfg, out: Path):
    s = np.linspace(88, 106, 181)
    eff = effective_rates(cfg, s, month=12)
    fig, ax = plt.subplots(figsize=(7.5, 4.0))
    for k in STRATEGIES:
        if k == "Forward 50%":
            continue
        ax.plot(s, eff[k], color=COLORS[k], lw=2.2 if k in ("Layered policy", "Zero-cost collar") else 1.5, label=k)
    ax.set_xlabel("USD/INR when the 12-month payment is due")
    ax.set_ylabel("Effective ₹ per $ paid")
    ax.set_title("What IndiGo pays per dollar in month 12, by strategy", loc="left")
    ax.legend(ncol=2, fontsize=8)
    fig.savefig(out / "payoff.png")
    plt.close(fig)


def risk_chart(mc: dict, out: Path):
    sc = mc["scenarios"]["base"]
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.8), gridspec_kw=dict(width_ratios=[1.5, 1]))
    data = [np.broadcast_to(sc["costs"][k], sc["costs"]["Unhedged"].shape) / 1000 for k in STRATEGIES]
    bp = a1.boxplot(data, vert=False, whis=(1, 99), showfliers=False, patch_artist=True, widths=0.55,
                    medianprops=dict(color="black", lw=1.2))
    for patch, k in zip(bp["boxes"], STRATEGIES):
        patch.set_facecolor(COLORS[k])
        patch.set_alpha(0.75)
    a1.set_yticks(range(1, len(STRATEGIES) + 1))
    a1.set_yticklabels(STRATEGIES)
    a1.axvline(mc["budget"] / 1000, color=GREY, ls="--", lw=0.9)
    a1.set_xlabel("12-month cost, ₹ thousand crore (whiskers: P1-P99)")
    a1.set_title("Distribution of the 12-month cost (10,000 paths)", loc="left")
    t = sc["table"]
    offs = {"Unhedged": (-10, 8), "Forward 100%": (5, -12), "Forward 50%": (5, 4), "USD call (ATM forward)": (-22, -14),
            "Zero-cost collar": (-10, 9), "Seagull": (6, -2), "Layered policy": (5, -10)}
    for k in STRATEGIES:
        x, y = t.loc[k, "Cost-at-risk (P95 - mean)"], t.loc[k, "vs budget"]
        a2.scatter(x, y, color=COLORS[k], s=40, zorder=3)
        a2.annotate(k.replace(" (ATM forward)", ""), (x, y), fontsize=7, xytext=offs[k], textcoords="offset points")
    a2.set_ylim(-25, 200)
    a2.set_xlabel("Cost-at-risk, ₹ crore (P95 - mean)")
    a2.set_ylabel("Expected cost vs budget, ₹ crore")
    a2.set_title("Risk vs cost", loc="left")
    fig.tight_layout()
    fig.savefig(out / "risk.png")
    plt.close(fig)


def backtest_chart(bt: dict, out: Path):
    s = bt["settle"]
    x = np.arange(len(s))
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(9, 3.6), gridspec_kw=dict(width_ratios=[1.4, 1]))
    a1.plot(x, s.values, color=GREY, marker="o", ms=3.5, label="Actual month-end rate")
    a1.plot(x, bt["forwards"], color=NAVY, marker="s", ms=3, label="Forward locked on 2 Jan")
    a1.fill_between(x, bt["collar_put_k"], bt["collar_call_k"], color=LBLUE, alpha=0.35, label="Collar range")
    a1.set_xticks(x)
    a1.set_xticklabels([p.strftime("%b") for p in s.index.to_timestamp()])
    a1.set_ylabel("₹ per $")
    a1.legend(fontsize=7.5, loc="upper left")
    a1.set_title("2026 back-test: hedges placed on 2 Jan 2026", loc="left")
    keys = ["Forward 100%", "USD call (ATM forward)", "Forward 50%", "Zero-cost collar", "Layered policy"]
    vals = [bt["saving_vs_unhedged"][k] for k in keys]
    a2.barh(keys[::-1], vals[::-1], color=[COLORS[k] for k in keys[::-1]])
    for i, v in enumerate(vals[::-1]):
        a2.text(v + 15, i, f"₹{v:,.0f} cr", va="center", fontsize=8)
    a2.set_xlabel("Saving vs unhedged, Jan-Oct 2026 (₹ crore)")
    a2.set_xlim(0, max(vals) * 1.35)
    a2.set_title("Saving vs unhedged", loc="left")
    fig.tight_layout()
    fig.savefig(out / "backtest.png")
    plt.close(fig)


def translation_chart(tr: dict, out: Path):
    rows = [r for r in tr["rows"]]
    fig, ax = plt.subplots(figsize=(7.5, 3.0))
    lab = [f"₹{r['move']:+g}" for r in rows]
    ax.bar(lab, [r["gross_loss"] for r in rows], color=[RED if r["move"] > 0 else GREEN for r in rows], width=0.6)
    for i, r in enumerate(rows):
        ax.text(i, r["gross_loss"] + (150 if r["gross_loss"] > 0 else -150), f"{r['gross_loss']:+,.0f}", ha="center",
                va="bottom" if r["gross_loss"] > 0 else "top", fontsize=8)
    ax.set_ylim(-6500, 11500)
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xlabel("Move in USD/INR between reporting dates")
    ax.set_ylabel("FX loss (+) / gain (-), ₹ crore")
    ax.set_title(f"Balance-sheet exposure: about ₹{tr['per_rupee']:,.0f} crore of reported P&L per ₹1 move", loc="left")
    fig.savefig(out / "translation.png")
    plt.close(fig)


def make_all(cfg, mc, bt, tr, out: Path):
    out.mkdir(parents=True, exist_ok=True)
    exposure_chart(cfg, out)
    rupee_chart(cfg, out)
    forward_chart(cfg, out)
    payoff_chart(cfg, out)
    risk_chart(mc, out)
    backtest_chart(bt, out)
    translation_chart(tr, out)
