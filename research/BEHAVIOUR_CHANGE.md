# Household behaviour and technology changes over time

**Status (22 Nov 2026):** weather-adjusted event analysis and an interactive **hypothetical** scenario explorer. This feature is **not a causal estimator**, independently validated adoption detector, thermostat setpoint reader or tariff quote. Code: [`domestic_energy/behaviour_change.py`](../domestic_energy/behaviour_change.py), [browser explorer](../behaviour.html). Future work should use consented event logs, matched controls and real equipment telemetry.

## Why a simple before/after bill comparison is misleading

A household is not stationary. Outdoor temperature, seasons, daylight hours, working-from-home patterns, holidays, occupants, tariffs, appliance efficiency, electrification and behaviours change over time. The question is not just `energy_after - energy_before`. It is:

> How much energy was measured after a declared event, versus the energy we would have expected *under the earlier behaviour*, at the same later weather/calendar circumstances and meter boundary?

Let measured post-event daily kWh be `y(t)` and the prediction from a **pre-event-only** model be `ŷ₀(t)`. Descriptive residual deviation is `Σ_post (y(t) − ŷ₀(t))`; a negative value indicates less measured energy than the old model expected. **This is not an experimentally identified treatment effect.** Without a control group, counterfactual structural changes remain unobserved, and pre-event model error may drift. Post-event samples never tune the pre-event baseline.

We distinguish:

1. **Observed:** metered import/export, confirmed setpoint/charger/PV measurement, actual rates and data completeness.
2. **Descriptive:** weather-normalised difference against an old regime, with held-out forecast error, diagnostic warnings and 30-day evolution.
3. **Screened candidate:** unexplained persistent load change identified statistically; neither event type nor occupant activity is known.
4. **Modelled scenario:** user-specified thermostat setting, EV miles/charging or PV yield. Not an observed intervention and not validated savings.
5. **Causal claim:** requires a stronger study design, with e.g. staggered adoption or control households, balanced before/after weather, measured intervention compliance and explicit confounder adjustments.

## Three motivating examples

### Thermostat 25°C → 22°C

**Directly measurable** if you have thermostat setpoint logs, actual indoor/outdoor temperatures and heating energy (gas input or heat-pump electricity with boundary). Meter data alone **cannot reveal a thermostat setpoint**. The user's 3°C change can decrease heat flow when outside is colder, but response differs with building heat transfer, internal/solar gains, overnight schedules, recovery time, TRVs, boiler efficiency, weather compensation and COP. A change to a gas meter may reflect simultaneous DHW/cooking changes.

For a **steady-state illustrative example**: 200 W/K home, 5°C outdoors for 14 identical heating hours, 85% boiler efficiency. A 3°C reduction corresponds to `0.2 kW/K × 3 K × 14 h = 8.4 kWh/day useful heat`, or `9.88 kWh/day gas input`, before gains or warm-up. At an illustrative 8p/kWh variable rate, that is about **£0.79 per such day**, **not** an empirically achieved saving or a 365-day annual projection. The [interactive browser scenario](../behaviour.html) uses this transparent calculation. For actual dynamic temperature/comfort and heat-pump recovery, use [heating control simulator](../domestic_energy/heating_controls.py), not this one-line sensitivity.

### Purchasing an EV

A newly installed EV may cause sustained import plateaux and more off-peak use. But immersion heaters, storage heaters, heat pumps and equipment can look similar at half-hour resolution. A charger submeter and a vehicle's charging sessions/availability/departure deadline are necessary for *verified* EV attribution. Gross imported kWh also depends on PV/battery self-supply and smart tariffs. The page asks weekly mileage, kWh/mile, charger efficiency, share charged at home, and assumed day/night proportions. A measured EV adoption study needs vehicle/charger log, not just an import change.

### Installing solar PV

