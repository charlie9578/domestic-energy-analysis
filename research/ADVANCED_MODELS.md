# Advanced models: expected energy, household patterns, technology, and cost

**Status: implemented and regression-tested 21 November 2026.** Treat this as an analysis framework, not a trained national predictor or validated NILM classifier. Outputs are only as credible as the local data supplied. Tests and the full-year scenario study use **SYNTHETIC** readings. A public repository must not contain real household meter traces or occupancy calendars.

## 1. The expected-usage question

The quantity of interest is `E[kWh | local date, weather, household circumstances, building, fuel, equipment]`, with two related but different predictions:

1. **Daily energy expectation** conditioned on local daily mean outdoor temperature, weekday/weekend, season phase, and *declared* work-from-home/away flags. The same fitted model may be driven by a different calendar and weather year for weather normalization. A distinct heat-loss coefficient may be estimated only with justified delivered-heat metering or gas-heating assumptions.
2. **Half-hourly expectation** allocates daily expected kWh over weekday/weekend local-hour patterns learned from the home's historical usage. The allocation operates over supplied UTC slots, including the 23- and 25-hour daylight-saving days. This is a planning profile; it is **not** a calibrated half-hourly probabilistic forecast.

The weather-response model has explanatory features:

`daily_kWh = intercept + β_HDD max(0, T_balance − T_out) + β_CDD max(0,T_out−22°C) + β_weekend + β_WFH + β_away + β_away_HDD + β_WFH_HDD + β_sin + β_cos`.

Parameters use standardized-feature ridge regression; the penalty downweights annual calendar harmonics relative to measured outdoor temperature to avoid arbitrarily attributing heating energy to the month instead of the weather. Heating balance temperature is selected from **12, 14, 15, 16, 18°C** by minimum MAE on a **time-ordered 20% holdout**, with the fit itself restricted to the earlier 80%. This is a simple first-stage benchmark: it is susceptible to time-varying household behavior and concept drift. The error band `± holdout_p90_absolute_error` is **indicative**, not a statistically valid 80/90% predictive interval. A weather forecast's own uncertainty is not included.

**Leakage warnings:** Never fit on a whole calendar year and report that year's training error as independent evidence; use blocked time-split evaluation. If solar or battery reduces net grid imports, the *import meter* is not gross household demand. If WFH/holiday flags are unavailable, an absent flag means unobserved, **not evidence the resident was home**. Weather at a nearby ERA5 grid point is not room temperature or thermostat setpoint. Heating demand is correlated with weather but also with ventilation, occupancy, solar gains, hot water and fabric.

## 2. Heat-loss and insulation inference

For daily **gas-meter kWh** with a justified boiler thermal efficiency `η` and credible isolation of space heating, the HDD gradient has an approximate heat loss:

`heat_loss_coefficient_W_per_K ≈ β_HDD * η * 1000 / 24`.

For **measured delivered useful heat**, do **not** multiply by boiler efficiency. Report `W/K` and `W/(K·m²)` when reliable floor area exists. This is a **heat-loss proxy**, not an EPC rating, material U-value or heat leak location. A 160 W/K property at a 20 K indoor–outdoor difference has an idealized ~3.2 kW heat loss before variable gains/air change; a 260 W/K property similarly has ~5.2 kW. This is an identity, not a claim that either value is typical of a UK building type. The synthetic scenario *assumes* such coefficients; the recovered value is not validation against field monitoring.

**Insulation before/after study:** collect full winter weather and meter data before/after measure, plus matching indoor setpoints/hot-water/occupancy records. Compare weather-normalized heating slopes and delivery-adjusted kWh; include a control group when possible (difference-in-differences). Uncontrolled comparisons can mistake a warm winter for insulation savings. Avoid claiming causal benefits from the correlation alone. For a genuine fabric diagnostic, measure indoor-outdoor ΔT, meter useful heat input, thermal storage and ventilation/solar gains, and consider co-heating or the UK SMETER methodology. EPC data and NEED conditional distributions are possible comparison priors; no generic 'bad insulation' threshold is hard-coded in this codebase.

