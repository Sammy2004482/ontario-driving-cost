"""Statistics Canada: retail gasoline prices (18-10-0001-01), CPI (18-10-0004-01)
and CPI basket weights (18-10-0007-01).

Run from the repo root:  python -m data.fetch_statcan [--refresh]
"""
from __future__ import annotations

import zipfile

import pandas as pd

from data._common import START_MONTH, download, write_csv

TABLE_URL = "https://www150.statcan.gc.ca/n1/tbl/csv/{pid}-eng.zip"

# Table 18-10-0001-01 has no London, Ontario series. Toronto is the closest
# large market (about 190 km) and is used as the London proxy in the models.
GAS_GEOS = {
    "Toronto, Ontario": "toronto",
    "Ottawa-Gatineau, Ontario part, Ontario/Quebec": "ottawa",
    "Thunder Bay, Ontario": "thunder_bay",
    "Canada": "canada",
}
GAS_FUELS = {
    "Regular unleaded gasoline at self service filling stations": "regular",
    "Premium unleaded gasoline at self service filling stations": "premium",
    "Diesel fuel at self service filling stations": "diesel",
}
CPI_ITEMS = {"All-items": "all_items", "Gasoline": "gasoline", "Energy": "energy",
             "All-items excluding energy": "all_items_ex_energy"}


def _read_table(pid: str, usecols: list[str]) -> pd.DataFrame:
    path = download(TABLE_URL.format(pid=pid), f"statcan_{pid}.zip")
    with zipfile.ZipFile(path) as z:
        with z.open(f"{pid}.csv") as f:
            return pd.read_csv(f, usecols=usecols, dtype=str)


def gasoline_prices() -> None:
    d = _read_table("18100001", ["REF_DATE", "GEO", "Type of fuel", "VALUE"])
    d = d[d.GEO.isin(GAS_GEOS) & d["Type of fuel"].isin(GAS_FUELS) & (d.REF_DATE >= START_MONTH)]
    out = pd.DataFrame({
        "month": d.REF_DATE,
        "geo": d.GEO.map(GAS_GEOS),
        "fuel": d["Type of fuel"].map(GAS_FUELS),
        "cents_per_litre": pd.to_numeric(d.VALUE, errors="coerce"),
    }).dropna().sort_values(["month", "geo", "fuel"])
    write_csv(out, "gas_prices_monthly.csv", TABLE_URL.format(pid="18100001"))


def cpi() -> None:
    d = _read_table("18100004", ["REF_DATE", "GEO", "Products and product groups", "VALUE"])
    d = d[d.GEO.isin(["Canada", "Ontario"]) & d["Products and product groups"].isin(CPI_ITEMS)
          & (d.REF_DATE >= START_MONTH)]
    d = d.assign(item=d["Products and product groups"].map(CPI_ITEMS),
                 VALUE=pd.to_numeric(d.VALUE, errors="coerce"))
    out = (d.pivot_table(index=["REF_DATE", "GEO"], columns="item", values="VALUE")
             .reset_index().rename(columns={"REF_DATE": "month", "GEO": "geo"}))
    out["geo"] = out.geo.str.lower()
    out = out[["month", "geo", *CPI_ITEMS.values()]].sort_values(["month", "geo"])
    write_csv(out, "cpi_monthly.csv", TABLE_URL.format(pid="18100004"))


def cpi_weights() -> None:
    d = _read_table("18100007", ["REF_DATE", "GEO", "Products and product groups",
                                  "Price period of weight", "Geographic distribution of weight", "VALUE"])
    d = d[(d.GEO == "Canada")
          & d["Products and product groups"].isin(["Gasoline", "All-items"])
          & (d["Price period of weight"] == "Weight at basket link month prices")
          & (d["Geographic distribution of weight"] == "Distribution to selected geographies")]
    out = (d.assign(VALUE=pd.to_numeric(d.VALUE))
             .pivot_table(index="REF_DATE", columns="Products and product groups", values="VALUE")
             .reset_index())
    out = pd.DataFrame({"basket_year": out.REF_DATE.astype(int),
                        "gasoline_weight_pct": out["Gasoline"],
                        "all_items_weight_pct": out["All-items"]})
    # Month in which each basket is linked into the index (StatCan basket-update notes):
    # 2013/2015/2017 baskets were linked in December of the following year,
    # baskets from 2020 on are linked in May of the following year.
    out["link_month"] = [f"{y + 1}-12" if y < 2020 else f"{y + 1}-05" for y in out.basket_year]
    out = out[out.basket_year >= 2011].sort_values("basket_year")
    write_csv(out, "cpi_basket_weights.csv", TABLE_URL.format(pid="18100007"))


def main() -> None:
    print("Statistics Canada")
    gasoline_prices()
    cpi()
    cpi_weights()


if __name__ == "__main__":
    main()
