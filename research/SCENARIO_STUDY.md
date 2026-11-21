# Reproducible full-year domestic energy scenario study

**Executed 21 November 2026. Dataset: ALL SYNTHETIC. These are software/regression experiments, NOT forecasts for a real household and NOT a supplier's tariffs.** Rerun locally:

```bash
python -m unittest discover -s tests -v
python scripts/run_study.py --out reports/synthetic_study
```

The script deterministically regenerates 2025, 17,520 UTC half-hour intervals for **four invented household archetypes** and evaluates **11 technology setups on two example tariffs = 88 full-year cases**. Full source truth (known HLC, labelled work-from-home, holiday periods, EV charge events, synthetic solar generation) and scenario tables are saved under ignored `reports/synthetic_study/`. Code has no API calls or dependencies beyond Python's standard library.

## A. Assumptions and design

| Factor | Constructed synthetic input | Caveat |
| --- | --- | --- |
| Geography/weather | Illustrative **London** outdoor daily temperature curve with deterministic jitter; alternative code inputs Glasgow (-2.5°C) and Plymouth (+1.5°C) | These are not measured 2025 temperatures or validated city climate normal values |
| Older detached | 260 W/K assumed heat-loss coefficient | Arbitrary example, not a DESNZ class median |
| Older semi | 210 W/K | Arbitrary example |
| Mid terrace | 160 W/K | Arbitrary example |
| Efficient flat | 80 W/K | Arbitrary example |
| Heating | Outdoor-temperature balance 16°C, 24h heat demand at constant heat-loss coefficient; 85% gas boiler, variable occupied-day profile | Ignores solar/occupant gains, emitter limits, indoor thermostat details, hot-water priority |
| WFH/holidays | Known declared Monday/Wednesday/Friday WFH; 17 summer holiday days with lower electricity and heating setback | Known from generator; algorithm should NOT assume these labels in real data |
| EV | Known 7 kW charging for 2 hours after 01:00 on selected days; ~2,086 kWh/year grid draw | Illustrative charging calendar with ~149 sessions |
| PV | Illustrative 4 kWp panel output of ~3,742 kWh/year before curtailment, rounded on each slot | **Not PVGIS-derived**, no roof/shading/seasonal temperature modelling |
| Gas standing/disconnection | Residual gas hot water assumed to require 0.85 kWh electricity per kWh gas if disconnected | Explicit *modelling choice*; changes hot water and cooktop equipment need capex |
| Battery | 5 kWh, 3 kW, 90% electrical round-trip efficiency, 0→0 kWh across year | Perfect future price/load/PV foresight; no aging/standby |
| Night-storage heater | 12 kWh thermal store, 7 kW charging limit, 95% charge conversion, 1%/h heat-loss outside space | Simplified thermal store and perfect foresight; no heat comfort model |
| Tariff A | Ofgem **October–December 2026** GB Direct Debit average electricity/gas/standing rates held through an artificial full 2025 year; synthetic fixed 5p/kWh export | Not an actual 2025/annual contract and exports not Ofgem-provided |
| Tariff B | Entirely **hypothetical** 10p/kWh 00:00–06:00, 31p/kWh daytime, 41p/kWh 16:00–19:00; identical standing/gas and hypothetical 5p export | Not a real tariff offer; change parameters to actual tariff-region rate histories |

## B. Main outcomes — mid-terrace synthetic household

| Portfolio | Yearly cost, illustrative flat £ | Yearly cost, hypothetical TOU £ | Key observation |
| --- | ---: | ---: | --- |
| Existing gas boiler, no PV | 2,329.65 | 2,043.27 | EV charging makes TOU cheaper |
| Add solar PV | 1,916.88 | 1,596.48 | Solar savings depend on daytime load, export credit and import tariff |
| 20% lower space-heat demand (insulation scenario) | 2,178.36 | 1,891.98 | Saves ~£151 on unchanged gas prices; not 20% off entire bill |
| Heat pump at SPF **2.4**, disconnect gas and replace other gas uses | 2,502.90 | 2,352.09 | Costs **MORE** here than existing boiler at this SPF |
| Heat pump at SPF **3.4**, disconnect gas and replace other gas uses | 2,242.69 | 2,053.81 | Saves £87 on flat; slightly **costlier** than existing gas on hypothetical TOU, due daytime electricity premium |
| Solar + heat pump SPF 3.4 | 1,646.65 | 1,392.63 | Combined effects differ from adding stand-alone savings |
| Direct resistance electric space heating | 3,741.50 | 3,771.88 | Very costly in this gas-heated building under these prices |
| Direct-electric + 12 kWh thermal store | 3,853.25 | 3,300.61 | Store has losses on flat tariff; shifts heat to cheap hours on TOU |
| Solar + 5 kWh electrical battery, retain gas | 1,785.67 | 1,573.85 | Battery's incremental annual benefit is context-dependent and optimistic |
| Solar + insulation + HP SPF 3.4 + 5 kWh battery | 1,374.73 | 1,025.32 | Lowest simulated bill among specified portfolios; **NOT** lowest lifetime ownership cost without capex |

