"""Bank of Canada Valet API: policy rate and CAD/USD exchange rate.

Run from the repo root:  python -m data.fetch_boc
(Valet responses are small, so they are always re-downloaded.)
"""
from __future__ import annotations

import pandas as pd

from data._common import START_MONTH, get_json, write_csv

VALET = "https://www.bankofcanada.ca/valet/observations/{series}/json?start_date={start}"
START = f"{START_MONTH}-01"


def _series(series: str) -> pd.Series:
    js = get_json(VALET.format(series=series, start=START))
    obs = [(o["d"], o[series]["v"]) for o in js["observations"] if series in o and o[series].get("v")]
    s = pd.Series({pd.Timestamp(d): float(v) for d, v in obs}, name=series)
    return s.sort_index()


def main() -> None:
    print("Bank of Canada")
    policy = _series("V39079")                 # target for the overnight rate, %, daily
    fx_new = _series("FXUSDCAD")               # CAD per USD, daily, 2017-01-03 onward
    fx_old = _series("IEXE0101")               # legacy noon rate, daily, to 2017-04-28
    fx = pd.concat([fx_old[fx_old.index < fx_new.index.min()], fx_new])

    daily = pd.DataFrame({"usdcad": fx})
    daily.index.name = "date"
    daily = daily.reset_index()
    daily["date"] = daily.date.dt.strftime("%Y-%m-%d")
    write_csv(daily, "boc_fx_daily.csv",
              [VALET.format(series=s, start=START) for s in ("FXUSDCAD", "IEXE0101")])

    m_policy = policy.resample("MS").mean()
    m_policy_end = policy.resample("MS").last()
    m_fx = fx.resample("MS").mean()
    out = pd.DataFrame({"policy_rate_pct": m_policy, "policy_rate_eom_pct": m_policy_end,
                        "usdcad": m_fx}).dropna(how="all")
    out.index = out.index.strftime("%Y-%m")
    out.index.name = "month"
    write_csv(out.reset_index(), "boc_monthly.csv",
              [VALET.format(series=s, start=START) for s in ("V39079", "FXUSDCAD", "IEXE0101")])


if __name__ == "__main__":
    main()
