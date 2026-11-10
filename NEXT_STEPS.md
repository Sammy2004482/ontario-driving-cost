# Status and resume notes (paused 2026-11-08)

## Done
- Phase 1, data: `python -m data.fetch_all` pulls all sources for 2014-01 onward. Re-running gives byte-identical files; pull dates are in data/processed/pull_log.json.
- Phase 2, TCO: drivecost/tco.py plus excel/tco_model.xlsx (live formulas). 12 tests pass, including Python vs Excel to the cent.
- Phase 3: drivecost/passthrough.py and drivecost/inflation.py, with charts in reports/figures.
- Phase 4: drivecost/risk.py. The base case is mean-reverting AR(1) with block-bootstrapped shocks; the random walk is the stress case. Fan chart covers 2027-2031.
- Phase 5: drivecost/hedge.py (hedge ratio, out-of-sample backtest, margin calls) and drivecost/credit_stress.py.
- Phase 6: drivecost/pricing.py runs on the full data (about 1.5 min, about 5 GB RAM). Results are in reports/tables/pricing_*. Two things still need fixing:
  - The test Gini of 0.008 is implausibly low, almost certainly a bug in `gini()` (check the ordering and normalisation). The Poisson deviance explained on the test set, 5.4%, is in line with the literature.
  - Vehicle age band "0" has a frequency relativity of about 4.6x. This is a known freMTPL2 artifact (very short-exposure new-car policies). The example premiums use VehAge 0, so they are inflated. Switch the examples to "1-4", and consider merging band 0 into 1-4.
  - Factor ranking (deviance): vehicle age, bonus-malus, driver age, power, region, area, brand, fuel. A 22-year-old new driver costs about 2.8x an experienced 45-year-old (to recheck after the band fix).

## To do
1. Fix the pricing Gini and the vehicle-age-0 band, then look at reports/figures/pricing_factors.png.
2. Tests for passthrough (recover known coefficients from simulated data), risk (VaR/ES on a known distribution), hedge (h* on synthetic data), credit_stress, inflation and pricing (small sample).
3. Notebooks: notebooks/03_passthrough.ipynb, executed with nbconvert ("coefficients and chart in a notebook").
4. data/data_dictionary.md
5. Memo (memo/memo.md, then pandoc to docx, then soffice to PDF; 2 pages, 4 charts): TCO bars, fan chart, pass-through, and a TCO sensitivity tornado.
6. README.md, requirements.txt, app.py (Streamlit), run_all.py

## Key findings so far
- TCO, 5 years, 16,000 km/yr: Corolla Hybrid cash $46.9k < Corolla gas cash $48.7k << Kona EV cash $61.1k. Finance and lease cost about $5-6k more nominal, about $2k more in NPV.
- Pass-through: crude to pump is about 1.44 c/L per 1 c/L, 87% of it in the first month. No direct rockets-and-feathers effect. In the error-correction model, fat margins take about 11 months to fall halfway back, while squeezed margins recover in about 1 month (p = 0.03).
- Gasoline added +1.0 pp to CPI inflation in 2022, took -0.8 pp off in 2015, and added +0.5 pp in 2026 YTD.
- Fuel risk, Corolla 5-year fuel bill: mean $7.7k, 95% VaR $1.5k (mean-reverting) vs $7.2k (random walk). An ADF test can't separate the two models (p = 0.51).
- Fleet hedge: h* = 0.90, about 2.5 RBOB contracts a year. Out-of-sample variance is cut by 89%. The worst 12-month budget miss falls from $95k to $35k.
- Credit: a +30% fuel rise with no surcharge takes debt/EBITDA from 3.0x to 5.8x. A covenant breach needs only a 9% fuel rise with 0% surcharge recovery, or 18% with 50% recovery.

## Environment notes
- No London, ON series in StatCan 18-10-0001; Toronto is used as the proxy.
- EIA RBOB futures series ended 2024-04; NY Harbor spot gasoline is used instead.
- pricing.py needs about 5 GB RAM on the full data.
