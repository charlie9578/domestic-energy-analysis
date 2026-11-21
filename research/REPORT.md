# Domestic energy and heating: evidence review and reproducible baseline

**Research dated 21 November 2026.** Initial scope **Great Britain**; the primary official household benchmark specifically covers **England and Wales**. These are separate forms of evidence:

- **Published measured household statistics** — DESNZ's 2026 NEED report, consumption year 2024.
- **Published actual tariff averages** — Ofgem's quarterly October–December 2026 regional-average Direct Debit rates.
- **Public time-series sources** — HeatpumpMonitor's daily monitored heat-pump observations; Octopus historical rates are accessible with the included adapters. No live source data has been fetched into the versioned repository.
- **Worked numerical modelling** — explicitly hypothetical boiler efficiency, heating share and seasonal COP using DESNZ-like input consumption; **not** a causal field trial or a forecast.

## Executive findings

1. **Gas remains substantially larger than grid-electricity input in gas-connected UK dwellings.** DESNZ NEED's 2024 E&W meter-matched *median* domestic gas was **10,000 kWh/year** (lower/upper quartile **6,500/14,400**); electricity median **2,500 kWh/year** (quartiles **1,600/4,100**). The corresponding means were **11,200 and 3,300 kWh**. Sample counts differ: **18.9 million gas-matched** vs **23.5 million electricity-matched** properties; these figures do not describe a paired median property. [DESNZ NEED 2026](https://www.gov.uk/government/statistics/national-energy-efficiency-data-framework-need-report-summary-of-analysis-2026/national-energy-efficiency-data-framework-need-report-summary-of-analysis-2026-accessible-webpage)
2. **The electricity-to-gas unit-price ratio determines a simple heat-pump break-even point, given system efficiency.** Ofgem's Q4 2026 GB Direct Debit averages are **26.32p/kWh electricity** and **7.97p/kWh gas** with daily standing charges **54.83p** and **29.68p**, respectively. For an 85%-efficient seasonal gas boiler, *variable unit-cost parity* is **SPF ≈ 2.81**. The actual ratio depends on tariff, seasonal heat pump performance, and delivery boundary. [Ofgem Q4 2026](https://www.ofgem.gov.uk/your-energy-supply/your-energy-bill/energy-price-cap-unit-rates-and-standing-charges)
3. **Keeping a live gas connection changes the economics materially.** Avoided gas standing charges cannot be counted if cooking or other use remains on the gas meter. At Ofgem's Q4 2026 regional-average gas standing charge, the annualized value of eliminating the connection would be **£108.33/year** (365 × 29.68p), before any meter closure costs or alternative-fuel provision. This saving **must not** be added to a mixed-gas-use case.
4. **Real heat-pump COP cannot be read from a model's rated SCOP or averaged from daily ratios.** Use metered total useful heat divided by metered total electrical inputs, with comparable SPF boundaries. Monitoring data suggest an efficiency/flow-temperature relationship and significant variation; the [Energy Systems Catapult EoH programme](https://es.catapult.org.uk/report/electrification-of-heat-summary-reports-and-datasets/) and [public HeatpumpMonitor API](https://heatpumpmonitor.org/api-helper) are complementary but have different sampling, instrumentation and populations.
5. **Time-of-use comparisons require matching consumption and actual price at the same UTC timestamp.** Dynamic tariff opportunities depend on the household's load timing, not a simple average day/night unit price. The project's synthetic one-day example uses **12.48 kWh** with a max **0.96 kW half-hourly average**, and produces **£3.83** under a 26.32p flat rate vs **£3.36** under invented TOU rates, including the same day's standing charge. This is a **test illustration, not a measured saving or real TOU offer**.
6. **Older public smart-meter panels are useful but cannot alone tell us current heat-pump load effects.** Low Carbon London sampled 5,567 London homes in 2011–2014; the IDEAL project measured both gas and electricity in 255 Scottish-area homes during 2016–2018. The former is useful for load-profile methodology, the latter for gas/thermal inference, but both predate the present tariff market and much heat-pump uptake. [London Datastore](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d), [IDEAL dataset](https://datashare.ed.ac.uk/items/15e82917-56ed-4282-99ef-7f211bf87f9d)

## 1. Worked boiler-to-heat-pump energy balance

**Constructed example**, not an observed combined household: annual gas input 10,000 kWh; assumed heating/hot-water fraction 85%; boiler seasonal efficiency 85%; baseline non-heating electricity 2,500 kWh; heat-pump system SPF 3.0; gas connection kept; annual standing-charge exposure 365 days; Ofgem Q4 2026 prices held fixed for 365 days solely to compare cases.

| Accounting step | Formula | Result |
| --- | --- | ---: |
| Old gas for useful heating | `10,000 × 0.85` | **8,500 kWh gas** |
| Useful annual heat | `8,500 × 0.85` | **7,225 kWh heat** |
| New heat-pump electrical input | `7,225 / 3.0` | **2,408.3 kWh electric** |
| Remaining gas for non-heating uses | `10,000 × 0.15` | **1,500 kWh gas** |
| Grid electricity before / after | `2,500` / `2,500+2,408.3` | **2,500 / 4,908.3 kWh** |
| Baseline annualized bill | All two-fuel unit costs + 365 days both standing charges | **£1,763.46** |
| Heat-pump annualized bill | Residual gas + all grid electric + both standing charges | **£1,719.88** |
| Operating saving | Before minus after | **£43.58/year** |

The £43.58 is a *small* saving in this particular scenario, with no capital expenditure allowed for. A different actual tariff, SPF, heating fraction, boiler efficiency or household demand can reverse the direction. No carbon claim is attached to these figures.

### SPF × electricity-price sensitivity

Gas 7.97p/kWh, 8,500 kWh of gas displaced, 85% boiler efficiency, gas supply retained and other assumptions above. The electricity rates **16p and 35p are hypothetical**, not observed tariff offers:

| Electricity unit rate | SPF 2.5 | SPF 3.0 | SPF 4.0 |
| --- | ---: | ---: | ---: |
| **16p/kWh (hypothetical)** | £215.05 saved | £292.12 saved | £388.45 saved |
| **26.32p/kWh (Ofgem Q4 average)** | **£83.20 extra cost** | **£43.58 saved** | **£202.05 saved** |
| **35p/kWh (hypothetical)** | £334.05 extra cost | £165.47 extra cost | £45.26 saved |

Full 36-case CSV and the transparent computation are generated with `python -m domestic_energy demo --out-dir reports/demo`.

The **SPF needed for unit-cost parity** is `boiler_efficiency × electricity_unit_rate ÷ gas_unit_rate`, i.e. `0.85 × 26.32 ÷ 7.97 = 2.807`. This parity excludes upfront installation, gas supply disconnection, grant eligibility, repairs, network upgrades and time-of-use consumption shifting. A retrospective bill comparison needs the exact real-world time intervals and fuel account histories, not one quarter's typical rates repeated over a year.

## 2. What the heat-pump evidence can and cannot tell us

**Direct instrumentation**: HeatpumpMonitor publishes a list of opt-in public systems, per-system daily data, measured heat/electricity, indoor/flow/outdoor temperatures and operational metadata. [API endpoints](https://heatpumpmonitor.org/api-helper) include `/system/stats/daily?id=...` CSV. The adapter downloads selected IDs on request and excludes low-quality/short-coverage days; it computes the combined observed energy ratio, not a certification-standard full-season performance factor. Different systems have different meter boundaries, hot-water tanks, pump and immersion measurements, occupants and equipment, and system-ID selection is nonrandom.

**Broader field project**: DESNZ-funded Energy Systems Catapult EoH monitoring collected data during 2020–2023; summary reports and cleansed 30-minute/daily data are available through the UK Data Service (some full downloads require access arrangements). The EoH [published analysis code](https://github.com/ES-Catapult/electrification_of_heat) states its energy traces are **cumulative**, so naïve addition of consecutive readings would catastrophically overstate consumption. For cross-study SPF comparisons, first match monitoring boundaries (SPFH2/H3/H4), observation duration, weather, flow temperature, property class and quality filters. [EoH data & reports](https://es.catapult.org.uk/report/electrification-of-heat-summary-reports-and-datasets/)

**Testable hypotheses** for an actual study: (a) lower heating-flow temperatures correlate with better efficiency after controlling for external temperature; (b) hot-water cycles can depress observed combined SPF relative to space-only performance; (c) building envelope and controls change both delivered heat requirements and performance; (d) afternoon/evening peak heat demand is not necessarily price-optimal and flexibility benefits depend on comfort constraints. These are *research hypotheses*, not causal findings from this repository.

## 3. Smart meters, price curves and peak loads

The project's CSV contract is **one row per physical interval**, with ISO8601 **offset-aware `start_utc`** and kWh imported during that interval. Convert kWh to interval-average kW by dividing by the interval hours. Output **peak** and **95th percentile** of interval-average power, UTC-duration completeness, mean load and the typical London-time interval consumption by hour. An absent reading is not equivalent to zero import, and solar PV/battery means grid import can be much lower than household electrical demand.

For time-of-use tariffs, match `meter.start_utc` to the **published rate** for that precise UTC slot. We supply a public Octopus tariff rate downloader, but deliberately do not fetch customer meter consumption (private endpoints require a key). Different GB regions and product versions have different codes, and the example rate file is invented. A full bill needs import/export direction, VAT, standing charges for the actual billing period, supplier-specific adjustments, potentially load shifting and complete time coverage.

**DST**: the clock repeats an hour on autumn's return to GMT and skips one on spring's change. Physical UTC slots do not repeat. Any processing that joins `02:00 local` labels alone can double-count or discard consumption, changing cost and COP time alignment. Unit tests include an autumn transition.

## 4. Evidence gaps and strongest next studies

| Priority | Study | Why it matters | Work required |
| --- | --- | --- | --- |
| **P0** | Quantify public heat-pump cohort SPF, cold-day consumption and bins | Measured performance can differ by weather and hydraulic design | Download 20+ diverse public systems, metadata, quality logs; select consistent boundaries and 365-day windows; publish exclusions and uncertainty |
| **P0** | EoH annual SPF distribution and flow-temperature sensitivity | Independent, more structured sample for triangulation | Acquire cleaned summary/interval tables from UKDS and replicate ES Catapult quality rules |
| **P1** | Calibrate model against **IDEAL** gas+electric+temperature | Test how much metered gas is heating vs base loads | Access panel, align gas meter to kWh, fit temperature-linked baseline, consider hot water/cooking and seasonal gaps |
| **P1** | Run genuine historic Octopus rate replay on LCL/synthetic-like and matched modern households | Quantify demand-timing value under realistic tariffs | Pick region/product/date and *contemporaneous* actual usage; do not apply a 2026 price history to 2012 data as an actual cost |
| **P1** | Weather-normalized fuel/heat demand regressions by property | Separate insulation from winter weather and occupancy | Join legitimate degree-day weather station/geography and evaluate with held-out periods |
| **P2** | Compare carbon and peak-grid effects | Carbon case may differ from money savings | Pair load and emissions factor per half hour, distinguish average vs marginal emissions and system boundary |
| **P2** | 2026 supply/grant economics | Upfront grants and maintenance may dominate financial payback | Link BUS and installation cost distribution with quotes and eligibility; avoid unsupported universal payback |

## Conclusions

The public UK data ecosystem is useful for a strong, reproducible study, but a *credible* heating conclusion depends on **meter boundaries, cohort selection, timestamp fidelity and fuel-price assumptions**. At current Q4-2026 averaged rates, a high-performing heat pump can reduce variable costs versus an 85%-efficient gas boiler, while a lower-performing heat pump may not. The result is highly specific to heating demand, electricity tariff and whether gas standing charges remain. The repository now operationalizes these questions and makes missing data, scenario assumptions and synthetic examples explicit rather than hiding uncertainty.

See [SOURCES.md](SOURCES.md) for primary data/source links and [METHODOLOGY.md](METHODOLOGY.md) for mathematical definitions and limitations.