The 5 kWh battery's incremental annual saving **on top of PV** is £131.21 on Tariff A but only £22.63 on Tariff B in this synthetic house. That does **not** prove batteries are unhelpful in the real world: it illustrates how load timing, the price spread and solar generation interact. It also does **not** include the new inverter and battery installation cost.

On a deliberately hypothetical **£6,500 solar installation cost**, with constant real savings of £412.77/year, 20 years, 3.5% discount and zero assumed maintenance/degradation, simple payback is **15.75 years**, while discounted NPV is **-£633.55**. Change the capex/maintenance/export rate and the conclusion changes. These capital costs are **inputs, not actual quotes**; a negative NPV in this toy case is not a judgment on real solar installations.

## C. Best-tariff reversal when an EV is present

For the same simulated mid-terrace building, weather and ordinary loads:

- **With EV:** tariff A £2,329.65, tariff B £2,043.27 — B cheaper by **£286.38/year**.
- **Without EV:** tariff A £1,780.61, tariff B £1,834.67 — A cheaper by **£54.06/year**.

The switch is entirely due to added EV charging after 01:00, in a period the *invented* TOU tariff discounts. A different EV charging clock, daytime WFH electric demand, heat pump and actual regional rates can reverse the order again. The real best offer requires verified, accessible regional tariffs, eligibility and price validity dates, not just published rate cap averages.

## D. Heating efficiency, solar/battery, and insulation tradeoffs

The same parameter sweep has these flat-reference *annual bill* changes from baseline:

| Synthetic building | Existing £ | 20% heating reduction saving £ | HP SPF 3.4 + all-gas replacement saving £ | PV 4 kWp saving £ |
| --- | ---: | ---: | ---: | ---: |
| Efficient flat | 1,829.32 | 75.64 | 20.99 | 375.95 |
| Mid terrace | 2,329.65 | 151.29 | 86.96 | 412.77 |
| Older semi | 2,627.08 | 198.57 | 128.19 | 430.46 |
| Older detached | 2,904.16 | 245.84 | 169.41 | 441.96 |

These input archetypes deliberately have different assumed HLC; greater space-heat demand therefore mechanically raises the savings from a **20% heat-demand reduction**. This is *not* empirical evidence that particular house types achieve 20% savings from a particular insulation measure. Savings do not include boiler replacement, gas disconnection, heat emitters, financing, roof constraints or grants.

## E. Detectability under perfectly labelled synthetic readings

On the synthetic mid-terrace example, 17 declared holiday days appear as two **unverified lower-electricity-activity spells**; the EV-like plateau detector flags 149 candidate high-load sessions. The generator provides the true EV and holiday labels, so these outcomes are only a **smoke test** under unusually clear signals, **not** a held-out field accuracy estimate. Whole-home half-hourly import profiles with PV, hot-water immersion, heat pumps or missing readings will produce false positives and missed events. For a real field study, run on consented recordings with independently verified labels and publish precision, recall, ambiguity and false-alert costs.

The daily weather-response model (held-out 2025 final 73 days) recovers **159.7 W/K** against the synthetic generator's 160 W/K input, with held-out MAE ~0.03 kWh/day, after adding an interaction for declared holiday heating setback. The striking closeness results from the deliberately simple deterministic generator; real data have noise, non-stationarity, control dynamics, solar gains and missing or biased boiler efficiency. **Never extrapolate the 0.03 kWh error to an actual home.**

## F. Next experiments using PUBLIC real data

- **Weather:** fetch Open-Meteo ERA5 local daily weather for many coordinates and years; join observed meter data on 23/25-hour local days, and compute weather-normalized per-household expectations without leaking weather from the holdout.
- **Building types:** download NEED anonymised annual microdata and floor-area consumption tables, with source licence review. Stratify by floor area, building age, detached/terraced/flat, EPC and installation year; correct for geography and matched-meter selection before ranking heat-loss likelihood.
- **Hourly roofs:** ingest validated PVGIS v6 hourly generation for multiple tilt/aspect/horizon/shading setups (the API changed in July 2026), and test PV+heat pump time-of-use interactions on geographically matched load profiles.
- **Observed heat pumps:** use EoH and HeatpumpMonitor with metering-boundary alignment, frost/defrost and hot-water separation; compare COP-vs-outdoor-temperature by system rather than assuming a fixed SPF.
- **Meter signatures:** use consented/submetered EV, immersion, heating and battery ground truth from labelled studies such as REFIT/UK-DALE, degrade to 30-min windows and report confusion matrices and uncertainty, including solar masking and holidays.
- **Dispatch:** test time-ordered model-predictive control with imperfect weather/tariff forecasts, explicit cycle cost, finite-horizon controls, economy-7 switching and thermal comfort bounds to replace optimistic perfect-foresight bounds.

**No current source data are bundled.** Source references/rights and missing measurement categories are listed in [SOURCES.md](SOURCES.md). All scenario code and reproducible outputs are generated from [scripts/run_study.py](../scripts/run_study.py).
