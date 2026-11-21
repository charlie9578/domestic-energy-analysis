# Methodology, units and failure modes

## 1. Research questions

1. How much gas/electricity does a comparable home use, and how does size/occupancy/EPC rating modify a sensible benchmark?
2. What is the observed rather than advertised **seasonal performance factor (SPF)** of a heat pump, conditional on weather, water-flow temperature and quality-filtered operation?
3. For the **same useful heating delivered**, at what seasonal COP and tariff does heat-pump operation cost more/less than a gas boiler? What happens if the household keeps the gas standing charge?
4. Can half-hourly electricity usage and exact, historical rate periods reveal peak demand and time-of-use opportunities? What happens on British Summer Time transitions and during missing intervals?
5. What changes if data come from households with solar PV, different occupancy, electric cars, or non-representative volunteer trials?

## 2. Accounting conventions

| Quantity | Formula | Units and assumptions |
| --- | --- | --- |
| Gas volume to input energy | `V(m³) × 1.02264 × calorific_value(MJ/m³) ÷ 3.6` | kWh on bill; imperial `hundred_ft3` is converted first |
| Gas heating input | `gas_kWh × heating_fraction` | Excludes separately accounted cooking/process gas |
| Useful heat from old boiler | `gas_heating_input_kWh × seasonal_boiler_efficiency` | kWh useful heat; not equal to gross gas kWh |
| Added heat-pump electricity | `useful_heat_kWh ÷ actual_system_SPF` | kWh electricity at same metering boundary |
| Break-even variable-only SPF | `boiler_efficiency × electricity_p/kWh ÷ gas_p/kWh` | **Gas standing charge cancels only if retained**; excludes capex |
| Bill | `Σ (interval_kWh × applicable_p/kWh)/100 + occupied_billing_days × standing_p/day/100` | GBP; no invented rates or null-as-zero |
| Average heat-pump COP over observations | `Σ heat_output_kWh / Σ heatpump_electricity_kWh` | Energy-weighted ratio, **not** mean of per-day COPs |
| Interval average electrical power | `kWh × 60 ÷ interval_minutes` | kW: average of each interval, **not** instantaneous peak |
| Coverage | `sum of observed interval durations / elapsed UTC duration` | Missing samples reduce coverage; no zero fill |

The boiler counterfactual assumes unchanged useful heat and other-electricity load. A gas-to-electric switch may also change hot-water production, cooker, immersion, pumps, flow temperatures, controls and behavior. **Gas removal is prohibited in the model if residual gas use is still present**, rather than quietly pretending it disappears. The tool does not evaluate upfront subsidies, finance, maintenance, inflation, meter removal cost, depreciation or carbon without explicit scenario inputs.

## 3. The pricing baseline is deliberately narrow

As of **21 Nov 2026**, Ofgem lists average GB Direct Debit rates for **1 Oct–31 Dec 2026** (units include current tax treatment, and average over regions): **26.32p/kWh electricity, 7.97p/kWh gas, electricity standing 54.83p/day, gas standing 29.68p/day**. From Oct 2026 electricity VAT is temporarily zero while gas rates include 5% VAT. Holding these rates for 365 days creates a **constant-price thought experiment**, *not* a full-year achieved bill, tax forecast, or national fixed price. Domestic actual rates vary by region, payment method and contract, and only genuine timestamped rates should be used for time-of-use assessment.

The price cap limits **unit rates and standing charges**, not a home's total bill. An Ofgem typical-bill headline is at *its own* Typical Domestic Consumption Values and must not be compared directly with an independently chosen household gas/electricity pair. Include both standing charges in absolute bills; only subtract the gas standing charge if the property actually ends the gas account and no other gas demand remains.

## 4. Time series, local time and completeness

Use an offset-aware UTC timestamp for **each interval start**, interval energy (kWh), and duration (minutes). Compute all sorting, coverage and tariff joins in **UTC**. Convert to `Europe/London` solely to group hours or billing dates. Fall DST means 25 local hours, spring DST means 23; **never deduplicate based on naive local wall times**. Record the timezone for each analysis.

- Reject duplicate timestamps, overlapping energy intervals, missing tariff rates, non-finite/negative consumption and unsupported interval lengths. **Negative unit rates are legitimate** for some dynamic tariffs.
- Day counts based on dates with observed data do **not** guarantee true standing-charge billing days in a incomplete period; provide a fully covered billing window for a bill-equivalent number.
- Peak kW is the *largest interval-average power*, not a 1-second grid demand. The observed p95 is over reported intervals and is sensitive to censoring and temporal resolution.
- Missing intervals cannot be imputed as zeros. For research-grade annual estimates, require a full-year observation window and acceptable coverage, or provide separately justified imputation and uncertainty bounds.
- Smart-meter profiles alone do not reveal heat-pump draw versus EV/cooking/appliances, especially if PV or storage distort net imports. Separate submetering is preferred.

