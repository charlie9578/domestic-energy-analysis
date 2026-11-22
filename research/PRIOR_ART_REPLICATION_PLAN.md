# Reproducible related-work benchmark plan

**Created:** 22 November 2026. Companion to [RELATED_WORK.md](RELATED_WORK.md) and [30-reference catalog](PRIOR_ART_CATALOG.csv). This is a specification of **proposed future experiments**, not a report of completed tests. Current repository results remain under [OBSERVED_VALIDATION.md](OBSERVED_VALIDATION.md) and [DEMAND_DECISIONS.md](DEMAND_DECISIONS.md).

## Research contract shared by all cards

1. Pin raw source URL, access date, publisher release, checksum, licence, collection dates and whether access is public, manual or controlled. Never upload private household data.
2. Preserve each household/building/sensor ID and measurement boundary, sample interval, local timezone and UTC offset, signal unit (W vs kW vs Wh vs interval kWh vs cumulative kWh), interpolation quality and missing intervals. For sources not from the same dwelling, **no actual observational joins**.
3. Predefine **training, validation and final test** chronologically; isolate final test household IDs for transfer experiments. Tuning, imputation thresholds, breakpoints, feature engineering selection and model comparison use training/validation only.
4. Compare a simple transparent baseline, an established external implementation if appropriate, and the proposed upgraded method on **exactly identical eligible observations**. Report denominators and excluded time/household counts.
5. Always publish two analyses: an **unconditional all-eligible** study and a **high-quality subset** with selection effects explicitly stated.
6. Keep actual counterfactual controls separate from **observed interventions** and **simulation**. A tariff replay is a historical reprice, not a randomised savings estimate. A thermostat strategy with no measured counterfactual is a modelled scenario.
7. Each experiment outputs a machine-readable results JSON (config, data hashes, eligibility, metrics, bootstrap seeds), a short Markdown interpretation, and unit/integration tests for timezone, DST, missing periods, reset counters and equipment failures.

## P0-A: External heat loss coefficient (HTC) validation — SMETER

**Question:** Can smart meter data, optionally indoor temperature and weather, estimate **measured physical fabric heat loss** with reliable uncertainty?

