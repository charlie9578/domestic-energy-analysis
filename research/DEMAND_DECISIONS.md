# Forecasting electricity demand and testing bill changes

This study distinguishes three questions. How accurately can we forecast grid import? Would a different tariff change the bill on the same readings? Would moving a separately metered load change the bill while preserving the energy service?

## Forecast evaluation

We use five public household import channels from Konstanz and the local October–December 2016 test period. Each prediction uses the same UTC half-hour one week before as the benchmark, or the median of up to four preceding weekly values. The values are available before the prediction day. The clock stays in UTC through the October time change. Publisher-interpolated data are excluded from both history and evaluation. Both forecasts are evaluated only where the target and one-week lag are available. We set the two methods in advance and use no test-period model selection. [OPSD publisher and metadata](https://data.open-power-system-data.org/household_data/2020-04-15/) · [Cohort preparation](OBSERVED_VALIDATION.md#one-year-of-half-hourly-household-import)

| Household | Shared half-hours | Last week MAE | Rolling median MAE | Rolling median vs last week, 95% interval |
| --- | ---: | ---: | ---: | ---: |
| Residential 1 | 4,418 | 0.144 | 0.109 | −0.046 to −0.024 |
| Residential 2 | 4,322 | 0.150 | 0.115 | −0.043 to −0.027 |
| Residential 4 | 2,360 | 0.205 | 0.176 | −0.041 to −0.017 |
| Residential 5 | 4,418 | 0.110 | 0.087 | −0.027 to −0.021 |
| Residential 6 | 4,418 | 0.108 | 0.095 | −0.021 to −0.005 |

Errors are in kWh per half-hour. We resampled UTC calendar weeks within each home, using 1,000 paired bootstrap draws and seed 26. The intervals describe the tested weeks and the subset that passed the data checks. Household 4 has especially incomplete coverage. The forecasts describe grid import, which may exclude on-site solar use. Meter-only histories cannot identify which end uses can be reduced.

The rolling median scored better on half-hour MAE for all five homes and underpredicted cost for all five when priced at 10p/kWh from 00:00–05:00 local and 30p elsewhere. Rare high-load intervals matter more for total energy and cost than for the median. A four-week mean reduced the bill underestimation for all five in this sample, and still underpredicted every observed total. The aggregate JSON reports both objectives on identical slots. The forecasts are benchmarks for routine demand, with no forward weather inputs or claim to generalise.

## Pricing changes with the same electricity use

We repriced the same observed intervals at a hypothetical 27p/kWh flat rate and the 10p/30p schedule above. The time-of-use tariff cost less for two homes and more for three. This comparison omits standing charges, tax changes, exports, switching terms and real regional tariff availability. The rates are illustrative UK pence figures applied to historical German electricity consumption.

## Moving a measured load

The publisher supplies a separate EV charging circuit for household 4. For the 365 overnight windows beginning in 2016 and ending in 2016, we considered the portion of charging from 20:00 through a 05:00 or 07:00 local deadline. Charging outside the window stays fixed. We required at least 1 kWh of EV charging in one contiguous block, complete unflagged import, EV, export and solar records, no solar generation or export, and EV consumption no greater than grid import in every half-hour.

For eligible windows, the replay releases the charge at the first observed charging interval. It assumes the vehicle can remain connected through the selected deadline. It fills the cheapest available intervals subject to the observed charging rate ceiling and the observed peak half-hour import in that window, while delivering exactly the same **grid-side charging kWh**. The replay uses realised background demand and knows the charge requirement. It does not establish future charger availability, live forecast-based scheduling performance or realised savings.

Both deadlines retained the same **three** windows. The 05:00 deadline excluded 222 nights for missing or flagged channels and 140 for charging below 1 kWh. Across the eligible windows the algorithm moved **13.148 of 17.238 kWh** and lowered modelled variable charges by **£2.63**. It removed no energy. The small and selected sample gives no basis for annualising that amount.

## Reducing use

A verified 1 kWh reduction in imported electricity changes variable charges by the rate in the affected interval. In the example above, reducing 1 kWh in a 30p interval saves 30p, while shifting the same kWh into a 10p interval saves 20p and preserves total consumption. A prediction of high use gives the time and size of the opportunity. A measured intervention or an engineering calculation with the correct service boundary is needed to establish what can actually be cut.

## Reproduce

Use the [cohort preparation commands](OBSERVED_VALIDATION.md#reproduce), then run:

```bash
python -m scripts.run_demand_decisions
python -m unittest discover -s tests -v
```

The [aggregate results](DEMAND_DECISIONS.json) pin the raw OPSD file hash. Timestamped household records remain local.
