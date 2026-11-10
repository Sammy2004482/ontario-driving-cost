# The real cost of driving in Ontario

What does a car really cost a new graduate in London, Ontario over five years, and how exposed is that cost to fuel prices, interest rates and inflation?

This repository combines **economics** (how crude oil prices pass through to the pump, and gasoline's share of CPI inflation), **personal finance** (buy cash vs finance vs lease, gas vs hybrid vs EV) and **risk** (fuel price Monte Carlo, value-at-risk, futures hedging and margin calls, a credit stress test and insurance pricing). Everything runs on free public data.

**The memo:** [`memo/memo.pdf`](memo/memo.pdf), *"Buy, lease or finance: a new grad's first car in London, Ontario"* (2 pages, 4 charts).

## Headline results (data to Sept/Oct 2026)

| Question | Answer |
|---|---|
| Cheapest car over 5 years (16,000 km/yr) | **Corolla Hybrid**: $46.9k net if bought with cash. Gas Corolla is $1.0k more (in today's dollars), Kona Electric $14.7k more |
| Finance or lease? | About the same in today's dollars ($48.8k vs $48.2k). Financing leaves you owning a car worth about $14.7k. Each +1 pt on the loan rate costs about $790 |
| When would the EV win? | Only if its price fell to about $27k (from $45k), gas averaged 574 ¢/L, or you drove 90,000 km a year |
| Biggest running cost | **Insurance** ($16k over 5 years), more than fuel ($6k for the hybrid) |
| Crude → pump pass-through | 1.44 ¢/L per ¢/L of crude (wholesale gasoline: 0.98 of the full 1.13 incl. HST). 87% happens in the same month |
| Rockets and feathers? | Not in the direct response. It shows up in margins: fat margins erode with a half-life of about 11 months, squeezed margins recover in about 1 month (p = 0.03) |
| Gasoline's share of CPI inflation | +1.0 pt in 2022, −0.8 pt in 2015, +0.5 pt so far in 2026 |
| Toronto pump price, Dec 2031 | Median 139 ¢/L, 90% range 100–191 ¢/L (mean-reverting). The random-walk stress case puts the 95th percentile at 470 ¢/L |
| Fuel-bill VaR (95%, 5 years) | Gas Corolla $1,478; hybrid $1,036; ES $1,934 / $1,357 |
| Fleet hedge (50 vans) | h* = 0.90, about 2.5 RBOB contracts a year. Removes 89% of variance out of sample; worst 12-month overrun $95k → $35k |
| Margin calls | 2022 spike and collapse: up to $118k tied up for a 3-contract hedge |
| Trucking credit stress | +30% fuel, no surcharge: debt/EBITDA 3.0x → 5.8x. Covenant breached at only a +9% fuel rise |
| Insurance pricing (freMTPL2) | Test Gini 0.29. Main factors: vehicle age, driving record (bonus-malus), driver age. A 22-year-old new driver costs 2.6x an experienced one |

## Repository layout

```
data/                 download scripts -> data/processed/*.csv, data_dictionary.md, pull_log.json
drivecost/
  data.py             loaders, Ontario fuel-tax table, monthly analysis panel
  tco.py              5-year cost of ownership: cash / finance / lease, any NRCan car
  excel_model.py      writes excel/tco_model.xlsx (live formulas) and checks it against tco.py
  passthrough.py      crude -> pump distributed-lag, asymmetric and error-correction models
  inflation.py        gasoline's contribution to CPI inflation since 2015
  risk.py             fuel price Monte Carlo, percentiles, VaR and expected shortfall
  hedge.py            minimum-variance futures hedge, out-of-sample backtest, margin calls
  credit_stress.py    trucking company coverage and leverage under fuel and rate shocks
  pricing.py          Poisson frequency and Gamma severity GLMs on freMTPL2
  decision.py         memo analysis: TCO chart, tornado, break-evens, rate stress
notebooks/03_passthrough_inflation.ipynb   executed notebook for the econometrics
excel/tco_model.xlsx  the TCO model as an Excel workbook, for interviews
memo/                 memo template, build script, memo.pdf
reports/figures, reports/tables   every chart and result table
app.py                Streamlit page
tests/                pytest suite (23 tests)
```

## How to run

```bash
pip install -r requirements.txt
```

```bash
python run_all.py --fetch
```

```bash
python -m pytest -q
```

```bash
streamlit run app.py
```

`run_all.py` without `--fetch` rebuilds everything from the CSVs already in `data/processed`. The memo needs `pandoc` and a Chromium browser (set `$CHROME` if it isn't found). The Excel check in the tests needs LibreOffice. The insurance models need about 5 GB of RAM.

## Data

| Source | Used for |
|---|---|
| Statistics Canada 18-10-0001-01 | Monthly pump prices (Toronto regular, self-serve) |
| Statistics Canada 18-10-0004-01, 18-10-0007-01 | CPI and basket weights |
| Bank of Canada Valet API | Policy rate, CAD/USD |
| US EIA spot prices | WTI crude, NY Harbor gasoline (monthly and daily), converted to CAD/L |
| NRCan Fuel Consumption Ratings | L/100 km and kWh/100 km for every model sold in Canada since 2015 |
| freMTPL2 (OpenML 41214/41215) | Insurance pricing models |

Details, units and caveats are in [`data/data_dictionary.md`](data/data_dictionary.md). Re-running the downloads gives byte-identical files, and pull dates go to `pull_log.json`.

## Methods in brief

* **Cost of ownership.** Annual cash flows over 5 years: HST on the full price when buying, but only on payments when leasing. Monthly loan and lease payments are amortised, resale value comes from a retention curve, and fuel, insurance and maintenance grow at their own rates. Results are reported both as a nominal total and as an NPV at your savings rate. The loan rate is the latest Bank of Canada policy rate plus a spread. The Excel workbook is generated from the same inputs, and a test recalculates it in LibreOffice and checks all 18 figures against Python to the cent.
* **Pass-through.** Monthly first differences in ¢/L, with tax changes (carbon charge, Ontario tax cut, cap-and-trade) controlled for. Newey-West standard errors. Rises and falls are split for the asymmetry tests, and an Engle-Granger error-correction model has separate adjustment speeds above and below the long-run level.
* **Inflation.** Gasoline's basket weight at link-month prices, updated for relative price change since the link month, times gasoline's y/y price change.
* **Fuel risk.** The pump price is split into a market part and fixed per-litre taxes plus HST. The market part follows an AR(1) in log real terms with 6-month block-bootstrapped residuals (base case), or a block-bootstrapped random walk (stress case). An ADF test can't tell the two apart (p = 0.51), so both are reported.
* **Hedging.** h* = Cov(ΔS, ΔF)/Var(ΔF) on monthly changes. The out-of-sample backtest uses rolling 12-month strips from 2022 on, with h* estimated on 2015–21 only. The daily margin account models initial and maintenance margin, calls and payouts of excess.
* **Credit stress.** EBITDA/interest, EBIT/interest and debt/EBITDA across fuel shocks, surcharge recovery, rate shocks and hedge cover. Bisection finds the fuel rise that breaks a covenant.
* **Insurance pricing.** Poisson GLM with a log-exposure offset, and a Gamma GLM on claims capped at the 99.5th percentile plus a large-loss load. Factor importance comes from likelihood-ratio deviance drops and relativity spreads. Validated on a 20% holdout (deviance explained and Gini).

## Limitations

* London has no StatCan price series; Toronto is used instead (London usually runs a few ¢/L cheaper).
* EIA stopped publishing RBOB futures prices in 2024, so NY Harbor spot gasoline stands in for the futures price. Basis and roll risk are ignored, and exchange margins are assumptions.
* Pump prices are monthly averages. Weekly or daily station data would give much sharper rockets-and-feathers tests.
* Car prices, insurance premiums, resale curves and the 0.17 $/kWh electricity price are estimates; check them against real quotes. No EV rebate is assumed.
* freMTPL2 is French data from 2004–05. It shows how insurers price risk, not what Ontario premiums are. Its vehicle-age-0 policies have very short exposures and an artificially high claim rate.
* The trucking company is illustrative, not a real borrower.

## Which piece maps to which kind of role

| Module | Role it practises |
|---|---|
| `passthrough.py`, `inflation.py` | Economics consultancy (e.g. Arup), central bank / policy economist |
| `tco.py`, Excel model | Personal finance, retail banking, FP&A |
| `risk.py` | Market risk |
| `hedge.py` | Collateral and margin (e.g. TD), commodity commercial risk (e.g. Phillips 66) |
| `credit_stress.py` | Credit analyst |
| `pricing.py` | Insurance pricing (e.g. NFU Mutual graduate scheme) |
