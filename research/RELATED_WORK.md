# Related work: what other researchers and developers have built

**Research snapshot:** 22 November 2026. This review records externally published work and concrete opportunities for `domestic-energy-analysis`. It is **not** evidence that this repository has reproduced every cited result. [Machine-readable catalogue](PRIOR_ART_CATALOG.csv) contains 30 attributed references with primary URLs, access status, limitations and priority.

## Executive finding

Three overlapping disciplines approach the question from different directions:

1. **Smart-meter analytics:** forecast electricity/gas and infer candidate loads from whole-home readings. Validated appliance attribution needs labels (and often seconds-level sampling); household *occupancy/absence* is an especially sensitive and error-prone inference.
2. **Building-physics and heat-pump monitoring:** estimate useful heat, loss coefficients, thermal response, SPF/COP and ability to shift heating while maintaining indoor temperature. Whole-home import alone is underdetermined.
3. **Tariff/asset optimization:** dispatch batteries, PV, EVs and heaters against prices. An optimizer can be mathematically correct and economically wrong if it uses future actual demand, assumes perfect forecasts, ignores standing charges/exports, or violates comfort and equipment constraints.

**Research opportunity:** train independently on actual household channels, validate time-ordered and across households, couple uncertainty-aware thermal/electric models to a solver, and report **cost, energy, comfort, prediction error and detector false positives together**. The current repo already has preliminary data ingestion, measured examples and separate thermal/tariff experiments; this review proposes a rigorous unified benchmark.

## 1. Measured household datasets: different signals, different questions

