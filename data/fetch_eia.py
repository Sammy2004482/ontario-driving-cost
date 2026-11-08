"""US EIA open data: WTI crude and wholesale gasoline, converted to CAD per litre.

Uses the public 'hist_xls' downloads (no API key needed).
* RWTC  : Cushing OK WTI spot, USD/barrel
* EER_EPMRU_PF4_Y35NY_DPG : New York Harbor conventional regular gasoline spot, USD/gallon.
  EIA stopped publishing its NYMEX RBOB futures series in April 2024, so NY Harbor
  spot gasoline (the delivery point of the RBOB contract) is used as the wholesale
  gasoline price and as the hedge instrument's price.

Run from the repo root:  python -m data.fetch_eia [--refresh]
Requires boc_fx_daily.csv / boc_monthly.csv (run data.fetch_boc first).
"""
from __future__ import annotations

import pandas as pd

from data._common import PROCESSED, START_MONTH, download, read_eia_xls, write_csv

URL = "https://www.eia.gov/dnav/pet/hist_xls/{code}.xls"
L_PER_BBL = 158.987294928
L_PER_GAL = 3.785411784
SERIES = {"wti_usd_bbl": "RWTC", "gasoline_nyh_usd_gal": "EER_EPMRU_PF4_Y35NY_DPG"}


def _load(freq: str) -> pd.DataFrame:
    frames = []
    for name, code in SERIES.items():
        p = download(URL.format(code=code + freq), f"eia_{code}{freq}.xls")
        frames.append(read_eia_xls(p, name).set_index("date"))
    return pd.concat(frames, axis=1).sort_index()


def main() -> None:
    print("US EIA")
    urls = [URL.format(code=c + f) for c in SERIES.values() for f in ("m", "d")]

    m = _load("m")
    m.index = m.index.strftime("%Y-%m")
    m = m[m.index >= START_MONTH]
    fx = pd.read_csv(PROCESSED / "boc_monthly.csv", index_col="month")["usdcad"]
    m = m.join(fx, how="left")
    m["wti_cad_l"] = m.wti_usd_bbl * m.usdcad / L_PER_BBL
    m["gasoline_nyh_cad_l"] = m.gasoline_nyh_usd_gal * m.usdcad / L_PER_GAL
    m.index.name = "month"
    write_csv(m.reset_index().dropna(subset=["usdcad"]), "eia_monthly.csv", urls)

    d = _load("d")
    d = d[d.index >= f"{START_MONTH}-01"]
    fxd = pd.read_csv(PROCESSED / "boc_fx_daily.csv", parse_dates=["date"], index_col="date")["usdcad"]
    d = d.join(fxd, how="left")
    d["usdcad"] = d.usdcad.ffill()          # US trading days on Canadian holidays
    d["wti_cad_l"] = d.wti_usd_bbl * d.usdcad / L_PER_BBL
    d["gasoline_nyh_cad_l"] = d.gasoline_nyh_usd_gal * d.usdcad / L_PER_GAL
    d.index = d.index.strftime("%Y-%m-%d")
    d.index.name = "date"
    write_csv(d.reset_index().dropna(subset=["usdcad"]), "eia_daily.csv", urls)


if __name__ == "__main__":
    main()
