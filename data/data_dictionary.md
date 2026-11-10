# Data dictionary

All files are in `data/processed/` and are produced by `python -m data.fetch_all` (add `--refresh` to re-download the raw files cached in `data/raw/`). The files are sorted and written with a fixed number format, so re-running the scripts on the same source data gives byte-identical files. The pull date, source URL, row count and SHA-256 of every file are recorded in **`pull_log.json`**, not in the data files themselves.

Coverage starts in **January 2014**, one year before the 2015 analysis window, so that lags and year-over-year changes exist from January 2015. Months are `YYYY-MM` and dates are `YYYY-MM-DD`.

| File | Script | Source | Grain |
|---|---|---|---|
| `gas_prices_monthly.csv` | `fetch_statcan` | StatCan table 18-10-0001-01 | month × city × fuel |
| `cpi_monthly.csv` | `fetch_statcan` | StatCan table 18-10-0004-01 | month × geography |
| `cpi_basket_weights.csv` | `fetch_statcan` | StatCan table 18-10-0007-01 | CPI basket |
| `boc_monthly.csv` | `fetch_boc` | Bank of Canada Valet API | month |
| `boc_fx_daily.csv` | `fetch_boc` | Bank of Canada Valet API | business day |
| `eia_monthly.csv` | `fetch_eia` | US EIA petroleum spot prices (hist_xls) | month |
| `eia_daily.csv` | `fetch_eia` | US EIA petroleum spot prices (hist_xls) | US trading day |
| `nrcan_fuel_ratings.csv` | `fetch_nrcan` | NRCan Fuel Consumption Ratings, open.canada.ca | vehicle model × variant |
| `fremtpl2_freq.csv.gz` | `fetch_fremtpl` | OpenML dataset 41214 | insurance policy |
| `fremtpl2_sev.csv.gz` | `fetch_fremtpl` | OpenML dataset 41215 | insurance claim |

## gas_prices_monthly.csv
Monthly average retail pump prices, **including all taxes**.

| Column | Type | Description |
|---|---|---|
| month | str | `YYYY-MM` |
| geo | str | `toronto`, `ottawa` (Ontario part), `thunder_bay`, `canada` |
| fuel | str | `regular`, `premium` (unleaded gasoline) or `diesel`, all at **self-service** stations |
| cents_per_litre | float | Average price, cents per litre |

The table has **no London, Ontario series**. Toronto is the closest large market (about 190 km away) and is used as the London proxy throughout.

## cpi_monthly.csv
Consumer Price Index, not seasonally adjusted, 2002 = 100.

| Column | Type | Description |
|---|---|---|
| month | str | `YYYY-MM` |
| geo | str | `canada` or `ontario` |
| all_items | float | All-items CPI |
| gasoline | float | Gasoline CPI |
| energy | float | Energy CPI (gasoline, fuel oil, electricity, natural gas, ...) |
| all_items_ex_energy | float | All-items excluding energy |

## cpi_basket_weights.csv
Canada, gasoline's weight in the CPI basket at **basket link-month prices** (distribution to selected geographies).

| Column | Type | Description |
|---|---|---|
| basket_year | int | Expenditure reference year of the basket (e.g. 2024) |
| gasoline_weight_pct | float | Gasoline's share of the basket, % |
| all_items_weight_pct | float | Always 100, kept as a check |
| link_month | str | Month the basket was linked into the index. Hard-coded from StatCan's basket-update notes: December of year+1 for baskets up to 2017, May of year+1 from the 2020 basket on |

## boc_monthly.csv
| Column | Type | Description |
|---|---|---|
| month | str | `YYYY-MM` (the latest month is partial) |
| policy_rate_pct | float | Target for the overnight rate (series V39079), monthly average of daily values, % |
| policy_rate_eom_pct | float | Same rate, last value of the month, % |
| usdcad | float | Canadian dollars per US dollar, monthly average of daily rates |

