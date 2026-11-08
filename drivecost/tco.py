"""Five-year total cost of ownership (TCO) for buying cash, financing or leasing a car in Ontario.

Conventions (mirrored exactly by excel/tco_model.xlsx so the two can be checked against each other):
* annual periods t = 1..N; anything paid on delivery is at t = 0;
* HST (13%) is charged on the full price when buying, but only on payments when leasing;
* loan and lease payments are monthly; the 12 payments of a year are summed into that year;
* fuel, insurance and maintenance in year t grow from their year-1 value at their own rates;
* the car is sold privately at the end of year N for price x retention[N-1] (no HST);
* `total` is the nominal sum of outflows minus resale; `npv` discounts each year's net
  cash flow at the discount rate (your savings rate: the return the cash could have earned).
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

import pandas as pd

HST = 0.13


@dataclass(frozen=True)
class Vehicle:
    name: str
    powertrain: str               # "ICE", "HEV" or "BEV"
    price: float                  # pre-tax price incl. freight and PDI, CAD
    l_per_100km: float = 0.0      # NRCan combined rating (gas cars)
    kwh_per_100km: float = 0.0    # NRCan combined rating (EVs; includes charging losses)
    retention: tuple[float, ...] = (0.80, 0.68, 0.58, 0.50, 0.43)  # resale value / price after each year
    insurance: float = 2900.0     # year-1 premium, CAD
    maintenance: float = 800.0    # year-1 maintenance and repairs, CAD
    charger: float = 0.0          # home Level-2 charger, installed, CAD (t = 0)
    rebate: float = 0.0           # purchase incentive, CAD (reduces price before tax)


@dataclass(frozen=True)
class Assumptions:
    years: int = 5
    km_per_year: float = 16_000
    policy_rate: float = 2.50     # Bank of Canada overnight rate, %
    loan_spread: float = 4.49     # lender spread over the policy rate, %-points
    lease_spread: float = 3.49    # lease rates are often subsidised below loan rates
    down_payment: float = 3_000.0
    loan_term_months: int = 60
    lease_term_months: int = 60
    lease_acquisition_fee: float = 695.0
    lease_km_allowance: float = 20_000
    lease_excess_per_km: float = 0.10
    gas_cpl: float = 160.0        # year-1 regular gasoline price, cents/L incl. taxes
    gas_growth: float = 0.02
    elec_per_kwh: float = 0.17    # blended home (ULO overnight) and public charging, $/kWh incl. HST
    elec_growth: float = 0.02
    insurance_growth: float = 0.04
    maintenance_growth: float = 0.08
    winter_tires: float = 1_000.0
    discount_rate: float = 0.035

    @property
    def loan_apr(self) -> float:
        return (self.policy_rate + self.loan_spread) / 100

    @property
    def lease_apr(self) -> float:
        return (self.policy_rate + self.lease_spread) / 100


def loan_payment(principal: float, apr: float, months: int) -> float:
    """Level monthly payment on an amortising loan (Excel PMT)."""
    if months <= 0:
        return 0.0
    r = apr / 12
    if r == 0:
        return principal / months
    return principal * r / (1 - (1 + r) ** -months)


def lease_payment(cap_cost: float, residual: float, apr: float, months: int) -> float:
    """Pre-tax monthly lease payment: depreciation fee + finance fee (money factor = APR/24)."""
    money_factor = apr / 24
    return (cap_cost - residual) / months + (cap_cost + residual) * money_factor


def _years_paid(term_months: int, year: int) -> int:
    """Number of monthly payments falling in year `year` (1-based)."""
    return int(max(0, min(12, term_months - 12 * (year - 1))))


def operating_costs(v: Vehicle, a: Assumptions) -> pd.DataFrame:
    """Energy, insurance and maintenance by year (index 0..N, year 0 = delivery)."""
    yrs = range(a.years + 1)
    rows = []
    for t in yrs:
        if t == 0:
            rows.append({"energy": 0.0, "insurance": 0.0, "maintenance": 0.0,
                         "other": a.winter_tires + v.charger})
            continue
        g = t - 1
        if v.powertrain == "BEV":
            energy = a.km_per_year / 100 * v.kwh_per_100km * a.elec_per_kwh * (1 + a.elec_growth) ** g
        else:
            energy = a.km_per_year / 100 * v.l_per_100km * a.gas_cpl / 100 * (1 + a.gas_growth) ** g
        rows.append({"energy": energy,
                     "insurance": v.insurance * (1 + a.insurance_growth) ** g,
                     "maintenance": v.maintenance * (1 + a.maintenance_growth) ** g,
                     "other": 0.0})
    return pd.DataFrame(rows, index=pd.Index(yrs, name="year"))


def tco(v: Vehicle, a: Assumptions, method: str) -> pd.DataFrame:
    """Annual cash flows for one vehicle and one acquisition method ('cash', 'finance', 'lease')."""
    n = a.years
    price = v.price - v.rebate
    flows = operating_costs(v, a)
    flows["acquisition"] = 0.0
    flows["resale"] = 0.0
    resale_value = price * v.retention[n - 1]

    if method == "cash":
        flows.loc[0, "acquisition"] = price * (1 + HST)
        flows.loc[n, "resale"] = -resale_value
    elif method == "finance":
        principal = price * (1 + HST) - a.down_payment
        pmt = loan_payment(principal, a.loan_apr, a.loan_term_months)
        flows.loc[0, "acquisition"] = a.down_payment
        for t in range(1, n + 1):
            flows.loc[t, "acquisition"] = pmt * _years_paid(a.loan_term_months, t)
        # a loan longer than the horizon is paid off from the sale proceeds
        flows.loc[n, "resale"] = -resale_value + loan_balance(principal, a.loan_apr, a.loan_term_months, 12 * n)
    elif method == "lease":
        term = a.lease_term_months
        lease_res = price * v.retention[term // 12 - 1]
        cap_cost = price + a.lease_acquisition_fee - a.down_payment / (1 + HST)
        pmt = lease_payment(cap_cost, lease_res, a.lease_apr, term) * (1 + HST)
        flows.loc[0, "acquisition"] = a.down_payment
        for t in range(1, n + 1):
            flows.loc[t, "acquisition"] = pmt * _years_paid(term, t)
        excess = max(0.0, (a.km_per_year - a.lease_km_allowance) * term / 12) * a.lease_excess_per_km * (1 + HST)
        flows.loc[term // 12, "other"] += excess
    else:
        raise ValueError(f"unknown method {method!r}")

    flows["net"] = flows[["acquisition", "energy", "insurance", "maintenance", "other", "resale"]].sum(axis=1)
    flows["discount_factor"] = [(1 + a.discount_rate) ** -t for t in flows.index]
    return flows


def loan_balance(principal: float, apr: float, months: int, paid: int) -> float:
    """Outstanding loan balance after `paid` monthly payments."""
    if paid >= months:
        return 0.0
    r = apr / 12
    pmt = loan_payment(principal, apr, months)
    if r == 0:
        return principal - pmt * paid
    return principal * (1 + r) ** paid - pmt * ((1 + r) ** paid - 1) / r


def summarize(v: Vehicle, a: Assumptions, method: str) -> dict:
    f = tco(v, a, method)
    total = f.net.sum()
    return {
        "vehicle": v.name, "powertrain": v.powertrain, "method": method,
        "acquisition": f.acquisition.sum(), "resale": f.resale.sum(),
        "energy": f.energy.sum(), "insurance": f.insurance.sum(),
        "maintenance": f.maintenance.sum(), "other": f.other.sum(),
        "total": total, "npv": (f.net * f.discount_factor).sum(),
        "per_km": total / (a.km_per_year * a.years),
        "per_month": total / (12 * a.years),
    }


def compare(vehicles: list[Vehicle], a: Assumptions,
            methods: tuple[str, ...] = ("cash", "finance", "lease")) -> pd.DataFrame:
    return pd.DataFrame([summarize(v, a, m) for v in vehicles for m in methods])


def sensitivity(v: Vehicle, a: Assumptions, method: str, changes: dict[str, tuple]) -> pd.DataFrame:
    """One-at-a-time sensitivity: {'gas_cpl': (130, 220), ...} -> low/high totals vs base."""
    base = summarize(v, a, method)["total"]
    rows = []
    for name, (lo, hi) in changes.items():
        if hasattr(a, name):
            lo_t = summarize(v, replace(a, **{name: lo}), method)["total"]
            hi_t = summarize(v, replace(a, **{name: hi}), method)["total"]
        else:
            lo_t = summarize(replace(v, **{name: lo}), a, method)["total"]
            hi_t = summarize(replace(v, **{name: hi}), a, method)["total"]
        rows.append({"input": name, "low": lo, "high": hi, "total_low": lo_t,
                     "total_high": hi_t, "base": base, "swing": abs(hi_t - lo_t)})
    return pd.DataFrame(rows).sort_values("swing", ascending=False)


def from_nrcan(make: str, model: str, model_year: int, price: float, **kwargs) -> Vehicle:
    """Build a Vehicle from the NRCan ratings file (any car sold in Canada since MY2015)."""
    from drivecost.data import nrcan

    d = nrcan()
    hit = d[(d.make.str.lower() == make.lower()) & (d.model.str.lower() == model.lower())
            & (d.model_year == model_year)]
    if hit.empty:
        raise KeyError(f"{model_year} {make} {model} not in NRCan ratings")
    row = hit.sort_values("comb_l100").iloc[0]
    pt = row.powertrain
    defaults = dict(name=f"{model_year} {make} {model}", powertrain=pt, price=price)
    if pt == "BEV":
        defaults["kwh_per_100km"] = float(row.comb_kwh100)
    else:
        defaults["l_per_100km"] = float(row.comb_l100)
    defaults.update(kwargs)
    return Vehicle(**defaults)


# ---- The three cars compared in the memo -------------------------------------------------
# Prices are estimated Canadian MSRP incl. freight/PDI for a well-equipped base trim (Nov 2026),
# to be checked against dealer quotes. Insurance figures are estimates for a 22-year-old with a
# full G licence in London, Ontario; get real quotes before deciding.
def memo_vehicles(field_overrides: dict | None = None) -> list[Vehicle]:
    o = field_overrides or {}
    gas = from_nrcan("Toyota", "Corolla (1-mode)", 2026, 26_500, name="Toyota Corolla LE (gas)",
                     insurance=2_900, maintenance=800, **o.get("gas", {}))
    hev = from_nrcan("Toyota", "Corolla Hybrid", 2026, 29_900, name="Toyota Corolla Hybrid",
                     retention=(0.83, 0.72, 0.63, 0.56, 0.49), insurance=3_000, maintenance=750,
                     **o.get("hev", {}))
    bev = from_nrcan("Hyundai", "Kona Electric", 2026, 45_000, name="Hyundai Kona Electric",
                     retention=(0.70, 0.58, 0.49, 0.42, 0.36), insurance=3_400, maintenance=450,
                     charger=1_800, **o.get("bev", {}))
    return [gas, hev, bev]


def default_assumptions(**overrides) -> Assumptions:
    """Assumptions tied to the latest data: BoC policy rate and trailing-12-month Toronto pump price."""
    from drivecost.data import gas_prices, latest_policy_rate

    base = dict(policy_rate=latest_policy_rate(),
                gas_cpl=round(float(gas_prices("toronto", "regular").iloc[-12:].mean()), 1))
    base.update(overrides)
    return Assumptions(**base)


if __name__ == "__main__":
    from drivecost.data import TABLES

    a = default_assumptions()
    print(a)
    res = compare(memo_vehicles(), a)
    res.to_csv(TABLES / "tco_comparison.csv", index=False, float_format="%.2f")
    pd.set_option("display.width", 200)
    print(res.round(0).to_string(index=False))
