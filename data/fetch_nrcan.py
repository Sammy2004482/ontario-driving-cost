"""NRCan fuel consumption ratings (open.canada.ca dataset 98f1a129...).

Combines conventional/hybrid vehicles (model years 2015-2026) and battery-electric
vehicles into one tidy file with a `powertrain` column (ICE, HEV, BEV).

Run from the repo root:  python -m data.fetch_nrcan [--refresh]
"""
from __future__ import annotations

import pandas as pd

from data._common import download, write_csv

BASE = "https://open.canada.ca/data/dataset/98f1a129-f628-4ce4-b24d-6f16bf24dd64/resource/"
FILES = {
    "ice_2015_2024": BASE + "c98b9dc8-b23f-4cd8-8b19-e892da1e4688/download/my2015-2024-fuel-consumption-ratings.csv",
    "ice_2025": BASE + "d589f2bc-9a85-4f65-be2f-20f17debfcb1/download/my2025-fuel-consumption-ratings.csv",
    "ice_2026": BASE + "9df1b18d-d036-4783-a61c-99f1f75b3ac5/download/my2026-fuel-consumption-ratings.csv",
    "bev": BASE + "026e45b4-eb63-451f-b34f-d9308ea3a3d9/download/my2012-2026-battery-electric-vehicles.csv",
}
FUEL_CODES = {"X": "regular", "Z": "premium", "D": "diesel", "E": "e85", "N": "natural_gas", "B": "electricity"}
COLS = ["model_year", "make", "model", "vehicle_class", "powertrain", "fuel", "transmission",
        "city_l100", "hwy_l100", "comb_l100", "comb_kwh100", "range_km", "co2_g_km"]


def _read(key: str) -> pd.DataFrame:
    p = download(FILES[key], f"nrcan_{key}.csv")
    d = pd.read_csv(p, encoding="latin-1")
    d.columns = [c.strip() for c in d.columns]
    return d


def main() -> None:
    print("NRCan fuel consumption ratings")
    ice = pd.concat([_read(k) for k in ("ice_2015_2024", "ice_2025", "ice_2026")], ignore_index=True)
    ice = pd.DataFrame({
        "model_year": ice["Model year"], "make": ice["Make"].str.strip(), "model": ice["Model"].str.strip(),
        "vehicle_class": ice["Vehicle class"], "fuel": ice["Fuel type"].map(FUEL_CODES),
        "transmission": ice["Transmission"], "city_l100": ice["City (L/100 km)"],
        "hwy_l100": ice["Highway (L/100 km)"], "comb_l100": ice["Combined (L/100 km)"],
        "co2_g_km": ice["CO2 emissions (g/km)"],
    })
    ice["powertrain"] = ice.model.str.contains("hybrid", case=False).map({True: "HEV", False: "ICE"})

    bev = _read("bev")
    bev = pd.DataFrame({
        "model_year": bev["Model year"], "make": bev["Make"].str.strip(), "model": bev["Model"].str.strip(),
        "vehicle_class": bev["Vehicle class"], "fuel": "electricity", "transmission": bev["Transmission"],
        "city_l100": bev["City (Le/100 km)"], "hwy_l100": bev["Highway (Le/100 km)"],
        "comb_l100": bev["Combined (Le/100 km)"], "comb_kwh100": bev["Combined (kWh/100 km)"],
        "range_km": bev["Range (km)"], "co2_g_km": 0, "powertrain": "BEV",
    })
    bev = bev[bev.model_year >= 2015]
    out = (pd.concat([ice, bev], ignore_index=True)[COLS]
             .sort_values(["model_year", "make", "model", "transmission", "comb_l100"]))
    write_csv(out, "nrcan_fuel_ratings.csv", list(FILES.values()))


if __name__ == "__main__":
    main()
