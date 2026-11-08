"""Build excel/tco_model.xlsx: the TCO model written as live Excel formulas.

Every number on the vehicle sheets is a formula that points at the Inputs sheet, so the
workbook can be opened in an interview and changed by hand. tests/test_tco.py recalculates
it with LibreOffice and checks that each total matches drivecost.tco to the cent.

    python -m drivecost.excel_model            # writes excel/tco_model.xlsx
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter

from drivecost.tco import HST, Assumptions, Vehicle, default_assumptions, memo_vehicles

OUT = Path(__file__).resolve().parents[1] / "excel" / "tco_model.xlsx"
BLUE = Font(color="0000CC")
BOLD = Font(bold=True)
HEAD = PatternFill("solid", fgColor="DDE7F0")

GLOBAL_LABELS = {
    "years": "Horizon (years) - workbook fixed at 5", "km_per_year": "Kilometres per year",
    "policy_rate": "Bank of Canada policy rate (%)", "loan_spread": "Loan spread over policy (%-pts)",
    "lease_spread": "Lease spread over policy (%-pts)", "down_payment": "Down payment ($, incl. HST on lease)",
    "loan_term_months": "Loan term (months)", "lease_term_months": "Lease term (months) - must be 60 here",
    "lease_acquisition_fee": "Lease acquisition fee ($)", "lease_km_allowance": "Lease km allowance / year",
    "lease_excess_per_km": "Lease excess km charge ($/km)", "gas_cpl": "Gasoline, year 1 (cents/L)",
    "gas_growth": "Gasoline price growth / yr", "elec_per_kwh": "Electricity, year 1 ($/kWh)",
    "elec_growth": "Electricity price growth / yr", "insurance_growth": "Insurance growth / yr",
    "maintenance_growth": "Maintenance growth / yr", "winter_tires": "Winter tires ($, year 0)",
    "discount_rate": "Discount rate (savings rate)",
}
VEHICLE_FIELDS = ["powertrain", "price", "rebate", "l_per_100km", "kwh_per_100km", "insurance",
                  "maintenance", "charger"]


def build(vehicles: list[Vehicle], a: Assumptions, path: Path = OUT) -> Path:
    if a.years != 5 or a.lease_term_months != 60:
        raise ValueError("the workbook layout assumes a 5-year horizon and a 60-month lease")
    wb = Workbook()
    ws = wb.active
    ws.title = "Inputs"
    ws["A1"] = "Inputs (blue = change me)"
    ws["A1"].font = BOLD
    ws["A2"], ws["B2"] = "HST", HST
    G = {"hst": "Inputs!$B$2"}
    r = 3
    for key, label in GLOBAL_LABELS.items():
        ws.cell(r, 1, label)
        c = ws.cell(r, 2, getattr(a, key))
        c.font = BLUE
        G[key] = f"Inputs!$B${r}"
        r += 1

    r += 1
    ws.cell(r, 1, "Vehicle inputs").font = BOLD
    for j, v in enumerate(vehicles):
        ws.cell(r, 2 + j, v.name).font = BOLD
    r += 1
    V: dict[str, dict[str, str]] = {v.name: {} for v in vehicles}
    for fld in VEHICLE_FIELDS + [f"retention_{k}" for k in range(1, 6)]:
        ws.cell(r, 1, fld)
        for j, v in enumerate(vehicles):
            col = get_column_letter(2 + j)
            val = v.retention[int(fld[-1]) - 1] if fld.startswith("retention_") else getattr(v, fld)
            ws.cell(r, 2 + j, val).font = BLUE
            V[v.name][fld] = f"Inputs!${col}${r}"
        r += 1
    for j, v in enumerate(vehicles):
        col = get_column_letter(2 + j)
        V[v.name]["retention_range"] = f"Inputs!${col}${r - 5}:${col}${r - 1}"
    ws.column_dimensions["A"].width = 42
    for j in range(len(vehicles)):
        ws.column_dimensions[get_column_letter(2 + j)].width = 24

    summary_refs = {}
    for idx, v in enumerate(vehicles, 1):
        summary_refs[v.name] = _vehicle_sheet(wb, f"Car{idx}", v.name, G, V[v.name])

    s = wb.create_sheet("Summary", 0)
    s["A1"] = "5-year total cost of ownership (nominal $, net of resale) and NPV"
    s["A1"].font = BOLD
    hdr = ["Vehicle", "Cash", "Finance", "Lease", "Cash NPV", "Finance NPV", "Lease NPV"]
    for j, h in enumerate(hdr, 1):
        s.cell(3, j, h).font = BOLD
        s.cell(3, j).fill = HEAD
    for i, v in enumerate(vehicles):
        s.cell(4 + i, 1, v.name)
        for j, key in enumerate(["cash", "finance", "lease", "cash_npv", "finance_npv", "lease_npv"]):
            c = s.cell(4 + i, 2 + j, f"={summary_refs[v.name][key]}")
            c.number_format = "#,##0"
    s.column_dimensions["A"].width = 28
    for j in range(2, 8):
        s.column_dimensions[get_column_letter(j)].width = 13
    wb.calculation.fullCalcOnLoad = True  # Excel recalculates every formula on open
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    return path


def _vehicle_sheet(wb: Workbook, title: str, name: str, G: dict, V: dict) -> dict:
    ws = wb.create_sheet(title)
    ws["A1"] = name
    ws["A1"].font = BOLD
    ws["A2"] = (f"Net price (after rebate): ")
    ws["C2"] = f"={V['price']}-{V['rebate']}"
    ws["A3"] = "Resale value end of year 5"
    ws["C3"] = f"=C2*INDEX({V['retention_range']},{G['years']})"
    ws["E2"], ws["F2"] = "Loan principal", f"=C2*(1+{G['hst']})-{G['down_payment']}"
    ws["E3"], ws["F3"] = "Loan payment / month", f"=PMT(({G['policy_rate']}+{G['loan_spread']})/1200,{G['loan_term_months']},-F2)"
    ws["H2"], ws["I2"] = "Lease cap cost", f"=C2+{G['lease_acquisition_fee']}-{G['down_payment']}/(1+{G['hst']})"
    ws["H3"], ws["I3"] = "Lease residual", f"=C2*INDEX({V['retention_range']},{G['lease_term_months']}/12)"
    ws["K2"], ws["L2"] = "Lease APR", f"=({G['policy_rate']}+{G['lease_spread']})/100"
    ws["K3"], ws["L3"] = "Lease payment incl. HST / month", \
        f"=((I2-I3)/{G['lease_term_months']}+(I2+I3)*L2/24)*(1+{G['hst']})"
    for ref in ("C2", "C3", "F2", "F3", "I2", "I3", "L3"):
        ws[ref].number_format = "#,##0.00"

    cols = ["Year", "Energy", "Insurance", "Maintenance", "Other (tires/charger)",
            "Cash: purchase", "Cash: resale", "Finance: payments", "Finance: resale less payoff",
            "Lease: payments", "Lease: excess km", "Discount factor", "Operating total",
            "Cash net", "Finance net", "Lease net"]
    hr = 5
    for j, h in enumerate(cols, 1):
        ws.cell(hr, j, h).font = BOLD
        ws.cell(hr, j).fill = HEAD
        ws.column_dimensions[get_column_letter(j)].width = 16
    first, last = hr + 1, hr + 6
    for t in range(6):
        r = first + t
        A = f"A{r}"
        ws[A] = t
        ws[f"B{r}"] = (f"=IF({A}=0,0,{G['km_per_year']}/100*IF({V['powertrain']}=\"BEV\","
                       f"{V['kwh_per_100km']}*{G['elec_per_kwh']}*(1+{G['elec_growth']})^({A}-1),"
                       f"{V['l_per_100km']}*{G['gas_cpl']}/100*(1+{G['gas_growth']})^({A}-1)))")
        ws[f"C{r}"] = f"=IF({A}=0,0,{V['insurance']}*(1+{G['insurance_growth']})^({A}-1))"
        ws[f"D{r}"] = f"=IF({A}=0,0,{V['maintenance']}*(1+{G['maintenance_growth']})^({A}-1))"
        ws[f"E{r}"] = f"=IF({A}=0,{G['winter_tires']}+{V['charger']},0)"
        ws[f"F{r}"] = f"=IF({A}=0,$C$2*(1+{G['hst']}),0)"
        ws[f"G{r}"] = f"=IF({A}={G['years']},-$C$3,0)"
        months = f"MAX(0,MIN(12,{G['loan_term_months']}-12*({A}-1)))"
        ws[f"H{r}"] = f"=IF({A}=0,{G['down_payment']},$F$3*{months})"
        rate = f"({G['policy_rate']}+{G['loan_spread']})/1200"
        payoff = (f"IF(12*{G['years']}>={G['loan_term_months']},0,"
                  f"-FV({rate},12*{G['years']},-$F$3,$F$2))")
        ws[f"I{r}"] = f"=IF({A}={G['years']},-$C$3+{payoff},0)"
        lmonths = f"MAX(0,MIN(12,{G['lease_term_months']}-12*({A}-1)))"
        ws[f"J{r}"] = f"=IF({A}=0,{G['down_payment']},$L$3*{lmonths})"
        ws[f"K{r}"] = (f"=IF({A}={G['lease_term_months']}/12,MAX(0,({G['km_per_year']}-{G['lease_km_allowance']})"
                       f"*{G['lease_term_months']}/12)*{G['lease_excess_per_km']}*(1+{G['hst']}),0)")
        ws[f"L{r}"] = f"=(1+{G['discount_rate']})^-{A}"
        ws[f"M{r}"] = f"=SUM(B{r}:E{r})"
        ws[f"N{r}"] = f"=M{r}+F{r}+G{r}"
        ws[f"O{r}"] = f"=M{r}+H{r}+I{r}"
        ws[f"P{r}"] = f"=M{r}+J{r}+K{r}"
        for j in range(2, 17):
            ws.cell(r, j).number_format = "#,##0.00"
    tr = last + 1
    ws.cell(tr, 1, "Total").font = BOLD
    for j in range(2, 17):
        col = get_column_letter(j)
        if col != "L":
            ws[f"{col}{tr}"] = f"=SUM({col}{first}:{col}{last})"
            ws[f"{col}{tr}"].number_format = "#,##0.00"
            ws[f"{col}{tr}"].font = BOLD
    nr = tr + 1
    ws.cell(nr, 1, "NPV").font = BOLD
    for col in "NOP":
        ws[f"{col}{nr}"] = f"=SUMPRODUCT({col}{first}:{col}{last},$L${first}:$L${last})"
        ws[f"{col}{nr}"].number_format = "#,##0.00"
    q = f"'{title}'!"
    return {"cash": f"{q}N{tr}", "finance": f"{q}O{tr}", "lease": f"{q}P{tr}",
            "cash_npv": f"{q}N{nr}", "finance_npv": f"{q}O{nr}", "lease_npv": f"{q}P{nr}"}


def recalculated_values(path: Path = OUT) -> dict[str, dict[str, float]]:
    """Recalculate the workbook with headless LibreOffice and return the Summary table."""
    soffice = shutil.which("soffice") or shutil.which("libreoffice")
    if not soffice:
        raise RuntimeError("LibreOffice (soffice) is needed to recalculate the workbook")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run([soffice, "--headless", "--calc", "--convert-to", "xlsx", "--outdir", tmp, str(path)],
                       check=True, capture_output=True, timeout=180)
        wb = load_workbook(Path(tmp) / path.name, data_only=True)
    s = wb["Summary"]
    out = {}
    for row in s.iter_rows(min_row=4, values_only=True):
        if not row[0]:
            break
        out[row[0]] = dict(zip(["cash", "finance", "lease", "cash_npv", "finance_npv", "lease_npv"], row[1:7]))
    return out


if __name__ == "__main__":
    a = default_assumptions()
    p = build(memo_vehicles(), a)
    print(f"wrote {p}")
    for name, vals in recalculated_values(p).items():
        print(name, {k: round(v, 2) for k, v in vals.items()})
