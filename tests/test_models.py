"""Tests for pass-through, inflation, risk, hedge and credit modules on synthetic data with known answers."""
import numpy as np
import pandas as pd
import pytest

from drivecost import credit_stress as cs
from drivecost import hedge, inflation, passthrough, risk
from tests.conftest import needs_data


def _synthetic_panel(n=400, b_pos=(0.8, 0.3), b_neg=(0.3, 0.3), seed=0):
    """Pump changes built from crude rises/falls with known lag coefficients."""
    rng = np.random.default_rng(seed)
    months = pd.period_range("1990-01", periods=n, freq="M").astype(str)
    dcrude = rng.normal(0, 3, n)
    pos, neg = dcrude.clip(min=0), dcrude.clip(max=0)
    lag = lambda x: np.r_[0, x[:-1]]
    dpump = (b_pos[0] * pos + b_pos[1] * lag(pos) + b_neg[0] * neg + b_neg[1] * lag(neg)
             + rng.normal(0, 0.5, n))
    crude = 50 + np.cumsum(dcrude)
    pump = 130 + np.cumsum(dpump)
    tax = np.where(np.arange(n) < n // 2, 20.0, 25.0)          # one tax increase mid-sample
    pump = pump + (tax - 20.0) * 1.13
    return pd.DataFrame({"pump_cpl": pump, "crude_cpl": crude, "tax_cpl": tax,
                         "pump_ex_tax_cpl": pump / 1.13 - tax}, index=months)


def test_passthrough_recovers_known_coefficients_and_detects_asymmetry():
    panel = _synthetic_panel()
    r = passthrough.estimate("crude_cpl", lags=1, panel=panel, start="1990-03")
    assert r.asymmetric.params["dxpos_l0"] == pytest.approx(0.8, abs=0.05)
    assert r.asymmetric.params["dxneg_l0"] == pytest.approx(0.3, abs=0.05)
    assert r.tests["wald_contemp_pos_eq_neg_p"] < 0.001


def test_passthrough_no_false_asymmetry():
    panel = _synthetic_panel(b_pos=(0.5, 0.5), b_neg=(0.5, 0.5), seed=3)
    r = passthrough.estimate("crude_cpl", lags=1, panel=panel, start="1990-03")
    assert r.tests["cum_symmetric"] == pytest.approx(1.0, abs=0.05)
    assert r.tests["wald_cum_pos_eq_neg_p"] > 0.01


def test_inflation_contribution_adds_up():
    months = pd.period_range("2019-01", periods=36, freq="M").astype(str)
    c = pd.DataFrame({"all_items": np.linspace(100, 110, 36), "gasoline": np.linspace(100, 140, 36)}, index=months)
    w = pd.DataFrame({"basket_year": [2017], "gasoline_weight_pct": [4.0], "link_month": ["2018-12"]})
    m = inflation.monthly_contribution(c, w)
    assert np.allclose(m.gasoline_contribution_pp + m.ex_gasoline_contribution_pp, m.headline_pct)
    # first month: weight is exactly 4% (no relative price change since the link month)
    first = m.iloc[0]
    assert first.gasoline_weight_eff_pct == pytest.approx(4.0 * (c.gasoline.iloc[0] / 100) / (c.all_items.iloc[0] / 100))
    assert first.gasoline_contribution_pp == pytest.approx(first.gasoline_weight_eff_pct / 100 * first.gasoline_yoy_pct)


def test_risk_measures_on_normal_distribution():
    x = np.random.default_rng(1).normal(1000, 100, 2_000_000)
    m = risk.risk_measures(x)
    assert m["var95"] == pytest.approx(1.6449 * 100, rel=0.01)
    # ES of a normal at 95%: sigma * pdf(1.645) / 0.05 = 2.063 sigma
    assert m["es95"] == pytest.approx(2.0627 * 100, rel=0.01)


def test_simulation_shapes_and_reproducibility():
    hist = pd.Series(np.exp(np.cumsum(np.random.default_rng(2).normal(0, 0.05, 120))) * 80,
                     index=pd.period_range("2016-10", periods=120, freq="M").astype(str))
    a = risk.simulate_market_price(500, "mean_reverting", seed=5, hist=hist, end="2031-12")
    b = risk.simulate_market_price(500, "mean_reverting", seed=5, hist=hist, end="2031-12")
    assert a.equals(b) and a.shape == (500, 63) and (a > 0).all().all()
    rw = risk.simulate_market_price(4000, "random_walk", seed=5, hist=hist, end="2031-12")
    mr = risk.simulate_market_price(4000, "mean_reverting", seed=5, hist=hist, end="2031-12")
    assert np.log(rw.iloc[:, -1]).std() > np.log(mr.iloc[:, -1]).std()


def test_min_variance_hedge_ratio_recovered():
    rng = np.random.default_rng(4)
    n = 300
    dF = rng.normal(0, 5, n)
    dS = 0.7 * dF + rng.normal(0, 1, n)
    months = pd.period_range("2000-01", periods=n, freq="M").astype(str)
    panel = pd.DataFrame({"pump_ex_tax_cpl": 80 + np.cumsum(dS), "wholesale_cpl": 70 + np.cumsum(dF)}, index=months)
    h = hedge.hedge_ratio("2000-01", panel=panel)
    assert h.h == pytest.approx(0.7, abs=0.03)
    assert h.contracts(hedge.L_PER_CONTRACT * 10) == pytest.approx(10 * h.h)


def test_margin_account_calls_and_conservation():
    prices = pd.Series([3.0, 2.9, 2.7, 2.8, 3.1], index=pd.bdate_range("2027-01-04", periods=5))
    fx = pd.Series(1.0, index=prices.index)
    a = hedge.margin_account(prices, fx, contracts=2, side=1, im=10_000, mm=9_000)
    # day 1: -0.10 x 42,000 x 2 = -8,400 -> balance 11,600 < 18,000 maintenance -> call 8,400
    assert a.margin_call_usd.iloc[0] == pytest.approx(8_400)
    # cash in/out net of the account must equal the futures P&L
    net_cash = a.excess_paid_usd.sum() - a.margin_call_usd.sum()
    assert net_cash + (a.balance_usd.iloc[-1] - 20_000) == pytest.approx(a.variation_margin_usd.sum())


def test_credit_ratios_and_breakeven():
    f = cs.Financials()
    base = cs.ratios(f)
    assert base["debt_to_ebitda"] == pytest.approx(f.debt / 3_000_000)
    full_recovery = cs.ratios(f, 0.30, 1.0)
    assert full_recovery["ebitda"] == pytest.approx(base["ebitda"])
    be = cs.breakeven_shock(f)
    assert cs.ratios(f, be * 1.001)["covenant_breach"] and not cs.ratios(f, be * 0.999)["covenant_breach"]


@needs_data
def test_real_data_sanity():
    from drivecost.data import monthly_panel
    p = monthly_panel()
    assert p.loc["2015-01":].index[0] == "2015-01"
    assert p.pump_cpl.between(60, 260).all()
    r = passthrough.estimate()
    assert 0.8 < r.tests["share_passed_through"] < 1.6


@needs_data
def test_pricing_glms_on_sample():
    from drivecost import pricing
    f, s = pricing.load(sample_frac=0.05)
    for x in pricing.FREQ_FACTORS:
        pricing.LEVELS[x] = sorted(f[x].unique())
    fm = pricing.fit_frequency(f)
    rate = f.ClaimNb.sum() / f.Exposure.sum()
    # a Poisson GLM with intercept reproduces total claims exactly
    assert pricing.predict_frequency(fm, f).sum() == pytest.approx(f.ClaimNb.sum(), rel=1e-6)
    assert 0.05 < rate < 0.15
    rel = pricing.relativities(fm, ["BonusMalusBand"]).set_index("level").relativity
    assert rel["121+"] > rel["50"]       # bad driving record costs more
