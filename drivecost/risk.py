"""Monte Carlo simulation of 5-year fuel cost (January 2027 to December 2031).

Price model
-----------
The Toronto regular pump price is split into a market part and a tax part:

    pump_t = (market_t + taxes) * (1 + HST),   taxes = 10 c/L federal excise + 9 c/L Ontario

so that tax changes in the history (carbon charge, Ontario tax cut) do not show up as price risk.
The market part (crude + refining + retail margin, in CAD) is simulated two ways:

* "mean_reverting" (base case): AR(1) in the log real price toward its 2015-2026 average,
  re-inflated at 2%/yr. The AR(1) shocks are drawn in 6-month blocks from the model's own
  residuals, so fat tails and volatility clusters in the history are kept. Estimated
  persistence phi ~ 0.93 per month (half-life ~ 10 months).
* "random_walk" (stress case): no mean reversion; de-meaned historical monthly log changes are
  drawn in 6-month blocks and given a 2%/yr inflation drift. An ADF test cannot reject a unit
  root in the 2015-2026 sample (p ~ 0.5), so this is a legitimate alternative, and it gives a
  much wider spread over five years.

Risk measures on the 5-year fuel bill (loss = bill minus expected bill):
* percentiles P5 / P50 / P95,
* 95% value-at-risk  VaR = P95 - mean   (exceeded only 5% of the time),
* 95% expected shortfall  ES = mean(bill | bill >= P95) - mean   (average loss in the worst 5%).

Run:  python -m drivecost.risk
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from drivecost.data import FIGURES, HST, TABLES, monthly_panel

FORWARD_TAX_CPL = 10.0 + 9.0       # federal excise + Ontario gas tax, no carbon charge (removed Apr 2025)
SIM_START, SIM_END = "2027-01", "2031-12"
INFLATION = 0.02


@dataclass(frozen=True)
class Exposure:
    name: str
    units: int
    km_per_year: float
    l_per_100km: float

    @property
    def litres_per_month(self) -> float:
        return self.units * self.km_per_year / 12 * self.l_per_100km / 100


def history(start: str = "2015-01") -> pd.Series:
    return monthly_panel().pump_ex_tax_cpl.loc[start:]


def simulate_market_price(n_paths: int = 20_000, method: str = "mean_reverting", block: int = 6,
                          seed: int = 2027, hist: pd.Series | None = None,
                          end: str = SIM_END) -> pd.DataFrame:
    """Simulated market (ex-tax) price, c/L, months after the last observation through `end`."""
    hist = history() if hist is None else hist
    rng = np.random.default_rng(seed)
    last = pd.Period(hist.index[-1], "M")
    months = pd.period_range(last + 1, pd.Period(end, "M"), freq="M")
    h = len(months)
    logp = np.log(hist.values)
    r = np.diff(logp)
    mu = np.log(1 + INFLATION) / 12
    n_blocks = int(np.ceil(h / block))

    def block_draws(pool: np.ndarray) -> np.ndarray:
        starts = rng.integers(0, len(pool) - block + 1, size=(n_paths, n_blocks))
        return pool[(starts[:, :, None] + np.arange(block)).reshape(n_paths, -1)[:, :h]]

    if method == "random_walk":
        paths = logp[-1] + np.cumsum(block_draws(r - r.mean()) + mu, axis=1)
    elif method == "mean_reverting":
        phi, level, resid = ar1_fit(hist)
        eps = block_draws(resid - resid.mean())
        cur = np.full(n_paths, logp[-1] - mu * (len(logp) - 1))
        paths = np.empty((n_paths, h))
        for k in range(h):
            cur = level + phi * (cur - level) + eps[:, k]
            paths[:, k] = cur + mu * (len(logp) + k)
    else:
        raise ValueError(method)
    return pd.DataFrame(np.exp(paths), columns=months.astype(str))


def ar1_fit(hist: pd.Series) -> tuple[float, float, np.ndarray]:
    """AR(1) on the log real (inflation-deflated) market price: returns phi, mean level, residuals."""
    mu = np.log(1 + INFLATION) / 12
    real = np.log(hist.values) - mu * np.arange(len(hist))
    level = real.mean()
    x, y = real[:-1] - level, real[1:] - level
    phi = float(x @ y / (x @ x))
    return phi, level, y - phi * x


def pump_price(market: pd.DataFrame, tax_cpl: float = FORWARD_TAX_CPL) -> pd.DataFrame:
    return (market + tax_cpl) * (1 + HST)


def fuel_cost(pump: pd.DataFrame, exposure: Exposure, start: str = SIM_START, end: str = SIM_END) -> pd.Series:
    cols = [c for c in pump.columns if start <= c <= end]
    return (pump[cols] / 100 * exposure.litres_per_month).sum(axis=1)


def risk_measures(cost: pd.Series | np.ndarray, level: float = 0.95) -> dict:
    c = np.asarray(cost)
    mean = c.mean()
    q = np.quantile(c, level)
    tail = c[c >= q]
    return {"mean": mean, "p5": np.quantile(c, 0.05), "p50": np.quantile(c, 0.5), "p95": q,
            "var95": q - mean, "es95": tail.mean() - mean}


CAR = Exposure("My car: Corolla LE, 16,000 km/yr", 1, 16_000, 6.7)
HYBRID = Exposure("My car: Corolla Hybrid, 16,000 km/yr", 1, 16_000, 4.7)
FLEET = Exposure("Delivery fleet: 50 gasoline vans, 60,000 km/yr each", 50, 60_000, 15.0)


def run(n_paths: int = 20_000, seed: int = 2027) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    rows, pumps = [], {}
    for method in ("mean_reverting", "random_walk"):
        pump = pump_price(simulate_market_price(n_paths, method, seed=seed))
        pumps[method] = pump
        for e in (CAR, HYBRID, FLEET):
            m = risk_measures(fuel_cost(pump, e))
            rows.append({"model": method, "exposure": e.name, "litres_5y": e.litres_per_month * 60, **m})
    return pd.DataFrame(rows), pumps


def fan_chart(pump: pd.DataFrame, stress: pd.DataFrame | None = None, path=None, hist_start: str = "2021-01"):
    hist = monthly_panel().pump_cpl.loc[hist_start:]
    q = pump.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).T
    q.index = pd.PeriodIndex(q.index, freq="M").to_timestamp()
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(pd.to_datetime(hist.index), hist.values, color="black", lw=1.5, label="Toronto regular, actual")
    ax.fill_between(q.index, q[0.05], q[0.95], color="#2e75b6", alpha=0.18, label="5th to 95th percentile")
    ax.fill_between(q.index, q[0.25], q[0.75], color="#2e75b6", alpha=0.35, label="25th to 75th percentile")
    ax.plot(q.index, q[0.5], color="#1f4e79", lw=1.6, label="median")
    if stress is not None:
        s95 = stress.quantile(0.95)
        s95.index = pd.PeriodIndex(s95.index, freq="M").to_timestamp()
        ax.plot(s95.index, s95.values, color="#c00000", ls="--", lw=1.1,
                label="95th percentile, random-walk stress case")
    for p_ in (0.05, 0.5, 0.95):
        ax.annotate(f"{q[p_].iloc[-1]:.0f}", (q.index[-1], q[p_].iloc[-1]), xytext=(4, 0),
                    textcoords="offset points", fontsize=8, va="center")
    ax.axvline(pd.Timestamp(SIM_START), color="grey", lw=0.6, ls=":")
    ax.set_ylim(0, None)
    ax.set_ylabel("cents per litre, incl. taxes")
    ax.set_title("Gasoline price fan chart, Toronto regular, 2027 to 2031")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "fuel_price_fan_chart.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    table, pumps = run()
    table.to_csv(TABLES / "fuel_risk.csv", index=False, float_format="%.2f")
    rows = []
    for method, pump in pumps.items():
        for col in [c for c in pump.columns if c.endswith("-12")]:
            rows.append({"model": method, "month": col, "p5": pump[col].quantile(0.05),
                         "p50": pump[col].median(), "p95": pump[col].quantile(0.95)})
    pd.DataFrame(rows).to_csv(TABLES / "fuel_price_percentiles_december.csv", index=False, float_format="%.1f")
    phi, _, _ = ar1_fit(history())
    print(f"AR(1) phi = {phi:.3f}, half-life = {np.log(0.5) / np.log(phi):.1f} months")
    fan_chart(pumps["mean_reverting"], pumps["random_walk"])
    pd.set_option("display.width", 200)
    print(table.round(0).to_string(index=False))
    print(pd.DataFrame(rows).round(0).to_string(index=False))
    return table


if __name__ == "__main__":
    main()
