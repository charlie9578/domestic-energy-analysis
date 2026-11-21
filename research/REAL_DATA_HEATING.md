# Measured London smart-meter data and thermostat strategy experiments

**Snapshot: 21 November 2026.** Code: `domestic_energy/real_meter.py`, `domestic_energy/heating_controls.py`, `scripts/run_heating_study.py`. Do not confuse three types of evidence:

1. **Measured:** UK Power Networks Low Carbon London electricity meter readings (2011–14), historical tariff traces when downloaded from the supplier, measured outdoor weather when fetched.
2. **Inferred:** estimated seasonal/weekday baseline or possible EV/heating/away signatures, subject to holdout error and false positives.
3. **Simulated:** building heat loss, thermal capacity, heater type, internal temperature, controller schedules, storage capacity, COP and alternative technology costs. The public electricity sample does **not** establish actual thermostat temperatures, gas or indoor comfort.

## Measured source and exact provenance

UK Power Networks / London Datastore **Low Carbon London** study recorded approximately 5,567 households at 30-minute intervals. Find the full research set at [London Datastore](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d). A small publicly hosted sample in [RTDIP Core](https://github.com/rtdip/core/blob/develop/tests/sdk/python/rtdip_sdk/data_models/meters/utils/test_data/smart_meters_london/CC_LCL-FullData.csv) contains meter `MAC000002` from **12 October–24 November 2012**, and is the provenance for `examples/real_lcl_mac000002_2012_part.csv`. The research fixture has **2,020 unique recorded half-hour intervals**, **546.956 kWh actually observed**, two exact duplicated timestamps and **three gaps** between successive records. Coverage is not complete, including a roughly one-day break. Source timestamps are interpreted as *UTC/GMT interval END* for this particular conversion; check original dataset conventions, especially before analyses spanning daylight-saving boundaries. Data remains attributed to original publishers; the repository's MIT code licence does **not** relicense third-party data.

The source is historical and short relative to annual/weather-normalised forecasting, and the sampling method is not an adequately representative contemporary population benchmark. No observed EV, holiday, heat-pump, solar, gas boiler, storage heating, or household presence labels accompany this extract.

### Reproduce on the real published fixture

```bash
python -m domestic_energy meter --csv examples/real_lcl_mac000002_2012_part.csv
python -m domestic_energy measured-profile --csv examples/real_lcl_mac000002_2012_part.csv
python -m domestic_energy measured-profile --csv examples/real_lcl_mac000002_2012_part.csv --expectations
python -m domestic_energy detect --electricity examples/real_lcl_mac000002_2012_part.csv
```

The `--expectations` option is a **time-ordered holdout, half-hour-by-weekday historical baseline** (with fallback for sparse weekdays). It only uses complete local days; excludes missing days and reports holdout mean absolute error. It is not weather-adjusted, and a six-week extract is insufficient to establish reliable year-ahead behavior or a seasonal building HLC. It is an instructive ingestion/QA and model-validation case. For weather-dependent forecasts use `prepare-daily`, `forecast`, and a longer matched weather/meter history.

### Import the full archive without reading it into memory

```bash
python -m domestic_energy import-lcl \
  --input data/raw/lcl/Power-Networks-LCL-June2015.csv \
  --household MAC000002 --timestamp-mode utc_end \
  --out data/derived/mac000002.csv --qa reports/mac000002_import_qa.json
```

Also supports `.csv.gz`, `.zip`, multiple `--input` blocks. Always inspect the selected dataset's actual timestamp semantics. In particular **do not assume that all local timestamps refer to UTC on summer dates**; the importer insists on a caller-specified raw UTC/GMT convention and refuses a silently guessed local-time conversion.

## Thermostat strategy model

Use a **single-zone, first-order RC thermal model** with temperature-dependent fabric loss, constant assumed internal gains, configurable thermal capacity and an idealized heating controller. The simulation evaluates a single building under exactly the same temperature/weather sequence, tariff and declared occupancy assumptions, changing one of:

- `constant`: 20°C throughout;
- `setback`: 20°C in the day, 17°C from 22:00 to 06:00;
- `timed`: 20°C 06:00–09:00 and 17:00–22:00; 14°C otherwise;
- `wfh_aware`: timed schedule, except *declared* working-from-home days hold 20°C during the day;
- `preheat`: a simple fixed 00:00–06:00 off-peak warm-up (21? see code: 20.8°C during 01:00–06:00 and 19.5°C otherwise), **not** price-aware model predictive control;
- `storage_constant`, `storage_setback`, `storage_timed`: electric resistive store can charge only during a configured cheap overnight window, discharge later subject to rate and storage constraints. Optional peak-time resistive backup supplies unmet demand if sized. Storage loss can be partly recovered as heat in the home; charging is not confused with instantaneous space heat.

Compatible heating sources are gas boiler, air-source heat pump (illustrative outdoor-temperature-dependent COP), direct resistive heater, electric thermal store. House parameters are *assumptions*, **not inferred from meter data**, unless separately calibrated. E.g., `heat_loss_w_per_k=200` means a 20 K inside-outside difference leaks 4 kW, plus dynamics. Changing thermal capacity changes how much a preheat or night setback shifts energy. `heat_loss_w_per_k`, `thermal_capacity_kwh_per_k`, heater power and COP must be sensitivity-tested.

**Comfort and safety:** a cheap storage schedule which leaves the store empty or the home below the nominated occupied threshold is flagged as **infeasible** and not ranked as optimal. The simple index counts occupied degree-hours below the threshold; it is not a clinical thermal comfort, damp, legionella, frost protection or heating design assessment. Report `occupied_unmet_degree_hours_c`, `occupied_hours_below_threshold`, `lowest_indoor_c`, backup electric use, peak electrical load and final store charge. Do not claim that a blanket night setback is always best: high thermal mass, poorly sized emitters, cold weather, heat-pump cycling, defrost and daytime tariff rates change the ranking.

### Reproduce thermostat strategies

```bash
# Generate deterministic **synthetic weather** and 120 comparisons, no network calls
PYTHONPATH=. python scripts/run_heating_study.py --out reports/heating_study

# With **real** outdoor temperatures (needs network)
python -m domestic_energy fetch-weather \
  --lat 51.5074 --lon -0.1278 --start 2025-01-01 --end 2025-01-31 \
  --hourly --out data/raw/london_weather_jan2025.csv
python -m domestic_energy heating-study \
  --weather data/raw/london_weather_jan2025.csv \
  --tariffs examples/hypothetical_heating_tariffs.json \
  --house-json examples/example_house.json --wfh-days 2025-01-07,2025-01-09 \
  --away-days 2025-01-13,2025-01-14 --out reports/heating_jan2025.json

# Inspect indoor temperature step-by-step to understand any comfort penalties
python -m domestic_energy heating-trace --weather data/raw/london_weather_jan2025.csv \
  --tariff examples/hypothetical_heating_tariffs.json --source heatpump \
  --strategy setback --out reports/heating_trace.json
```

Note: `heating-trace --tariff` accepts **one tariff JSON object**, not the example JSON list; save one object to a local file first. Or call `simulate_heating` directly in Python. (Future interface enhancement: choose a tariff from the list by name.)

`heating-study` does not automatically add historical whole-home electricity to its heat-pump scenario, because existing whole-home electric meter load may **already include heating**. It accepts `--baseload-csv` only if the operator explicitly asserts `--confirm-nonheating-baseload` and provides a contiguous UTC time-aligned non-space-heating interval series. Historical LCL readings are suitable for baseline-only calculations **only if separate evidence shows no electric space heating**. Do not claim that from the meter pattern itself.

### Reproducible sensitivity demonstration

`PYTHONPATH=. python scripts/run_heating_study.py` evaluates four **hypothetical houses** (well insulated light/heavy, medium, leaky), two **illustrative** tariffs (27p flat, 9p overnight/35p daytime) and 15 heating/control combinations each: **120 simulations**, with comfort screening, a weather formula and explicit WFH/away dates. It does not observe 120 buildings. Reports are placed under `reports/heating_study` (ignored by git). It excludes standing charges, installation cost, boiler servicing, electricity supply/network export constraints, PV self-consumption and hot water. The cheapest *heating-only variable-bill* model run is not necessarily the cheapest lifetime retrofit.

## Further evidence and model improvements

Prioritise: (1) longer multi-season smart-meter + matched weather time series with gap/DST QA; (2) separately monitored indoor temperatures, thermostat setpoints, heating power and occupancy schedules for calibration; (3) measured multi-day step tests for heat-loss coefficient and thermal mass; (4) heat-pump COP as a function of outside temperature and flow temperature, defrost, domestic hot water and backup resistance; (5) full comfort-constrained optimisation using forecasts of demand and prices with rolling horizon—not perfect foresight; (6) controlled comparisons of real Economy 7/Agile tariffs including region-specific standing charges; (7) calibrated house archetype and fabric intervention uncertainties; (8) datasets with known EV/solar/heat equipment labels for precision/recall of disaggregation; (9) appliance signatures subject to **false positive testing**, not definitive household behavior surveillance.
