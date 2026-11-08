"""Hedging the delivery fleet's fuel bill with gasoline futures, and the margin calls it creates.

Exposure: the fleet in drivecost.risk.FLEET (50 vans, 2.25 million litres over 5 years,
450,000 L a year). A business recovers the 13% HST as an input tax credit, and the per-litre
taxes are fixed, so the risk to hedge is the *market* part of the pump price (c/L, CAD).

Hedge instrument: NYMEX RBOB gasoline futures (42,000 US gallons = 158,987 L per contract,
priced in USD/gal, delivered New York Harbor). EIA stopped publishing RBOB futures prices in
2024, so NY Harbor spot gasoline is used as the futures price (the front contract converges to
it). Futures P&L is converted to CAD at each day's Bank of Canada rate.

1. Minimum-variance hedge ratio  h* = Cov(dS, dF) / Var(dF), from monthly changes, where S is the
   Toronto market price and F is NY Harbor gasoline, both in CAD c/L. Contracts:
   N* = h* x litres hedged / 158,987.  Risk removed in-sample = R^2 of that regression.
2. Out-of-sample check: h* estimated on 2015-2021 and applied to rolling 12-month strips in
   2022-2026; compares the spread of the "budget miss" (actual fuel bill minus the bill at the
   price when the hedge was put on) with and without the hedge.
3. Margin calls: daily variation margin = N x 42,000 x dF (USD). The account starts at the
   initial margin; when it drops below maintenance margin the fleet must post cash to restore
   it to initial margin (a margin call). Gains above initial margin are paid out.

Run:  python -m drivecost.hedge
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from drivecost.data import FIGURES, TABLES, eia_daily, monthly_panel
from drivecost.risk import FLEET

GAL_PER_CONTRACT = 42_000
L_PER_CONTRACT = GAL_PER_CONTRACT * 3.785411784
# Exchange margins change often; these are assumptions of the right order for RBOB futures.
INITIAL_MARGIN_USD = 9_000.0
MAINTENANCE_MARGIN_USD = 8_200.0


@dataclass
class HedgeRatio:
    h: float
    se: float
    r2: float
    n_obs: int
    sample: str

    def contracts(self, litres: float) -> float:
        return self.h * litres / L_PER_CONTRACT


def hedge_ratio(start: str = "2015-01", end: str | None = None, panel: pd.DataFrame | None = None) -> HedgeRatio:
    p = (monthly_panel() if panel is None else panel).loc[start:end]
    d = p[["pump_ex_tax_cpl", "wholesale_cpl"]].diff().dropna()
    res = sm.OLS(d.pump_ex_tax_cpl, sm.add_constant(d.wholesale_cpl)).fit()
    return HedgeRatio(float(res.params["wholesale_cpl"]), float(res.bse["wholesale_cpl"]), float(res.rsquared),
                      int(res.nobs), f"{d.index[0]} to {d.index[-1]}")


def strip_backtest(h: float, start: str = "2022-01", litres_per_month: float = FLEET.litres_per_month,
                   panel: pd.DataFrame | None = None) -> pd.DataFrame:
    """For each month m0, hedge the next 12 months' fuel at m0's price; compare budget misses.

    Unhedged miss  = sum_k Q (S_k - S_0)
    Hedged miss    = unhedged miss - h Q sum_k (F_k - F_0)
    (in CAD, ex-HST; S = Toronto market price, F = NY Harbor gasoline in CAD/L)
    """
    p = (monthly_panel() if panel is None else panel)
    S, F = p.pump_ex_tax_cpl / 100, p.wholesale_cpl / 100
    idx = list(p.index)
    rows = []
    for i, m0 in enumerate(idx):
        if m0 < start or i + 12 >= len(idx):
            continue
        win = idx[i + 1:i + 13]
        unhedged = litres_per_month * (S[win] - S[m0]).sum()
        fut = litres_per_month * (F[win] - F[m0]).sum()
        rows.append({"start": m0, "unhedged_miss": unhedged, "futures_pnl": h * fut,
                     "hedged_miss": unhedged - h * fut})
    return pd.DataFrame(rows)


def margin_account(prices_usd_gal: pd.Series, usdcad: pd.Series, contracts: float, side: int = 1,
                   im: float = INITIAL_MARGIN_USD, mm: float = MAINTENANCE_MARGIN_USD) -> pd.DataFrame:
    """Daily margin account for `contracts` futures (side +1 = long/buyer, -1 = short/seller).

    Returns daily variation margin, margin calls (cash posted, CAD, positive = outflow),
    excess paid out to the hedger (CAD) and the account balance (USD).
    """
    prices_usd_gal = prices_usd_gal.dropna()   # EIA spot series has a few missing days
    n = abs(contracts)
    bal = im * n
    rows = []
    prev = prices_usd_gal.iloc[0]
    for date, price in prices_usd_gal.iloc[1:].items():
        vm = side * n * GAL_PER_CONTRACT * (price - prev)
        prev = price
        bal += vm
        call = excess = 0.0
        if bal < mm * n:
            call = im * n - bal
            bal = im * n
        elif bal > im * n:
            excess = bal - im * n
            bal = im * n
        fx = usdcad.get(date, np.nan)
        rows.append({"date": date, "price": price, "variation_margin_usd": vm, "margin_call_usd": call,
                     "excess_paid_usd": excess, "balance_usd": bal, "usdcad": fx})
    df = pd.DataFrame(rows).set_index("date")
    df["usdcad"] = df.usdcad.ffill().bfill()
    for c in ("variation_margin", "margin_call", "excess_paid"):
        df[f"{c}_cad"] = df[f"{c}_usd"] * df.usdcad
    df["cum_net_cash_cad"] = (df.excess_paid_cad - df.margin_call_cad).cumsum() - im * n * df.usdcad.iloc[0]
    return df


def synthetic_spike(start_price: float = 2.70, up: float = 0.50, up_days: int = 30, down: float = 0.40,
                    down_days: int = 40, vol: float = 0.012, seed: int = 7) -> pd.Series:
    """A stylised spike: +50% over 30 trading days, then a 40% fall over 40 days, with daily noise."""
    rng = np.random.default_rng(seed)
    drift = np.r_[np.full(up_days, np.log(1 + up) / up_days), np.full(down_days, np.log(1 - down) / down_days)]
    shocks = drift + vol * rng.standard_normal(len(drift))
    shocks -= (shocks - drift).mean()
    path = start_price * np.exp(np.r_[0, np.cumsum(shocks)])
    return pd.Series(path, index=pd.bdate_range("2027-01-04", periods=len(path)))


def margin_summary(acct: pd.DataFrame, label: str) -> dict:
    return {"scenario": label, "days": len(acct), "call_days": int((acct.margin_call_usd > 0).sum()),
            "total_calls_cad": acct.margin_call_cad.sum(),
            "largest_call_cad": acct.margin_call_cad.max(),
            "peak_cumulative_outflow_cad": -acct.cum_net_cash_cad.min(),
            "net_futures_pnl_cad": acct.variation_margin_cad.sum()}


def plot_margin(accts: dict[str, pd.DataFrame], path=None):
    fig, axes = plt.subplots(len(accts), 1, figsize=(9, 2.8 * len(accts)), sharex=False)
    for ax, (label, a) in zip(np.atleast_1d(axes), accts.items()):
        ax2 = ax.twinx()
        ax2.plot(a.index, a.price, color="#7f7f7f", lw=1, label="gasoline price (USD/gal)")
        ax2.set_ylabel("USD/gal", color="#7f7f7f", fontsize=8)
        ax.bar(a.index, a.margin_call_cad / 1000, color="#c00000", width=1.5, label="margin call posted")
        ax.bar(a.index, -a.excess_paid_cad / 1000, color="#2e75b6", width=1.5, label="excess margin paid out")
        ax.plot(a.index, a.cum_net_cash_cad / 1000, color="black", lw=1.4,
                label="cumulative net cash to hedger (after posting initial margin)")
        ax.axhline(0, color="black", lw=0.5)
        ax.set_ylabel("CAD thousands")
        ax.set_title(label, fontsize=10, loc="left")
        ax.spines[["top"]].set_visible(False)
        ax.set_zorder(ax2.get_zorder() + 1)
        ax.patch.set_visible(False)
    h1, l1 = np.atleast_1d(axes)[0].get_legend_handles_labels()
    h2, l2 = ax2.get_legend_handles_labels()
    np.atleast_1d(axes)[0].legend(h1 + h2, l1 + l2, frameon=False, fontsize=7, loc="upper left", ncol=2)
    fig.tight_layout()
    path = path or FIGURES / "hedge_margin_calls.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    hr = hedge_ratio()
    hr_is = hedge_ratio(end="2021-12")
    litres_12m = FLEET.litres_per_month * 12
    n_exact = hr.contracts(litres_12m)
    n = max(1, round(n_exact))
    print(f"min-variance hedge ratio h* = {hr.h:.3f} (se {hr.se:.3f}), R^2 = {hr.r2:.2f}, {hr.sample}")
    print(f"12-month volume {litres_12m:,.0f} L -> {n_exact:.2f} contracts, use {n}")

    bt = strip_backtest(hr_is.h)
    sd_u, sd_h = bt.unhedged_miss.std(), bt.hedged_miss.std()
    summary = {
        "hedge_ratio_full_sample": hr.h, "hedge_ratio_se": hr.se, "r2_variance_removed_in_sample": hr.r2,
        "hedge_ratio_2015_2021": hr_is.h, "litres_hedged_12m": litres_12m, "contracts_exact": n_exact,
        "contracts_used": n,
        "oos_strips": len(bt), "oos_sd_budget_miss_unhedged_cad": sd_u, "oos_sd_budget_miss_hedged_cad": sd_h,
        "oos_variance_reduction": 1 - (sd_h / sd_u) ** 2,
        "oos_worst_miss_unhedged_cad": bt.unhedged_miss.max(), "oos_worst_miss_hedged_cad": bt.hedged_miss.max(),
    }
    bt.to_csv(TABLES / "hedge_backtest_strips.csv", index=False, float_format="%.0f")

    d = eia_daily()
    accts = {
        "2022 spike and collapse: fleet long 3 contracts from 1 Feb 2022":
            margin_account(d.gasoline_nyh_usd_gal.loc["2022-02-01":"2022-12-30"], d.usdcad, n, side=1),
        "2026 spike: fuel supplier short 3 contracts from 2 Jan 2026 (the other side of a fixed-price deal)":
            margin_account(d.gasoline_nyh_usd_gal.loc["2026-01-02":], d.usdcad, n, side=-1),
        "Synthetic spike (+50% in 30 days, -40% in 40 days): fleet long 3 contracts":
            margin_account(synthetic_spike(), pd.Series(1.40, index=synthetic_spike().index), n, side=1),
    }
    rows = [margin_summary(a, k) for k, a in accts.items()]
    # the same synthetic spike for a 100x bigger hedger, which is where collateral desks earn their keep
    big = margin_account(synthetic_spike(), pd.Series(1.40, index=synthetic_spike().index), 100 * n, side=-1)
    rows.append(margin_summary(big, f"Synthetic spike: refiner short {100 * n} contracts"))
    ms = pd.DataFrame(rows)
    ms.to_csv(TABLES / "hedge_margin_calls.csv", index=False, float_format="%.0f")
    pd.Series(summary).to_csv(TABLES / "hedge_summary.csv", header=["value"], float_format="%.4f")
    plot_margin({k.split(":")[0] + ": " + k.split(":")[1].strip(): v for k, v in accts.items()})
    print(pd.Series(summary).round(3).to_string())
    pd.set_option("display.width", 200)
    print(ms.round(0).to_string(index=False))
    return summary, ms


if __name__ == "__main__":
    main()
