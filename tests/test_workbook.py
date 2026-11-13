"""The Excel workbook and the Python model must agree after changing inputs in the workbook."""
import copy
import shutil
import subprocess

import numpy as np
import pytest
from openpyxl import load_workbook

from fxhedge.analysis import scenario_grid
from fxhedge.model import STRATEGIES, load_config, price_book
from scripts.build_workbook import build

SOFFICE = shutil.which("soffice") or shutil.which("libreoffice")
pytestmark = pytest.mark.skipif(SOFFICE is None, reason="LibreOffice not installed")


@pytest.fixture(scope="module")
def template(tmp_path_factory):
    path = tmp_path_factory.mktemp("wb") / "model.xlsx"
    build(load_config(), path)
    return path


def _set(wb, nm, value):
    sheet, ref = list(wb.defined_names[nm].destinations)[0]
    wb[sheet][ref.replace("$", "")] = value


def _with(**kw):
    def apply(c):
        for path, v in kw.items():
            node = c
            *keys, last = path.split(".")
            for k in keys:
                node = node[int(k)] if k.isdigit() else node[k]
            node[int(last) if last.isdigit() else last] = v
        return c
    return apply


CASES = [
    ("base", {}, _with()),
    ("weaker rupee, higher vol", {"Spot": 98.5, "Vol": 0.09}, _with(**{"market.spot": 98.5, "market.vol": 0.09})),
    ("full reserve pass-through", {"FERR_Pass": 1.0, "INR_Rate": 0.07},
     _with(**{"market.ferr_passthrough": 1.0, "market.inr_rate": 0.07})),
    ("bigger exposure, wider collar", {"Lease_Maint": 2600, "Collar_M": 1.04, "Fuel_Linked": 1.0},
     _with(**{"company.lease_maint_usd": 2600, "strategies.collar_call_moneyness": 1.04, "company.fuel_usd_linked": 1.0})),
    ("more hedging", {"Lay_Q1": 0.9, "Lay_Q4": 0.5, "Fwd_Share": 0.5},
     _with(**{"strategies.layered.ratios.0": 0.9, "strategies.layered.ratios.3": 0.5,
              "strategies.layered.forward_share": 0.5})),
]


@pytest.mark.parametrize("label,xl_changes,py_changes", CASES, ids=[c[0] for c in CASES])
def test_workbook_matches_python(template, tmp_path, label, xl_changes, py_changes):
    wb = load_workbook(template)
    for k, v in xl_changes.items():
        _set(wb, k, v)
    src = tmp_path / "in" / template.name
    src.parent.mkdir()
    wb.save(src)
    subprocess.run([SOFFICE, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(tmp_path), str(src)],
                   check=True, capture_output=True, timeout=180)
    calc = load_workbook(tmp_path / template.name, data_only=True)

    cfg = py_changes(copy.deepcopy(load_config()))

    b = price_book(cfg)
    ws = calc["Pricing"]
    col = lambda c: np.array([ws[f"{c}{r}"].value for r in range(6, 18)], dtype=float)  # noqa: E731
    assert col("C") == pytest.approx(b.fwd, rel=1e-10)
    assert col("D") == pytest.approx(b.ferr, rel=1e-9, abs=1e-12)
    assert col("F") == pytest.approx(b.call_atm, rel=1e-9)
    assert col("I") == pytest.approx(b.collar_put_k, rel=1e-9)
    assert col("O") == pytest.approx(b.seagull_put_k, rel=1e-9)
    assert ws["F20"].value == "OK"

    grid = scenario_grid(cfg)
    sc = calc["Scenarios"]
    for i, strat in enumerate(STRATEGIES):
        xl = [sc.cell(5 + i, 2 + j).value for j in range(len(grid))]
        assert xl == pytest.approx(grid[strat].values.tolist(), rel=1e-9), strat
