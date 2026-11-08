"""Loaders for the processed CSVs in data/processed and the Ontario fuel-tax table."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROCESSED = ROOT / "data" / "processed"
FIGURES = ROOT / "reports" / "figures"
TABLES = ROOT / "reports" / "tables"
FIGURES.mkdir(parents=True, exist_ok=True)
TABLES.mkdir(parents=True, exist_ok=True)

HST = 0.13
FEDERAL_EXCISE_CPL = 10.0
# Federal fuel charge on gasoline in Ontario, cents/L, effective month. Removed 1 April 2025.
FUEL_CHARGE_CPL = {"2019-04": 4.42, "2020-04": 6.63, "2021-04": 8.84, "2022-04": 11.05,
                   "2023-04": 14.31, "2024-04": 17.61, "2025-04": 0.0}
# Ontario gasoline tax, cents/L: cut from 14.7 to 9.0 on 1 July 2022 (since made permanent).
ON_GAS_TAX_CPL = {"2000-01": 14.7, "2022-07": 9.0}
# Ontario cap-and-trade (Jan 2017 - Jul 2018) was embedded in rack prices; about 4.3 c/L.
CAP_TRADE_CPL = {"2017-01": 4.3, "2018-07": 0.0}


def _step(schedule: dict[str, float], months: pd.Index) -> pd.Series:
    s = pd.Series(0.0, index=months)
    for start, val in sorted(schedule.items()):
        s[s.index >= start] = val
    return s


def gasoline_taxes(months) -> pd.DataFrame:
    """Per-litre taxes and levies on Ontario gasoline by month (cents/L, before HST)."""
    months = pd.Index(months)
    t = pd.DataFrame(index=months)
    t["excise"] = FEDERAL_EXCISE_CPL
    t["ontario_gas_tax"] = _step(ON_GAS_TAX_CPL, months)
    t["fuel_charge"] = _step(FUEL_CHARGE_CPL, months)
    t["cap_and_trade"] = _step(CAP_TRADE_CPL, months)
    t["per_litre_total"] = t.sum(axis=1)
    return t


@lru_cache
def gas_prices(geo: str = "toronto", fuel: str = "regular") -> pd.Series:
    g = pd.read_csv(PROCESSED / "gas_prices_monthly.csv")
    s = g[(g.geo == geo) & (g.fuel == fuel)].set_index("month")["cents_per_litre"]
    s.name = f"{geo}_{fuel}_cpl"
    return s


@lru_cache
def monthly_panel() -> pd.DataFrame:
    """Toronto pump prices, crude, wholesale gasoline, FX, policy rate and taxes on one monthly index."""
    eia = pd.read_csv(PROCESSED / "eia_monthly.csv", index_col="month")
    boc = pd.read_csv(PROCESSED / "boc_monthly.csv", index_col="month")
    p = pd.DataFrame({"pump_cpl": gas_prices("toronto", "regular"),
                      "diesel_cpl": gas_prices("toronto", "diesel")})
    p = p.join(eia[["wti_usd_bbl", "gasoline_nyh_usd_gal", "wti_cad_l", "gasoline_nyh_cad_l"]], how="inner")
    p = p.join(boc[["policy_rate_pct", "usdcad"]], how="left")
    p["crude_cpl"] = p.wti_cad_l * 100
    p["wholesale_cpl"] = p.gasoline_nyh_cad_l * 100
    taxes = gasoline_taxes(p.index)
    p["tax_cpl"] = taxes.per_litre_total
    # pump price with HST and per-litre taxes stripped out: what crude/refining/margins explain
    p["pump_ex_tax_cpl"] = p.pump_cpl / (1 + HST) - p.tax_cpl
    return p.sort_index()


@lru_cache
def cpi() -> pd.DataFrame:
    c = pd.read_csv(PROCESSED / "cpi_monthly.csv")
    return c[c.geo == "canada"].set_index("month").drop(columns="geo")


@lru_cache
def cpi_weights() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "cpi_basket_weights.csv")


@lru_cache
def eia_daily() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "eia_daily.csv", parse_dates=["date"], index_col="date")


@lru_cache
def nrcan() -> pd.DataFrame:
    return pd.read_csv(PROCESSED / "nrcan_fuel_ratings.csv")


def latest_policy_rate() -> float:
    b = pd.read_csv(PROCESSED / "boc_monthly.csv")
    return float(b.policy_rate_eom_pct.dropna().iloc[-1])