A solar installation can reduce grid imports even if lights, cooking, EV charging and heating demand remain unchanged. With correct boundaries, `gross household load = grid import − grid export + PV generation − battery losses/flows` **only after defining metering architecture and all storage flows**; do not apply that expression blindly to net metering or double-count self-consumption. Confirm PV via generation or inverter telemetry; export may arise from other technologies. The browser model estimates `min(PV production × assumed self-use fraction, annual household demand)` as avoided imports, with remaining PV exported. This ignores hourly coincidence, shading, storage, inverter clipping and changing consumption; use measured/export interval data or engineering PV simulations for real advice.

## Data contract

Recommended daily CSV fields:
```csv
date,consumption_kwh,temperature_c,coverage_fraction,work_from_home,away,ev_submeter_kwh,pv_generation_kwh,pv_self_used_kwh,heatpump_electric_kwh,setpoint_c
2024-01-01,22.31,7.2,1,true,false,0,0,0,0,25
```

- `date` = **local civil day** for the dwelling; history and outdoor temperature must already be aligned to the same local date. Missing days must be omitted, **not filled with zero**. Optional flags are used in the model only when available for all pre-event rows. If active before the event they must also be provided later, or analysis stops.
- `consumption_kwh` = nonnegative energy for **one explicitly selected meter boundary**, e.g. `gas_input`, `electricity_import`, `electricity_export`, `gross_electricity`, `delivered_heat`. Never conflate these.
- `temperature_c` = same-day outdoor temperature at dwelling or documented weather grid. Coverage fraction must reflect the proportion of physically present meter intervals (including 23/25-hour DST days). The model ignores dates below 95% coverage by default.
- `work_from_home`, `away` = **user-provided explicit labels** only. Do not silently treat missing as 'home'.
- `ev_submeter_kwh`, `pv_generation_kwh`, `pv_self_used_kwh`, `heatpump_electric_kwh` = optional **separately measured** channels, not inferred from aggregate meter traces. Their post totals are summarised separately when complete.
- `setpoint_c` = only from thermostat/log or known survey; never estimate from smart meter consumption and pretend it was measured.

An event log is a JSON list, e.g.:
```json
[
  {"date":"2024-06-01","event_type":"thermostat","documented":true,"meter_boundary":"gas_input"},
  {"date":"2024-11-01","event_type":"heat_pump","documented":true,"meter_boundary":"gas_input"}
]
```
The same gas meter may cease to exist after a heat-pump installation! **Do not analyse fuel-switching solely on one channel**: instead combine space-heat delivered, gas input, electric heat-pump consumption, residual gas and heating-system removal appropriately. A missing gas account is not evidence of zero historic household heat.

## Command line: run locally

Only Python 3.11+ standard library. Commands:
```bash
# Use real, complete, weather-joined daily data:
python -m domestic_energy.behaviour_change evaluate \
  --csv data/derived/house_gas_daily.csv \
  --event-date 2024-03-01 --event-type thermostat \
  --meter-boundary gas_input --documented --washout-days 7 \
  --price-p-per-kwh 8

# Screening for unverified changes, NEVER equipment diagnosis:
python -m domestic_energy.behaviour_change scan \
  --csv data/derived/house_electric_daily.csv --meter-boundary electricity_import

# Multiple separately logged events; refuses simultaneous individual attribution:
python -m domestic_energy.behaviour_change timeline \
  --csv data/derived/house_electric_daily.csv \
  --events data/private/events.json --meter-boundary electricity_import

# Convert interval kWh and contemporaneous hourly weather to complete local days:
python -m domestic_energy.behaviour_change aggregate \
  --meter data/derived/meter.csv \
  --weather data/derived/hourly_weather.csv \
  --timezone Europe/London \
  --output data/derived/meter_weather_daily.csv

# Illustrative thermostat arithmetic, NOT observed savings:
python -m domestic_energy.behaviour_change setpoint \
  --old-c 25 --new-c 22 --outside-c 5 \
  --heat-loss-w-per-k 200 --hours-per-day 14 \
  --fuel gas --efficiency-or-cop .85 --price-p-per-kwh 8

# Generate labelled synthetic control scenarios for testing only:
python -m scripts.run_behaviour_study --out reports/behaviour_changes
python -m unittest discover -s tests -v
```

