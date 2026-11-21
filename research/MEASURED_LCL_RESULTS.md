# Preliminary empirical study: Low Carbon London smart-meter extract

**Source:** [RTDIP Core test fixture](https://github.com/rtdip/core/blob/develop/tests/sdk/python/rtdip_sdk/data_models/meters/utils/test_data/smart_meters_london/CC_LCL-FullData.csv), based on the [UK Power Networks Low Carbon London](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d) research collection. **Household**: public pseudonym `MAC000002`; **period**: 2012-10-12 00:00 UTC to 2012-11-24 03:00 UTC; raw source label presumed end-of-interval and converted by subtracting 30 minutes. **Data**: measured aggregate electricity demand, *not* a device-level or heating/occupancy dataset. Original publisher's usage/attribution terms apply.

## Directly observed (no imputation)

| Quantity | Observation |
|---|---:|
| Unique 30-minute readings | **2,020** |
| Measured energy, observed intervals only | **546.956 kWh** |
| Observed hours | **1,010 h** |
| Calendar span | **1,035 h** |
| Coverage within span | **97.585%** |
| Time gaps | **0.5 h + 0.5 h + 24 h** |
| Maximum measured 30-minute import | **2.160 kWh** (4.32 kW half-hour average) |
| UTC dates containing any observations | **43** |
| UTC dates with all 48 half-hours | **40** |
| Mean of complete UTC days | **13.091 kWh/day** |

All figures were calculated by parsing the published 2,022 raw rows for `MAC000002`, identifying and excluding **two identical duplicate timestamps**, converting source end-stamps to UTC start-stamps, then aggregating 2,020 unique nonnegative half-hourly values. The 24-hour missing section spans 2012-11-08 UTC, not a zero-usage or evidence-of-holiday interval; it is a data gap. Two other isolated half-hour gaps occur on 2012-10-12 and 2012-11-02. Extrapolation to a complete bill or year would require assumptions about these gaps, seasons and house type; do not multiply 13.091 by 365 and call it a measured annual estimate.

## Very limited forecasting check

A **simple day-of-week median** trained on the first 30 full UTC days and evaluated on the last 10 full UTC days had an **illustrative held-out daily MAE of 2.869 kWh/day**. This is an explanatory check of forecast error, *not* the repository's default half-hour forecasting implementation (which uses half-hour weekday-slot medians and British local dates, and will give different results). Do not mix these metrics. Also, 40 days of one autumn are not sufficient to quantify full-year weather-driven variability or annual investment economics.

## Implications for tariffs and heating controls

The measured profile can be used for **historical electricity tariff replay and peak/off-peak energy shares**, provided tariff prices align with each exact timestamp and missing readings are handled explicitly. What **cannot** be measured from these readings alone: whether the resident was at home, whether space heating was on, whether EV charging occurred, what thermostat setpoints were used, the insulation level, the heat pump seasonal efficiency or gas consumption. The heating controller and storage heating study in `research/REAL_DATA_HEATING.md` is a separate physical simulation which requires explicit assumed or independently observed building characteristics. This separation prevents the common error of reporting simulated thermostat savings as results *measured* in Low Carbon London.

## Reproduction

```bash
python -m unittest discover -s tests -v
python -m domestic_energy measured-profile \
  --csv examples/real_lcl_mac000002_2012_part.csv --expectations \
  --out reports/measured_lcl_profile.json
python -m domestic_energy detect \
  --electricity examples/real_lcl_mac000002_2012_part.csv \
  --out reports/measured_lcl_hypotheses.json
```

For a robust consumer product, obtain linked **meter + regional tariff + weather + indoor thermostat/temperature + building geometry** (where consent is available). Use labelled appliance/charger submeter data to evaluate any EV or heating event detector against false-positive and false-negative rates. Without these labels, detections must remain low-confidence hypotheses.
