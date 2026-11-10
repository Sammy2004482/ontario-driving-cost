"""Insurance pricing on freMTPL2: a frequency model and a severity model combined into a premium.

* Frequency: Poisson GLM, log link, offset log(exposure)  ->  expected claims per policy-year
* Severity:  Gamma GLM, log link, weighted by claim count  ->  expected cost per claim
* Pure premium = frequency x severity. The insurer then adds expenses and profit.

Data preparation follows common practice for this dataset (Noll, Salzmann & Wuthrich 2018):
claim counts capped at 4, exposure capped at 1 year, continuous factors banded, and
individual claims capped at the 99.5th percentile, with the capped excess spread across all
policies as a flat large-loss load.

Which factors move the price most is measured two ways: the spread of each factor's
relativities (highest level / lowest level) and the drop in deviance when the factor is
removed from the model (a likelihood-ratio test).

The data are French motor third-party liability policies from 2004-2005, so the levels are
not Ontario premiums; the *structure* (age, bonus-malus = driving record, vehicle, territory)
is the same one Ontario insurers file with FSRA.

Run:  python -m drivecost.pricing
"""
from __future__ import annotations

import gc

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import statsmodels.api as sm

from drivecost.data import FIGURES, PROCESSED, TABLES

FREQ_FACTORS = ["DrivAgeBand", "BonusMalusBand", "VehAgeBand", "VehPowerBand", "VehBrand", "VehGas",
                "AreaBand", "Region"]
SEV_FACTORS = ["DrivAgeBand", "BonusMalusBand", "VehAgeBand", "VehGas"]
BASE_LEVELS = {"DrivAgeBand": "41-50", "BonusMalusBand": "50", "VehAgeBand": "1-4", "VehPowerBand": "6",
               "VehBrand": "B1", "VehGas": "Regular", "AreaBand": "C", "Region": "R24"}
LABELS = {"DrivAgeBand": "Driver age", "BonusMalusBand": "Bonus-malus (driving record)",
          "VehAgeBand": "Vehicle age", "VehPowerBand": "Vehicle power", "VehBrand": "Vehicle brand",
          "VehGas": "Fuel type", "AreaBand": "Area density class", "Region": "Region"}


