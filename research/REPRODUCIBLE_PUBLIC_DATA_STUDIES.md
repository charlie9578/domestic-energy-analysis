# Studies built on public household-energy data: reproducibility shortlist

**Reviewed:** 22 November 2026. Companion to [RELATED_WORK.md](RELATED_WORK.md), [PRIOR_ART_CATALOG.csv](PRIOR_ART_CATALOG.csv) and [PRIOR_ART_REPLICATION_PLAN.md](PRIOR_ART_REPLICATION_PLAN.md).

The question is **not** just whether a paper is free to read. The useful cases are: (1) paper describes a falsifiable method, (2) the **underlying time-series data** can be obtained legally without private household access, and preferably (3) exact code/configurations can also be rerun. Each study below explicitly distinguishes these.

## Best empirically reproducible candidates

### 1. 2026: An empirical benchmark of deep time-series models for smart meter energy forecasting

- **Paper:** [Energy and AI 25 (2026), 100870](https://doi.org/10.1016/j.egyai.2026.100870); [public preprint](https://arxiv.org/abs/2608.18675).
- **Public input:** [UK Power Networks Low Carbon London (LCL)](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d). Study also uses [Pecan Street Dataport](https://www.pecanstreet.org/dataport/), which may have different access/usage conditions; **do not assume free, unrestricted raw-data download**.
- **Method:** comparative forecasting benchmark of nine models across simple/MLP/convolution/Transformer families. It studies input context, prediction horizon, computational cost and practical/statistical differences.
- **Reproduction status:** publicly sourced LCL arm can be rebuilt; **not reproduced in this repo**. Exact paper implementation, data subsets and hyperparameters must be obtained or independently specified.
- **Useful test:** on the *same houses and held-out dates*, compare last-week, rolling median, gradient-boosted trees and a small DL method; report MAE, bias, pinball loss, tariff error, elapsed CPU time and per-household performance. The published result does not justify universal deployment of a particular deep architecture.

### 2. 2026: Explainable AI for predicting household demand flexibility

- **Paper:** [Energy and AI 2026, 100686](https://doi.org/10.1016/j.egyai.2026.100686).
- **Public input:** [Low Carbon London time-of-use pilot](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d).
- **Method:** household- and hour-level price response estimated using regularised regression, followed by interpretable nonlinear features/explanations. The trial has actual ToU treatment history; it is stronger evidence for *price response* than retrospectively re-pricing a fixed meter profile.
- **Reproduction status:** underlying public meter dataset available; **published exact model and selection are not yet rerun**.
- **Useful test:** reproduce the trial TOU group comparison with appropriate treatment assignment/baseline adjustment, meter coverage and season effects; evaluate distribution of response, not only the average. Separate **observed behavioral adjustment** from **counterfactual tariff re-pricing**. Never interpret a regression coefficient alone as proof of causation.

### 3. 2026: Measuring the in-use thermal performance of dwellings — improving precision by accounting for variability

- **Paper:** [Energy & Buildings/Building Services journal publisher DOI 10.1177/17442591251365953](https://doi.org/10.1177/17442591251365953).
- **Public input:** [SMETER TEST phase 2, 30 homes, UK Data Service 856978](https://reshare.ukdataservice.ac.uk/856978/). Open to anyone without registration, **23 MB archive**, with half-hourly electricity, gas, room temperatures, measured reference HTC, local weather and QA.
- **Method:** 19 eligible homes; repeatedly calculate apparent HTC on overlapping 20-day windows, describe its variability with changing thermal/weather boundary conditions and compare independent aggregate heat-loss test results.
- **Important negative result:** adjusting HTC estimates to extrapolated co-heating test boundary conditions did *not* improve agreement with independent test HTC in the reported experiment. The source reports 12.2% CVRMSE for in-use HTC and 35.5% for the extrapolated adjusted comparison. Do not assume adding more covariates will improve external validity.
- **Reproduction status:** dataset readily retrievable and reference labels included; paper's exact code not verified as downloadable. **Highest priority new independent replication**.
- **Useful test:** estimate HTC from (A) gas + outdoor-only degree days and (B) measured indoor/outdoor difference plus solar/wind, then test against **independent aggregate heat-loss coefficient** with held-out homes, MAE, bias, interval coverage and sensitivity to heating/hot-water separation. Do not fit on reference HTC before an external validity comparison.

### 4. 2026: Residential Energy Dataset with EVs, Photovoltaic Generation and Tariff Variability in Ireland

- **Data descriptor/paper:** [Scientific Data 13, 834 (2026)](https://www.nature.com/articles/s41597-026-07186-3).
- **Open source + dataset:** [Figshare DOI 10.6084/m9.figshare.30294478](https://doi.org/10.6084/m9.figshare.30294478). Authors state they provide raw and processed records plus data-preparation/validation/figure-generation Python scripts in the `/code` directory.
- **Measured content:** four Dingle Peninsula households; half-hourly grid import/export, solar PV and tariff data; EV charge sessions and journey logs; battery and heat-pump streams for a **shorter, partially overlapping window** (roughly mid-2021 to early-2022), not three full years of all channels.
- **Method:** data descriptor including data cleaning, missingness accounting, charger/vehicle energy checks and multi-stream alignment. **Not by itself a claim that a tariff optimiser outperformed another in the field.**
- **Reproduction status:** raw data, authors' processing code and measured positive EV events available; suitable small fully labelled benchmark (only four, non-representative households).
- **Useful test:** compare whole-home meter EV events against charger-labelled sessions; measure false positives versus heat pump, hot water and battery; run actual-vs-forecast EV charging and grid-cost dispatch with charger deadlines and recorded tariffs. Keep interpolation flags and evaluate **raw, non-imputed** periods separately.

### 5. 2022: ELECTRIcity — transformer for non-intrusive load monitoring

- **Paper:** [Sensors 22(8), 2926](https://doi.org/10.3390/s22082926).
- **Public input:** [UK-DALE](https://www.nature.com/articles/sdata20157), [REFIT](https://doi.org/10.15129/31da3ece-f902-4e95-a093-e0a9536983c4), REDD (check redistribution terms).
- **Method:** tests appliance-level load identification across public labelled datasets and multiple train/test home splits.
- **Reproduction status:** public datasets established, but exact training-code reproducibility requires separate code/license review.
- **Useful test:** using the exact same periods and labels, compare event detector performance at 8s/1min/15min/**30min**, measure household-held-out F1, PR-AUC and **false EV-like events per household-month**. These are appliance labels, **not verified resident presence/absence**.

### 6. 2022: An empirical energy demand flexibility metric for residential properties

- **Paper:** [Energies 15(14), 5304](https://doi.org/10.3390/en15145304); [UCL author repository](https://discovery.ucl.ac.uk/id/eprint/10153333/).
- **Method:** infer heating interruption flexibility from measured indoor temperature decay after heating switches off; study reports the metric for 96% of 193 homes, with mean temperature reduction of 1.5°C over 3 hours under a standardised 15°C indoor-outdoor differential.
- **Data limitation:** the **paper is open access**, but the *exact 193-home source records* have **not been independently verified as unrestricted downloadable research data**. Do not list as one-click reproduction.
- **Useful test:** compare cooling curves/temperature decay and comfort feasibility in openly available IDEAL/SMETER cohorts; treat matching the headline paper number as an external benchmark only where metadata and conditions are comparable.

## Further useful reference works

- **2023 UK empirical dataset inventory:** [The Use of Real Energy Consumption Data in Characterising Residential Energy Demand with an Inventory of UK Datasets](https://doi.org/10.3390/en16166069). Excellent survey to systematically discover new open data. An inventory is not a model-validation experiment.
- **2021 IDEAL data paper:** [The IDEAL Household Energy Dataset](https://doi.org/10.1038/s41597-021-00921-y), sensor documentation for 255 UK homes and actual electric/gas and room/boiler temperatures. Some source files large, missing channels vary, **room temperature is not logged thermostat setpoint**.
- **2017 REFIT data paper:** [An electrical load measurements dataset of United Kingdom households from a two-year longitudinal study](https://doi.org/10.1038/sdata.2016.122), with 20-home labelled 8-second appliance data.
- **2026 SERL electricity/gas archetypes:** [Residential electricity and gas demand in Great Britain](https://doi.org/10.1016/j.erss.2026.104808) uses contemporary SMART Energy Research Lab microdata for over 10k electricity homes and 8k gas homes after filtering. **Published article does not imply unrestricted public household-level data**. Use aggregate findings as an external reference until research access is approved.
- **Original SMETER government evaluation:** [DESNZ/BEIS evaluation](https://www.gov.uk/government/publications/smart-meter-enabled-thermal-efficiency-ratings-smeter-technologies-project-technical-evaluation), method and performance interpretation supporting independent HTC checks.

## Suggested sequence for the repo

**Phase 1 (practical this week if work is run locally):**

1. Fetch the 23MB official SMETER archive, verify archive hash and file dictionary, produce a **QA-preserving** 30-home panel. Reproduce the reported 19-home eligible set with a clear selection flowchart, *then* run blind reference-HTC comparison.
2. Fetch Figshare Irish data and scripts, audit per-channel availability and missingness, run **simple zero/plateau and labelled EV-charge detection** at 30min; compare against sessions and heat-pump/battery records.
3. Re-run the repository's LCL demand forecast and tariff comparison on the **identical LCL subset** used in published 2026 work if recoverable, with retrospective tariff replay and actual tariff trial outcomes reported separately.
4. Downsample REFIT/UK-DALE while preserving energy and gaps; demonstrate the inevitable ambiguity between equipment signals at half-hour resolution.

**Phase 2:** implement and validate thermostat alternatives only after collecting independent measured indoor temperature, heat-input and outdoor weather. Evaluate held-out one-hour/six-hour temperature error before quoting counterfactual cost or comfort. Use real supplier prices only for times/regions they apply. Default to an honest time-of-decision forecast and place perfect foresight in an explicitly marked oracle benchmark.

## Scientific/ethical safeguards

- A study **about** publicly available datasets may include a second dataset with separate access restrictions (Pecan Street, SERL).
- Time-varying indoor temperature + heat delivery enables thermal inference but **does not prove actual thermostat setpoints**.
- No reliable comparison of alternate heating strategies can be made from a single observed thermostat policy without assumptions, controlled interventions or external controls.
- Do not infer resident holiday status as ground truth from absence of appliance usage.
- Do not redistribute raw meters with addresses, identity mappings, EV journeys or occupancy diaries beyond source terms; keep individual household processing local.
- Pin raw downloads by SHA-256 and scripts by commit. Keep vendor/author claims distinct from reproduced independent measurements.

