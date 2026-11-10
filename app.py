"""Streamlit page: the real cost of driving in Ontario.

    streamlit run app.py
"""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st

from drivecost import risk
from drivecost.data import FIGURES, TABLES, nrcan
from drivecost.tco import Vehicle, compare, default_assumptions, memo_vehicles, tco

def money(x: float) -> str:
    return f"-${-x:,.0f}" if x < 0 else f"${x:,.0f}"


st.set_page_config(page_title="Real cost of driving in Ontario", layout="wide")
st.title("The real cost of driving in Ontario")
st.caption("5-year cost of ownership, fuel price risk and the economics behind the pump price. "
           "Data: Statistics Canada, Bank of Canada, US EIA, NRCan. Toronto prices are used for London, ON.")

base = default_assumptions()
defaults = {v.powertrain: v for v in memo_vehicles()}


@st.cache_data
def catalogue() -> pd.DataFrame:
    d = nrcan()
    d = d[d.model_year >= 2024].copy()
    d["label"] = d.model_year.astype(str) + " " + d.make + " " + d.model + " (" + d.transmission + ")"
    return d.drop_duplicates("label").sort_values("label")


def pick_vehicle(col, key: str, default_label: str, default_price: float, default: Vehicle) -> Vehicle:
    cat = catalogue()
    labels = list(cat.label)
    idx = next((i for i, l in enumerate(labels) if l.startswith(default_label)), 0)
    label = col.selectbox("Model (NRCan ratings)", labels, index=idx, key=f"{key}_m")
    row = cat[cat.label == label].iloc[0]
    price = col.number_input("Price before tax ($)", 10_000, 150_000, int(default_price), 500, key=f"{key}_p")
    ins = col.number_input("Insurance, year 1 ($)", 500, 10_000, int(default.insurance), 100, key=f"{key}_i")
    maint = col.number_input("Maintenance, year 1 ($)", 0, 5_000, int(default.maintenance), 50, key=f"{key}_mt")
    resale = col.slider("Resale value after 5 years (% of price)", 20, 70, int(default.retention[-1] * 100), key=f"{key}_r")
    r = np.array(default.retention)
    pt = row.powertrain
    return Vehicle(name=label.split(" (")[0], powertrain=pt, price=price,
                   l_per_100km=0.0 if pt == "BEV" else float(row.comb_l100),
                   kwh_per_100km=float(row.comb_kwh100) if pt == "BEV" else 0.0,
                   retention=tuple(r * resale / 100 / r[-1]), insurance=ins, maintenance=maint,
                   charger=1_800 if pt == "BEV" else 0.0)


with st.sidebar:
    st.header("Your situation")
    km = st.slider("Kilometres per year", 5_000, 40_000, int(base.km_per_year), 1_000)
    gas = st.slider("Gas price, year 1 (¢/L)", 100, 250, int(base.gas_cpl))
    elec = st.slider("Electricity ($/kWh, blended)", 0.08, 0.40, base.elec_per_kwh, 0.01)
    policy = st.slider("Bank of Canada policy rate (%)", 0.0, 6.0, base.policy_rate, 0.25)
    spread = st.slider("Loan spread over policy rate (%-pts)", 0.0, 10.0, base.loan_spread, 0.25)
    lease_spread = st.slider("Lease spread over policy rate (%-pts)", -2.5, 8.0, base.lease_spread, 0.25)
    down = st.number_input("Down payment ($)", 0, 50_000, int(base.down_payment), 500)
    disc = st.slider("Your savings rate, for discounting (%)", 0.0, 8.0, base.discount_rate * 100, 0.25)

a = replace(base, km_per_year=km, gas_cpl=gas, elec_per_kwh=elec, policy_rate=policy, loan_spread=spread,
            lease_spread=lease_spread, down_payment=down, discount_rate=disc / 100)

tab_tco, tab_risk, tab_econ, tab_biz = st.tabs(["Cost of ownership", "Fuel price risk", "Pump prices & inflation",
                                                 "Fleet, credit & insurance"])