**Ground truth:** [SMETER phase 2 research data, 30 English dwellings](https://reshare.ukdataservice.ac.uk/856978/), including independently measured reference HTC; cross-check [2022 technical evaluation](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-technologies-project-technical-evaluation) and [2025 retrofit evaluation](https://www.gov.uk/government/publications/green-homes-grant-ghg-smeter-project-evaluation). Check the *actual accessible data dictionary, household permissions, sensor units and date ranges* before building parsers.

**Variants:**

- A0: dwelling size + type + construction-era prior (requires metadata and trained priors; exclude absent fields, no imputation with targets).
- A1: heating energy versus heating-degree-days (choose base temperature only in inner validation), conversion from input fuel to useful heat with uncertainty.
- A2: measured heat input, measured indoor-minus-outdoor temperature, degree-hours and solar proxy, with intercept for internal gains.
- A3: first-order or two-node grey-box RC thermal dynamics fitted on earlier sensor days; separate model identification from retrofit effect.
- A4: compare existing repo's heat balance/HDD to a documented published SMETER-style method if its code/data are obtainable under licence.

**Split and outputs:** group by dwelling, use leave-one-dwelling-out or grouped K-fold with a locked final group; train/holdout days within a dwelling for personalized estimates but report separately from cross-home generalization. MAE and median absolute percentage error (guard small denominators), signed HTC bias, % within ±15/±25%, 50/80/95% prediction interval coverage, conditional errors by property type and data quality. Bootstrap **by dwelling**, not by half-hour interval. Publish matched-coverage counts.

**Acceptance gate:** only state that an apparent HTC *tracks reference HTC* if independently held-out results beat basic metadata baseline and uncertainty interval coverage is credible. No generic "poor insulation" classification before defining building size/material and benchmark distribution; no causality claim without measured retrofit or controlled pre/post.

**Threats:** unmetered room gains, heating system inefficiency, hot water/cooking, solar, infiltration/window opening, indoor placement, heat stored in walls, resident behavior, insufficient thermal excitation, weather localisation and ground-truth HTC uncertainty.

## P0-B: Device / equipment signature tests — REFIT, UK-DALE, OPSD

**Question:** Can we identify **real** EV charging, heat pump, resistance storage, immersion, PV and battery from whole-home 30-min grid import without claiming more certainty than the meter supports?

**Labels:** 2016 OPSD residential EV/HP/PV channels and [REFIT](https://pmc.ncbi.nlm.nih.gov/articles/PMC5315495/) / [UK-DALE](https://www.nature.com/articles/sdata20157) submeter channels. Explicitly verify the semantics of each load before accepting it as ground truth; heat pump *presence* and *on-state* are distinct tasks.

**Ablation:**

- Compare native observed resolution to reaggregated 1, 5, 15 and 30 min interval **kWh** from exactly the same source periods. Power-average and integration must respect gaps; do not turn missing samples into zero energy.
- Baselines: per-household threshold, 1–3h plateau detector, temperature-conditioned high-load rule, random/prevalence predictors.
- Additional methods: logistic/gradient-boosted features, basic NILMTK method and a documented probabilistic abstaining detector.
- Split by household ID **before** any standardization/feature tuning. The UK-DALE/OPSD small samples must never masquerade as nationally representative.
- For solar/battery, use net-import and direct generator channels separately and quantify how much self-consumption hides the physical equipment signature.

**Metrics:** macro and per-class event-level precision/recall/F1, false-positive **events/home-month**, AUCPR (class imbalance), onset delay, calibration reliability and coverage of abstentions. Include confusion matrices specifically **EV ↔ storage heater ↔ immersion ↔ heat pump**; where no labelled storage heater exists, call the comparison a simulation rather than an empirical confusion matrix.

**Acceptance gate:** any public "EV detected" result requires prospective test-house precision above an explicitly preregistered threshold and sufficient positives; otherwise display "**EV-like event, unverified**". Do not deploy home-absence/occupancy alerts from these device signatures.

## P0-C: Thermostat control and heat-pump comfort

**Question:** How do constant, overnight-setback, morning/evening, WFH, preheat and overnight-charge strategies compare for *the same heat service*?

**Datasets:** [IDEAL](https://www.nature.com/articles/s41597-021-00921-y) real room/boiler/gas/electric readings; [HeatpumpMonitor](https://heatpumpmonitor.org/) same-site optional indoor/outdoor/heat channels; [Electrification of Heat](https://es.catapult.org.uk/report/electrification-of-heat-summary-reports-and-datasets/) monitoring with system type where legally accessible. For claim about *actual resident thermostat settings* require setpoint logs; indoor temperatures alone are insufficient.

**Models:** current 1-zone baseline, grey-box 1R1C and 2R2C, weather+solar gains, emitter/output-water temperature-dependent COP, optional DHW and thermal-store state. Include gas boiler and electrical resistance heater comparison where labels exist.

**Strategies:** 20°C constant; 20°C waking / 17°C sleeping; 19°C/16°C; 20°C 06–09 and 17–22 only; continuous during WFH; away setback; preheat 00–07; physical storage heating charged 00–07; rolling MPC with forecast.

**Measured-validatable part:** fit heat-loss and thermal capacitance on earlier measured periods, test **indoor temperature**, delivered space heat, electrical input, peak power, and COP on later periods under *observed* heating control. Compare to last temperature / simple RC baseline. Group 7-day error blocks for interval bootstrap.

**Counterfactual-only part:** simulate alternative controls with input outdoor weather and historical tariff; vary fitted parameters within uncertainty, flow temp, heat-pump max output, storage standing losses, gains, schedule and outage. Report why some strategies are **not physically feasible**. Without field intervention **do not claim realized savings**.

**Metrics:** bill (£, p10–p90 over param uncertainty), total electricity and gas, peak-period kWh, useful heat, occupied comfort degree-hours under 18/19/20°C minimum and above comfort max, coldest occupied period, morning warmup time, cycling and water temperature constraints, resistive backup. Show Pareto frontier £ vs discomfort.

**Acceptance gate:** no "best thermostat setting" unless comfort constraints satisfied at uncertainty quantile and sensitivity to heat-pump COP/forecast quality is displayed.

## P1-D: Tariff + EV, PV, battery, thermal optimization

**Question:** How much value comes from *switching tariff alone*, *load adaptation*, and *installed hardware*, separately?

**Sources:** same-home OPSD labels for physically available EV/HP/PV; current tariffs from official supplier APIs for relevant region and historical period. Never apply 2026 GB rates to 2016 Germany and describe as real historic spending.

**Competing controllers:** static flat baseline; Economy-7 charge timer; cheapest-known-window EV charger; rolling best-effort plan; and, where compatible, a [Predbat](https://github.com/springfall2008/batpred) or [EMHASS](https://emhass.readthedocs.io/en/latest/) style solver verified on identical fixtures. See also [tvofi Heat Pump Cost Optimizer](https://github.com/tvofi/heatpump_optimizer).

**Dispatch physics:** import/export limits, availability windows, charging energy deadlines, EV plug in/out, battery state of charge and round-trip efficiency/degradation, PV inverter losses, hot water demand and maximum thermal store temperature, heat-pump COP/output constraints, no simultaneous physically impossible import/export or battery charge/discharge, standing charges.

**Honest forecasts:** forecast inputs available **at the time of decision** only; never allow actual future consumption/price beyond published notice horizon to leak. Record a perfect-foresight **oracle upper bound** separately.

**Metrics:** annual bill only with enough coverage or justified imputation, held-out actual variable cost and per-day savings, monthly distribution, negative-price handling, maximum and 95th percentile comfort deficits, demand peak, unserved EV kWh, extra cycles/degradation and opportunity cost of foregone PV export. Compare multiple weather years.

**Acceptance gate:** every optimized policy must beat a reasonable non-optimizing rule on same scenarios **while preserving service**, not just the oracle. Include baseline tariff suitability before retrofit; present capital-cost ranges and sensitivity rather than one payback number.

## P1-E: Forecast transfer and weather normalization

**Datasets:** LCL (30 min), OPSD (15 min), matched Open-Meteo ERA5 weather, 2023–24 HeatpumpMonitor monitored heat data. Distinguish model's *grid import* from whole-home demand (PV changes the relationship).

**Compare:** previous week's same-slot; training hour-week median/mean; temperature-HDD GLM or ridge; gradient boosting with rolling effects; Bayesian/pinball quantile predictions; optional occupancy flags only if explicitly provided. Include bank holidays and DST.

**Design:** 1–3 month rolling-origin backtests with purged gap for lags; leave-household-out transfer evaluation; test extreme cold weeks and missing intervals. Report daily and half-hour MAE, RMSE, seasonal energy bias, positive-load exceedance rates and p50/p90 interval coverage by month/temp/house type. Compare forecast errors to actual bill errors, not only squared error.

**Acceptance gate:** no annual £ claim from a one-month sample; present distribution of predicted annual energy after weather normalisation, with explicit uncertainty.

## P2-F: Solar, retrofit, payback validation

Use [JRC PVGIS](https://photovoltaic-geographic-information-system.ec.europa.eu/en/about-pvgis-6) site radiation and [pvlib](https://pvlib-python.readthedocs.io/en/stable/) module/inverter equations. Compare predicted generation against verified OPSD PV channels where orientation/inverter metadata available; missing metadata ⇒ scenario bands.

For insulation, define a before/after cohort with matched heating services, weather and occupancy. Estimate difference-in-differences with a comparable untreated group when available, otherwise document confounding. For batteries, cross-check simulation accounting against [NREL SAM](https://sam.nlr.gov/) on common fixtures but override all US-region defaults for GB policy.

Capital decisions require installer quotation range, maintenance, tariff and discount sensitivity, battery replacement and heating-system lifetimes. No confident simple payback if tariff and performance are highly uncertain.

## Why we must not collapse all experiments into a single leaderboard

- A meter forecasting model can predict grid imports accurately and still misidentify all appliances.
- A thermostat controller can reduce energy while violating comfort.
- A heat pump can have good SPF with a larger absolute bill if tariffs change.
- Solar can substantially reduce **grid imports** while not changing the true electrical appliance usage.
- A heat-loss proxy is not a certified U-value, EPC or independent whole-building HTC.
- A historical retrospective optimizer with full next-day demand has unrealistic perfect information.
- A household-absence classifier can appear convincing while being wrong or invasive.

**Outputs should retain their evidence tiers:** measured, forecast and held-out, independently labelled detection, thermal estimate, and counterfactual optimization. This is a safety, privacy and scientific-reproducibility constraint, not only presentation.

## Suggested implementation tree

```
research/
  RELATED_WORK.md                 # literature and products reviewed
  PRIOR_ART_CATALOG.csv           # 30 reference records
  PRIOR_ART_REPLICATION_PLAN.md   # this proposal
benchmarks/
  README.md                       # future commands, outputs and data contracts
  configs/
    heat_loss_smeter.json
    nilm_resolution.json
    heat_control.json
    tariff_dispatch.json
    forecast_transfer.json
```

Start by implementing **one** benchmark end-to-end, including dataset permission checks and held-out scoring. The recommended first two are SMETER HTC and the OPSD-labelled 30-minute EV/heat-pump/PV resolution ablation. Those have the clearest external measurements for falsifiable claims.
