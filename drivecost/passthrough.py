"""How fast do crude oil price changes reach the Toronto pump, and do prices rise faster
than they fall ("rockets and feathers")?

Everything is in Canadian cents per litre, monthly, January 2015 onward.

1. Symmetric distributed lag (ADL):
       dPump_t = a + sum_k b_k dCrude_{t-k} + c dTax_t + e_t
   With HST at 13%, full pass-through of a 1 c/L crude move is 1.13 c/L at the pump.
2. Asymmetric distributed lag: dCrude split into rises (dCrude+) and falls (dCrude-), each
   with its own lags. Rockets and feathers = rises are passed through faster, i.e. the
   cumulative response to rises exceeds the response to falls at short horizons.
3. Asymmetric error-correction model (Borenstein, Cameron & Gilbert 1997 style):
   long run   PumpExTax_t = alpha + gamma Crude_t + u_t
   short run  dPump_t = ... + theta+ u+_{t-1} + theta- u-_{t-1}
   u+ > 0 means the pump is ABOVE its long-run level (fat margins), u- < 0 means BELOW
   (squeezed margins). Rockets and feathers in this form: theta- is much more negative than
   theta+, i.e. squeezed margins are rebuilt quickly while fat margins erode slowly.

Standard errors are Newey-West (HAC). Run:  python -m drivecost.passthrough
"""
from __future__ import annotations

from dataclasses import dataclass

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from drivecost.data import FIGURES, HST, TABLES, monthly_panel

START = "2015-01"


def build_frame(driver: str = "crude_cpl", lags: int = 3, start: str = START,
                panel: pd.DataFrame | None = None) -> pd.DataFrame:
    p = (monthly_panel() if panel is None else panel).copy()
    d = pd.DataFrame(index=p.index)
    d["dpump"] = p.pump_cpl.diff()
    # tax changes enter the pump price with HST on top
    d["dtax"] = p.tax_cpl.diff() * (1 + HST)
    dx = p[driver].diff()
    for k in range(lags + 1):
        d[f"dx_l{k}"] = dx.shift(k)
        d[f"dxpos_l{k}"] = dx.clip(lower=0).shift(k)
        d[f"dxneg_l{k}"] = dx.clip(upper=0).shift(k)
    d["level_pump_ex_tax"] = p.pump_ex_tax_cpl
    d["level_x"] = p[driver]
    return d.loc[start:].dropna()


def _hac(y, X, maxlags=3):
    return sm.OLS(y, sm.add_constant(X)).fit(cov_type="HAC", cov_kwds={"maxlags": maxlags})


@dataclass
class PassThroughResult:
    driver: str
    lags: int
    symmetric: object
    asymmetric: object
    ecm: object
    long_run: object
    cum_sym: pd.DataFrame
    cum_asym: pd.DataFrame
    tests: dict


def _cumulative(res, prefix: str, lags: int) -> pd.DataFrame:
    names = list(res.params.index)
    rows = []
    for k in range(lags + 1):
        w = np.zeros(len(names))
        for j in range(k + 1):
            w[names.index(f"{prefix}_l{j}")] = 1
        est = float(w @ res.params.values)
        se = float(np.sqrt(w @ res.cov_params().values @ w))
        rows.append({"month": k, "cum": est, "lo": est - 1.96 * se, "hi": est + 1.96 * se, "se": se})
    return pd.DataFrame(rows)


def _wald(res, lhs: list[str], rhs: list[str]) -> tuple[float, float]:
    names = list(res.params.index)
    R = np.zeros((1, len(names)))
    for n in lhs:
        R[0, names.index(n)] += 1
    for n in rhs:
        R[0, names.index(n)] -= 1
    t = res.wald_test(R, scalar=True)
    return float(t.statistic), float(t.pvalue)