with tab_tco:
    c1, c2 = st.columns(2)
    c1.subheader("Car A")
    va = pick_vehicle(c1, "a", "2026 Toyota Corolla Hybrid", defaults["HEV"].price, defaults["HEV"])
    c2.subheader("Car B")
    vb = pick_vehicle(c2, "b", "2026 Hyundai Kona Electric", defaults["BEV"].price, defaults["BEV"])
    res = compare([va, vb], a)
    show = res[["vehicle", "method", "total", "npv", "per_month", "acquisition", "resale", "energy",
                "insurance", "maintenance", "other"]].copy()
    best = show.loc[show.npv.idxmin()]
    st.success(f"Cheapest in today's dollars: **{best.vehicle}, {best['method']}**. "
               f"Net 5-year cost ${best.total:,.0f} (${best.per_month:,.0f}/month), NPV ${best.npv:,.0f}.")
    st.dataframe(show.style.format({c: money for c in show.columns if c not in ("vehicle", "method")}),
                 hide_index=True, width="stretch")
    chart = show.assign(option=show.vehicle + " · " + show["method"]).set_index("option")[["npv"]]
    st.bar_chart(chart, horizontal=True)
    with st.expander("Year-by-year cash flows"):
        v_pick = st.radio("Vehicle", [va.name, vb.name], horizontal=True)
        m_pick = st.radio("Method", ["cash", "finance", "lease"], horizontal=True)
        v = va if v_pick == va.name else vb
        st.dataframe(tco(v, a, m_pick).round(0), width="stretch")
    st.caption(f"Loan rate {a.loan_apr * 100:.2f}%, lease rate {a.lease_apr * 100:.2f}%, 60-month terms, HST 13%. "
               "The same model in Excel: excel/tco_model.xlsx.")

with tab_risk:
    st.subheader("5-year fuel bill, 2027-2031: Monte Carlo")
    model = st.radio("Price model", ["mean_reverting", "random_walk"], horizontal=True,
                     help="Mean-reverting is the base case; the random walk is the stress case (the data cannot reject it).")
    n = st.select_slider("Simulated paths", [2_000, 5_000, 10_000, 20_000], 5_000)

    @st.cache_data
    def sim(model: str, n: int) -> pd.DataFrame:
        return risk.pump_price(risk.simulate_market_price(n, model))

    pump = sim(model, n)
    rows = []
    for v in (va, vb):
        if v.powertrain == "BEV":
            continue
        e = risk.Exposure(v.name, 1, km, v.l_per_100km)
        rows.append({"vehicle": v.name, **risk.risk_measures(risk.fuel_cost(pump, e))})
    if rows:
        r = pd.DataFrame(rows)
        st.dataframe(r.style.format({c: money for c in r.columns if c != "vehicle"}), hide_index=True)
        st.caption("VaR = the fuel bill exceeded only 5% of the time, minus the expected bill. "
                   "ES = the average overrun in that worst 5%. Electricity is treated as a fixed, inflating price.")
    q = pump.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).T
    q.columns = ["P5", "P25", "median", "P75", "P95"]
    q.index = pd.PeriodIndex(q.index, freq="M").to_timestamp()
    st.line_chart(q, y_label="¢/L, Toronto regular")

with tab_econ:
    for name, cap in [("passthrough_crude_cpl.png", "Crude-to-pump pass-through, rises vs falls"),
                      ("inflation_gasoline_contribution.png", "Gasoline's contribution to CPI inflation")]:
        if (FIGURES / name).exists():
            st.image(str(FIGURES / name), caption=cap)
    if (TABLES / "passthrough_tests.csv").exists():
        st.dataframe(pd.read_csv(TABLES / "passthrough_tests.csv", index_col=0), width="stretch")

with tab_biz:
    for name, cap in [("hedge_margin_calls.png", "Fleet hedge: daily margin calls"),
                      ("credit_stress.png", "Trucking company credit stress"),
                      ("pricing_factors.png", "Insurance pricing factors (freMTPL2)")]:
        if (FIGURES / name).exists():
            st.image(str(FIGURES / name), caption=cap)
    for t in ("hedge_summary.csv", "credit_stress_scenarios.csv", "pricing_example_premiums.csv"):
        if (TABLES / t).exists():
            st.markdown(f"**{t}**")
            st.dataframe(pd.read_csv(TABLES / t), width="stretch")