## 3. Identifying possible systems or activities

| Possible signal | What the code actually checks | Competing explanations / guardrails |
| --- | --- | --- |
| EV charging | Sustained >2.5 kW near-flat *excess* demand for ≥1.5 hours relative to per-clock-hour low-quantile baseline | Immersion heater, storage heater, oven, heat pump, equipment; EV model/ownership **cannot** be confirmed |
| Heating switched on | Consecutive high gas-consumption intervals on days colder than 14°C, when gas and weather are supplied | Domestic hot water and cooking can burn gas; half-hourly data cannot locate precise burner start times |
| Weather-responsive heating | A descriptive positive energy-vs-heating-degree-day slope with enough complete days | Correlation with occupancy, PV, charging and season, cannot distinguish compressor vs resistance vs storage |
| Holiday/absence candidate | ≥3 consecutive **complete** days at less than 45% of median daily electricity imports | Low demand may be mild weather, solar masking, missing data, EV absence, set-back; **never asserts occupancy** |
| Daytime activity | Variation in weekday 09:00–17:00 average load | **Cannot establish** WFH, who is home, job type, or schedule |
| Solar panels | Positive export confirms some export capable system, **not necessarily PV** | Solar **cannot** be inferred reliably from daytime grid import dips alone |
| Battery system | No claim from aggregate import alone | Export, PV, tariff shifting and standby loads confound signature; read inverter telemetry for proof |

Low-frequency NILM research explains that half-hourly aggregation makes event-level appliance separation especially difficult. The output explicitly lists non-identifiable technologies and marks all inferred events as **unverified candidates**. Do not interpret these signals as consent to monitor an occupant; only run locally with appropriate household authorization. Never upload named household holidays/absence candidates to a public repo.

For serious identification research, use independently labelled EV charger/heat-pump/immersion submetering and user-verified holiday/occupancy diary (with consent). Construct a confusion matrix (precision, recall, false-positive rate, calibration) by building, tariff, month and meter resolution. Avoid accuracy scores based only on clean synthetic data.

## 4. Tariff replay: cheapest is contextual

Each interval's import price is either an actual published UTC-specific tariff period, a flat rate, or a *fully defined* local-hour schedule. The program rejects missing prices, duplicated timestamps, overlapping readings, malformed schedules and negative consumption. **Negative wholesale-linked unit rates are allowed.** Standing charges cover the calendar span of each analysis, even when meter data are missing; low coverage is reported and not magically imputed. The `compare-tariffs` table ranks only the supplied candidates, not all real products sold in a postcode.

For an actual purchasing decision, obtain the precise region/postcode, payment method, tariff eligibility, bill-specific tax treatment, unit rate and standing-charge validity periods, smart-meter requirements, EV eligibility, contract commitment, exit fees, possible exit costs, export tariff eligibility and expected future prices. Distinguish gross consumption from net grid import. Compare tariff **paired with equipment**: a tariff optimal for an EV charging overnight can be expensive for a home whose heat pump mostly runs during a 16:00–19:00 peak.

Dynamic tariff replay to a future year requires future rate **scenarios**, not dishonest reuse of actual historical future outcomes. Use time-ordered tariff forecasts with separate stress cases, e.g. negative midday pricing, extreme winter peaks, restrictions on grid charging, feed-in/export rates cut, or gas/electricity price ratio changes. Do not calculate battery profits using ex-post prices and claim they are reliably achievable.

## 5. Retrofit economics: measure by measure

`simulate_portfolio` needs **gross electricity demand** before behind-the-meter PV, plus modelled or measured PV generation aligned with it. Its `consumption_kwh` is **not** automatically equal to the smart meter import number for a PV household. Supplying net grid import as gross demand would double count PV benefits. Electricity `gas_heating_kwh` is the portion of GAS INPUT used by space heating (not useful heat), and `electric_heating_kwh` is separately identified **resistive** heating. Do not claim those disaggregated subloads can be inferred confidently from import-only data.

