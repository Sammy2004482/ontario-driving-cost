"""How much did gasoline contribute to Canadian CPI inflation each year since 2015?

Contribution of gasoline to year-over-year all-items inflation in month t (percentage points):

    c_t = w_eff(t-12) * (G_t / G_{t-12} - 1) * 100
    w_eff(t-12) = w_b * (G_{t-12} / G_link) / (I_{t-12} / I_link)

w_b is gasoline's basket weight at link-month prices (table 18-10-0007-01) for the basket in
force at t-12, G and I are the gasoline and all-items indexes, and the ratio updates the
weight for relative price changes since the basket link month. This is the standard
weight-times-price-change decomposition; it is exact when t-12 and t use the same basket and
a close approximation across basket updates. Annual figures average the 12 monthly values,
matching annual-average CPI inflation.

Run:  python -m drivecost.inflation
"""
from __future__ import annotations

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from drivecost.data import FIGURES, TABLES, cpi, cpi_weights


def basket_for(month: str, weights: pd.DataFrame) -> pd.Series:
    """Basket in force in `month`: the latest one whose link month is before it."""
    eligible = weights[weights.link_month < month]
    return eligible.iloc[-1]


def monthly_contribution(c: pd.DataFrame | None = None, w: pd.DataFrame | None = None) -> pd.DataFrame:
    c = cpi() if c is None else c
    w = cpi_weights() if w is None else w
    months = list(c.index)
    rows = []
    for i, m in enumerate(months):
        if i < 12:
            continue
        base = months[i - 12]
        b = basket_for(base, w)
        link = b.link_month if b.link_month in c.index else months[0]
        w_eff = b.gasoline_weight_pct / 100 * (c.gasoline[base] / c.gasoline[link]) / (c.all_items[base] / c.all_items[link])
        headline = (c.all_items[m] / c.all_items[base] - 1) * 100
        gas_yoy = (c.gasoline[m] / c.gasoline[base] - 1) * 100
        contrib = w_eff * gas_yoy
        rows.append({"month": m, "headline_pct": headline, "gasoline_yoy_pct": gas_yoy,
                     "gasoline_weight_eff_pct": w_eff * 100, "gasoline_contribution_pp": contrib,
                     "ex_gasoline_contribution_pp": headline - contrib})
    return pd.DataFrame(rows).set_index("month")


def annual_contribution(monthly: pd.DataFrame | None = None, start_year: int = 2015) -> pd.DataFrame:
    m = monthly_contribution() if monthly is None else monthly
    m = m.assign(year=m.index.str[:4].astype(int))
    a = m.groupby("year").agg(headline_pct=("headline_pct", "mean"),
                              gasoline_contribution_pp=("gasoline_contribution_pp", "mean"),
                              gasoline_yoy_pct=("gasoline_yoy_pct", "mean"),
                              months=("headline_pct", "size"))
    a["ex_gasoline_contribution_pp"] = a.headline_pct - a.gasoline_contribution_pp
    a["gasoline_share_of_inflation"] = a.gasoline_contribution_pp / a.headline_pct
    return a.loc[start_year:]


def plot(annual: pd.DataFrame, monthly: pd.DataFrame, path=None):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2), gridspec_kw={"width_ratios": [1.2, 1]})
    ax = axes[0]
    x = np.arange(len(annual))
    labels = [f"{y}" if n == 12 else f"{y}\n(to {monthly.index[-1][5:]})" for y, n in zip(annual.index, annual.months)]
    gas, rest = annual.gasoline_contribution_pp.values, annual.ex_gasoline_contribution_pp.values
    ax.bar(x, rest, color="#bdd7ee", label="everything else")
    ax.bar([], [], color="#c00000", label="gasoline (pushed up)")
    ax.bar([], [], color="#2e75b6", label="gasoline (pulled down)")
    # stack gasoline on the same side as 'rest' when signs agree, otherwise from zero
    bottom = np.where(np.sign(gas) == np.sign(rest), rest, 0)
    ax.bar(x, gas, bottom=bottom, color=np.where(gas >= 0, "#c00000", "#2e75b6"))
    ax.plot(x, annual.headline_pct, "ko-", ms=4, lw=1, label="CPI inflation")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x, labels, fontsize=8)
    ax.set_ylabel("percentage points")
    ax.set_title("Gasoline's contribution to Canadian CPI inflation")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    ax = axes[1]
    mi = pd.to_datetime(monthly.index)
    ax.plot(mi, monthly.headline_pct, color="black", lw=1.4, label="headline CPI, y/y")
    ax.plot(mi, monthly.ex_gasoline_contribution_pp, color="#5b9bd5", lw=1.2, label="CPI excluding gasoline's contribution")
    ax.fill_between(mi, monthly.ex_gasoline_contribution_pp, monthly.headline_pct, color="#c00000", alpha=0.25,
                    label="gasoline contribution")
    ax.axhline(2, color="grey", ls=":", lw=0.8)
    ax.text(mi[0], 2.15, "BoC 2% target", fontsize=7, color="grey")
    ax.set_title("Monthly, year over year")
    ax.legend(frameon=False, fontsize=7, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "inflation_gasoline_contribution.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    m = monthly_contribution()
    a = annual_contribution(m)
    m.loc["2015-01":].to_csv(TABLES / "inflation_gasoline_monthly.csv", float_format="%.4f")
    a.to_csv(TABLES / "inflation_gasoline_annual.csv", float_format="%.4f")
    plot(a, m.loc["2015-01":])
    print(a.round(2).to_string())
    return a


if __name__ == "__main__":
    main()
