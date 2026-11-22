# Day-ahead electricity profiles: ERA5 hindcast versus persistence

This study tests next-day grid-import profiles on **measured** CoSSMic / OPSD household electricity against historical ERA5 weather. Results appear on the [interactive forecast page](../day-ahead.html) and under [published result files](../docs/assets/day-ahead/summary.json). **ERA5 reanalysis was not an issued day-ahead forecast: these are perfect-weather retrospective hindcasts.**

## Data, timing, and exclusions

[Open Power System Data Household Data (2020-04-15)](https://data.open-power-system-data.org/household_data/2020-04-15/) provides cumulative quarter-hourly residential grid-import counters (CC BY 4.0). Counter differences form 30-minute energy intervals. Five Konstanz households (residential1, 2, 4, 5 and 6) cover 2016. Publisher interpolation flags carry into derived readings. [Open-Meteo historical ERA5](https://open-meteo.com/en/docs/historical-weather-api) supplies gridded 2m outdoor temperature for 47.6603 N, 9.1758 E, one regional proxy for all five homes. Grid import is not gross household demand where solar self-consumption is present.

Days use the Europe/Berlin civil clock. Only complete **48 × 30-minute** days with unflagged meter readings and hourly weather qualify. Partial days, publisher-interpolated intervals, weather gaps and the 23/25-hour daylight-saving days are excluded, never treated as zero. This excludes many days for residential4, leaving a small, potentially highly selected test sample.

## Models and backtest

Per home, sort complete eligible days chronologically. Fit on the earlier 80%, test on the later 20%, and require an eligible previous local day for each test day. Compare three predictions on the **same held-out half-hours**:

1. **ERA5 regression:** learn average energy for each of 48 local half-hours and weekday/weekend, plus a pooled regularised temperature slope fitted on within-slot residuals. Predicted negative energy is clipped to zero.
2. **Calendar-only:** the same trained time-of-day/weekday model, no weather effect.
3. **Yesterday persistence:** copy all 48 readings from the preceding complete local day (the zero-order hold).

This is a frozen chronological split (not walk-forward re-fitting). No held-out target enters model fitting. Score MAE, RMSE, signed bias and predictive R² on kWh/half-hour, plus daily-total MAE and bias (kWh/day). Regress held-out **observed on predicted** for calibration slope, intercept and correlation R²; distinguish this from predictive R². All scores use the same test days. No statistical confidence intervals are claimed, and the results may not transfer to other buildings, years or future issued forecasts.

## Measured results

The following published numbers derive from the source-hashed 2016 dataset, as calculated by `scripts/run_day_ahead.mjs`. All three MAEs are **kWh per half-hour**; smaller is better.

| Household | Paired test days | ERA5-regression MAE | Calendar-only MAE | Yesterday MAE |
| --- | ---: | ---: | ---: | ---: |
| residential1 | 70 | 0.11427 | **0.10697** | 0.12828 |
| residential2 | 59 | 0.11270 | **0.11014** | 0.14409 |
| residential4 | 12 | 0.06237 | 0.28882 | **0.05426** |
| residential5 | 68 | 0.08237 | **0.08003** | 0.11315 |
| residential6 | 62 | 0.13829 | 0.13621 | **0.12266** |

ERA5 reduces half-hour MAE relative to yesterday for **three of five homes**, but improves over the calendar-only model for only **residential4**. Crucially, the previous day is more accurate for residential4 and residential6. Residential4's unusually large calendar-only error and only 12 comparable days make its estimated weather advantage especially uncertain. The published JSON contains unrounded scoring results rounded to five decimal places, exclusion counts, daily errors, calibration regressions and full test-day profiles.

**Input hashes:** OPSD SHA-256 `eca7dee5ac6e53373cd0209bc05ba3383cd860bfa5d5e995f74fa78db8857c58`; ERA5 SHA-256 `2ac0e359be920e92c40af4e66d27cf0de3781950e1f1df73b9bd9b15eba4dc72`. These distinguish this snapshot from future upstream data revisions.

## Reproduce and refresh

From repository root (Python 3.11+, Node 24, internet access to the public data hosts):

```bash
python -m scripts.prepare_day_ahead
node scripts/run_day_ahead.mjs
node --test tests/day_ahead.test.mjs
```

The Python script downloads the source OPSD quarter-hour file and ERA5 observations (2015-12-31 to 2017-01-01 UTC), converts to local-day-aligned half-hour channels under `data/derived/`, and writes a hash manifest. The Node script produces `docs/assets/day-ahead/summary.json` and one `residential*.json` full held-out trace per household. Raw data live under the ignored `data/` directory; no private meter data should be committed. The [automated workflow](../.github/workflows/day-ahead-data.yml) runs on relevant changes to `main` and commits these outputs directly; it fails on unavailable sources instead of inventing data.

Future validation should substitute **archived forecast weather with a known day-ahead issue time** and test rolling re-fits, a seven-day persistence benchmark, and error uncertainty by consecutive week.