The raw interval CSV uses `start_utc,consumption_kwh,duration_minutes` with explicit timezone-aware timestamps, 15/30/60-minute intervals. Weather uses `start_utc,temperature_c` (hourly start). Both are joined UTC then aggregated to `Europe/London` local days, correctly respecting 23- and 25-hour DST days. The basic converter drops meter intervals with no hourly weather reading within the last 60 min and excludes insufficiently covered days. It assumes each interval fits inside one local day; split longer intervals crossing midnight before input.

## Statistical details and caveats

- Ridge regression uses pre-event outdoor HDD, CDD, weekend and annual harmonic terms, plus *provided* consistent WFH/away flags.
- Select HDD balance point on an **inner pre-event chronological validation**; evaluate error on a separate later pre-event holdout. Then refit before calculating post counterfactual. No post-treatment leakage.
- 42 pre-event and 14 post-event complete days required; this is an engineering guardrail, **not evidence that such a short period is sufficient**. Whole-year weather cycles are preferable. Coverage is checked per local civil day.
- Report naive change, forecast-adjusted kWh, pre-event holdout error/bias/WAPE, temperature outside pre-event range, omitted days, named competing events, and 30-day post-event differences. Week-block resampling of earlier forecast residuals gives a **sensitivity band, not a causal 90% confidence interval**; it omits post-event model drift, intervention timing confounding, correlated changes and structural breaks.
- When multiple interventions occur sequentially, fit a distinct pre-only baseline within each prior regime and truncate post before next regime. This reduces mixing but **cannot uniquely attribute** events that co-occur or overlap (e.g. EV + heat pump + solar installation).
- A **scan** contrasts short rolling residual means against a fixed prehistory baseline; it generates candidates *without labelling their causes*. Change point dates chosen on the same data do not have naive inferential p-values.
- No direct appliance identification, occupancy inference or diagnosis of poor insulation from a single unlabelled series.

### Next scientific improvements

1. Link verified event calendars (change date, verified setpoints, meter equipment, EV charge sessions, installation dates) to consented home data, including indoor weather and heat demand.
2. Implement a **controlled interrupted time-series / difference-in-differences** framework using independent, matched untreated dwellings and pretrend diagnostics; compare with IPMVP whole-building energy measurement and verification protocol (Option C). Document parallel trends and event-study leads/lags.
3. Train **multiple regimes with time-varying parameters**: weather response and weekday patterns may drift smoothly over years rather than jump at one date. Evaluate continual online updating *without forgetting the old baseline*; use chronological rolling origins and concept drift tests.
4. Model tariff change and equipment adoption jointly; compare demand shifting vs genuine kWh reduction and use interval-specific import/export prices, not a fixed assumed p/kWh.
5. For solar, reconcile PV, battery, import, export and gross-house energy at interval resolution with self-consumption, round-trip losses and provenance.
6. For thermostat, add heat-input/indoor-temperature/flow-temperature measurements, thermal RC dynamics and a labelled setpoint change; test held-out indoor trajectories and comfort.
7. Publish independent predictions/uncertainty and false positives against real longitudinal changes; do not claim calibration from generated examples.

## Related work

- [SMETER building thermal efficiency methods](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-technologies-project-technical-evaluation)
- [IPMVP energy savings measurement and verification framework](https://evo-world.org/en/products-services-mainmenu-en/protocols/ipmvp)
- [IDEAL measured UK household energy and indoor sensors](https://www.nature.com/articles/s41597-021-00921-y)
- [Low Carbon London half-hourly trial](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d)
- [OPSD 15-minute EV, heat pump, solar labelled meters](https://data.open-power-system-data.org/household_data/2020-04-15/)
- [Open-Meteo historical weather archive](https://open-meteo.com/en/docs/historical-weather-api)
- [NILMTK labelled appliance monitoring and evaluation](https://github.com/nilmtk/nilmtk)

Keep sensitive homeowner event logs, holidays, device IDs and private meter usage **locally**, never in public Git.
