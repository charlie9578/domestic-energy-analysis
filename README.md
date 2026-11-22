# Domestic Energy Analysis

**Public-data-first, reproducible research into domestic heating, gas, electricity, heat pumps, half-hourly smart meters and energy prices.**

The initial scope is **Great Britain**, with official statistics for **England and Wales** clearly distinguished from GB tariffs and other UK datasets. The repository started empty; this is a standalone Python 3.11+ foundation with no runtime dependencies. A small, attributed **real historical Low Carbon London electricity sample** is bundled as a research fixture; the large raw datasets are not copied.

> Research snapshot: **21 November 2026**. Default prices are the **Ofgem 1 October–31 December 2026 GB Direct Debit regional averages**, held constant for illustrative comparisons. They are **not** an annual forecast, a supplier quote or a guarantee for an individual postcode. The modelled scenario/weather/price example time series are **synthetic**, while the separately attributed Low Carbon London electricity extract is **measured**.

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

## Demand forecasting and bill decisions

The [demand and tariff analysis](https://charlie9578.github.io/domestic-energy-analysis/tariffs.html#demand-decisions) compares chronological half-hourly demand forecasts on five public homes. It then reprices the same observed load and separately tests shifting an observed EV charging circuit subject to energy, timing and peak constraints. [Methods and reproduction](research/DEMAND_DECISIONS.md)

## Hourly heat-balance validation

A measured heat input and indoor/outdoor temperatures drive a single-zone energy balance. We fit its parameters on earlier hours and compare later predictions against a persistence baseline at one and six hours. The result supports a narrow check of model behaviour under recorded heating. The project treats equipment sizing and changed thermostat schedules as separate questions. [Methods, results and data preparation](research/HOURLY_HEAT_BALANCE.md)

## HTML research explorer

Visit the [research explorer on GitHub Pages](https://charlie9578.github.io/domestic-energy-analysis/). To preview changes locally, open [index.html](index.html) or serve the frontend from the repository root.

```bash
python -m http.server 8000
```

Visit http://localhost:8000. Datasets, the meter explorer, heating, tariffs and upgrades have dedicated pages. The tariff comparison uses observed London interval totals, and the upgrade selector uses the published synthetic scenario table.

In the [meter explorer](https://charlie9578.github.io/domestic-energy-analysis/meter-explorer.html), load a gas or electricity interval CSV, or both, and optionally an hourly ERA5 CSV for the same area and dates. Uploads stay in the tab. Use `start_utc,consumption_kwh,duration_minutes` for meter readings and `start_utc,temperature_c` for weather. Gas values must already be in kWh. The explorer keeps native interval durations and uses UTC for charts and complete-day checks. The details table shows the first day of the selected window.

Optional unvalidated pattern rules flag sustained cold-weather gas use, elevated cold-day electricity relative to mild days, short gas/electrical bursts, EV-like plateaus and unusually low or high daily use. Short bursts can be consistent with cooking or hot water, including showers. Several devices can produce similar signatures. The low-use rule compares at least three complete days against a median from at least 14 eligible days. Missing or publisher-interpolated values are excluded from the rules, and the synthetic demo illustrates the checks without supplying field accuracy estimates.

Run the browser-analysis unit tests with `node --test tests/meter_analysis.test.mjs` (Node 24).

## Monitored indoor temperature example

Open the [meter explorer](https://charlie9578.github.io/domestic-energy-analysis/meter-explorer.html) and choose **Load real monitored profile**. Edit the day and night target temperatures and the hours when they start to compare targets against the measured indoor means by clock hour.

Fetch the original hourly inputs and prepare CSVs for the explorer:

```bash
python -m scripts.fetch_monitored_home
```

This downloads public HeatpumpMonitor system 3 data for 8–21 January 2024 and a matching Manchester-area hourly ERA5 series. It writes `indoor.csv`, `heating.csv`, `heatpump-electricity.csv` and `weather-era5.csv` under `data/derived/monitored-home`. Use the corresponding upload fields in the explorer. Select **Electricity file is a heat-pump submeter** when loading its electrical channel. This keeps the readings visible and excludes them from whole-home and appliance heuristics. `site-hourly.csv` also includes the site's outdoor sensor and domestic hot-water signal. [HeatpumpMonitor public time-series API](https://heatpumpmonitor.org/api-helper)

The site publishes 24 clock-hour averages, each based on 14 observations. Mean indoor temperature ranged from **18.62°C at 06:00** to **19.04°C at 21:00**. Outdoor temperature uses hourly ERA5 at Manchester city centre as a regional proxy. Activation comes from the monitored central-heating mode signal. Its hourly mean estimates the fraction of the hour in that mode. Values just above one in the source are capped at one, and null readings are left blank. An hourly fraction cannot identify exact switching times or compressor state.

When users provide an activation log, the explorer displays it alongside indoor temperature and defers to it for fully covered heating intervals. User-supplied clock-hour profiles use duration-weighted averages grouped by the local hour at interval start. They show indoor sampling hours and omit flagged values and intervals longer than one hour. The proposed schedule is a reference for comparing observed temperatures. It does not estimate future temperature, bills or energy savings under a changed setpoint.

## Hourly historical weather

Fetch gridded ERA5 reanalysis for an inclusive UTC date range through Open-Meteo.

```bash
python -m domestic_energy fetch-weather --lat 51.5 --lon -0.12 \
  --start 2025-01-01 --end 2025-01-07 --hourly --out data/raw/london_era5.csv
```

Each `start_utc` row contains 2 m air temperature (`temperature_c`) and 10 m wind speed (`wind_speed_m_s`) at the timestamp, plus precipitation accumulated in the hour starting at that timestamp (`precipitation_mm`) and mean global horizontal irradiance over the same hour (`shortwave_w_m2`). The adapter shifts the provider’s preceding-hour precipitation and irradiance forward into start-labelled intervals. This corrects the irradiance alignment in older hourly exports, so regenerate those CSVs before comparing them. Use at most 32 UTC dates per request. The adapter retrieves an extra day to close the last interval, so choose an end date with the following day available. [Open-Meteo historical weather API](https://open-meteo.com/en/docs/historical-weather-api)

ERA5 represents a grid cell. Compare against on-site or station measurements where accuracy near a particular home matters. Horizontal irradiance can drive a solar model after accounting for roof geometry and shading. Existing validation results still use their documented weather sources.

## Held-out validation

The measured-data study pairs heating energy with indoor and outdoor temperatures at five HeatpumpMonitor sites, tests heat signatures on a later year, and matches five Konstanz-area households and the London smart-meter fixture to hourly ERA5. It also compares tariff and thermostat scenarios and screens retrofit economics under explicit assumptions. See [methods and findings](research/OBSERVED_VALIDATION.md) and [aggregate results](research/OBSERVED_VALIDATION.json).

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

`data/` and `reports/` are ignored by Git; leave full raw third-party data in their own location, respect each licence and avoid exposing non-public smart-meter consumption or identifiers. The small public study extract is explicitly attributed and contains only the publisher's existing pseudonymous household identifier. No credentials are needed for the currently implemented public API adapters.

## Reproducibility and limitations

The project separates **(1) official published figures**, **(2) genuine source API data downloaded when you explicitly request it**, **(3) synthetic tests and examples**, and **(4) modelled counterfactuals**. The repository does not pretend that a scenario is an observed trial or that selected volunteer heat pumps represent all installations. There is no live API download performed by CI. All calculations use kWh for energy, kW for power, and pence for price.

Under MIT licence for the code only; linked external data retain their own licences, attribution requirements and privacy conditions. Research and models are informational, not regulated energy, engineering or financial advice.

## New: measured electricity + realistic thermostat scenarios (2026-11-21)

A **real, historical Low Carbon London single-household half-hourly extract** (2020 unique recorded intervals, 546.956 kWh observed, with missing gaps) is under [`examples/real_lcl_mac000002_2012_part.csv`](examples/real_lcl_mac000002_2012_part.csv). This is real aggregate electricity, not a synthetic heat-pump/home-temperature dataset. Import additional archive blocks with `import-lcl` (streaming CSV, gzip or ZIP); validate coverage using `measured-profile` and `measured-profile --expectations` (time-ordered holdout calendar baseline) and generate cautious hypotheses via `detect`. Only genuine observed kWh may be described as observed. For this small sample, annualisation, room temperature and heating appliance labels are **not** identifiable.

`domestic_energy/heating_controls.py` adds a single-zone heat-balance model for **constant 20°C, 17°C overnight setback, 06:00–09:00/17:00–22:00 timed heating, declared WFH/away days, illustrative overnight preheat**, and gas boiler / air heat pump / resistive electric / 00:00–07:00 chargeable night-storage heating. It simulates heat leakage, thermal capacity, maximum heat output, store charge/discharge and standing comfort penalties; **cheap but cold** scenarios are excluded from recommended cheapest feasible strategies. Example tariffs are HYPOTHETICAL, and neither properties nor thermostat setpoints are inferred from the real meter extract.

Run `PYTHONPATH=. python scripts/run_heating_study.py --out reports/heating_study` to reproduce **120 synthetic winter scenarios** (4 archetypes × 2 tariffs × 15 heat/control configurations). With weather downloaded from Open-Meteo, run `python -m domestic_energy heating-study --weather data/raw/weather.csv --tariffs examples/hypothetical_heating_tariffs.json --house-json examples/example_house.json --out reports/real_weather_study.json`. The weather may be real, but the house thermodynamics remain **assumed** until calibrated.

**Read [`research/REAL_DATA_HEATING.md`](research/REAL_DATA_HEATING.md) for exact data provenance, gaps, interpretation, commands, modelling limitations and what further evidence would be needed to assess an individual building.**


## Real-world data hub: public examples + repeatable local downloads

The repository now contains **three small, attributed, real-world electricity extracts from distinct study families**:

* [Low Carbon London](examples/real_lcl_mac000002_2012_part.csv) — historical 30-minute measured electricity, one anonymised household, with missing periods.
* [UCI household power](examples/real/uci_2006_power_30min.csv) — 33 complete half-hour samples converted from minute-average power readings; one French home, a partial two-day extract.
* [OPSD residential4 provisional mirror](examples/real/opsd_residential4_counters_15min.csv) — 479 quarter-hour samples with labelled heat-pump/EV/PV channels, derived by differencing an unverified cumulative-counter reproduction. **Recheck against the original publisher for authoritative analysis.**

**Run locally (Python 3.11+, no runtime dependencies):**

```bash
python -m domestic_energy.dataset_hub list
python scripts/run_public_data.py --dataset opsd-hourly --fetch --household residential4
python scripts/run_public_data.py --dataset uci --fetch
python scripts/run_public_data.py --dataset opsd-quarterhour --fetch --household residential4 --allow-large --max-mb 80
python scripts/run_public_data.py --dataset refit-house1 --fetch --allow-large --max-mb 650
python -m domestic_energy meter --csv data/public/processed/opsd-hourly_residential4.csv
```

These download from allow-listed publisher URLs, leave large raw and converted data in **gitignored `data/public/`**, record checksums, refuse to overwrite outputs and preserve missing-period gaps. REFIT / UK-DALE are power recordings (W), UCI minute-average power is kW, OPSD published channels are interval kWh, and the OPSD **third-party sample mirror** is a counter series — the conversions deliberately differ. ZIPs can be read without extracting the full archive.

**Details and exact source terms:** [Public datasets, example provenance, full local workflow and limitations](research/PUBLIC_DATASETS.md). Historical data priced on today's tariffs must be labelled counterfactual. The dataset downloads have not been live-tested in CI.

## Prior art: academic evidence and open-source comparisons

The [related-work review](research/RELATED_WORK.md) compares real measured-household studies, NILM/disaggregation, heat-loss measurement, heat-pump thermal controls and energy-management tools (EMHASS, Predbat, Heat Pump Cost Optimizer, NILMTK and NILMbench). It distinguishes field evidence from software demonstrations, documents known failure modes, and identifies what *this* research still needs to validate.

- [30-source machine-readable prior-art catalogue](research/PRIOR_ART_CATALOG.csv) — publications, dataset access, design, granularity, gaps and links.
- [Six replication/benchmark protocols](research/PRIOR_ART_REPLICATION_PLAN.md) — SMETER reference HTC, cross-household NILM and resolution ablations, thermostat comfort, honest tariff dispatch, weather forecasting, PV and retrofit validation.
- The most important next validation is **measured reference heat loss**, using [SMETER 30-dwelling research measurements](https://reshare.ukdataservice.ac.uk/856978/), followed by detection error at *half-hourly resolution* using independently labelled appliance circuits.

These are **research plans**, not claims that all external benchmarks have been reproduced. Do not merge raw private traces or imply occupancy from low-load periods without separate verified labels and appropriate consent.
