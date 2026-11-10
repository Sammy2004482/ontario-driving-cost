"""Pulls the models together for the memo: which car, and how should I pay for it?

* TCO for the three memo cars x three ways to pay (chart 1)
* fuel-bill risk by car, using the simulated pump prices from drivecost.risk (chart 3)
* tornado: which inputs could flip "hybrid vs EV" (chart 4), and break-even values
* rate stress: what a +200 bp Bank of Canada move does to the finance and lease options

Run:  python -m drivecost.decision
"""
from __future__ import annotations

from dataclasses import replace

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from drivecost import risk
from drivecost.data import FIGURES, TABLES
from drivecost.tco import compare, default_assumptions, memo_vehicles, summarize

COMPONENTS = [("acquisition", "payments / purchase", "#1f4e79"), ("resale", "resale value", "#a9d18e"),
              ("energy", "fuel / electricity", "#c55a11"), ("insurance", "insurance", "#7f7f7f"),
              ("maintenance", "maintenance", "#bdd7ee"), ("other", "tires, charger, lease km", "#ffd966")]
SHORT = {"Toyota Corolla LE (gas)": "Corolla (gas)", "Toyota Corolla Hybrid": "Corolla Hybrid",
         "Hyundai Kona Electric": "Kona Electric"}


def tco_chart(res: pd.DataFrame, path=None):
    fig, ax = plt.subplots(figsize=(8, 4.2))
    x = np.arange(len(res))
    pos = np.zeros(len(res))
    neg = np.zeros(len(res))
    for key, label, color in COMPONENTS:
        v = res[key].values / 1000
        bottom = np.where(v >= 0, pos, neg)
        ax.bar(x, v, bottom=bottom, color=color, label=label, width=0.7)
        pos += np.where(v >= 0, v, 0)
        neg += np.where(v < 0, v, 0)
    ax.scatter(x, res.total / 1000, marker="D", color="black", zorder=5, s=22, label="net 5-year cost")
    for xi, t in zip(x, res.total / 1000):
        ax.text(xi, pos[xi] + 1, f"net \\${t:.1f}k", ha="center", fontsize=7.5, fontweight="bold")
    ax.axhline(0, color="black", lw=0.6)
    ax.set_xticks(x, [f"{SHORT[v]}\n{m}" for v, m in zip(res.vehicle, res.method)], fontsize=7.5)
    for b in (2.5, 5.5):
        ax.axvline(b, color="grey", lw=0.5, ls=":")
    ax.set_ylabel("CAD thousands over 5 years")
    ax.set_title("5-year cost of ownership, net of resale (London ON, 16,000 km/yr)")
    ax.legend(frameon=False, fontsize=7, ncol=3, loc="upper left")
    ax.set_ylim(neg.min() - 3, pos.max() + 14)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "memo_tco.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def fuel_risk_by_car(n_paths: int = 20_000):
    a = default_assumptions()
    pump = risk.pump_price(risk.simulate_market_price(n_paths, "mean_reverting"))
    stress = risk.pump_price(risk.simulate_market_price(n_paths, "random_walk"))
    out, dists = [], {}
    for v in memo_vehicles():
        if v.powertrain == "BEV":
            elec = sum(a.km_per_year / 100 * v.kwh_per_100km * a.elec_per_kwh * (1 + a.elec_growth) ** g
                       for g in range(5))
            base = st = np.full(n_paths, elec)
        else:
            e = risk.Exposure(v.name, 1, a.km_per_year, v.l_per_100km)
            base = risk.fuel_cost(pump, e).values
            st = risk.fuel_cost(stress, e).values
        dists[v.name] = base
        for model, d in (("mean_reverting", base), ("random_walk", st)):
            out.append({"vehicle": v.name, "model": model, **risk.risk_measures(d)})
    return pd.DataFrame(out), dists


