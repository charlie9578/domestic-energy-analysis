# Existing domestic-energy dashboards, products and open-source tools

**Landscape reviewed:** 22 November 2026. Scope: UK-first, relevant international open-source and monitoring work included. Companion [57-entry CSV catalogue](EXISTING_PRODUCTS_CATALOG.csv), [related academic work](RELATED_WORK.md), and [replication plan](PRIOR_ART_REPLICATION_PLAN.md).

## How to interpret the list

- **Public dashboard** = can view aggregate, experimental or contributed data without entering a household account. This does **not** mean the plotted raw household measurements are downloadable or legally redistributable.
- **Customer dashboard** = an actual household's energy data, accessible only with their login/consent. Do not treat it as an open dataset.
- **Commercial product** = a marketed feature or vendor claim; this review **does not independently validate claimed bill savings, COP gains, equipment compatibility or current price**.
- **Open-source controller** = inspectable code, not proof that real households achieved savings. Compare forecast assumptions, physical constraints and commissioning requirements.
- **Access details and pricing change**. URLs and feature descriptions were reviewed as of 2026-11-22; the catalogue intentionally avoids invented subscription fees or unsupported savings percentages. An API being documented does not guarantee anonymous usage, a free developer plan or unlimited extraction.

## Public dashboards worth examining