FX: series `FXUSDCAD` from 2017-01-03 onward. Before that it uses the legacy noon rate `IEXE0101`, which was discontinued in April 2017.

## boc_fx_daily.csv
| Column | Type | Description |
|---|---|---|
| date | str | `YYYY-MM-DD` |
| usdcad | float | CAD per USD (same series splice as above) |

## eia_monthly.csv / eia_daily.csv
| Column | Type | Description |
|---|---|---|
| month / date | str | Period |
| wti_usd_bbl | float | WTI crude spot, Cushing OK (EIA series RWTC), USD per barrel |
| gasoline_nyh_usd_gal | float | New York Harbor conventional regular gasoline spot (EER_EPMRU_PF4_Y35NY_DPG), USD per US gallon |
| usdcad | float | Bank of Canada CAD per USD for the same period. The daily file carries the last value forward on Canadian holidays |
| wti_cad_l | float | WTI in CAD per litre = USD/bbl × usdcad ÷ 158.987 |
| gasoline_nyh_cad_l | float | Gasoline in CAD per litre = USD/gal × usdcad ÷ 3.78541 |

EIA stopped publishing NYMEX RBOB futures prices in April 2024. NY Harbor spot gasoline, the RBOB delivery point, stands in as the wholesale gasoline price and as the hedge instrument's price.

## nrcan_fuel_ratings.csv
One row per model-year / make / model / transmission variant. Model years 2015–2026.

| Column | Type | Description |
|---|---|---|
| model_year | int | |
| make, model | str | As published by NRCan |
| vehicle_class | str | e.g. `Compact`, `Sport utility vehicle: Small` |
| powertrain | str | `ICE`, `HEV` (model name contains "hybrid") or `BEV` |
| fuel | str | `regular`, `premium`, `diesel`, `e85`, `natural_gas`, `electricity` |
| transmission | str | NRCan code (A = automatic, AM = automated manual, AS = select shift, AV = CVT, M = manual; number = gears) |
| city_l100, hwy_l100, comb_l100 | float | Fuel consumption, L/100 km (litres-equivalent for BEVs) |
| comb_kwh100 | float | BEV only: combined kWh/100 km, including charging losses |
| range_km | float | BEV only: rated range |
| co2_g_km | float | Tailpipe CO2, g/km (0 for BEVs) |

Plug-in hybrids are not included.

## fremtpl2_freq.csv.gz
French motor third-party liability portfolio, 678,013 policies, mostly one year each.

| Column | Description |
|---|---|
| IDpol | Policy id |
| ClaimNb | Number of claims in the exposure period |
| Exposure | Years of exposure (0–1, a few above 1, which are capped in modelling) |
| Area | Density class of the city, A (rural) to F (urban centre) |
| VehPower | Vehicle power band (4–15) |
| VehAge | Vehicle age, years |
| DrivAge | Driver age, years |
| BonusMalus | French bonus-malus coefficient: 50 = best record, new drivers start at 100, above 100 = past claims |
| VehBrand | Anonymised brand code (B1 ... B14) |
| VehGas | `Regular` or `Diesel` |
| Density | Inhabitants per km² where the driver lives |
| Region | French region code (R11 ...) |

## fremtpl2_sev.csv.gz
| Column | Description |
|---|---|
| IDpol | Policy id (joins to the frequency file) |
| ClaimAmount | Claim cost, EUR. One row per claim |

## Derived series (built in code, not saved)
`drivecost/data.py` builds the monthly analysis panel. Its tax table holds the federal excise tax (10 ¢/L), the Ontario gasoline tax (14.7 ¢/L, cut to 9.0 ¢/L from July 2022), the federal fuel charge (April 2019 – March 2025) and Ontario cap-and-trade (about 4.3 ¢/L, Jan 2017 – Jul 2018). Subtracting these and HST from the pump price gives `pump_ex_tax_cpl`, the market part of the price that the risk and hedging models simulate.