- **Insulation** scales only the explicitly identified heating subloads, never total energy (cooking, TV and EV charging do not fall by 20% just because heating demand does). Assumed reduction is hypothetical, not measured.
- **Heat pump** converts the displaced gas input to useful heat via seasonal boiler efficiency and then to electricity via a fixed SPF or an input outdoor-temperature/COP curve. A COP curve varies with emitter temperatures, defrost, hot water and flow temperatures: do not use a generic curve as a guaranteed product rating.
- **Other gas loads** (hot water/cooking) are not silently deleted. Disconnecting the gas account requires zero remaining gas use, with an explicit `remaining_gas_to_electric_kwh_per_kwh` conversion if those uses are electrified; replacement equipment costs are separate.
- **PV** replays supplied interval generation; orientation/shading, roof suitability, inverter clipping, installation limits, self-consumption and export rates strongly change results. Use PVGIS, verified installer modelling or a measured PV inverter profile before proposing financial savings.
- **Battery** uses discretized state of charge, charge/discharge power and round-trip efficiency, avoids battery-to-grid export revenue, and forces 0 kWh initial and final state. It has **perfect foresight** of load, prices and PV, so the bill is an optimistic control upper bound on savings. Grid charging is allowed; restrictions/fees must be added if needed. Degradation, lifetime, inverter idle load and battery replacement must be considered in the separate investment appraisal.
- **Night-storage heating** uses a separate thermal battery with heater power, thermal kWh capacity, charging efficiency, heat loss and a zero initial/final store; it cannot miss an interval's assumed useful heat demand. Its optimized schedule also uses perfect foresight and ignores room comfort, heat emitter sizing and heating-system installation. Do not confuse it with electrical battery storage.
- **EV scheduling** finds cheapest available charge windows for declared required battery energy, charger power and charging efficiency; it is a planning counterfactual. It must not be applied on top of whole-home data already including the same unremoved EV load.
- **Investment** provides real-price NPV, simple undiscounted payback, maintenance/degradation and lifetime, **not** a financing offer. Compare installed capital net of relevant grants, roof replacement, inverter replacement, heat-emitter upgrades, servicing and VAT conditions.

## 6. Suggested real-data experiments and novel scenarios

1. Hold the same building, weather and occupancy fixed while varying *tariff-specific* 30-minute price spikes and EV charging times. Identify the interval-level trigger for tariff rank reversals.
2. Vary 2-week holiday dates across winter/summer; compare true consumption reduction with smart-meter absence flag recall and false positives under solar PV + battery.
3. Stress PV generation over north/south-facing roofs, cloudier western regions and winter peaks; calculate winter solar self-supply rather than just annual export yield.
4. Vary heat-pump flow temperature, defrost and immersion duty in an outdoor-temperature COP curve; compare morning recovery with steady low-flow heating.
5. Split hot-water vs space heating by use hours, and test replacement with heat-pump water heater, immersion/solar diverter, or retaining gas standing charge.
6. Compare high-heat-loss older detached houses to efficient flats at identical daily temperature, then weather-normalize to a different city. Separate fabric, geography and occupancy mechanisms rather than blaming location for inefficient construction.
7. Run battery under negative midday import prices, export-credit changes, and daylight-saving tariff schedules; charge only within inverter limits and no free start state.
8. Measure post-insulation heat-pump SPF changes at lower flow temperature, not only energy saved. Avoid simply adding independent percent savings without thermodynamic effects.
9. Test storage-heater heat retention and daytime comfort, including 23/25-hour tariff days and consecutive severe cold days; no storage model proves a property can stay warm.
10. Use REFIT/UK-DALE higher-frequency labelled appliance data to quantify 30-minute aggregation-induced false EV/immersion/storage-heater identifications; report false positives and privacy risks.

## 7. Reproducibility

Run `python -m unittest discover -s tests -v` (offline) and `python scripts/run_study.py --out reports/synthetic_study` (offline). The synthetic study creates 88 full-year scenarios; the 2025 synthetic source has known heat-loss parameters, WFH/holiday dates, EV and PV schedules. Report outputs are ignored by Git; neither raw public datasets nor actual household readings are committed. See [SCENARIO_STUDY.md](SCENARIO_STUDY.md) for reproducible findings.
