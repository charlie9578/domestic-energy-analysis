# Domestic Energy Analysis

**Public-data-first, reproducible research into domestic heating, gas, electricity, heat pumps, half-hourly smart meters and energy prices.**

The initial scope is **Great Britain**, with official statistics for **England and Wales** clearly distinguished from GB tariffs and other UK datasets. The repository started empty; this is a standalone Python 3.11+ foundation with no runtime dependencies. Data from third parties are **not copied into the repository**.

> Research snapshot: **21 November 2026**. Default prices are the **Ofgem 1 October–31 December 2026 GB Direct Debit regional averages**, held constant for illustrative comparisons. They are **not** an annual forecast, a supplier quote or a guarantee for an individual postcode. The example time series are **entirely synthetic**.

## What works today

| Analysis | What it does | Critical caveat |
| --- | --- | --- |
| Official consumption benchmark | Stores published DESNZ NEED 2026 release statistics for 2024 | Meter-matched samples differ for gas and electricity |
| Boiler-to-heat-pump scenario | Equal useful heat, gas share, actual SPF, standing charges, installation sensitivity and break-even COP | Must input real heating fraction, efficiency and tariffs for a property |
| Gas meter conversion | Metric and imperial volume to kWh, with bill calorific value | Use actual CV; not a flat 11.2 kWh per cubic metre |
| Smart-meter analysis | Interval kWh, coverage, peak kW, p95 and local-hour profile | A missing interval is not a zero reading |
| Tariff replay | Exact UTC joins to half-hourly unit rates, and daily standing charges | Prices must cover every recorded interval |
| Public Octopus rate adapter | Download historical unit-rate spans for a known product/region | Public endpoint; no private usage or account access |
| HeatpumpMonitor adapter | Download public *daily* energy/temperature and compute quality-filtered observed SPF and temperature bins | Volunteer participants are not a representative UK sample |
| Sensitivity grid | Recompute saving by SPF and unit price | Synthetic scenarios, not observed savings |

Read [the research report](research/REPORT.md), [methodology and caveats](research/METHODOLOGY.md), and [the public data catalogue](research/SOURCES.md) before quoting results.

## Quick start

```bash
# No pip install required if running from repo root
python -m unittest discover -s tests -v
python -m domestic_energy benchmark
python -m domestic_energy scenario
python -m domestic_energy demo --out-dir reports/demo

# Optional editable install / console command
python -m pip install -e .
domestic-energy --help
```

A worked scenario (10,000 kWh gas, of which 85% used for heating; 85% seasonal boiler efficiency; SPF 3; 2,500 kWh pre-existing electricity; gas still connected) gives **£43.58/year variable-cost saving**, or **2.81 break-even SPF**, *under those specific Q4 2026 rates*. See [research/REPORT.md](research/REPORT.md) for the accounting and sensitivities.

## Run your own analyses

**Gas volume:**

```bash
python -m domestic_energy gas-convert 100 --unit m3 --calorific-mj 39.5
python -m domestic_energy scenario --gas-kwh 13000 --heating-fraction 0.9 \
  --boiler-efficiency 0.87 --spf 3.4 --electricity-p 20 \
  --gas-p 7.97 --gas-standing-p 29.68 --electricity-standing-p 54.83 \
  --capex 8000 --out reports/my_scenario.json
```

