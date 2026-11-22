# Hourly heat balance validated on a monitored room

## Measurement boundary

HeatpumpMonitor system 3 supplies hourly-start room and on-site outdoor temperature samples, hourly average signed thermal power from the heat meter and an hourly domestic hot-water mode signal. Manchester-area ERA5 supplies a separate hourly outdoor temperature series using city-centre coordinates. We use measured thermal power directly and retain negative values. The model therefore fits no COP, boiler efficiency, thermostat schedule, occupancy, weather forecast or assumed thermal mass. A room sensor approximates the temperature of one effective zone. The heat-meter boundary may differ from the room boundary. [HeatpumpMonitor API](https://heatpumpmonitor.org/api-helper) · [Hourly ERA5 export](../README.md#hourly-historical-weather)

The experiment spans 8–21 January 2024. We excluded 60 of 336 hours because the hot-water signal was nonzero. The accepted hours have aligned start and end temperatures, both outdoor sources and a valid heat reading. Missing values are excluded. As a timestamp check, the first four hourly heat values matched averages of the thirty 120-second samples beginning at each timestamp to the precision reported. The public hourly averages do not supply a per-feed completeness measure. Mixed-mode hours are excluded in full, so the validation represents uninterrupted eligible windows and omits much of normal operation.

## Model and evaluation

The energy balance is **C dT/dt = Q + G − H(T − T_out)**, with delivered thermal power *Q*, effective heat-loss conductance *H*, effective heat capacity *C* and constant residual net power *G*. For a one-hour interval with constant forcing, the exact update is **T_next = T + a(T_out − T) + bQ + c**, with **a = 1 − exp(−HΔt/C)**, **b = a/H** and **c = bG**. Ordinary least squares fits *a*, *b* and *c* to training hours. A fit with *a* outside (0,1) or nonpositive *b* is inadmissible. The intercept can absorb several omitted effects, including solar gains, ventilation, heat distribution and meter offsets.

We fit on the first eight days and withhold the last six. The 14-day period was already used for the project's descriptive profile and is an availability pilot. The split is chronological within that period. A six-hour run begins at 00:00, 06:00, 12:00 or 18:00 UTC, takes the first measured indoor temperature as its initial state and then advances without further indoor measurements. Each model receives the same realised delivered heat and uses either on-site outdoor temperature or ERA5. Persistence repeats the initial indoor reading. The score is endpoint MAE on shared eligible windows.

| Outdoor input | 1 h model vs persistence MAE (°C) | 6 h model vs persistence MAE (°C) |
| --- | ---: | ---: |
| On-site | 0.1075 vs 0.1074 | 0.2969 vs 0.3466 |
| ERA5 | 0.1084 vs 0.1074 | 0.2969 vs 0.3466 |

The model shows no clear one-hour improvement across 113 eligible windows. The six-hour MAE reduction is about 0.05°C across ten windows drawn from six days. The paired day-block bootstrap intervals for model minus baseline MAE were −0.068 to −0.020°C for the on-site model and −0.074 to −0.002°C for ERA5 at six hours. These intervals describe within-sample day variability. Six days and ten windows offer limited evidence of performance in other conditions.

Training day-block resamples give on-site effective conductance **194 W/K (41–348 W/K)** and effective capacity **57.6 kWh/K (43.9–94.2 kWh/K)**. For ERA5 the conductance estimate is **235 W/K (102–402 W/K)**. These are model-dependent estimates. Thermal capacity and residual gain are weakly constrained by this experiment. We sampled 1,000 whole UTC days with replacement in each partition, using seed 26 and percentile intervals. Parameter intervals use admissible fits and are displayed only if at least 95% of resamples pass the stability check. See the [aggregate results](HOURLY_HEAT_BALANCE.json) for all diagnostics and input hashes.

The model is conditional on realised heat input. Predicting setbacks, preheating or savings would also require an equipment and controller model tested on observed changes in operation. The older synthetic scenario rankings remain examples of how the simulator behaves under specified inputs.

## Reproduce

```bash
python -m scripts.fetch_monitored_home
python -m scripts.validate_hourly_heat_balance --download
python -m unittest discover -s tests -v
```

Raw downloads and timestamped household-level records stay under the ignored data directory. Run the validation again without `--download` to reuse the downloaded inputs. Remote data corrections can change a new snapshot.