def _band(x: pd.Series, edges: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(x, edges, labels=labels, right=True, include_lowest=True).astype(str)


def load(sample_frac: float | None = None, seed: int = 1) -> tuple[pd.DataFrame, pd.DataFrame]:
    freq = pd.read_csv(PROCESSED / "fremtpl2_freq.csv.gz")
    sev = pd.read_csv(PROCESSED / "fremtpl2_sev.csv.gz")
    if sample_frac:
        freq = freq.sample(frac=sample_frac, random_state=seed)
    f = freq.copy()
    f["ClaimNb"] = f.ClaimNb.clip(upper=4)
    f["Exposure"] = f.Exposure.clip(upper=1)
    f["DrivAgeBand"] = _band(f.DrivAge, [17, 20, 25, 30, 40, 50, 60, 70, 120],
                             ["18-20", "21-25", "26-30", "31-40", "41-50", "51-60", "61-70", "71+"])
    f["BonusMalusBand"] = _band(f.BonusMalus, [0, 50, 60, 70, 80, 90, 100, 120, 400],
                                ["50", "51-60", "61-70", "71-80", "81-90", "91-100", "101-120", "121+"])
    f["VehAgeBand"] = _band(f.VehAge, [-1, 0, 4, 9, 14, 200], ["0", "1-4", "5-9", "10-14", "15+"])
    f["VehPowerBand"] = f.VehPower.clip(upper=12).astype(int).astype(str)
    f["AreaBand"] = f.Area.astype(str).str.strip("'")
    for c in ("VehBrand", "Region", "VehGas"):
        f[c] = f[c].astype(str).str.strip("'")

    # severity: per-claim amounts joined to the policy's rating factors
    s = sev.merge(f.drop(columns=["ClaimNb"]), on="IDpol", how="inner")
    cap = s.ClaimAmount.quantile(0.995)
    s["ClaimCapped"] = s.ClaimAmount.clip(upper=cap)
    f.attrs["claim_cap"] = float(cap)
    f.attrs["large_loss_excess"] = float((s.ClaimAmount - s.ClaimCapped).sum())
    return f, s


LEVELS: dict[str, list[str]] = {}


def design(df: pd.DataFrame, factors: list[str]) -> pd.DataFrame:
    """Treatment-coded dummies (base level dropped) plus intercept. Built once, no patsy copies."""
    cols = {"const": np.ones(len(df))}
    for x in factors:
        levels = LEVELS.setdefault(x, sorted(df[x].unique()))
        vals = df[x].values
        for lev in levels:
            if lev != BASE_LEVELS[x]:
                cols[f"{x}[{lev}]"] = (vals == lev).astype(np.float64)
    return pd.DataFrame(cols, index=df.index)


def fit_frequency(f: pd.DataFrame, factors: list[str] = FREQ_FACTORS, X: pd.DataFrame | None = None):
    X = design(f, factors) if X is None else X
    return sm.GLM(f.ClaimNb.values, X, family=sm.families.Poisson(), offset=np.log(f.Exposure.values)).fit()


def fit_severity(s: pd.DataFrame, factors: list[str] = SEV_FACTORS):
    return sm.GLM(s.ClaimCapped.values, design(s, factors),
                  family=sm.families.Gamma(sm.families.links.Log())).fit()


def predict_frequency(model, df: pd.DataFrame, factors: list[str] = FREQ_FACTORS) -> np.ndarray:
    return np.exp(design(df, factors).values @ model.params.values) * df.Exposure.values


def predict_severity(model, df: pd.DataFrame, factors: list[str] = SEV_FACTORS) -> np.ndarray:
    return np.exp(design(df, factors).values @ model.params.values)


def relativities(model, factors: list[str]) -> pd.DataFrame:
    rows = []
    for x in factors:
        rows.append({"factor": x, "level": BASE_LEVELS[x], "relativity": 1.0, "p": np.nan})
        for name, coef in model.params.items():
            if name.startswith(f"{x}["):
                rows.append({"factor": x, "level": name[len(x) + 1:-1], "relativity": float(np.exp(coef)),
                             "p": float(model.pvalues[name])})
    return pd.DataFrame(rows)


def factor_importance(f: pd.DataFrame, freq_model, rel_freq: pd.DataFrame, rel_sev: pd.DataFrame) -> pd.DataFrame:
    rows = []
    X = design(f, FREQ_FACTORS)
    for x in FREQ_FACTORS:
        reduced = fit_frequency(f, X=X[[c for c in X.columns if not c.startswith(f"{x}[")]])
        lr = reduced.deviance - freq_model.deviance
        df = int(freq_model.df_model - reduced.df_model)
        del reduced          # each fitted GLM keeps copies of the design matrix; free it now
        gc.collect()
        rf = rel_freq[rel_freq.factor == x].relativity
        rs = rel_sev[rel_sev.factor == x].relativity if x in SEV_FACTORS else pd.Series([1.0])
        rows.append({"factor": x, "label": LABELS[x], "freq_spread": rf.max() / rf.min(),
                     "sev_spread": rs.max() / rs.min(), "freq_deviance_drop": lr, "df": df,
                     "deviance_per_df": lr / df})
    return pd.DataFrame(rows).sort_values("freq_deviance_drop", ascending=False)


def gini(actual: np.ndarray, predicted: np.ndarray, weight: np.ndarray) -> float:
    """Normalised Gini: rank policies by predicted loss *per year of exposure*, highest first, and
    compare the concentration of actual losses with a perfect ranking (0 = no lift, 1 = perfect).

    actual: losses per policy; predicted: predicted rate per exposure-year; weight: exposure."""
    def _g(order):
        a, w = actual[order], weight[order]
        cum_w = np.cumsum(w) / w.sum()
        cum_a = np.cumsum(a) / a.sum()
        return 1 - 2 * np.trapezoid(cum_a, cum_w)
    return _g(np.argsort(-predicted)) / _g(np.argsort(-actual / np.maximum(weight, 1e-9)))


def example_premiums(freq_model, sev_model, large_loss_load: float) -> pd.DataFrame:
    # VehAge 0 is avoided on purpose: in freMTPL2 brand-new cars carry very short exposures and an
    # implausible 3.4x claim rate (a known data artifact), so the examples use a 1-4 year-old car.
    base = {"VehAgeBand": "1-4", "VehPowerBand": "6", "VehBrand": "B12", "VehGas": "Regular",
            "AreaBand": "D", "Region": "R24", "Exposure": 1.0}
    profiles = {
        "New grad, 22, new licence record (BM 100)": {"DrivAgeBand": "21-25", "BonusMalusBand": "91-100"},
        "Same driver after 5 clean years (BM ~77), age 27": {"DrivAgeBand": "26-30", "BonusMalusBand": "71-80"},
        "Experienced driver, 45, best record (BM 50)": {"DrivAgeBand": "41-50", "BonusMalusBand": "50"},
        "Driver 19, new record (BM 100)": {"DrivAgeBand": "18-20", "BonusMalusBand": "91-100"},
    }
    rows = []
    for name, p in profiles.items():
        d = pd.DataFrame([{**base, **p}])
        fr = float(predict_frequency(freq_model, d)[0])
        sv = float(predict_severity(sev_model, d)[0])
        rows.append({"profile": name, "claim_frequency": fr, "claim_severity_eur": sv,
                     "pure_premium_eur": fr * sv + large_loss_load})
    out = pd.DataFrame(rows)
    out["vs_experienced"] = out.pure_premium_eur / out.pure_premium_eur.iloc[2]
    return out


def plot(importance: pd.DataFrame, rel_freq: pd.DataFrame, rel_sev: pd.DataFrame, path=None):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.2), gridspec_kw={"width_ratios": [1.1, 1, 1]})
    ax = axes[0]
    imp = importance.iloc[::-1]
    ax.barh(imp.label, imp.freq_deviance_drop, color="#2e75b6")
    ax.set_xlabel("deviance explained (drop when factor removed)")
    ax.set_title("Which factors drive claim frequency")
    ax.spines[["top", "right"]].set_visible(False)
    for ax, factor in zip(axes[1:], ["DrivAgeBand", "BonusMalusBand"]):
        rf = rel_freq[rel_freq.factor == factor].copy()
        rs = rel_sev[rel_sev.factor == factor].set_index("level").relativity
        order = sorted(rf.level, key=lambda s: float(s.split("-")[0].rstrip("+")))
        rf = rf.set_index("level").loc[order]
        pp = rf.relativity * rs.reindex(order).fillna(1.0)
        x = np.arange(len(order))
        ax.bar(x - 0.2, rf.relativity, 0.4, color="#9dc3e6", label="frequency")
        ax.bar(x + 0.2, pp, 0.4, color="#1f4e79", label="pure premium (freq x sev)")
        ax.axhline(1, color="black", lw=0.6)
        ax.set_xticks(x, order, rotation=45, fontsize=8)
        ax.set_title(f"{LABELS[factor].split(' (')[0]} relativities (base = {BASE_LEVELS[factor]})", fontsize=10)
        ax.legend(frameon=False, fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    path = path or FIGURES / "pricing_factors.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def main(sample_frac: float | None = None):
    f, s = load(sample_frac)
    for x in FREQ_FACTORS:  # fix the level list on the full data so train/test/examples share columns
        LEVELS[x] = sorted(f[x].unique())
    rng = np.random.default_rng(42)
    test_ids = set(rng.choice(f.IDpol.values, size=len(f) // 5, replace=False))
    is_test = f.IDpol.isin(test_ids)
    train, test = f[~is_test], f[is_test]
    s_train = s[~s.IDpol.isin(test_ids)]

    fm = fit_frequency(train)
    sm_ = fit_severity(s_train)
    load_per_year = f.attrs["large_loss_excess"] / f.Exposure.sum()

    # out-of-sample checks
    mu = pd.Series(predict_frequency(fm, test), index=test.index)
    null_rate = train.ClaimNb.sum() / train.Exposure.sum()
    pois_dev = lambda y, m: 2 * np.sum(np.where(y > 0, y * np.log(np.where(y > 0, y, 1) / m), 0) - (y - m))
    dev_model = pois_dev(test.ClaimNb.values, mu.values)
    dev_null = pois_dev(test.ClaimNb.values, null_rate * test.Exposure.values)
    test_losses = s[s.IDpol.isin(test_ids)].groupby("IDpol").ClaimCapped.sum().reindex(test.IDpol).fillna(0).values
    pp_rate = mu.values / test.Exposure.values * predict_severity(sm_, test)   # pure premium per year
    metrics = {
        "policies": len(f), "exposure_years": f.Exposure.sum(), "claims": int(f.ClaimNb.sum()),
        "claim_frequency": f.ClaimNb.sum() / f.Exposure.sum(), "claim_cap_eur": f.attrs["claim_cap"],
        "large_loss_load_eur_per_year": load_per_year,
        "test_poisson_deviance_explained": 1 - dev_model / dev_null,
        "test_gini_pure_premium": gini(test_losses, pp_rate, test.Exposure.values),
        "mean_severity_eur": s.ClaimCapped.mean(),
    }

    rf = relativities(fm, FREQ_FACTORS)
    rs = relativities(sm_, SEV_FACTORS)
    imp = factor_importance(train, fm, rf, rs)
    ex = example_premiums(fm, sm_, load_per_year)

    rf.to_csv(TABLES / "pricing_frequency_relativities.csv", index=False, float_format="%.4f")
    rs.to_csv(TABLES / "pricing_severity_relativities.csv", index=False, float_format="%.4f")
    imp.to_csv(TABLES / "pricing_factor_importance.csv", index=False, float_format="%.4f")
    ex.to_csv(TABLES / "pricing_example_premiums.csv", index=False, float_format="%.4f")
    pd.Series(metrics).to_csv(TABLES / "pricing_metrics.csv", header=["value"], float_format="%.4f")
    plot(imp, rf, rs)
    pd.set_option("display.width", 200)
    print(pd.Series(metrics).round(4).to_string())
    print(imp.round(2).to_string(index=False))
    print(ex.round(3).to_string(index=False))
    return metrics, imp, ex


if __name__ == "__main__":
    main()