def estimate(driver: str = "crude_cpl", lags: int = 3, panel: pd.DataFrame | None = None,
             start: str = START) -> PassThroughResult:
    d = build_frame(driver, lags, start, panel)
    sym_cols = [f"dx_l{k}" for k in range(lags + 1)] + ["dtax"]
    pos = [f"dxpos_l{k}" for k in range(lags + 1)]
    neg = [f"dxneg_l{k}" for k in range(lags + 1)]
    sym = _hac(d.dpump, d[sym_cols])
    asym = _hac(d.dpump, d[pos + neg + ["dtax"]])

    # Engle-Granger long-run relation on pre-tax levels, then asymmetric ECM
    lr = sm.OLS(d.level_pump_ex_tax, sm.add_constant(d.level_x)).fit()
    u = lr.resid.shift(1)
    e = d.assign(ect_pos=u.clip(lower=0), ect_neg=u.clip(upper=0)).dropna()
    ecm = _hac(e.dpump, e[pos + neg + ["dtax", "ect_pos", "ect_neg"]])

    tests = {}
    tests["wald_cum_pos_eq_neg_F"], tests["wald_cum_pos_eq_neg_p"] = _wald(asym, pos, neg)
    tests["wald_contemp_pos_eq_neg_F"], tests["wald_contemp_pos_eq_neg_p"] = _wald(asym, pos[:1], neg[:1])
    tests["wald_ecm_adjust_eq_F"], tests["wald_ecm_adjust_eq_p"] = _wald(ecm, ["ect_pos"], ["ect_neg"])
    cum_s = _cumulative(sym, "dx", lags)
    tests["cum_symmetric"] = float(cum_s.cum.iloc[-1])
    tests["share_passed_through"] = float(cum_s.cum.iloc[-1] / (1 + HST))
    tests["share_in_first_month"] = float(cum_s.cum.iloc[0] / cum_s.cum.iloc[-1])
    tests["tax_coef"] = float(sym.params["dtax"])
    tests["long_run_gamma"] = float(lr.params["level_x"])
    tests["ect_pos"], tests["ect_neg"] = float(ecm.params["ect_pos"]), float(ecm.params["ect_neg"])
    for k, th in (("pos", tests["ect_pos"]), ("neg", tests["ect_neg"])):
        tests[f"half_life_months_{k}"] = float(np.log(0.5) / np.log(1 + th)) if -1 < th < 0 else float("nan")
    tests["n_obs"] = int(sym.nobs)
    tests["sample"] = f"{d.index[0]} to {d.index[-1]}"

    cum_a = pd.concat([_cumulative(asym, "dxpos", lags).assign(direction="rise"),
                       _cumulative(asym, "dxneg", lags).assign(direction="fall")])
    return PassThroughResult(driver, lags, sym, asym, ecm, lr, cum_s, cum_a, tests)


def coefficient_table(r: PassThroughResult) -> pd.DataFrame:
    rows = []
    for name, res in (("symmetric", r.symmetric), ("asymmetric", r.asymmetric), ("ecm", r.ecm)):
        for k in res.params.index:
            rows.append({"model": name, "term": k, "coef": res.params[k], "se_hac": res.bse[k],
                         "p": res.pvalues[k]})
    return pd.DataFrame(rows)


def plot(r: PassThroughResult, path=None):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    p = monthly_panel().loc[START:]
    ax = axes[0]
    ax.plot(pd.to_datetime(p.index), p.pump_cpl, color="#1f4e79", lw=1.8, label="Toronto regular, pump")
    ax.plot(pd.to_datetime(p.index), p.wholesale_cpl, color="#c55a11", lw=1.2, label="NY Harbor gasoline (CAD)")
    ax.plot(pd.to_datetime(p.index), p.crude_cpl, color="#7f7f7f", lw=1.2, label="WTI crude (CAD)")
    ax.set_ylabel("cents per litre")
    ax.set_title("Pump, wholesale and crude prices")
    ax.legend(frameon=False, fontsize=8)
    ax.spines[["top", "right"]].set_visible(False)

    ax = axes[1]
    colors = {"rise": "#c00000", "fall": "#2e75b6"}
    for direction, g in r.cum_asym.groupby("direction"):
        ax.plot(g.month, g.cum, marker="o", color=colors[direction],
                label=f"crude {'rises' if direction == 'rise' else 'falls'}")
        ax.fill_between(g.month, g.lo, g.hi, color=colors[direction], alpha=0.12)
    ax.axhline(1 + HST, color="black", ls="--", lw=0.8)
    ax.text(r.lags, 1 + HST + 0.03, "full pass-through incl. HST", ha="right", fontsize=8)
    ax.set_xticks(range(r.lags + 1))
    ax.set_xlabel("months after the crude price change")
    ax.set_ylabel("cumulative pump change per 1 c/L crude change")
    ax.set_title(f"Pass-through: rises vs falls (p = {r.tests['wald_contemp_pos_eq_neg_p']:.2f} same-month)")
    ax.legend(frameon=False, fontsize=8, loc="lower right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / f"passthrough_{r.driver}.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main():
    out = {}
    for driver in ("crude_cpl", "wholesale_cpl"):
        r = estimate(driver)
        coefficient_table(r).to_csv(TABLES / f"passthrough_coefs_{driver}.csv", index=False, float_format="%.4f")
        r.cum_asym.to_csv(TABLES / f"passthrough_cumulative_{driver}.csv", index=False, float_format="%.4f")
        plot(r)
        out[driver] = r.tests
    t = pd.DataFrame(out)
    t.to_csv(TABLES / "passthrough_tests.csv")
    print(t.to_string())
    return out


if __name__ == "__main__":
    main()