| Dataset | What the authors collected | What can be tested | Crucial boundary |
|---|---|---|---|
| [Low Carbon London](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d) | 5,567 London homes, half-hour electricity, 2011–14; standard vs trial time-of-use arms | representative-ish historical load shapes, weekday/season patterns and retrospective tariff replays | no ground-truth thermostat, occupants, EV charger or heat-pump identification; dated prices and trial effects |
| [IDEAL](https://www.nature.com/articles/s41597-021-00921-y) | 255 UK homes, up to 23 months, electricity/gas, room and boiler temperatures, contextual sensors and surveys | thermal dynamics, indoor temperature, heating events, appliance detection for monitored channels, heterogeneity | room temperature **is not the thermostat setpoint**; channel presence varies; check access and sampling |
| [REFIT](https://pmc.ncbi.nlm.nih.gov/articles/PMC5315495/) | 20 UK homes with about 8 s whole-home and up to nine appliance power sensors | event-based detection, false positive rates and realistic degradation when downsampled to 30 min | small/nonrandom cohort, limited ground-truth heating comfort; 8 s **W**, not interval kWh |
| [UK-DALE](https://www.nature.com/articles/sdata20157) | five UK homes with aggregate and appliance electrical channels | transfer-learning and sampling-resolution ablations | very few homes; not a dataset of daily thermostat setpoints |
| [OPSD household](https://data.open-power-system-data.org/household_data/2020-04-15/) | Konstanz-area residential grid, PV, EV and heat-pump counters at 15 min/hour | measured-load oracle signatures, solar masking and EV/HP classifier confusion | German households; many series are **cumulative kWh**, needing differencing and gap/reset checks |
| [Electrification of Heat](https://es.catapult.org.uk/report/electrification-of-heat-summary-reports-and-datasets/) | field demonstration with hundreds of UK installations, monitoring and published reports | external heat-pump performance and system variation | site selection, inconsistent metering boundaries; check dataset permissions |
| [HeatpumpMonitor](https://heatpumpmonitor.org/) | contributor-provided electrical/thermal energy and optional outdoor/indoor/flow sensors | SPF, performance against ambient/flow temperature, measured heating dynamics | volunteer cohort, varying sensors, inaccurate cross-site comparisons unless boundaries match |
| [SMETER phase-2 dataset](https://reshare.ukdataservice.ac.uk/856978/) | 30 English dwellings with independently measured heat transfer coefficients, in-use temperatures, energy, weather and dwelling/occupancy information | **direct external reference for heat-loss estimation**; compare proxy HTC against independent HTC | access terms must be checked; sample is small and measurement circumstances vary |

For original authors, licence and sampling details follow each linked publication; **do not rehost whole datasets**. Hold-out households must never leak into model tuning. See [download/source guide](PUBLIC_DATASETS.md) and [existing observed validation](OBSERVED_VALIDATION.md).

### Priority: SMETER benchmark was previously missing

The [2022 BEIS technical evaluation](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-technologies-project-technical-evaluation), [2025 Green Homes Grant SMETER evaluation](https://www.gov.uk/government/publications/green-homes-grant-ghg-smeter-project-evaluation) and the [30-home phase-2 research dataset](https://reshare.ukdataservice.ac.uk/856978/) are especially relevant to the claim "how well insulated is this building?". These projects investigate measured heat-loss coefficients and whether meter-supported methods can detect retrofit-induced changes. We should distinguish:

- a **heating-degree-day gradient** (input energy vs weather);
- an **apparent whole-building heat-transfer coefficient** (requires heat delivery and indoor/outdoor difference, gains and storage assumptions);
- a **reference HTC** obtained by independent test; and
- an **EPC rating**, which is a distinct standardized asset assessment.

The first is not automatically the second; neither automatically establishes the third or fourth. Validate prediction intervals against reference HTC before making consumer recommendations. A simulated insulation upgrade is not empirical verification of a property's fabric.

## 2. NILM, activity detection, and privacy

[NILMTK](https://github.com/nilmtk/nilmtk) establishes common meter-data conversion, disaggregation evaluation and appliance labels. [NILMbench](https://nilmtk.github.io/nilmbench/) distinguishes T1 (within building), T2 (unseen building) and T3 (unseen dataset) tests; follow the [protocol audit](https://github.com/nilmtk/nilmbench/blob/main/docs/protocol-audit.md) rather than conflating archived experiments with the current leaderboard.

[Occupancy detection of residential buildings using smart meter data: a large-scale study](https://www.sciencedirect.com/science/article/abs/pii/S0378778818316724) studied more than 5,000 households over 18 months. It demonstrates the research relevance and **privacy risk** of inference, not a license to assert that an individual is on holiday. In the UK, review [smart meter consumer rights and expectations](https://www.gov.uk/government/publications/smart-meters-your-rights-and-expectations/smart-meters-your-rights-and-expectations) before linking meter streams to personal occupancy calendars.

**Benchmark plan:**

1. Build appliance labels from measured submetering (REFIT/UK-DALE and OPSD EV/HP) and **downsample the SAME channels** to 1 min, 15 min and 30 min. Do not treat high-frequency results as applicable at SMETS half-hour granularity.
2. Compare simple rules (threshold/plateau/HDD), supervised gradient boosting and NILMTK baseline(s) under matched constraints. Include "unknown/abstain" outcomes.
3. Separate (a) **EV charging exists**, (b) **EV charging at this time**, (c) **heating activity**, (d) **electric heating technology present**, and (e) **someone away**: different labels, error costs and evidence.
4. Report household-held-out **precision, recall, F1, false positives per home-month, calibration**, and event-level detection delay. Class prevalence matters; a high accuracy with few events may be useless. Split household IDs before fitting any thresholds or scalers.
5. For holidays and WFH, without freely consented **ground-truth occupancy diaries**, report *unusual low-use days only*; no occupancy detection "accuracy". Suppress identifiable traces, precise absence alerts and personal profiles from public reports.

**Failure cases:** storage heating imitates EV charging; hot-water immersion imitates a long resistor load; solar and batteries mask household gross load; gas spikes reflect DHW and cooking; missing meter intervals produce false holidays; demand-response changes normal signatures.

## 3. Indoor temperatures, heating dynamics and thermostat strategies

[Bacher & Madsen (2011)](https://doi.org/10.1016/j.enbuild.2011.02.005) describe identifying reduced-order ("grey-box") thermal RC models from measurements. [Oldewurtel et al. (2012)](https://www.sciencedirect.com/science/article/pii/S0378778811004105) formalise weather-aware, uncertainty-aware building control. These methods connect with the repo's [hourly heat-balance pilot](HOURLY_HEAT_BALANCE.md) but require **time-varying indoor temperature, heat input and external weather** for convincing parameter estimation.

Heat pump control is distinct from simple electric-resistance thermostats:

- Overnight setback lowers indoor–outdoor losses but could require high output water temperatures, resistive backup or poor morning COP for recovery; results depend on thermal mass, weather, emitter sizing and maximum temperature.
- Constant low-flow operation may improve some systems' COP but can cost more if heat is delivered during expensive tariff periods. Continuous heating is **not** a universal energy-saving rule.
- Morning/evening schedules can be cheaper when the house is unoccupied, but risk discomfort if time to temperature is underestimated.
- Cheap overnight resistance storage uses a real thermal store with state-of-charge, charge power, standing losses and release constraints. Do not model a virtual "store" with unlimited heat transfer.
- Preheat / thermal load shifting should be limited by indoor max, heating capacity, forecast uncertainty and cold-day recovery. Heat pumps are not infinitely dispatchable.

The [NBER/Octopus heat-pump and TOU study](https://www.nber.org/papers/w33036) (2024) reports major observed gas-electricity substitution and evening peak shifting in the studied adopter cohort; it does **not** identify which thermostat schedule should be universally adopted. Use it to assess whether directional demand shifts are plausible, not as a calibration for every home. More recent [third-party control field research](https://www.sciencedirect.com/science/article/abs/pii/S0306261925004350) and [household flexibility participation study](https://www.sciencedirect.com/science/article/pii/S0140988325003895) provide field-facing checks on feasibility and acceptability.

**Preregister thermostat comparison:** continuous 20°C; 20/17°C overnight setback; 19/16°C; 06–09 + 17–22 heating; WFH and away with declared schedules; overnight preheat; storage charge only in named tariff windows. For each strategy report:

- useful delivered heat and input electricity/gas on the **same service boundary**;
- tariff-paid £ including standing charges and demand shifted at peak;
- occupied degree-hours below min comfort, hottest degree-hours above max, morning recovery minutes, equipment run/cycle limits;
- room temperature prediction MAE (1 h and 6 h) on held-out real sensor data;
- uncertainty and scenario failure rate across weather years and building HTC/thermal mass;
- an **oracle with future information** vs an honest day-ahead forecast vs a simple thermostat baseline.

Without measured *thermostat setpoints*, describe these as counterfactual simulations constrained by observed temperatures and heating power, not observed thermostat experiments.

## 4. Tariffs, PV, battery, EV and optimiser prior art

Existing open source systems provide rich baselines:

| Project | What is already implemented elsewhere | Proposed use in this project |
|---|---|---|
| [EMHASS](https://emhass.readthedocs.io/en/latest/) | optimization for grid import/export, batteries, PV, flexible loads and a [heat-pump-as-thermal-battery](https://emhass.readthedocs.io/en/stable/study_cases/heat_pump_walkthrough.html) | reuse mathematical constraint patterns and compare common input/output fixtures, subject to licences |
| [Predbat](https://github.com/springfall2008/batpred) | Home Assistant battery scheduling, forecast demand, dynamic tariffs, [annual what-if economics](https://github.com/springfall2008/batpred/blob/main/docs/annual-prediction.md) | benchmark battery and PV dispatch versus simple charging and no-storage baselines |
| [Heat Pump Cost Optimizer](https://github.com/tvofi/heatpump_optimizer) | Home Assistant scheduling against prices/weather, two-zone thermal estimates, hot water and comfort | compare heater constraints, adaptive planning and control safety; **project claims are not independent trial findings** |
| [Home Assistant Energy](https://www.home-assistant.io/docs/energy/) | metering integration and visual energy accounting | interoperability and local-first user interface, not assumed causal bill savings |
| [pvlib-python](https://pvlib-python.readthedocs.io/en/stable/) + [JRC PVGIS](https://photovoltaic-geographic-information-system.ec.europa.eu/en/about-pvgis-6) | solar radiation, PV output and engineering loss models | site/orientation-specific PV scenarios, irradiance sensitivity |
| [NREL System Advisor Model](https://sam.nlr.gov/) | PV, storage dispatch and financial projections | independent approximate cost/dispatch reference; replace non-GB default rates/costs |

**Do not claim a tariff is "best" by comparing only the same fixed measured consumption.** Report both:
(a) *bill replay*: tariff changes, usage fixed (observational counterfactual);
(b) *adapted dispatch*: optimized usage **changes** and is constrained by service delivery, prediction error, baseline load, import/export, peak current, efficiency and battery wear.

For every plan, use exact, dated tariffs and export rules; account for standing charges, gas removal eligibility, debt/exit fees if supplied, battery cost/degradation and installer costs. Optimise **expected** future bills; evaluate realised bills on later intervals with prices that would actually have been known at decision time. Compare oracle, simple rules (e.g. Economy 7 timer), forecast-assisted scheduling and an MPC policy. Use safety fallback if forecast feeds fail.

## 5. What's genuinely different about this proposed platform?

The repo currently contains baseline half-hour demand and heat-balance validation, real public examples, synthetic retrofit/scenario analysis and reproducible tariff tools; see [observed validation](OBSERVED_VALIDATION.md), [demand decisions](DEMAND_DECISIONS.md), and [heating study](REAL_DATA_HEATING.md). **Do not describe those preliminary models as production-calibrated recommendations.**

Proposed contribution is an **evidence ladder**:

| Tier | Output | Evidence required |
|---|---|---|
| A | measured energy, meter quality, supplier tariff replay | real interval imports/rates with coverage and provenance |
| B | weather-normalised expected demand / anomaly | time-ordered evaluation, calibrated uncertainty, missingness audit |
| C | device/heating candidate | labelled circuit or user-confirmed systems; household-held-out confusion matrix |
| D | heat-loss/thermal flexibility inference | indoor/outdoor readings, heat input metering, validation vs reference HTC or intervention |
| E | *best action* (thermostat/EV/PV/HP/battery/tariff) | physically constrained counterfactual, honest forecasting, comfort and economic risk, observed pilot where possible |

An "identified EV" without circuit/owner label should remain **EV-like load**. A "bad insulation" verdict without independent HTC is unwarranted. A cheap counterfactual that leaves rooms cold is not an acceptable energy recommendation.

## 6. Replication priorities

See [experiment cards and acceptance gates](PRIOR_ART_REPLICATION_PLAN.md).

1. **P0: SMETER HTC** — measured reference building heat-loss vs meter/HDD and temperature-augmented methods, with calibration. Most differentiating for insulation claims.
2. **P0: appliance signatures across sampling rates** — OPSD-labelled EV/HP/PV and REFIT/UK-DALE high-frequency labels downsampled to half-hour. Most differentiating for system detection.
3. **P0: thermostat forecast and comfort** — IDEAL/HeatpumpMonitor heat + indoor/temp joined by same house and time; emulate control alternatives and validate indoor trajectory.
4. **P1: cost optimization with honest forecasts** — grid import + variable tariffs; compare oracle, static, and rolling strategies for EV, heating, storage and battery.
5. **P1: cross-household weather expectation** — London and OPSD chronological + leave-household-out forecast comparison, including baseline and uncertainty calibration.
6. **P2: PV and retrofits** — PVGIS/pvlib solar scenarios plus controlled retrofit or SMETER before/after; make interval bill vs long-run capex distinction.

## Source handling / update policy

All URLs, study types and restrictions are in [PRIOR_ART_CATALOG.csv](PRIOR_ART_CATALOG.csv). The table is intentionally an annotated reference index, **not** a systematic review or meta-analysis. Selected sources were verified in public search in November 2026; exact software features and access rules can change. Literature citations do not grant dataset licences or reproducibility. For each reproduced experiment, pin publication/data DOI or dataset release, SHA-256, retrieval date, timezone/units, transformation commit, inclusion exclusions and code revision. No personal occupancy calendar or meter-address matching data goes in public Git.

