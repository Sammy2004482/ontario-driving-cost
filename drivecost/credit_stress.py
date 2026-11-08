"""Credit stress test: what a 30% fuel price spike does to a small trucking company.

A credit analyst asks two questions: can the borrower still cover its interest
(interest coverage = EBITDA / interest, and EBIT / interest), and is it over-levered
(debt / EBITDA)? Bank covenants put floors and ceilings on these ratios.

The company is a simplified, illustrative southwestern-Ontario regional carrier. Fuel is
20% of revenue. Carriers pass part of fuel increases to customers through fuel surcharges,
usually with a lag, so the stress is run across surcharge-recovery rates. Optional extras:
a +200 bp rise in its floating loan rate, and the fuel hedge from drivecost.hedge.

Hedge sizing lesson: hedge only the fuel cost the surcharge does NOT recover. With 50%
recovery, hedging 70% of volume over-hedges: surcharge plus hedge gains exceed the shock and
the company is then exposed to fuel price *falls*.

Run:  python -m drivecost.credit_stress
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from drivecost.data import FIGURES, TABLES


@dataclass(frozen=True)
class Financials:
    revenue: float = 24_000_000
    fuel: float = 4_800_000
    wages: float = 9_600_000
    other_opex: float = 6_600_000
    depreciation: float = 1_500_000
    debt: float = 9_000_000
    rate: float = 0.0695           # floating: prime + 1.5%
    tax_rate: float = 0.265        # Ontario combined general rate
    max_debt_to_ebitda: float = 3.5
    min_ebitda_coverage: float = 3.0


def ratios(f: Financials, fuel_shock: float = 0.0, surcharge_recovery: float = 0.0,
           rate_shock_bp: float = 0.0, hedged_share: float = 0.0, hedge_ratio: float = 0.9) -> dict:
    """Annual P&L and credit ratios after a fuel price shock.

    fuel_shock          proportional rise in fuel prices for the year (0.30 = +30%)
    surcharge_recovery  share of the extra fuel cost billed back to customers
    hedged_share        share of fuel volume hedged with futures; the hedge pays
                        hedge_ratio x shock x hedged fuel cost
    """
    extra_fuel = f.fuel * fuel_shock
    surcharge = extra_fuel * surcharge_recovery
    hedge_gain = f.fuel * hedged_share * hedge_ratio * fuel_shock
    revenue = f.revenue + surcharge
    ebitda = revenue - (f.fuel + extra_fuel) - f.wages - f.other_opex + hedge_gain
    ebit = ebitda - f.depreciation
    interest = f.debt * (f.rate + rate_shock_bp / 10_000)
    pretax = ebit - interest
    net = pretax * (1 - f.tax_rate) if pretax > 0 else pretax
    out = {
        "fuel_shock": fuel_shock, "surcharge_recovery": surcharge_recovery, "rate_shock_bp": rate_shock_bp,
        "hedged_share": hedged_share, "revenue": revenue, "fuel_cost": f.fuel + extra_fuel,
        "hedge_gain": hedge_gain, "ebitda": ebitda, "ebitda_margin": ebitda / revenue, "ebit": ebit,
        "interest": interest, "net_income": net,
        "ebitda_coverage": ebitda / interest, "ebit_coverage": ebit / interest,
        "debt_to_ebitda": f.debt / ebitda if ebitda > 0 else np.inf,
    }
    out["breaches_leverage"] = out["debt_to_ebitda"] > f.max_debt_to_ebitda
    out["breaches_coverage"] = out["ebitda_coverage"] < f.min_ebitda_coverage
    out["covenant_breach"] = out["breaches_leverage"] or out["breaches_coverage"]
    return out


def scenarios(f: Financials = Financials()) -> pd.DataFrame:
    rows = [
        ("Base case", ratios(f)),
        ("Fuel +30%, no surcharge", ratios(f, 0.30, 0.0)),
        ("Fuel +30%, 50% surcharge recovery", ratios(f, 0.30, 0.5)),
        ("Fuel +30%, 80% surcharge recovery", ratios(f, 0.30, 0.8)),
        ("Fuel +30%, 50% recovery, +200 bp rates", ratios(f, 0.30, 0.5, 200)),
        ("Fuel +30%, 50% recovery, +200 bp, unrecovered 50% hedged", ratios(f, 0.30, 0.5, 200, 0.5)),
    ]
    return pd.DataFrame([{"scenario": k, **v} for k, v in rows])


def breakeven_shock(f: Financials = Financials(), surcharge_recovery: float = 0.0, rate_shock_bp: float = 0.0,
                    hedged_share: float = 0.0) -> float:
    """Smallest fuel price rise that breaches a covenant (bisection)."""
    lo, hi = 0.0, 5.0
    if not ratios(f, hi, surcharge_recovery, rate_shock_bp, hedged_share)["covenant_breach"]:
        return np.inf
    for _ in range(60):
        mid = (lo + hi) / 2
        if ratios(f, mid, surcharge_recovery, rate_shock_bp, hedged_share)["covenant_breach"]:
            hi = mid
        else:
            lo = mid
    return hi


def plot(f: Financials = Financials(), path=None):
    shocks = np.linspace(0, 0.6, 61)
    recov = np.linspace(0, 1, 51)
    lev = np.array([[ratios(f, s, r)["debt_to_ebitda"] for s in shocks] for r in recov])
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    ax = axes[0]
    im = ax.pcolormesh(shocks * 100, recov * 100, np.minimum(lev, 8), cmap="RdYlGn_r", shading="auto", vmin=2, vmax=6)
    cs = ax.contour(shocks * 100, recov * 100, lev, levels=[f.max_debt_to_ebitda], colors="black", linewidths=1.5)
    ax.clabel(cs, fmt=lambda v: f"covenant {v:.1f}x", fontsize=8)
    ax.plot(30, 50, "wo", mec="black")
    ax.annotate("+30% fuel,\n50% recovery", (30, 50), xytext=(8, 8), textcoords="offset points", fontsize=8)
    fig.colorbar(im, ax=ax, label="debt / EBITDA (x)")
    ax.set_xlabel("fuel price rise (%)")
    ax.set_ylabel("fuel surcharge recovery (%)")
    ax.set_title("Leverage after a fuel shock")

    ax = axes[1]
    sc = scenarios(f)
    y = np.arange(len(sc))[::-1]
    ax.barh(y, sc.ebitda_coverage, color=np.where(sc.covenant_breach, "#c00000", "#2e75b6"))
    ax.axvline(f.min_ebitda_coverage, color="black", ls="--", lw=1)
    ax.text(f.min_ebitda_coverage, len(sc) - 0.4, " coverage covenant", fontsize=8)
    for yi, (cov, lev_) in zip(y, zip(sc.ebitda_coverage, sc.debt_to_ebitda)):
        ax.text(cov + 0.05, yi, f"{cov:.1f}x  (debt/EBITDA {lev_:.1f}x)", va="center", fontsize=8)
    ax.set_yticks(y, sc.scenario, fontsize=8)
    ax.set_xlabel("EBITDA / interest (x)")
    ax.set_xlim(0, sc.ebitda_coverage.max() * 1.6)
    ax.set_title("Interest coverage by scenario (red = covenant breach)")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "credit_stress.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    f = Financials()
    sc = scenarios(f)
    sc.to_csv(TABLES / "credit_stress_scenarios.csv", index=False, float_format="%.4f")
    be = pd.DataFrame([{"surcharge_recovery": r, "rate_shock_bp": b, "hedged_share": h,
                        "breakeven_fuel_rise": breakeven_shock(f, r, b, h)}
                       for r in (0, 0.5, 0.8) for b in (0, 200) for h in (0, 0.5)])
    be.to_csv(TABLES / "credit_stress_breakeven.csv", index=False, float_format="%.4f")
    plot(f)
    pd.set_option("display.width", 220)
    cols = ["scenario", "ebitda", "ebitda_margin", "interest", "ebitda_coverage", "ebit_coverage",
            "debt_to_ebitda", "covenant_breach"]
    print(sc[cols].round(2).to_string(index=False))
    print(be.round(3).to_string(index=False))
    return sc


if __name__ == "__main__":
    main()
