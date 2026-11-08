import shutil

import numpy as np
import pytest

from drivecost.tco import Assumptions, Vehicle, compare, lease_payment, loan_balance, loan_payment, summarize, tco
from tests.conftest import needs_data

CAR = Vehicle("Test car", "ICE", price=30_000, l_per_100km=7.0, insurance=2_000, maintenance=1_000)
EV = Vehicle("Test EV", "BEV", price=40_000, kwh_per_100km=18.0, insurance=2_400, maintenance=500,
             charger=1_500, retention=(0.7, 0.6, 0.5, 0.42, 0.35))
A = Assumptions(policy_rate=2.5, gas_cpl=150, km_per_year=15_000)


def test_loan_payment_matches_textbook_value():
    # $20,000 at 6% for 60 months -> $386.66 (standard amortisation table)
    assert loan_payment(20_000, 0.06, 60) == pytest.approx(386.656, abs=1e-3)
    assert loan_payment(12_000, 0.0, 48) == 250


def test_loan_balance_zero_at_maturity_and_consistent():
    p, apr, n = 25_000, 0.07, 72
    assert loan_balance(p, apr, n, n) == 0
    # balance after k payments = PV of the remaining payments
    pmt, r, k = loan_payment(p, apr, n), apr / 12, 24
    pv_remaining = pmt * (1 - (1 + r) ** -(n - k)) / r
    assert loan_balance(p, apr, n, k) == pytest.approx(pv_remaining, rel=1e-10)


def test_lease_payment_formula():
    # cap cost 30,000, residual 15,000, 6% APR (money factor 0.0025), 36 months
    assert lease_payment(30_000, 15_000, 0.06, 36) == pytest.approx(15_000 / 36 + 45_000 * 0.0025)


def test_cash_purchase_by_hand():
    """Independent hand calculation of the cash scenario (the 'Excel check' done on paper)."""
    s = summarize(CAR, A, "cash")
    fuel = sum(15_000 / 100 * 7.0 * 1.50 * 1.02 ** g for g in range(5))
    ins = sum(2_000 * 1.04 ** g for g in range(5))
    maint = sum(1_000 * 1.08 ** g for g in range(5))
    expected = 30_000 * 1.13 + fuel + ins + maint + 1_000 - 30_000 * 0.43
    assert s["total"] == pytest.approx(expected, abs=0.01)


def test_finance_costs_more_than_cash_when_rate_exceeds_discount_rate():
    s_cash, s_fin = summarize(CAR, A, "cash"), summarize(CAR, A, "finance")
    assert s_fin["total"] > s_cash["total"]
    # with a 0% loan, financing is cheaper than cash in NPV terms
    zero = Assumptions(policy_rate=0, loan_spread=0, gas_cpl=150, km_per_year=15_000)
    assert summarize(CAR, zero, "finance")["npv"] < summarize(CAR, zero, "cash")["npv"]


def test_finance_interest_equals_payments_minus_principal():
    f = tco(CAR, A, "finance")
    principal = 30_000 * 1.13 - A.down_payment
    pmt = loan_payment(principal, A.loan_apr, 60)
    assert f.acquisition.sum() == pytest.approx(A.down_payment + 60 * pmt)
    assert 60 * pmt - principal > 0


def test_long_loan_paid_off_from_sale():
    a = Assumptions(policy_rate=2.5, gas_cpl=150, loan_term_months=84)
    f = tco(CAR, a, "finance")
    principal = 30_000 * 1.13 - a.down_payment
    assert f.loc[5, "resale"] == pytest.approx(-30_000 * 0.43 + loan_balance(principal, a.loan_apr, 84, 60))


def test_lease_has_no_resale_and_charges_excess_km():
    high_km = Assumptions(policy_rate=2.5, gas_cpl=150, km_per_year=25_000)
    f = tco(CAR, high_km, "lease")
    assert f.resale.sum() == 0
    assert f.loc[5, "other"] == pytest.approx(5_000 * 5 * 0.10 * 1.13)


def test_ev_uses_electricity_and_charger():
    f = tco(EV, A, "cash")
    assert f.loc[1, "energy"] == pytest.approx(15_000 / 100 * 18 * 0.17)
    assert f.loc[0, "other"] == 1_000 + 1_500


def test_gas_price_raises_ice_but_not_ev_cost():
    hi = Assumptions(policy_rate=2.5, gas_cpl=250, km_per_year=15_000)
    assert summarize(CAR, hi, "cash")["total"] > summarize(CAR, A, "cash")["total"]
    assert summarize(EV, hi, "cash")["total"] == summarize(EV, A, "cash")["total"]


def test_compare_shape():
    df = compare([CAR, EV], A)
    assert len(df) == 6 and set(df.method) == {"cash", "finance", "lease"}
    assert np.isfinite(df.total).all()


@needs_data
@pytest.mark.skipif(not shutil.which("soffice"), reason="LibreOffice needed to recalculate Excel")
def test_python_matches_excel_workbook(tmp_path):
    from drivecost.excel_model import build, recalculated_values
    from drivecost.tco import default_assumptions, memo_vehicles

    a = default_assumptions()
    vehicles = memo_vehicles()
    xl = recalculated_values(build(vehicles, a, tmp_path / "tco_model.xlsx"))
    for v in vehicles:
        for m in ("cash", "finance", "lease"):
            s = summarize(v, a, m)
            assert xl[v.name][m] == pytest.approx(s["total"], abs=0.01), (v.name, m)
            assert xl[v.name][f"{m}_npv"] == pytest.approx(s["npv"], abs=0.01), (v.name, m)
