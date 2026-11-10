"""Fill memo_template.md with numbers from reports/tables, render to HTML and print to memo.pdf.

    python memo/build_memo.py
Needs pandoc and the Playwright Chromium (node) that ships with the dev environment, or any
Chromium given in $CHROME.
"""
from __future__ import annotations

import datetime as dt
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
T = ROOT / "reports" / "tables"
MEMO = ROOT / "memo"

CSS = """
@page { size: Letter; margin: 0.45in 0.5in; }
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 9.2pt; line-height: 1.36; color: #111; }
h1 { font-size: 14pt; margin: 0 0 2px 0; color: #1f4e79; }
p { margin: 0 0 6px 0; text-align: justify; }
p:has(img) { display: flex; gap: 2%; margin: 4px 0 6px 0; }
img { height: auto; }
em { color: #444; }
"""


def k(x: float) -> str:
    return f"{x / 1000:.1f}"


def values() -> dict:
    from drivecost.tco import default_assumptions, memo_vehicles

    a = default_assumptions()
    tco = pd.read_csv(T / "tco_comparison.csv").set_index(["vehicle", "method"])
    H, G, E = "Toyota Corolla Hybrid", "Toyota Corolla LE (gas)", "Hyundai Kona Electric"
    gas, hev, ev = memo_vehicles()
    fr = pd.read_csv(T / "fuel_risk_by_car.csv").set_index(["vehicle", "model"])
    be = pd.read_csv(T / "breakevens_ev_vs_hybrid.csv", index_col=0)["value"]
    rs = pd.read_csv(T / "tco_rate_stress.csv")
    rs_h = rs[(rs.vehicle == H) & (rs.method == "finance")].set_index("shock_bp").npv
    tor = pd.read_csv(T / "tornado_ev_vs_hybrid.csv")
    pct = pd.read_csv(T / "fuel_price_percentiles_december.csv").set_index(["model", "month"])
    pt = pd.read_csv(T / "passthrough_tests.csv", index_col=0)["crude_cpl"]
    inf = pd.read_csv(T / "inflation_gasoline_annual.csv", index_col=0)
    hs = pd.read_csv(T / "hedge_summary.csv", index_col=0)["value"]
    mc = pd.read_csv(T / "hedge_margin_calls.csv")
    cs = pd.read_csv(T / "credit_stress_scenarios.csv").set_index("scenario")
    cb = pd.read_csv(T / "credit_stress_breakeven.csv")
    pm = pd.read_csv(T / "pricing_metrics.csv", index_col=0)["value"]
    pe = pd.read_csv(T / "pricing_example_premiums.csv")

    from statsmodels.tsa.stattools import adfuller
    from drivecost import risk
    import numpy as np
    phi, _, _ = risk.ar1_fit(risk.history())
    adf_p = adfuller(np.log(risk.history().values), result_object=False)[1]

    hev_cash = tco.loc[(H, "cash")]
    return dict(
        date=dt.date.today().strftime("%B %Y"),
        hev_cash_k=k(hev_cash.total), hev_cash_upfront_k=k(hev.price * 1.13),
        per_100bp=f"{rs_h[100] - rs_h[0]:,.0f}",
        gas_vs_hev=k(tco.loc[(G, "cash")].npv - hev_cash.npv), ev_vs_hev=k(tco.loc[(E, "cash")].npv - hev_cash.npv),
        hev_fin_month=f"{tco.loc[(H, 'finance')].per_month:,.0f}",
        hev_ins_k=k(hev_cash.insurance), hev_fuel_k=k(hev_cash.energy),
        loan_apr=f"{a.loan_apr * 100:.2f}", policy=f"{a.policy_rate:.2f}", disc=f"{a.discount_rate * 100:.1f}",
        hev_lease_npv_k=k(tco.loc[(H, "lease")].npv), hev_fin_npv_k=k(tco.loc[(H, "finance")].npv),
        hev_resale_k=k(-hev_cash.resale),
        base_gap_k=k(tco.loc[(E, "cash")].npv - hev_cash.npv),
        ev_be_k=k(be["ev_price_breakeven"]), ev_price_k=k(ev.price), gas_be=f"{be['gas_cpl_breakeven']:.0f}",
        km_be=f"{be['km_per_year_breakeven'] / 1000:.0f}",
        half_life=f"{np.log(0.5) / np.log(phi):.0f}",
        p50_2031=f"{pct.loc[('mean_reverting', '2031-12'), 'p50']:.0f}",
        p5_2031=f"{pct.loc[('mean_reverting', '2031-12'), 'p5']:.0f}",
        p95_2031=f"{pct.loc[('mean_reverting', '2031-12'), 'p95']:.0f}",
        rw_p95_2031=f"{pct.loc[('random_walk', '2031-12'), 'p95']:.0f}",
        hev_var=f"{fr.loc[(H, 'mean_reverting'), 'var95']:,.0f}", hev_mean=f"{fr.loc[(H, 'mean_reverting'), 'mean']:,.0f}",
        hev_es=f"{fr.loc[(H, 'mean_reverting'), 'es95']:,.0f}", gas_var=f"{fr.loc[(G, 'mean_reverting'), 'var95']:,.0f}",
        hev_var_rw=f"{fr.loc[(H, 'random_walk'), 'var95']:,.0f}", adf_p=f"{adf_p:.2f}",
        first_month=f"{float(pt['share_in_first_month']) * 100:.0f}", pt_crude=f"{float(pt['cum_symmetric']):.2f}",
        hl_pos=f"{float(pt['half_life_months_pos']):.0f}", hl_neg=f"{float(pt['half_life_months_neg']):.0f}",
        ecm_p=f"{float(pt['wald_ecm_adjust_eq_p']):.2f}",
        gas_cpi_2022=f"{inf.loc[2022, 'gasoline_contribution_pp']:+.1f}",
        gas_cpi_2026=f"{inf.loc[2026, 'gasoline_contribution_pp']:+.1f}",
        contracts=f"{hs['contracts_exact']:.1f}", h=f"{hs['hedge_ratio_full_sample']:.2f}",
        oos_vr=f"{hs['oos_variance_reduction'] * 100:.0f}",
        worst_u=k(hs["oos_worst_miss_unhedged_cad"]), worst_h=k(hs["oos_worst_miss_hedged_cad"]),
        margin_peak=f"{mc.peak_cumulative_outflow_cad.iloc[0] / 1000:.0f}",
        lev_30=f"{cs.loc['Fuel +30%, no surcharge', 'debt_to_ebitda']:.1f}",
        be_0=f"{cb[(cb.surcharge_recovery == 0) & (cb.rate_shock_bp == 0) & (cb.hedged_share == 0)].breakeven_fuel_rise.iloc[0] * 100:.0f}",
        gini=f"{pm['test_gini_pure_premium']:.2f}",
        young_x=f"{pe.vs_experienced.iloc[0]:.1f}", clean_x=f"{pe.vs_experienced.iloc[1]:.1f}",
        gas_price_k=k(gas.price), hev_price_k=k(hev.price), down=f"{a.down_payment:,.0f}",
        gas_cpl=f"{a.gas_cpl:.0f}", elec=f"{a.elec_per_kwh:.2f}",
    )