**Your own or publicly sourced interval CSV** (never commit a household's private readings):

```csv
start_utc,consumption_kwh,duration_minutes
2026-11-01T00:00:00+00:00,0.24,30
2026-11-01T00:30:00+00:00,0.19,30
```

```bash
python -m domestic_energy meter --csv examples/synthetic_smart_meter.csv
python -m domestic_energy meter --csv examples/synthetic_smart_meter.csv \
  --rates examples/synthetic_tou_rates.csv --standing-p 54.83
```

Tariff CSV requires `start_utc,unit_rate_p_per_kwh` and exactly one price for every measurement start time. Negative rates are allowed. Billing dates use `Europe/London` by default to deal with daylight-saving clock changes; the timestamps themselves **must have an explicit UTC offset**.

**Real, public heat-pump data (network required):**

```bash
python -m domestic_energy fetch-heatpumps --ids 1,2 --out-dir data/raw/heatpumps
python -m domestic_energy heatpump --csv data/raw/heatpumps/system_1_daily.csv
```

To choose system IDs, browse [HeatpumpMonitor's public systems](https://heatpumpmonitor.org/system/list/public.json). The tool downloads observed daily data and outputs an aggregate JSON for each ID. It filters days below 95% electricity/heat quality or below 23 hours' measured coverage; this is **not automatically seasonal performance over a full year**.

**Real public tariff prices (network required):**

```bash
# Replace PRODUCT and REGIONAL_TARIFF with actual published Octopus API codes.
python -m domestic_energy fetch-rates \
  --product PRODUCT --tariff REGIONAL_TARIFF \
  --start 2026-11-01T00:00:00Z --end 2026-11-02T00:00:00Z \
  --out data/raw/tariff_2026-11-01.csv
```

Explore [public Octopus products](https://api.octopus.energy/v1/products/) and check the selected product's *regional tariff code*, VAT treatment and valid-from/to periods. The adapter refuses to invent rates for gaps. **Octopus smart-meter consumption endpoints require customer authentication and are intentionally not accessed here.**

## Directory guide

```text
domestic_energy/     dependency-free CLI, analytics, safe public API adapters
examples/            tiny SYNTHETIC CSVs for time series and tariff tests
research/            literature/source registry, methods, results, next research
scripts/             (reserved for future reproducible studies)
tests/               unit/regression tests including DST and data gaps
.github/workflows/   offline CI tests; no network calls or secrets
```

`data/` and `reports/` are ignored by Git; leave raw third-party data in their own location, respect each licence, and avoid exposing smart-meter consumption or identifiers. No credentials are needed for the currently implemented public API adapters.

## Reproducibility and limitations

The project separates **(1) official published figures**, **(2) genuine source API data downloaded when you explicitly request it**, **(3) synthetic tests and examples**, and **(4) modelled counterfactuals**. The repository does not pretend that a scenario is an observed trial or that selected volunteer heat pumps represent all installations. There is no live API download performed by CI. All calculations use kWh for energy, kW for power, and pence for price.

Under MIT licence for the code only; linked external data retain their own licences, attribution requirements and privacy conditions. Research and models are informational, not regulated energy, engineering or financial advice.

## Expanded analysis: weather, occupancy, buildings, tariffs and technologies

> **Version 0.2 / 21 Nov 2026.** All newly introduced study data are **SYNTHETIC** and generate no HTTP requests. The first study evaluates **88 complete illustrative household-years** (four building-heat-loss setups × two tariff structures × eleven portfolios). See [Scenario study](research/SCENARIO_STUDY.md), [Advanced models](research/ADVANCED_MODELS.md), and [Source status](research/SOURCES.md).

New commands build **expected domestic energy consumption by calendar and weather**, identify cautious patterns, and compare complete building/energy-system combinations:

| Feature | Input | Output | What it does NOT assert |
| --- | --- | --- | --- |
| Local weather retrieval | Coordinates, dates, [Open-Meteo ERA5](https://open-meteo.com/en/docs/historical-weather-api) | Historical daily or hourly weather CSV | A historical series is not a future forecast; station/microclimate may differ |
| Local-day join | Half-hourly UTC meter + local-day weather + declared occupancy | Validated daily consumption table | Missing periods are zero demand; a missing activity flag means home |
| Daily expected energy | 42+ daily paired readings, temperature, optional WFH/away | Time-ordered holdout error, expected kWh and bounds | A guaranteed forecast or verified causal insulation effect |
| Indicative heat loss | Daily gas/weather, boiler efficiency and optional floor area | W/K, W/(K·m²) proxy | Certified EPC score, thermal-image diagnosis or actual U-values |
| Household pattern hypotheses | Half-hourly electric, optional gas, weather and export | Candidate EV plateaus, gas heating runs, low activity/away, daytime variation, weather sensitivity | Confirmed EV, resident absence, WFH, solar panel or heat-pump ownership |
| Portfolio × tariff | **Gross** household demand, submetered/heating allocations, PV generation, actual or hypothetical prices | Full-time-series import, export, standing, gas and £ costs | Forward tariff price forecast, genuine PV generation or warranty |
| Electrical battery | Above and battery kWh, kW, efficiency | Perfect-foresight state-of-charge charge/discharge optimised bill | Guaranteed achievable battery ROI |
| Thermal night-storage | Known useful space-heat demand and electrical conversion | Thermal-state heat shifting, heat loss and bill | Validated thermal comfort or emitter feasibility |
| EV charging | Known parking window, charger kW, tariff 30-minute prices | Cheapest charging slots vs charging on arrival | True EV ownership/availability inferred from meter |
| Capital economics | Modelled annual savings, assumed capex, upkeep, degradation, discount rate | NPV and simple payback | Real quote, grant eligibility or financing assessment |

### Run the full-year synthetic study

```bash
python scripts/run_study.py --out reports/synthetic_study
# 88 full-year cases, 2025 synthetic readings, 2026 price-cap scenario,
# known EV, declared holiday/WFH calendars and a 4 kWp synthetic PV profile
```

Its outputs include `SYNTHETIC_scenario_grid.csv`, `SYNTHETIC_truth.json`, `forecast_and_detection.json`, and mock daily/interval readings that can be used by the following commands. Generated files stay under Git-ignored `reports/`.

### Model a weather-corrected home from real/consented meter data

```bash
# Public historic weather; network required; coordinates are sent to Open-Meteo
python -m domestic_energy fetch-weather \
    --lat 51.5 --lon -0.12 --start 2025-01-01 --end 2025-12-31 \
    --out data/weather_london_2025.csv

# Use local-day date,temperature_c and optionally declared away/WFH flags.
# All meter timestamps must be offset-aware ISO timestamps, with energy in kWh.
python -m domestic_energy prepare-daily --meter my_OWN_meter.csv \
    --weather data/weather_london_2025.csv --occupancy my_OWN_calendar.csv \
    --out data/daily_for_model.csv --qa reports/quality.json

python -m domestic_energy forecast --csv data/daily_for_model.csv \
    --fuel gas --boiler-efficiency .85 --floor-area 110 \
    --out reports/weather_model.json

# To make future expected consumption, create a future weather + known-calendar CSV.
python -m domestic_energy forecast --csv data/daily_for_model.csv \
    --future-csv data/future_weather_assumptions.csv --out reports/future.json
```

Train the gas model **only on gas readings** and the electricity model **only on electricity readings**; do not confuse gas meter volume with gas energy units. For genuine building comparisons, add floor area/building type/EPC statistics from NEED with comparable climate/occupancy, then field-validate the inferred heat-loss coefficient. The fitted model is trained on 80% of days and tested on the later 20%; its error band is only indicative.

### Explore meter signatures and systems (no definitive identification)

```bash
# Run on synthetic generated example first
python -m domestic_energy detect \
    --electricity reports/synthetic_study/SYNTHETIC_mid_terrace_2025_intervals.csv \
    --out reports/detection.json

# Optional real, locally-held and consented gas/weather/export data
python -m domestic_energy detect --electricity my_OWN_meter.csv \
    --gas my_OWN_gas_intervals.csv --weather data/weather_london_2025.csv \
    --export my_OWN_export_intervals.csv --out reports/my_hypotheses.json
```

The engine explicitly **does not claim to determine** someone's holiday or WFH status, whether a house owns a car, or which exact electrical appliance is operating from a 30-minute aggregate meter. EV/immersion/storage-heater signatures overlap; solar and batteries can mask import. Use confirmed charger, inverter, thermostat and heating submetering to validate. **Do not commit private meter readings, household identifiers, coordinates, holiday calendars or activity inferences**. If publishing results, use aggregated consented statistics.

### Compare tariffs and energy systems

The advanced simulator requires **gross electricity use before behind-the-meter solar generation** (`consumption_kwh`), optional `pv_generation_kwh`, `gas_kwh`, `gas_heating_kwh`, `electric_heating_kwh`, and optional `temperature_c`, all aligned at `start_utc` as a separate `duration_minutes` interval. `gas_heating_kwh` is **GAS INPUT** attributable to space heating. `electric_heating_kwh` is known *resistive* heating electricity, not automatically estimated by looking at peaks. A smart meter's net **grid import from an existing PV home is NOT gross electrical demand**; reconstruct from properly metered PV/battery data before running PV comparisons or conclusions will be wrong.

```bash
python -m domestic_energy compare-tariffs \
    --csv reports/synthetic_study/SYNTHETIC_mid_terrace_2025_intervals.csv \
    --tariffs examples/hypothetical_tariffs.json \
    --out reports/tariff_ranking.json

python -m domestic_energy portfolio-grid \
    --csv reports/synthetic_study/SYNTHETIC_mid_terrace_2025_intervals.csv \
    --tariffs examples/hypothetical_tariffs.json \
    --scenarios examples/retrofit_portfolios.json \
    --out reports/portfolios.json

# For custom scenarios, see python -m domestic_energy compare-tariffs --help.
# EV off-peak time-shifting:
python -m domestic_energy ev-plan --rates examples/synthetic_tou_rates.csv \
    --arrival 2026-11-01T00:00:00Z --departure 2026-11-02T00:00:00Z \
    --battery-energy-kwh 7 --charger-kw 7
```

**What is actually the cheapest?** Only a supplied list of tariffs/assumptions can be ranked. Real buying comparisons require verified supplier product codes, regional prices, valid dates and standing charges, contract/exit fees, export eligibility, technology availability, financing and capital costs. Battery/thermal dispatch is computed with unrealistically perfect knowledge of future prices and loads; treat the optimized bill as an **optimistic** bound. Heat-pump conversion must electrify all residual gas loads before dropping the gas standing charge. None of these outputs is a personalized or official insulation/EPC assessment.

### Reproducibility and privacy rules

No model is trained on anyone's private data by default. All public APIs are called only by explicit `fetch-*` commands. Historic weather adapter uses the current Open-Meteo format and rejects missing days. Solar PVGIS version 6 changed field names in July 2026, so public hourly solar series must be separately converted and verified before use; **there is no automatic PVGIS downloader yet**. Core dependency is Python ≥3.11, without machine-learning packages or external keys. Regression checks now include DST local-day preparation, missing data, thermal/electrical storage energy conservation, and deliberately ambiguous appliance detection.