def fuel_risk_chart(dists: dict[str, np.ndarray], path=None):
    fig, ax = plt.subplots(figsize=(6.6, 4.0))
    colors = {"Toyota Corolla LE (gas)": "#c55a11", "Toyota Corolla Hybrid": "#2e75b6",
              "Hyundai Kona Electric": "#70ad47"}
    bins = np.linspace(0, max(np.quantile(d, 0.995) for d in dists.values()) / 1000, 90)
    for name, d in dists.items():
        d = d / 1000
        if np.ptp(d) < 1e-9:
            ax.axvline(d[0], color=colors[name], lw=2.5, label=f"{SHORT[name]}: \\${d[0]:.1f}k (electricity, ~fixed)")
            continue
        m = risk.risk_measures(d)
        ax.hist(d, bins=bins, color=colors[name], alpha=0.55, density=True,
                label=f"{SHORT[name]}: median \\${m['p50']:.1f}k, 95% VaR +\\${m['var95']:.1f}k")
        ax.axvline(m["p95"], color=colors[name], ls="--", lw=1)
    ax.set_xlabel("5-year energy bill, 2027-2031 (CAD thousands)")
    ax.set_yticks([])
    ax.set_title("How uncertain is the 5-year fuel bill?\n(20,000 simulated price paths; dashed = 95th percentile)", fontsize=10)
    ax.legend(frameon=False, fontsize=8, loc="upper right")
    ax.spines[["top", "right", "left"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "memo_fuel_risk.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


TORNADO_INPUTS = {
    # name: (where, low, high, label)
    "gas_cpl": ("a", 120.0, 220.0, "Gas price, year 1 (120 to 220 c/L)"),
    "km_per_year": ("a", 10_000, 25_000, "Km per year (10k to 25k)"),
    "elec_per_kwh": ("a", 0.10, 0.30, "Electricity ($0.10 to $0.30/kWh)"),
    "ev_price": ("ev", 38_000, 50_000, "Kona price ($38k to $50k)"),
    "ev_resale": ("ev", 0.28, 0.48, "Kona resale after 5 yrs (28% to 48%)"),
    "ev_insurance": ("ev", 2_900, 3_900, "Kona insurance ($2.9k to $3.9k/yr)"),
    "rebate": ("ev", 0, 5_000, "EV rebate ($0 to $5k)"),
    "discount_rate": ("a", 0.0, 0.07, "Discount rate (0% to 7%)"),
}


def _gap(a, gas, ev, method="cash"):
    return summarize(ev, a, method)["npv"] - summarize(gas, a, method)["npv"]


def _apply(a, hev, ev, name, value):
    where = TORNADO_INPUTS[name][0]
    if where == "a":
        return replace(a, **{name: value}), hev, ev
    if name == "ev_price":
        return a, hev, replace(ev, price=value)
    if name == "ev_resale":
        r = np.array(ev.retention)
        return a, hev, replace(ev, retention=tuple(r * value / r[-1]))
    if name == "ev_insurance":
        return a, hev, replace(ev, insurance=value)
    if name == "rebate":
        return a, hev, replace(ev, rebate=value)
    raise KeyError(name)


def tornado(method: str = "cash") -> tuple[pd.DataFrame, float]:
    a = default_assumptions()
    _, hev, ev = memo_vehicles()
    base = _gap(a, hev, ev, method)
    rows = []
    for name, (_, lo, hi, label) in TORNADO_INPUTS.items():
        g_lo = _gap(*_apply(a, hev, ev, name, lo), method)
        g_hi = _gap(*_apply(a, hev, ev, name, hi), method)
        rows.append({"input": name, "label": label, "gap_low": g_lo, "gap_high": g_hi,
                     "swing": abs(g_hi - g_lo)})
    return pd.DataFrame(rows).sort_values("swing"), base


def tornado_chart(t: pd.DataFrame, base: float, path=None):
    fig, ax = plt.subplots(figsize=(6.8, 4.2))
    y = np.arange(len(t))
    for yi, (_, r) in zip(y, t.iterrows()):
        lo, hi = r.gap_low / 1000, r.gap_high / 1000
        ax.barh(yi, lo - base / 1000, left=base / 1000, color="#9dc3e6", height=0.6)
        ax.barh(yi, hi - base / 1000, left=base / 1000, color="#1f4e79", height=0.6)
    ax.axvline(base / 1000, color="black", lw=1)
    ax.axvline(0, color="#c00000", lw=1.2, ls="--")
    ax.text(0, len(t) - 0.4, " EV wins left of this line", color="#c00000", fontsize=8)
    ax.set_yticks(y, t.label.str.replace("$", r"\$", regex=False), fontsize=8)
    ax.set_xlabel("Kona Electric minus Corolla Hybrid,\n5-yr cost in today's dollars (CAD thousands)")
    ax.set_title(f"What would change the answer? Base gap: EV costs \\${base / 1000:.1f}k more\n"
                 "(light = low end of range, dark = high end)", fontsize=10)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "memo_tornado.png"
    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def breakevens(method: str = "cash") -> dict:
    """Value of each input at which the Kona Electric costs the same as the Corolla Hybrid (NPV)."""
    a = default_assumptions()
    _, hev, ev = memo_vehicles()

    def solve(name, lo, hi):
        f = lambda x: _gap(*_apply(a, hev, ev, name, x), method)
        if np.sign(f(lo)) == np.sign(f(hi)):
            return np.nan
        for _ in range(80):
            mid = (lo + hi) / 2
            if np.sign(f(mid)) == np.sign(f(lo)):
                lo = mid
            else:
                hi = mid
        return (lo + hi) / 2

    return {"ev_price_breakeven": solve("ev_price", 20_000, 60_000),
            "gas_cpl_breakeven": solve("gas_cpl", 100, 800),
            "km_per_year_breakeven": solve("km_per_year", 5_000, 150_000)}


def rate_stress() -> pd.DataFrame:
    rows = []
    for bp in (-100, 0, 100, 200):
        a = default_assumptions()
        a = replace(a, policy_rate=a.policy_rate + bp / 100)
        res = compare(memo_vehicles(), a)
        res["policy_rate"] = a.policy_rate
        res["shock_bp"] = bp
        rows.append(res)
    return pd.concat(rows)


def main():
    a = default_assumptions()
    res = compare(memo_vehicles(), a)
    res.to_csv(TABLES / "tco_comparison.csv", index=False, float_format="%.2f")
    tco_chart(res)
    fr, dists = fuel_risk_by_car()
    fr.to_csv(TABLES / "fuel_risk_by_car.csv", index=False, float_format="%.2f")
    fuel_risk_chart(dists)
    t, base = tornado()
    t.to_csv(TABLES / "tornado_ev_vs_hybrid.csv", index=False, float_format="%.2f")
    tornado_chart(t, base)
    be = breakevens()
    pd.Series(be).to_csv(TABLES / "breakevens_ev_vs_hybrid.csv", header=["value"], float_format="%.2f")
    rs = rate_stress()
    rs.to_csv(TABLES / "tco_rate_stress.csv", index=False, float_format="%.2f")
    risk.fan_chart(risk.pump_price(risk.simulate_market_price(20_000, "mean_reverting")),
                   risk.pump_price(risk.simulate_market_price(20_000, "random_walk")))
    pd.set_option("display.width", 200)
    print(a)
    print(res[["vehicle", "method", "total", "npv", "per_month"]].round(0).to_string(index=False))
    print(fr.round(0).to_string(index=False))
    print(t.round(0).to_string(index=False), "\nbase gap", round(base))
    print({k: round(v, 1) for k, v in be.items()})
    print(rs.pivot_table(index=["vehicle", "method"], columns="shock_bp", values="npv").round(0))


if __name__ == "__main__":
    main()
