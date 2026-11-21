# Public household energy datasets — practical acquisition guide

Updated 21 November 2026. These are **historical, real measurements** except where explicitly identified as modelled, mirrored or synthetic. Original publishers retain copyright, licences and attribution requirements. Avoid publishing private meter readings, address mappings or credentials.

## Source catalogue and coverage

| Data | Location and signals | Access and limitations |
| --- | --- | --- |
| [Low Carbon London (UKPN)](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d) | 5,567 London households, 30-minute electricity imports, 2011–2014 | Large historical multi-household dataset; public blocks, manual download; no direct thermostat or verified EV labels. |
| [Open Power System Data household_data, 2020-04-15](https://data.open-power-system-data.org/household_data/2020-04-15/) | German households; quarter-hour/hourly grid import plus labelled heat pump, EV and PV channels | 15-minute ~58 MB, hourly ~15 MB. Original publisher CSV contains cumulative energy in **kWh**. Different country and housing stock from GB. |
| [UCI Individual Household Electric Power Consumption](https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption) | One French home, 2,075,259 minute-average power measurements 2006–2010, three circuit submeters | Small ZIP (~20 MB), CC BY 4.0. 1-minute kW must be converted to interval kWh. Submeters are Wh/min. |
| [REFIT cleaned](https://zenodo.org/records/5063428) | UK 8-second measured whole-home and appliance power, 20 homes | Cleaned House 1 ~401 MB; opt into size cap. Power **W** not kWh; sampling gaps must not be filled. |
| [UK-DALE](https://jack-kelly.com/data/) | UK five-home whole-home and appliance power, sub-10-second streams | Obtain relevant house/channels manually; channel.dat often Unix seconds + Watts. |
| [IDEAL household energy](https://datashare.ed.ac.uk/items/15e82917-56ed-4282-99ef-7f211bf87f9d) | 255 UK homes, gas, electricity, room/boiler temperatures and building metadata | Best source here for learning heating/thermal dynamics, but very large and requires per-house sensor join and source/licence review. **Room temperature is not thermostat setpoint.** |
| [HeatpumpMonitor](https://heatpumpmonitor.org/) | Real volunteer heat-pump heat output and electrical input; public daily measurements | Useful observed COP/SPF and weather-response; not a representative building sample and may lack setpoints. |
| [Open-Meteo historic weather](https://open-meteo.com/en/docs/historical-weather-api) | Hourly temperature, wind, radiation, location | Join with meter intervals by timestamp and local area; weather station/model errors matter. |

These sources complement one another but **do not provide the same households**. Do not pretend an unrelated weather, indoor-temperature or tariff series was recorded in the same property. Cross-source joins are modelling assumptions, not sensor-matched empirical observations.

## Small examples committed to the repository

* **Low Carbon London**: [one household's 2,020 actual half-hour intervals](../examples/real_lcl_mac000002_2012_part.csv), ~546.956 kWh *observed*, with gaps.
* **UCI**: [33 full 30-minute periods](../examples/real/uci_2006_power_30min.csv) converted from the first 1,000 genuinely measured minutes. Original UCI data were read via a [public third-party excerpt](https://github.com/Day-yong/Machine_Learning/blob/master/datas/household_power_consumption_1000.txt). The excerpt covers only part of two days and is not an annual sample. One-minute kW values were integrated as energy; circuit submeters retained.
* **OPSD-derived**: [479 quarter-hour intervals](../examples/real/opsd_residential4_counters_15min.csv) using a [third-party reproduction](https://github.com/Chirag-Kathuria-009/Energy_Stimulator/blob/main/data/sample/bronze/opsd/household_data_15min.csv) of residential4 grid, heat-pump, EV and PV counters. This **provisional mirrored excerpt contains cumulative counters**, so adjacent samples were differenced. The reproduction has **not been independently matched byte-for-byte or value-for-value against OPSD's published counter file**. Do not treat it as independently verified publisher ground truth. Re-run the original publisher CSV for validated inference.
* Each example is a **truncated extract**. Do not extrapolate annual costs or household absence from these short windows.

Use:
```bash
python -m domestic_energy meter --csv examples/real_lcl_mac000002_2012_part.csv
python -m domestic_energy meter --csv examples/real/uci_2006_power_30min.csv
python -m domestic_energy meter --csv examples/real/opsd_residential4_counters_15min.csv
```

## One-command local download + conversion

Python **3.11+**. No extra dependencies. Network fetches are **opt-in** and hard-capped by size; existing downloads are reused only if their SHA-256 matches a provenance manifest. Raw archives and large processed files stay in gitignored `data/`, not the repository.

```bash
git clone https://github.com/charlie9578/domestic-energy-analysis.git
cd domestic-energy-analysis
python -m unittest discover -s tests -v

# Inspect catalogue without downloading anything.
python -m domestic_energy.dataset_hub list

# Original OPSD hourly public data; default 32 MiB cap.
python scripts/run_public_data.py --dataset opsd-hourly --fetch --household residential4

# UCI original ZIP. Output is 30-minute kWh; full minute bins only.
python scripts/run_public_data.py --dataset uci --fetch

# Higher-resolution OPSD: ~58 MB, explicit opt in to 80-MiB cap.
python scripts/run_public_data.py --dataset opsd-quarterhour --fetch \
  --household residential4 --allow-large --max-mb 80

# REFIT House 1 original cleaned CSV: ~401 MB; budget for CSV and storage.
python scripts/run_public_data.py --dataset refit-house1 --fetch \
  --allow-large --max-mb 650

# Manual ZIP/CSV: no internet necessary; original source remains local.
python scripts/run_public_data.py --dataset lcl \
  --input /path/to/UKPN_block.csv --household MAC000002

# Example offline OPSD conversion from publisher file, not mirrored counters.
python -m domestic_energy.dataset_hub convert opsd-hourly \
  --input /path/to/household_data_60min_singleindex.csv \
  --household residential4 --value-mode counter \
  --out data/public/processed/opsd_residential4.csv

# Analyse a normalized interval file.
python -m domestic_energy meter --csv data/public/processed/opsd_residential4.csv
```

The original OPSD publisher CSV contains cumulative kWh. Use counter mode for that file. Use interval mode for inputs independently verified as interval energy. Grid imports, self-consumed PV, household demand and appliance submeter channels **must not be naively summed**.

`fetch` is restricted to publisher endpoints in the code. `--max-mb` limits compressed/raw download *transfer bytes*, not the expanded ZIP contents or downstream processing disk space. ZIP files are read with a streaming member rather than extracted en masse.

## Data joining, quality control and honest evaluation

* **Unit type:** W is power, Wh and kWh are energy. UCI minute-average kW × (1/60 h) = kWh. REFIT and UK-DALE stepwise W are integrated over measured time only; long gaps are discarded.
* **Timestamps:** store UTC with explicit offset, group by local time only when comparing tariffs or daily routines. UCI wall times use `Europe/Paris`; ambiguous/nonexistent DST readings are skipped rather than guessed.
* **Coverage:** report actual observed intervals and hours. Missing/duplicated intervals are never treated as zero or annualised without explicit model forecasts. If an entire day or sensor span is missing, leave a gap.
* **Detector validation:** use separate labelled EV, heat pump and appliance channels where available to measure precision, recall and error. Whole-home load spikes alone do **not** prove EV charging or holidays.
* **Thermal modelling:** use indoor temperature, outdoor temperature, actual heating input and building metadata from the **same home** if available, with holdout winter periods. Thermostat setpoints are usually **not measured**; avoid interpreting boiler pipe temperature as setpoint or heat delivery.
* **Tariff comparison:** replay identical metered loads under clearly labelled *hypothetical* prices, or historical known tariff prices. Historical data billed at 2026 prices are counterfactual comparisons, **not actual household historic bills**.
* **Privacy:** observed home routines can be sensitive even when pseudonymous. Do not upload private meter export files to public GitHub.

## Dataset-specific limitations

**Low Carbon London:** enormous original archive, incomplete household runs, representative sampling caveats and mixed timing conventions across secondary copies. Check timestamp-is-interval-start versus interval-end and detect duplicate/dropped periods before calculating an annual tariff.

**UCI:** one French dwelling cannot characterize British heating; three submeter channels provide some appliance label context but not thermostat schedules. Resampled readings are measured-derived, not native smart-meter half-hour readings.

**OPSD:** matched heat-pump/EV/PV channels can help validate technology classifiers, but they are German and coverage varies by channel. The small GitHub counter mirror is provisional; publisher format is definitive.

**IDEAL:** strongest candidate for modelling heating schedules, fabric thermal response and temperature decay. Start with documentation/metadata (small), then select a few households and join sensor IDs to avoid downloading the full multi-GB corpus blindly. Survey descriptors may be missing; metered indoor temperature is not an actual thermostat setpoint.

**REFIT/UK-DALE:** useful for appliance-level validation. A non-EV appliance load can look like a charging session in 30-minute aggregate demand; treat detector labels as hypotheses until checked against these richer recordings.

### Scope of validation so far

Automated tests cover download size caps, malformed/missing samples, cumulative reset handling, UTC/DST conversion, and power-to-energy units; they are **offline**. Actual multi-gigabyte transfers and publisher API availability have **not** been exercised in CI. The two smaller third-party example extracts were retrieved through GitHub, transformed and committed. Do not interpret this as a completed nationwide longitudinal study.