def chrome() -> str:
    if os.environ.get("CHROME"):
        return os.environ["CHROME"]
    for c in ("/opt/pw-browsers/chromium-1243/chrome-linux64/chrome", shutil.which("chromium"),
              shutil.which("google-chrome")):
        if c and Path(c).exists():
            return c
    raise RuntimeError("set $CHROME to a Chromium binary")


def main():
    md = (MEMO / "memo_template.md").read_text().format(**values())
    (MEMO / "memo.md").write_text(md)
    (MEMO / "memo.css").write_text(CSS)
    subprocess.run(["pandoc", "memo.md", "-o", "memo.html", "--standalone", "--css", "memo.css",
                    "--metadata", "pagetitle=Buy, lease or finance", "--embed-resources"],
                   cwd=MEMO, check=True)
    subprocess.run([chrome(), "--headless", "--no-sandbox", "--disable-gpu", "--no-pdf-header-footer",
                    f"--print-to-pdf={MEMO / 'memo.pdf'}", (MEMO / "memo.html").as_uri()],
                   check=True, capture_output=True, timeout=120)
    pages = subprocess.run(["pdfinfo", str(MEMO / "memo.pdf")], capture_output=True, text=True).stdout
    print(next((l for l in pages.splitlines() if l.startswith("Pages")), "pdfinfo not available"))


if __name__ == "__main__":
    main()
