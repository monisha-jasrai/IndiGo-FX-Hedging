#!/usr/bin/env python3
"""Generate IndiGo_FX_Hedging_Model.xlsx from config/indigo.yaml.

Exposure, pricing (including the zero-cost strike solves), flat-rate scenarios, translation
exposure and the forward back-test are live Excel formulas driven by the Inputs tab. The
Monte Carlo tables and the option back-test come from Python and are marked [Python].
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from openpyxl import Workbook  # noqa: E402
from openpyxl.drawing.image import Image as XLImage  # noqa: E402
from openpyxl.formatting.rule import CellIsRule  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402
from openpyxl.utils import get_column_letter as L  # noqa: E402
from openpyxl.workbook.defined_name import DefinedName  # noqa: E402

from fxhedge.analysis import backtest, load_rates, monte_carlo  # noqa: E402
from fxhedge.model import STRATEGIES, load_config  # noqa: E402

FONT, NAVY = "Arial", "1F3864"
BLUE_IN, BLACK, GREEN, GREY = "0000FF", "000000", "008000", "595959"
FILL_HDR = PatternFill("solid", fgColor=NAVY)
FILL_SEC = PatternFill("solid", fgColor="D9E1F2")
FILL_KEY = PatternFill("solid", fgColor="FFFF00")
FILL_PY = PatternFill("solid", fgColor="FCE4D6")
NUM, NUM1, NUM2, NUM4 = '#,##0;(#,##0);"-"', '#,##0.0;(#,##0.0);"-"', '#,##0.00', '0.0000'
PCT, PCT2 = '0.0%;(0.0%);"-"', '0.00%'
MONTHS = 12
R0 = 6                                   # first month row on Pricing / Solver
NEWTON = 10


def put(ws, ref, value, color=BLACK, fmt=None, bold=False, fill=None, italic=False, align=None, size=10):
    c = ws[ref]
    c.value = value
    c.font = Font(name=FONT, color=color, bold=bold, italic=italic, size=size)
    if fmt:
        c.number_format = fmt
    if fill:
        c.fill = fill
    if align:
        c.alignment = Alignment(horizontal=align, vertical="center")
    return c


def title(ws, text, sub):
    put(ws, "A1", text, NAVY, bold=True, size=16)
    put(ws, "A2", sub, GREY, italic=True)
    ws.sheet_view.showGridLines = False


def section(ws, row, text, width=8):
    for i in range(1, width + 1):
        ws.cell(row=row, column=i).fill = FILL_SEC
    put(ws, f"A{row}", text, NAVY, bold=True)


def header(ws, row, labels, start=1):
    for i, lab in enumerate(labels):
        c = ws.cell(row=row, column=start + i, value=lab)
        c.font = Font(name=FONT, color="FFFFFF", bold=True, size=10)
        c.fill = FILL_HDR
        c.alignment = Alignment(horizontal="left" if i == 0 else "center", wrap_text=True)


def name(wb, nm, sheet, ref):
    col = "".join(ch for ch in ref if ch.isalpha())
    row = "".join(ch for ch in ref if ch.isdigit())
    sh = f"'{sheet}'" if " " in sheet else sheet
    wb.defined_names[nm] = DefinedName(nm, attr_text=f"{sh}!${col}${row}")


# ---------------------------------------------------------------- option formula strings
def _d(F, K, t, sign):
    return f"(LN({F}/{K}){sign}0.5*Vol^2*{t})/(Vol*SQRT({t}))"


def call_x(F, K, t):
    return f"EXP(-RD*{t})*({F}*NORMSDIST({_d(F, K, t, '+')})-{K}*NORMSDIST({_d(F, K, t, '-')}))"


def put_x(F, K, t):
    return f"EXP(-RD*{t})*({K}*NORMSDIST(-{_d(F, K, t, '-')})-{F}*NORMSDIST(-{_d(F, K, t, '+')}))"


def newton_x(K, F, t, target):
    deriv = f"EXP(-RD*{t})*NORMSDIST(-{_d(F, K, t, '-')})"
    return f"={K}-({put_x(F, K, t)}-{target})/({deriv})"


def build(cfg: dict, out: Path, py: dict | None = None, charts: dict | None = None):
    wb = Workbook()
    ws_cov = wb.active
    ws_cov.title = "Cover"
    sheets = {n: wb.create_sheet(n) for n in ["Inputs", "Exposure", "Pricing", "Solver", "Scenarios", "Translation",
                                             "Backtest", "Monte Carlo", "Rates 2026", "Summary"]}
    m, c, s, bt = cfg["market"], cfg["company"], cfg["strategies"], cfg["backtest"]

    # ======================= INPUTS =======================
    ws = sheets["Inputs"]
    title(ws, "Inputs", "Blue = input you can change  |  Yellow = key lever  |  $ million and ₹ crore unless stated")
    ws.column_dimensions["A"].width = 50
    ws.column_dimensions["B"].width = 13
    ws.column_dimensions["C"].width = 80
    row = [3]

    def sec(text):
        row[0] += 1
        section(ws, row[0], text, 3)
        row[0] += 1

    def sc(label, value, nm, fmt, note="", key=False):
        r = row[0]
        put(ws, f"A{r}", label)
        put(ws, f"B{r}", value, BLUE_IN, fmt, fill=FILL_KEY if key else None, align="right")
        if note:
            put(ws, f"C{r}", note, GREY, italic=True, size=9)
        name(wb, nm, "Inputs", f"B{r}")
        row[0] += 1

    sec("Market (pricing date 22 Oct 2026)")
    sc("USD/INR spot", m["spot"], "Spot", NUM4, "Bank of England reference rate, 22 Oct 2026", key=True)
    sc("INR rate (1-year, annual)", m["inr_rate"], "INR_Rate", PCT2, "364-day T-bill cut-off, 14 Oct 2026")
    sc("USD rate (1-year, annual)", m["usd_rate"], "USD_Rate", PCT2, "Fed funds 3.75-4.00% midpoint (assumption)")
    sc("USD/INR volatility", m["vol"], "Vol", PCT, "Realised 2026: 5.5% YTD, 4.0% last 60 days (see Rates 2026)", key=True)
    sc("RBI Foreign Exchange Risk Reserve", m["ferr_reserve"], "FERR_Reserve", PCT, "20% of INR notional in cash with RBI, from 10 Oct 2026")
    sc("Share of reserve cost passed to IndiGo", m["ferr_passthrough"], "FERR_Pass", PCT, "Assumption: 0 = bank absorbs it, 100% = fully passed on", key=True)
    sec("IndiGo exposure (annual run-rate, H1 FY27 x 2)")
    sc("Revenue from operations (₹ crore)", c["revenue_inr"], "Revenue", NUM, "Q1 24,584.1 + Q2 23,363.8, annualised")
    sc("Fuel cost (₹ crore)", c["fuel_inr"], "Fuel", NUM, "Q1 10,832.9 + Q2 9,966.8, annualised")
    sc("Share of fuel cost linked to USD", c["fuel_usd_linked"], "Fuel_Linked", PCT, "ATF priced at import parity; taxes mostly ad valorem (assumption)")
    sc("Lease rentals and maintenance paid in USD ($ mn)", c["lease_maint_usd"], "Lease_Maint", NUM, "Estimate from lease liabilities of ₹53,756 crore (~$5.7 bn)", key=True)
    sc("Other USD costs ($ mn)", c["other_usd"], "Other_USD", NUM, "Overseas airport, navigation, handling, parts (estimate)")
    sc("International share of capacity", c["international_share"], "Intl_Share", PCT, "~30% (management, Aug 2026)")
    sc("Share of international revenue collected in FX", c["fx_collected_share"], "FX_Collected", PCT, "Assumption")
    sec("Balance-sheet exposure")
    sc("Net USD liabilities ($ mn)", c["net_usd_liabilities"], "Net_USD_Liab", NUM, "'Nearly $10 billion' (management, May 2026)")
    sc("Existing hedge book ($ mn)", c["hedge_book_usd"], "Hedge_Book", NUM, "~$1.3 bn hedged (May 2026)")
    sc("Tax rate", c["tax_rate"], "Tax_Rate", PCT2)
    sec("Hedge structures")
    sc("Collar call strike (x forward)", s["collar_call_moneyness"], "Collar_M", NUM4, "Put strike is solved for zero net premium (Solver tab)")
    sc("Seagull upper call strike (x forward)", s["seagull_upper"], "Seagull_Up", NUM4, "Buy call at forward, sell call here, sell put solved for zero cost")
    for i, rt in enumerate(s["layered"]["ratios"]):
        sc(f"Layered policy hedge ratio, months {3*i+1}-{3*i+3}", rt, f"Lay_Q{i+1}", PCT, key=(i == 0))
    sc("Layered policy: share of hedge in forwards", s["layered"]["forward_share"], "Fwd_Share", PCT, "Rest in zero-cost collars")
    sec("Back-test (hedges placed 2 Jan 2026)")
    sc("USD/INR on 2 Jan 2026", float(load_rates().iloc[0]), "BT_S0", NUM4, "BoE reference rate")
    sc("1-year forward premium at the time (annual)", bt["forward_premium"], "BT_Prem", PCT2, "Dec 2025 market data point")

    # ======================= EXPOSURE =======================
    ws = sheets["Exposure"]
    title(ws, "Exposure", "12-month USD flows, $ million")
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 60
    items = [
        ("Fuel, USD-linked", "=Fuel*Fuel_Linked*10/Spot", "₹ crore x linked share / spot", "Fuel_USD"),
        ("Lease rentals and maintenance", "=Lease_Maint", "", None),
        ("Other USD costs", "=Other_USD", "", None),
        ("Gross USD payments", "=SUM(B5:B7)", "", "Gross_USD"),
        ("Less: revenue collected in foreign currency", "=Revenue*Intl_Share*FX_Collected*10/Spot", "Natural hedge", "FX_Rev"),
        ("Net USD payable, next 12 months", "=B8-B9", "", "Net_USD"),
        ("Natural hedge ratio", "=B9/B8", "", None),
        ("Monthly net USD payable", "=Net_USD/12", "Settled at each month end", "Monthly_USD"),
        ("Net payable at spot (₹ crore)", "=Net_USD*Spot/10", "", None),
    ]
    header(ws, 4, ["Line", "Value", "Note"])
    for i, (lab, f, note, nm) in enumerate(items):
        r = 5 + i
        bold = lab.startswith(("Gross", "Net USD"))
        put(ws, f"A{r}", lab, bold=bold)
        put(ws, f"B{r}", f, fmt=PCT if "ratio" in lab else NUM1, bold=bold)
        put(ws, f"C{r}", note, GREY, italic=True, size=9)
        if nm:
            name(wb, nm, "Exposure", f"B{r}")
    if charts and "exposure" in charts:
        img = XLImage(str(charts["exposure"]))
        img.width, img.height = 640, 307
        ws.add_image(img, "A16")

    # ======================= PRICING =======================
    ws = sheets["Pricing"]
    title(ws, "Pricing", "Forwards by covered interest parity; options by Garman-Kohlhagen (₹ per $)")
    put(ws, "A3", "INR rate (continuous)")
    put(ws, "B3", "=LN(1+INR_Rate)", fmt=PCT2)
    name(wb, "RD", "Pricing", "B3")
    put(ws, "C3", "USD rate (continuous)")
    put(ws, "D3", "=LN(1+USD_Rate)", fmt=PCT2)
    name(wb, "RF", "Pricing", "D3")
    cols = ["Month", "t (years)", "Forward", "RBI reserve cost", "Forward all-in", "ATM call premium",
            "Collar call strike", "Call premium", "Collar put strike", "Put premium", "Net premium",
            "Seagull K1", "Seagull K2", "Call spread premium", "Seagull put strike", "Seagull net premium",
            "Monthly USD ($ mn)", "Layered hedge ratio"]
    header(ws, 5, cols)
    for i, w in enumerate([8, 10, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 11, 12, 11, 12, 12, 12]):
        ws.column_dimensions[L(i + 1)].width = w
    for k in range(MONTHS):
        r = R0 + k
        t, F = f"B{r}", f"C{r}"
        put(ws, f"A{r}", k + 1, fmt="0")
        put(ws, t, f"=A{r}/12", fmt=NUM4)
        put(ws, F, f"=Spot*EXP((RD-RF)*{t})", fmt=NUM4)
        put(ws, f"D{r}", f"=FERR_Pass*FERR_Reserve*{F}*(EXP(RD*{t})-1)", fmt=NUM4)
        put(ws, f"E{r}", f"={F}+D{r}", fmt=NUM4, bold=True)
        put(ws, f"F{r}", "=" + call_x(F, F, t), fmt=NUM4)
        put(ws, f"G{r}", f"=Collar_M*{F}", fmt=NUM4)
        put(ws, f"H{r}", "=" + call_x(F, f"G{r}", t), fmt=NUM4)
        put(ws, f"I{r}", f"=Solver!{L(3 + NEWTON)}{r}", fmt=NUM4, bold=True)
        put(ws, f"J{r}", "=" + put_x(F, f"I{r}", t), fmt=NUM4)
        put(ws, f"K{r}", f"=H{r}-J{r}", fmt=NUM4)
        put(ws, f"L{r}", f"={F}", fmt=NUM4)
        put(ws, f"M{r}", f"=Seagull_Up*{F}", fmt=NUM4)
        put(ws, f"N{r}", "=" + call_x(F, f"L{r}", t) + "-" + call_x(F, f"M{r}", t), fmt=NUM4)
        put(ws, f"O{r}", f"=Solver!{L(3 + NEWTON)}{r + 16}", fmt=NUM4, bold=True)
        put(ws, f"P{r}", f"=N{r}-" + put_x(F, f"O{r}", t), fmt=NUM4)
        put(ws, f"Q{r}", "=Monthly_USD", fmt=NUM1)
        put(ws, f"R{r}", f"=CHOOSE(INT((A{r}-1)/3)+1,Lay_Q1,Lay_Q2,Lay_Q3,Lay_Q4)", fmt=PCT)
    last = R0 + MONTHS - 1
    put(ws, f"A{last + 2}", "Net premium columns should be ~0: structures are zero-cost (no net premium received, as RBI requires).",
        GREY, italic=True, size=9)
    put(ws, f"A{last + 3}", "Check: zero-cost structures", bold=True)
    put(ws, f"F{last + 3}", f'=IF(MAX(MAX(K{R0}:K{last}),-MIN(K{R0}:K{last}),MAX(P{R0}:P{last}),-MIN(P{R0}:P{last}))<0.0001,"OK","CHECK")', bold=True)
    ws.conditional_formatting.add(f"F{last + 3}", CellIsRule(operator="equal", formula=['"OK"'], font=Font(color=GREEN, bold=True)))

    # ======================= SOLVER =======================
    ws = sheets["Solver"]
    title(ws, "Solver", "Newton's method finds the put strike whose premium equals the target (zero net premium)")
    for block, (label, target_col, start) in enumerate([("Collar put strike", "H", R0), ("Seagull put strike", "N", R0 + 16)]):
        hr = start - 1
        section(ws, hr - 1, label, 3 + NEWTON)
        header(ws, hr, ["Month", "Target premium", "Start (forward)"] + [f"Iter {i+1}" for i in range(NEWTON)])
        for k in range(MONTHS):
            r, pr = start + k, R0 + k
            F, t = f"Pricing!$C${pr}", f"Pricing!$B${pr}"
            put(ws, f"A{r}", k + 1, fmt="0")
            put(ws, f"B{r}", f"=Pricing!{target_col}{pr}", fmt=NUM4)
            put(ws, f"C{r}", f"={F}", fmt=NUM4)
            for it in range(NEWTON):
                prev = f"{L(3 + it)}{r}"
                put(ws, f"{L(4 + it)}{r}", newton_x(prev, F, t, f"$B{r}"), fmt=NUM4)
    for i in range(1, 4 + NEWTON):
        ws.column_dimensions[L(i)].width = 12

    # ======================= SCENARIOS =======================
    ws = sheets["Scenarios"]
    levels = cfg["scenario_levels"]
    title(ws, "Scenarios", "Total 12-month cost (₹ crore) if USD/INR sits at a flat level at every settlement")
    ws.column_dimensions["A"].width = 26
    lc = [L(2 + j) for j in range(len(levels))]
    header(ws, 4, ["USD/INR level"] + [""] * len(levels))
    for j, lv in enumerate(levels):
        put(ws, f"{lc[j]}4", lv, "FFFFFF", NUM1, bold=True, fill=FILL_HDR, align="center")
        name(wb, f"Level_{j+1}", "Scenarios", f"{lc[j]}4")
    block0 = 16
    blocks = {st: block0 + b * (MONTHS + 3) + 1 for b, st in enumerate(STRATEGIES)}
    for b, strat in enumerate(STRATEGIES):
        top = block0 + b * (MONTHS + 3)
        section(ws, top - 1, f"{strat}: ₹ per $ by month", 1 + len(levels))
        for k in range(MONTHS):
            r, pr = top + 1 + k, R0 + k
            put(ws, f"A{r}", f"Month {k+1}", GREY)
            for j in range(len(levels)):
                lvl = f"{lc[j]}$4"
                P = lambda col: f"Pricing!${col}${pr}"  # noqa: E731
                f = {
                    "Unhedged": f"={lvl}",
                    "Forward 100%": f"={P('E')}",
                    "Forward 50%": f"=0.5*{P('E')}+0.5*{lvl}",
                    "USD call (ATM forward)": f"=MIN({lvl},{P('C')})+{P('F')}*EXP(RD*{P('B')})+{P('D')}",
                    "Zero-cost collar": f"=MAX({P('I')},MIN({lvl},{P('G')}))+{P('D')}",
                    "Seagull": f"=MAX({lvl},{P('O')})-MAX({lvl}-{P('L')},0)+MAX({lvl}-{P('M')},0)+{P('D')}",
                    "Layered policy": (f"={P('R')}*Fwd_Share*{P('E')}+{P('R')}*(1-Fwd_Share)*{lc[j]}{blocks['Zero-cost collar'] + k}"
                                       f"+(1-{P('R')})*{lvl}"),
                }[strat]
                put(ws, f"{lc[j]}{r}", f, fmt=NUM2)
    for b, strat in enumerate(STRATEGIES):
        r = 5 + b
        put(ws, f"A{r}", strat, bold=strat == "Layered policy")
        first = blocks[strat]
        for j in range(len(levels)):
            put(ws, f"{lc[j]}{r}", f"=SUMPRODUCT(Pricing!$Q${R0}:$Q${last},{lc[j]}{first}:{lc[j]}{first + MONTHS - 1})/10",
                fmt=NUM, bold=strat == "Layered policy")
    for col in lc:
        ws.column_dimensions[col].width = 12

    # ======================= TRANSLATION =======================
    ws = sheets["Translation"]
    title(ws, "Translation", "Reported FX loss on USD liabilities when USD/INR moves between reporting dates (₹ crore)")
    ws.column_dimensions["A"].width = 40
    put(ws, "A4", "FX loss per ₹1 move (gross)")
    put(ws, "B4", "=Net_USD_Liab/10", fmt=NUM, bold=True)
    put(ws, "A5", "Offset from existing hedge book per ₹1")
    put(ws, "B5", "=-Hedge_Book/10", fmt=NUM)
    put(ws, "A6", "Net per ₹1 move")
    put(ws, "B6", "=B4+B5", fmt=NUM, bold=True)
    put(ws, "A7", "Check: Q2 FY26 loss ~₹2,900 crore on a ₹3.18 move implies ($ bn)")
    put(ws, "B7", "=2900/3.18/100", fmt=NUM1)
    header(ws, 9, ["Move in USD/INR (₹)", "Gross loss", "Hedge offset", "Net loss", "After tax"])
    for i, mv in enumerate([-5, -2.5, -1, 1, 2.5, 5, 10]):
        r = 10 + i
        put(ws, f"A{r}", mv, BLUE_IN, '+0.0;-0.0')
        put(ws, f"B{r}", f"=$B$4*A{r}", fmt=NUM)
        put(ws, f"C{r}", f"=$B$5*A{r}", fmt=NUM)
        put(ws, f"D{r}", f"=B{r}+C{r}", fmt=NUM, bold=True)
        put(ws, f"E{r}", f"=D{r}*(1-Tax_Rate)", fmt=NUM)
    for col in "BCDE":
        ws.column_dimensions[col].width = 13

    # ======================= BACKTEST =======================
    ws = sheets["Backtest"]
    title(ws, "Backtest", "Hedges placed on 2 Jan 2026 for the Jan-Oct 2026 payments; settled at each month's last fixing")
    py_bt = (py or {}).get("backtest")
    header(ws, 4, ["Month", "t", "Settlement rate", "Forward (2 Jan)", "Monthly USD", "Unhedged (₹ cr)",
                   "Forward 100% (₹ cr)", "Forward 50% (₹ cr)"])
    settle = py_bt["settle"] if py_bt else None
    for k in range(bt["months"]):
        r = 5 + k
        put(ws, f"A{r}", settle.index[k].strftime("%b %Y") if settle is not None else k + 1)
        put(ws, f"B{r}", f"={k + 1}/12", fmt=NUM4)
        put(ws, f"C{r}", float(settle.iloc[k]) if settle is not None else None, BLUE_IN, NUM4)
        put(ws, f"D{r}", f"=BT_S0*EXP(LN(1+BT_Prem)*B{r})", fmt=NUM4)
        put(ws, f"E{r}", "=Monthly_USD", fmt=NUM1)
        put(ws, f"F{r}", f"=E{r}*C{r}/10", fmt=NUM)
        put(ws, f"G{r}", f"=E{r}*D{r}/10", fmt=NUM)
        put(ws, f"H{r}", f"=E{r}*(0.5*C{r}+0.5*D{r})/10", fmt=NUM)
    tr = 5 + bt["months"]
    put(ws, f"A{tr}", "Total", bold=True)
    for col in "FGH":
        put(ws, f"{col}{tr}", f"=SUM({col}5:{col}{tr - 1})", fmt=NUM, bold=True)
    put(ws, f"A{tr + 1}", "Saving vs unhedged", bold=True)
    for col in "GH":
        put(ws, f"{col}{tr + 1}", f"=$F${tr}-{col}{tr}", fmt=NUM, bold=True, color=GREEN)
    if py_bt:
        put(ws, f"A{tr + 3}", "[Python] Option strategies, same back-test (₹ crore)", NAVY, bold=True)
        header(ws, tr + 4, ["Strategy", "Total cost", "Average ₹/$", "Saving vs unhedged"])
        for i, k in enumerate(STRATEGIES):
            r = tr + 5 + i
            put(ws, f"A{r}", k, fill=FILL_PY)
            put(ws, f"B{r}", py_bt["totals"][k], fmt=NUM, fill=FILL_PY)
            put(ws, f"C{r}", py_bt["avg_rate"][k], fmt=NUM2, fill=FILL_PY)
            put(ws, f"D{r}", py_bt["saving_vs_unhedged"][k], fmt=NUM, fill=FILL_PY)
    for i, w in enumerate([24, 9, 14, 14, 12, 15, 17, 17]):
        ws.column_dimensions[L(i + 1)].width = w

    # ======================= MONTE CARLO =======================
    ws = sheets["Monte Carlo"]
    title(ws, "Monte Carlo [Python]", "10,000 simulated USD/INR paths; total 12-month cost, ₹ crore")
    ws.column_dimensions["A"].width = 26
    r = 4
    if py and "mc" in py:
        put(ws, f"A{r}", "Budget (strip at today's forwards, before reserve cost)", bold=True)
        put(ws, f"D{r}", py["mc"]["budget"], fmt=NUM, fill=FILL_PY)
        r += 2
        cols_mc = ["Expected cost", "vs budget", "Std dev", "P5", "P95", "P99", "Cost-at-risk (P95 - mean)", "Variance reduction"]
        for key, sc_ in py["mc"]["scenarios"].items():
            section(ws, r, sc_["label"], 1 + len(cols_mc))
            header(ws, r + 1, ["Strategy"] + cols_mc)
            for i, k in enumerate(STRATEGIES):
                rr = r + 2 + i
                put(ws, f"A{rr}", k, fill=FILL_PY)
                for j, col in enumerate(cols_mc):
                    put(ws, f"{L(2 + j)}{rr}", float(sc_["table"].loc[k, col]), fmt=PCT if col == "Variance reduction" else NUM,
                        fill=FILL_PY)
            r += len(STRATEGIES) + 3
        for j in range(len(cols_mc)):
            ws.column_dimensions[L(2 + j)].width = 14

    # ======================= RATES 2026 =======================
    ws = sheets["Rates 2026"]
    title(ws, "Rates 2026", "Bank of England USD/INR reference rates; realised volatility from daily log returns")
    rates = load_rates()
    header(ws, 7, ["Date", "USD/INR", "Log return"])
    for i, (d, v) in enumerate(rates.items()):
        r = 8 + i
        put(ws, f"A{r}", d.date(), fmt="dd-mmm-yy")
        put(ws, f"B{r}", float(v), BLUE_IN, NUM4)
        if i:
            put(ws, f"C{r}", f"=LN(B{r}/B{r-1})", fmt="0.0000%")
    end = 7 + len(rates)
    put(ws, "A4", "Realised vol, 2026 YTD (annualised)")
    put(ws, "C4", f"=STDEV(C9:C{end})*SQRT(252)", fmt=PCT2, bold=True)
    put(ws, "A5", "Realised vol, last 60 days")
    put(ws, "C5", f"=STDEV(C{end - 59}:C{end})*SQRT(252)", fmt=PCT2, bold=True)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 12
    ws.column_dimensions["C"].width = 12

    # ======================= SUMMARY =======================
    ws = sheets["Summary"]
    title(ws, "Summary", "Key outputs (live)")
    ws.column_dimensions["A"].width = 52
    ws.column_dimensions["B"].width = 16
    lines = [
        ("Net 12-month USD payable ($ mn)", "=Net_USD", NUM),
        ("Natural hedge from USD revenue", "=Exposure!B11", PCT),
        ("12-month forward", f"=Pricing!C{last}", NUM2),
        ("12-month forward premium", f"=Pricing!C{last}/Spot-1", PCT2),
        ("RBI reserve cost, 12-month (₹ per $)", f"=Pricing!D{last}", NUM2),
        ("12-month ATM call premium (₹ per $)", f"=Pricing!F{last}", NUM2),
        ("12-month zero-cost collar: put / call strike", f'=TEXT(Pricing!I{last},"0.00")&" / "&TEXT(Pricing!G{last},"0.00")', None),
        ("Layered policy: average hedge ratio", "=AVERAGE(Lay_Q1,Lay_Q2,Lay_Q3,Lay_Q4)", PCT),
        ("Layered policy: USD hedged ($ mn)", f"=SUMPRODUCT(Pricing!Q{R0}:Q{last},Pricing!R{R0}:R{last})", NUM),
        ("Cost at USD/INR 105, unhedged (₹ crore)", f"=Scenarios!{lc[-1]}5", NUM),
        ("Cost at USD/INR 105, layered policy (₹ crore)", f"=Scenarios!{lc[-1]}11", NUM),
        ("Translation: FX loss per ₹1 move (₹ crore)", "=Translation!B4", NUM),
        ("Back-test saving, forwards Jan-Oct 2026 (₹ crore)", f"=Backtest!G{tr + 1}", NUM),
    ]
    for i, (lab, f, fmt) in enumerate(lines):
        put(ws, f"A{4 + i}", lab)
        put(ws, f"B{4 + i}", f, fmt=fmt, bold=True, align="right")

    # ======================= COVER =======================
    ws = ws_cov
    title(ws, "IndiGo (InterGlobe Aviation): USD/INR hedging analysis",
          "Learning exercise, not investment or hedging advice. Pricing date 22 Oct 2026.")
    ws.column_dimensions["A"].width = 22
    ws.column_dimensions["B"].width = 100
    notes = [
        ("Question", "How should India's largest airline hedge the rupee, and what does each choice cost?"),
        ("Inputs", "All assumptions, with sources. Blue cells can be changed; everything else recalculates."),
        ("Exposure", "12-month net USD payable: USD-linked fuel + leases + other, less USD revenue."),
        ("Pricing", "Forwards (interest parity), RBI reserve cost, option premiums (Garman-Kohlhagen), zero-cost strikes."),
        ("Solver", "Newton iterations that solve the zero-cost put strikes inside Excel."),
        ("Scenarios", "Total cost of each strategy if USD/INR sits at 90-105."),
        ("Translation", "Reported FX loss on USD lease liabilities per ₹1 move."),
        ("Backtest", "What forwards placed on 2 Jan 2026 would have saved through October."),
        ("Monte Carlo", "[Python] 10,000 paths, three rupee regimes: risk vs cost of each strategy."),
        ("Rates 2026", "Daily USD/INR and realised volatility."),
        ("Colour key", "Blue = input; black = formula; orange fill = pasted from Python; yellow = key lever."),
    ]
    for i, (a_, b_) in enumerate(notes):
        put(ws, f"A{4 + i}", a_, NAVY, bold=True)
        put(ws, f"B{4 + i}", b_)

    wb.move_sheet("Summary", offset=-(len(wb.sheetnames) - 2))
    wb.save(out)
    return out


def main():
    cfg = load_config()
    py = {"mc": monte_carlo(cfg), "backtest": backtest(cfg)}
    img = ROOT / "docs" / "img"
    charts = {"exposure": img / "exposure.png"} if (img / "exposure.png").exists() else None
    out = build(cfg, ROOT / "IndiGo_FX_Hedging_Model.xlsx", py, charts)
    print("wrote", out)


if __name__ == "__main__":
    main()