| Dashboard | What you can actually see | Data available to our project? | Best lesson |
|---|---|---|---|
| [HeatpumpMonitor](https://heatpumpmonitor.org/) | individual contributed heat pump monitoring, COP/SPF, time plots, optional indoor/outdoor channels | Public APIs for qualifying systems, check channel and participant permissions | energy/heat-flow metering boundary, real heat-pump COP, explainability |
| [Electrification of Heat monitoring](https://eoh.heatpumpmonitor.org/) | archived UK heat pump pilot field monitoring where available | separate data releases, access rules and quality assessment | compare whole fleet without only self-selected hobbyist systems |
| [Octopus Cosy fleet performance](https://octopus.energy/cosy-heat-pump-performance/) | supplier-reported installed-system performance and illustrative running cost | displayed aggregate ≠ open system-by-system raw measurements | presentation of heat-pump field performance, metering definitions, comparison sensitivity |
| [Emoncms MyHeatpump](https://openenergymonitor.org/docs/emoncms/apps.html) | system-owner heat/power/temperature diagrams; some owners choose to share | open code; household streams require owner sharing | instrumented system UX and time-series semantics |
| [Emoncms MyElectric](https://openenergymonitor.org/docs/emoncms/apps.html) | grid, solar, batteries and site energy-flow displays | open code; no global open collection of household feeds | correct separation of import/export/gross house load |
| [Energy Stats UK](https://energy-stats.uk/) | public GB-area Octopus tariff graphs | public supplier rate API with historic validity spans | dynamic tariff comparison, regional/DST-aware charts |
| [Agile Rates](https://www.agile-rates.uk/) / [Agile Dashboard](https://www.agiledashboard.co.uk/) | public half-hour Agile price plots | public tariff rates only, **not private meter readings** | understandable price graphs, negative-rate presentation |
| [UK Grid Live](https://www.ukgridlive.co.uk/), [Energy Dashboard UK](https://www.energydashboard.co.uk/data) | live power mix, carbon, demand and energy systems | grid-level public feeds, not household consumption | carbon-price system context |
| [NESO carbon dashboard](https://dashboard.neso.energy/) and [Carbon Intensity](https://www.carbonintensity.org.uk/) | regional carbon intensity forecasts and historical estimates | official/associated APIs with version and terms checks | carbon-aware demand shifting distinct from cheapest £ |
| [Electricity Maps](https://app.electricitymaps.com/map) | international generation/consumption carbon mix | map public; API history may need commercial licence | location-aware emissions view and uncertainty |
| [EPC dashboard](https://www.gov.uk/government/statistics/energy-performance-of-buildings-certificates-data-dashboard) and [Welsh EPC dashboard](https://www.gov.wales/analysis-home-energy-performance-certificate-epc-data-interactive-dashboard) | rating distributions by geography/property type | official downloadable certificates/statistics; licensing varies | prior building-stock benchmark, **not** measured thermal loss |
| [DESNZ subnational maps](https://www.gov.uk/government/statistical-data-sets/maps-showing-average-energy-consumption) | local gas/electricity consumption averages | aggregated statistics | contextual priors and comparators, never person-level classification |
| [JRC PVGIS](https://re.jrc.ec.europa.eu/pvg_tools/en/) | solar site yield/irradiance and PV system scenarios | documented European Commission solar data API | PV expected generation, orientation/region input |

These dashboards provide at least **three distinct reference layers** for our future frontend: a) *real measured household/system profile*, b) *public regional energy/price/weather context*, and c) *engineering/simulated technology outcome*. Mixing them into one undifferentiated chart would undermine credibility.

## Consumer and commercial solutions

### Smart-meter monitoring and personalised tariffs

| Offering | Stated capabilities | What we should check |
|---|---|---|
| [Bright / Glowmarkt](https://glowmarkt.com/bright) | consented UK smart meter gas/electricity use; Glow API; optional live Consumer Access Device | actual accessible API permissions, freshness, 30-min timestamps, export, GDPR |
| [Loop](https://loop.homes/) | connected smart-meter consumption, carbon and household-use insights | onboarding, meter latency, per-end-use claims and tariff accuracy |
| [ivie](https://ivie.co.uk/ivie-app/) | consumption charts and estimated usage breakdowns | what is modelled vs directly submetered, appliance ground-truth validation |
| [Uswitch Utrack](https://www.uswitch.com/utrack/) | smart-meter app, inferred appliance tracker and savings insights | confidence and error bars for inferred appliance classes |
| [Octopus Energy app](https://octopus.energy/blog/track-my-energy-use/) | native bills, smart consumption and supported smart tariffs | reliable direct meter/tariff sync and billing explanations |
| [Octopus Compare](https://octopus.compare/) | same observed consumption repriced under multiple tariffs, load shifting | forecast for adapted demand distinct from historic reprice |
| [Octopus Watch](https://octopus.smarthound.uk/docs/020-compare/) | smart-rate history and consumer usage/tariff comparisons | dynamic product logic, user data handling |
| [EnerLy](https://enerly.co.uk/compare.html) / [Wattly](https://wattly.uk/compare.php) | independent Octopus connected comparisons | whether standing charges, export, missing data and timing match our engine |

**Noteworthy competitor baseline:** a household does not need an AI model to compare tariffs using **unchanged** real smart-meter consumption; several tools already do this. Differentiation requires modelling *new controllable assets* and *behaviour change* with measured, independently tested constraints.

### Heating control, heat pumps and thermal storage

| Product | Stated scope | Important verification question |
|---|---|---|
| [Homely](https://www.homelyenergy.com/pricing-tariffs/) | learning heat-pump control using indoor thermal response, forecast weather and prices | comfort guarantees, telemetry boundaries, subscription/hardware terms and independently measured realised savings |
| [Havenwise](https://www.havenwise.co.uk/) | heat pump scheduling based on dynamic price, weather and comfort | controls available for actual pump brands, hot water, backup resistance and cold snap response |
| [Passiv Smart Thermostat](https://www.passivuk.com/passiv-smart-thermostat/) | self-learning heat-pump/room and water heating control | plant compatibility, room-sensor position, telemetry export and independent evaluations |
| [tado° Heat Pump Optimizer / Balance](https://www.tado.com/en-gb/products/heat-pumps) | smart heat-pump control with optional price-based optimisation | subscription/service scope, equipment brands and flow-temp/COP effects |
| [Octopus Cosy](https://octopus.energy/heat-pump-help/cosy/) | integrated equipment, heating schedule and specialist electricity tariffs | bundled supplier incentives versus independently usable controller |
| [Mixergy](https://www.mixergy.co.uk/solutions/apps-and-dashboards/) | hot water cylinder thermal storage and demand learning | hot-water storage is not space-heating storage; measure reheat losses and hot water comfort |

**Comparison is inherently physical:** a timed resistive storage heater, an oversized radiator on a gas boiler, an air-source heat pump with weather compensation, and a cylinder of hot water all have radically different efficiency, thermal storage and comfort behaviour. A generic "overnight cheap heating" checkbox cannot cover these honestly.

### EV, batteries and solar

| Product | Stated scope | Research question |
|---|---|---|
| [ev.energy](https://www.ev.energy/en-gb/drivers/smart-charging) | smart EV charging with departure deadline and tariff integration | what charging remains feasible under charger availability and uncertainty? |
| [Ohme](https://ohme-ev.com/support/explore-charging/) | ready-by charge planning and price conditions | time-varying import cap and real charger power |
| [myenergi](https://www.myenergi.com/the-app/) | zappi EV, eddi hot water/solar diverter, libbi battery | combined device energy accounting and avoiding double-counted PV |
| [GivEnergy](https://givenergy.com/resource-hub/customer-guides/givenergy-portal-guide/) | installed battery, PV and smart-tariff automation | real round-trip losses, backup reserve, forecast errors |
| [Tesla Powerwall](https://www.tesla.com/en_gb/support/energy/powerwall/mobile-app/energy-data) | battery and solar monitoring, time-based dispatch | measured vs planned battery state, export and self-consumption |
| [SolarEdge ONE](https://www.solaredge.com/) | vendor-optimised PV/EV/storage workflows | what data and control are accessible outside SolarEdge ecosystem? |

### Retrofit planning and finance

| Service | Stated proposition | Research question |
|---|---|---|
| [Snugg](https://which.snugg.com/) | homeowner retrofit pathway, cost and property improvement scenarios | how close are savings priors to weather-normalised household data? |
| [Furbnow](https://furbnow.com/home-energy-survey) | survey-based retrofit plans and installer guidance | independent heat-loss survey vs simulated model gap |
| [PropEco](https://www.propeco.io/data) | UK property-level environmental and retrofit estimates/API | can we improve beyond bulk EPC/stock archetypes with actual bills and indoor temps? |
| [Heat Geek](https://www.heatgeek.com/articles/the-secret-to-high-heat-pump-efficiencies) | heat pump installation quality, design/performance and consumer education | commissioning/flow temps/emitter sizing as major hidden heterogeneity |
| [Energy Saving Trust](https://energysavingtrust.org.uk/) | trusted household retrofit and heating advice | use as a conservative explanation/check, not as proof of custom ROI |

Provider scope, installation costs, savings estimates and plans may differ today; none of the above is an endorsement or validated pricing comparison. For products with no public hardware-neutral data API, mark *access unknown* rather than implying it can be scraped.

## Open-source products: build versus compare

| Codebase | Capabilities to benchmark | Caveat |
|---|---|---|
| [EMHASS](https://emhass.readthedocs.io/en/latest/) | LP/MPC home tariff + batteries + PV + thermal/flexible assets | model correctness != measured savings; deployment depends on solver and sensors |
| [Predbat](https://github.com/springfall2008/batpred) | predictive battery import/export scheduling and tariff counterfactuals | oracle vs forecast, reserve SoC and battery life |
| [Heat Pump Cost Optimizer](https://github.com/tvofi/heatpump_optimizer) | two-zone predictive heat pump and hot water control | compatibility and occupant comfort measurement |
| [Home Assistant Energy](https://www.home-assistant.io/docs/energy/) | energy dashboard and broad meter/device integrations | user configuration determines completeness, not a national data repository |
| [FlexMeasures](https://github.com/FlexMeasures/flexmeasures) | scheduling framework for flexible assets and timeseries | broader platform, not out-of-box household retrofit science |
| [pvlib-python](https://pvlib-python.readthedocs.io/en/stable/) | sunlight/PV yield and equipment equations | needs panel/orientation/shading metadata |

**Best build-vs-buy:** adopt compatible local meter/open-source integrations where justified by licence, but own our **data quality, causal/economics layer, validation and reporting**. Reimplementing a Home Assistant dashboard or basic battery optimiser is lower value than investigating insulation inference and half-hourly NILM with actual reference labels.

## Product capability assessment: proposed scorecard

**Do not manufacture 0–10 ratings from homepage claims.** Scores should be completed only after real account/demo walkthroughs, independent papers or technical code review. Record *Unknown* where there is no evidence.

- Access: anonymous public; freely downloadable raw data; user-consented meter; paid account; hardware lock-in; enterprise.
- Source provenance: measured or imputed or inferred or modelled, channel units, meter boundary, sampling interval, time zone, latency and coverage.
- Forecasts: trained on which homes? cold-start performance? held-out MAE/calibration? weather input? does it avoid future-information leakage?
- Tariff: exact region, date, gas and electricity standing, import/export, negative prices, taxes, smart switching and demand adaptation.
- Heating: setpoint logs vs room temperature; thermal modelling; hot water; weather compensation; flow temperature and auxiliary heater; comfort limits.
- Detection: labelled EV/HP/heater/solar ground truth, false positives per home-month at 30 min, abstain option, privacy implications.
- PV/battery: PV generation vs net imports; state of charge, charge power, degradation, inverter constraints, export opportunity cost.
- Economics: gross capital vs grants, fixed ongoing fees, maintenance, replacement and confidence bands; sensitivity to rates and performance.
- Interoperability: API, CSV, MQTT, Home Assistant, Octopus, Glow, supplier limitations, ability to export **everything**.
- Evidential credibility: independent measured field trial > author-reproduced case study > calibrated simulation > undocumented supplier marketing.

## What could make this repository distinct?

1. **Transparent data ladder:** every number marked *observed*, *imputed*, *forecast*, *classified candidate* or *counterfactual*, with downloadable provenance.
2. **Open, supplier-independent smart meter import** (when homeowner consent and licensing permit) and meter-aware holiday/EV-like *anomaly suggestions* rather than false certainty.
3. **Blind benchmark against SMETER HTC** and real indoor temperature, not just EPC or "poor insulation" guesses from gas use.
4. **Comfort-cost Pareto frontier:** show cheap strategies and **how cold they make the home**; not just a single price-optimal day plan.
5. **Realistic controls for heat pumps, storage heaters and hot water** with COP, charging efficiency, thermal mass, emitter and recovery-time constraints.
6. **Best tariff after upgrades** as well as before upgrades; recommend bundles of energy measures, not just single paybacks.
7. **Independent cross-home NILM:** compare to appliance submeters at 30 min, publish negatives and abstentions; avoid "we can tell you're on holiday" claims.
8. **Developer-friendly reproducibility:** scripts that download open raw records under their terms, preserve hashed source and quality metadata, and run identical cost/comfort benchmarks.

## Shortlist for hands-on product reviews

| Priority | Product/service | Replicable investigation |
|---|---|---|
| P0 | HeatpumpMonitor + EoH | independently measured COP, thermal dynamics, human-reviewable performance |
| P0 | Octopus Compare + Energy Stats UK | tariff engine parity for the same known intervals, standing charges and DST |
| P0 | Bright / Glow + Octopus Energy account APIs | reliable, explicitly consented UK half-hour smart-meter ingestion and latency |
| P0 | EMHASS + Predbat | common-fixture scheduling baseline, forecast-only vs oracle |
| P0 | Homely + Havenwise + Passiv | owner/demo comparison of actual thermostat/setpoint data and weather-aware dispatch; seek independent field data |
| P1 | Loop + ivie + Utrack | how appliances and absence are represented, where error/uncertainty is disclosed |
| P1 | Ohme + ev.energy + myenergi | charger deadline, PV diversion, time-of-use adaptation and real sessions |
| P1 | Snugg + Furbnow + PropEco | building information, action costs, quote uncertainty and insulation evidence |
| P1 | tado° + Mixergy + Cosy | thermostat and thermal storage state, demand shifting under comfort constraints |

### Audit process

For each product, record date, plan/region/device eligibility, evidence/screenshots with permission, actual exposed data export and terms, five objectively checkable test cases, and false positives or hidden assumptions. Never connect a real customer account, share occupancy information, or reverse-engineer closed APIs without permission.

**Useful standard test fixtures:** (a) UK October DST fallback with 50 half-hours, (b) full 48-slot winter day and missing meter intervals, (c) negative electricity price and gas standing-charge retention, (d) solar gross demand > import, (e) EV and resistance heater making identical aggregate flat-load events, (f) undersized heat pump unable to recover by 07:00, (g) thermal store with realistic charge/discharge limit. Compare outputs on identical fixtures, not unrelated marketing screenshots.

## Footnotes and further sources

The [57-entry structured catalogue](EXISTING_PRODUCTS_CATALOG.csv) records primary links, access model, stated capabilities, limitations, and why each platform deserves review. Where an item's public website is descriptive but detailed technical documentation was not verified, the entry records **claimed capability**, not an audited feature. Prior academic literature is under [RELATED_WORK.md](RELATED_WORK.md) and [REPRODUCIBLE_PUBLIC_DATA_STUDIES.md](REPRODUCIBLE_PUBLIC_DATA_STUDIES.md).
