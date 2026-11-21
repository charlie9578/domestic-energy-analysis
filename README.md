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

## New: measured electricity + realistic thermostat scenarios (2026-11-21)

A **real, historical Low Carbon London single-household half-hourly extract** (2020 unique recorded intervals, 546.956 kWh observed, with missing gaps) is under [`examples/real_lcl_mac000002_2012_part.csv`](examples/real_lcl_mac000002_2012_part.csv). This is real aggregate electricity, not a synthetic heat-pump/home-temperature dataset. Import additional archive blocks with `import-lcl` (streaming CSV, gzip or ZIP); validate coverage using `measured-profile` and `measured-profile --expectations` (time-ordered holdout calendar baseline) and generate cautious hypotheses via `detect`. Only genuine observed kWh may be described as observed. For this small sample, annualisation, room temperature and heating appliance labels are **not** identifiable.

`domestic_energy/heating_controls.py` adds a single-zone heat-balance model for **constant 20°C, 17°C overnight setback, 06:00–09:00/17:00–22:00 timed heating, declared WFH/away days, illustrative overnight preheat**, and gas boiler / air heat pump / resistive electric / 00:00–07:00 chargeable night-storage heating. It simulates heat leakage, thermal capacity, maximum heat output, store charge/discharge and standing comfort penalties; **cheap but cold** scenarios are excluded from recommended cheapest feasible strategies. Example tariffs are HYPOTHETICAL, and neither properties nor thermostat setpoints are inferred from the real meter extract.

Run `PYTHONPATH=. python scripts/run_heating_study.py --out reports/heating_study` to reproduce **120 synthetic winter scenarios** (4 archetypes × 2 tariffs × 15 heat/control configurations). With weather downloaded from Open-Meteo, run `python -m domestic_energy heating-study --weather data/raw/weather.csv --tariffs examples/hypothetical_heating_tariffs.json --house-json examples/example_house.json --out reports/real_weather_study.json`. The weather may be real, but the house thermodynamics remain **assumed** until calibrated.

**Read [`research/REAL_DATA_HEATING.md`](research/REAL_DATA_HEATING.md) for exact data provenance, gaps, interpretation, commands, modelling limitations and what further evidence would be needed to assess an individual building.**