## 5. Heat-pump measurements and selection

The HeatpumpMonitor public **daily CSV** includes `combined_elec_kwh`, `combined_heat_kwh`, `quality_elec`, `quality_heat`, `combined_data_length` (seconds), and outdoor-temperature summaries. The adapter retains only rows with finite, positive input electricity, nonnegative heat output, quality >=95% on both energy channels, and >=23 hours observed data. It then computes **energy-weighted observed SPF** and grouped outdoor-temperature bins. These thresholds are choices, *not* platform guarantees or a certified SPFH2/H3/H4 method.

Crucially, the daily `combined_*` boundary may omit or include pumps, immersion heaters, backup boilers and defrost depending on the system and metadata. Consult `metering_boundary_code`, `metering_inc_*` and public notes before comparative claims. For a robust cross-system cohort, require comparable metering boundaries, minimum observation duration, matched season/weather, an exclusion flowchart, and uncertainty intervals. Current `heatpump` outputs are **descriptive of downloaded systems/days only**; no claim of representative population performance is made.

When using EoH's archived monitoring data, energy-series values are **cumulative counters**, not per-half-hour consumption; take differences *after* reset/outlier handling, using the published cleaning code and quality score. Always state whether SPFH2, SPFH3 or SPFH4 was used. A simple published daily energy ratio is not interchangeable with an audited full-year SPF.

## 6. Source representativeness and data engineering priorities

- **NEED (DESNZ)**: for 2024, E&W domestic meter-matched *gas* and *electricity* samples differ. Comparing gas median 10,000 kWh with electric median 2,500 kWh is a **constructed representative-like scenario**, not the median of household totals or a verified matching property.
- **Low Carbon London**: 2011–14, London, 5,567 participants with an estimated 167 million half-hour rows; treat as a historical experiment, not a modern national profile. Acquire in chunks and convert to partitioned Parquet only after checking licence, sample selection and timestamp anomalies.
- **IDEAL**: gas/electricity plus room/boiler temperature in 255 households; valuable for heating baseload separation, but limited to parts of Scotland and 2016–18. Household consent/privacy and missing sensors matter.
- **EPC**: modeled certificate demand ≠ actual metered heat demand; would need legally acceptable matching and bias analysis.
- **Carbon**: grid **average** carbon intensity by period is not marginal emissions from a newly switched heat pump. For emissions, define gas direct/chain factors and electrical dispatch/time horizon, and do not conflate them with carbon intensity forecasts.

## 7. Verification and reproducibility

`python -m unittest discover -s tests -v` runs offline tests for units, gas conversions, price/standing-charge arithmetic, scenario invariants, DST fall-back, missing rates/intervals, negative rates, and energy-weighted COP. `python -m domestic_energy demo` builds outputs from clearly labeled **synthetic** example files; calculations are deterministic with no network calls. Public download commands run only when explicitly invoked and can fail if the provider changes its API, serves a new schema or requires authorization.

Suggested study protocol: register a source snapshot date and checksums; define property eligibility and metering boundaries; record raw unit/locale/timezone; enforce quality thresholds; calculate source-level descriptive stats and cohort exclusions; analyze tariff and SPFs as paired time-series; compare weather-normalized estimates; perform sensitivity/uncertainty checks; only then release aggregate results with appropriate attribution.

## 8. New occupancy/weather/retrofitting modules (21 Nov 2026)

See [ADVANCED_MODELS.md](ADVANCED_MODELS.md). Earlier `gas-convert`, `scenario`, `heatpump`, `meter` and `fetch-rates` features are unchanged. The new modules add local-day weather join with DST-compliant 23/25-hour coverage, holdout-validated HDD/cooling-degree-day models, calibrated only on a **SYNTHETIC** demonstration; candidate detection of EV-like events/low activity/gas runs; tariff×portfolio replay; electrical battery dynamic programming; thermal storage scheduling; and investment NPV screens.

### New guardrails and what is NOT claimed

- Only **conditional** usage expectation. Heating slope is an indicative HLC conditional on assumed boiler efficiency and consistent occupants, not measured insulation quality.
- A public half-hour electricity meter normally measures **net grid import**, while PV retrofit simulations require **gross household demand** plus a separately modelled PV generation time series. Never double-count existing solar.
- Heat-pump gas-standing-charge removal requires explicitly electrifying ALL residual gas loads; DHW/cooker changes must be declared.
- Electrical battery and night-storage heating price minimizers have perfect future knowledge and omit some real-world restrictions; resulting savings are **optimistic** rather than achievable guarantees.
- Public API availability, weather/PVGIS product versions, tariff prices and local equipment costs change. No live feeds were queried during offline tests.
- Distinguishing holiday, WFH, EV, heat pump, solar or battery from whole-home 30-minute electricity data is fundamentally **ambiguous** without corroboration; only heuristic **candidate** flags are emitted.
