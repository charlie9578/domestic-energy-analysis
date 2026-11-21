# Held-out validation on monitored heat pumps and London smart-meter data

**Snapshot taken 21 November 2026.** The [machine-readable results](OBSERVED_VALIDATION.json) include input hashes, exclusions, holdout metrics, bootstrap intervals and each scenario outcome.

## Measurements and inferred heat signatures

The heat-pump pilot uses the five lowest public HeatpumpMonitor system IDs with indoor-temperature monitoring declared in the system registry snapshot. It includes four reported air-source systems and one ground-source system. The equipment and control descriptions come from that registry. The monitored space-heat and electrical channels provide direct evidence of heat-pump operation in this cohort. Equipment identification from aggregate import remains unvalidated because the study has no labelled negatives or independent aggregate-import labels. [HeatpumpMonitor API](https://heatpumpmonitor.org/api-helper)

The model uses heating-season civil days in 2023 for training and heating-season civil days in 2024 for testing, defined here as October through April. Each retained row pairs daily mean indoor and outdoor temperatures with metered space heat and space electricity from the same system and day. Required channels have quality flags of at least 95% and combined coverage of at least 95% of physical day length. Missing space-mode values are excluded, which conditions the conclusions on reported active space-heating days. Local midnight defines the source day, including 23- and 25-hour days. Results use the metering boundaries declared by each contributor.

The models regress mean delivered space-heat power on either negative outdoor temperature or indoor-minus-outdoor temperature, with an intercept. Daily energy predictions restore the corresponding day length and clip negative power to zero. A constant training mean power provides a benchmark. This is retrospective estimation conditional on observed temperature. Indoor temperature partly reflects heating and controls, and daily aggregates omit gains from sun and occupants, storage in the building and ventilation changes. The slope represents an apparent heat-loss coefficient under this model. No independent fabric or co-heating measurements were used to validate it.

| Public system | Train / test days | Mean baseline MAE | Outdoor-only MAE | Indoor–outdoor MAE | Apparent heat loss, W/K (95% interval) | Observed holdout space heat/electricity |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 3 | 175 / 202 | 7.93 | 4.24 | 6.53 | 132 (104–153) | 3.33 |
| 4 | 187 / 207 | 10.53 | 8.69 | 6.75 | 143 (121–165) | 4.59 |
| 8 | 196 / 209 | 18.71 | 8.11 | 10.18 | 251 (230–266) | 4.37 |
| 9 | 207 / 208 | 14.19 | 7.25 | 6.73 | 196 (179–209) | 4.49 |
| 11 | 147 / 147 | 11.55 | 9.10 | 9.83 | 93 (55–125) | 4.59 |

MAE is in kWh of delivered space heat per day. All five indoor–outdoor models improved on the constant baseline. Adding indoor temperature improved on the outdoor-only model for systems 4 and 9 and worsened it for systems 3, 8 and 11. Paired 95% interval endpoints for indoor-minus-outdoor-model MAE retain those directions in this sample. Individually resample calendar weeks within each partition, 1,000 replicates with seed 26. This captures some serial dependence and omits cross-season drift, sensor bias, selection and systematic metering error. The reported heat/electricity ratios cover accepted holdout days only.

## London smart-meter and station join

The bundled Low Carbon London household trace was joined by local civil date to historical daily mean temperature from Heathrow station 03772. Heathrow is a regional proxy for an anonymised London location, and station-day temperature uses the publisher's daily aggregation. The aligned series kept 40 complete local meter days and excluded three partial days and one missing day. A weather regression trained on 30 days yielded **2.98 kWh/day** MAE over the final 10 days from 14 November 2012, versus **2.93 kWh/day** for the training mean-power benchmark. The small sample supports no conclusion about the home's heating fuel or heat loss. [Low Carbon London](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d), [Meteostat station 03772](https://meteostat.net/en/station/03772)

The held-out load contained **108.876 kWh** measured across 480 half-hours. With consumption unchanged, illustrative flat 27p/kWh pricing totals **£34.90** and illustrative 9p overnight/35p daytime pricing totals **£38.09**, both with 55p/day standing charges. Overnight means 00:00–07:00 local. These are hypothetical replays of observed consumption.

## Thermostat and retrofit scenarios

For the four air-source systems, the study compared a 20°C constant, three night setback temperatures, and fixed overnight preheat. Each schedule was screened across nine combinations of training slope and assumed thermal capacity. The simulator drove each half-hour with its day's observed outdoor mean over 8–21 January 2024. Thermal capacity, heat output limit, indoor gains, initial temperature, COP curve and occupancy rules are assumptions. Indoor temperature dynamics were never validated on held-out intervals. The model reused the training slope estimate as an envelope input and tested its bootstrap endpoints as sensitivity cases. The ground-source system was excluded from the air-source thermostat scenarios.

Among schedules satisfying the existing comfort screen in all nine cases, 18°C night setback had the lowest worst-case heating energy cost under the illustrative flat tariff at all four systems. Fixed preheat ranked first under both the illustrative night tariff and published Octopus Agile region G rates for the same dates. The latter comparison applies the same regional price series to all simulated systems and matches simulated half-hourly load in UTC. It compares heating energy charges only, using fixed schedules chosen from a small menu. It does not establish a realised saving, a region-specific quote or a price-responsive control policy. [Octopus standard unit rates](https://api.octopus.energy/v1/products/AGILE-23-12-06/electricity-tariffs/E-1R-AGILE-23-12-06-G/standard-unit-rates/)

The retrofit screen assumes a £4,000 upfront cost, 20% reduction in apparent heat loss, 1,800–3,000 annual heating degree-days, SPF 2.5–4.5, 27p/kWh, 25 years and a 3.5% real discount rate. Across 135 scenarios, estimated net present value ranged from **−£3,533 to +£2,822**, with 16 positive cases. The grid counts are sensitivity outcomes with no probability weights. The experiment has no measured pre/post retrofit or thermostat intervention outcomes.

## Reproduce

Run from the repository root with Python 3.11 or later. Public endpoints can update past records or append observations. Raw files remain under the ignored data directory, and the aggregate report pins their downloaded SHA-256 digests. Save the raw snapshot locally for byte-identical reproduction.

```bash
mkdir -p data/raw
curl --fail --location 'https://heatpumpmonitor.org/system/list/public.json' \
  -o data/raw/hpm_systems.json
for id in 3 4 8 9 11; do
  curl --fail --location "https://heatpumpmonitor.org/system/stats/daily?id=${id}" \
    -o "data/raw/system_${id}.csv" || exit
done
curl --fail --location 'https://bulk.meteostat.net/v2/daily/03772.csv.gz' \
  -o data/raw/heathrow.csv.gz
python -m domestic_energy fetch-rates \
  --product AGILE-23-12-06 --tariff E-1R-AGILE-23-12-06-G \
  --start 2024-01-08T00:00:00Z --end 2024-01-22T00:00:00Z \
  --out data/raw/agile_jan2024.csv
python -m scripts.run_observed_validation
python -m unittest discover -s tests -v
```
