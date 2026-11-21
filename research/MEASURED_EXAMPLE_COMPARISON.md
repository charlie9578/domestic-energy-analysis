# Comparison of three observed household electricity excerpts

Research snapshot 21 November 2026. These figures are **calculated from the exact small example CSV files committed to this repository**, not national estimates or synthetic profiles. Reproduce:

```bash
python scripts/profile_public_examples.py --output reports/public_examples.json
```

| Dataset | Observation window (UTC) | Samples | Observed hours | Coverage of its bounding window | Grid imports observed | Local 00:00–07:00 share |
|---|---|---:|---:|---:|---:|---:|
| UKPN Low Carbon London, anonymised MAC000002 | Oct 12–Nov 24, 2012 | 2,020 × 30 min | 1,010.0 | 97.58% | **546.956 kWh** | **18.35%** (Europe/London) |
| UCI French home, excerpt of minute data | Dec 16–17, 2006 | 33 × 30 min | 16.5 | 100% | **39.751 kWh** | **35.21%** (Europe/Paris) |
| Provisional OPSD third-party mirror, residential4 | May 2–6, 2016 | 479 × 15 min | 119.75 | 100% | **18.500 kWh** | **35.12%** (Europe/Berlin) |

*Coverage* refers only to each file's **bounding time window**, not to a complete season or year. The 100% figure for the UCI sample means consecutive complete half-hours *within that short clipped fragment*, not a complete 24-hour day. The LCL period has 25 observed hours absent within its bounding window. Overnight shares are calculated with the source-local clock and, for London, span a daylight-saving transition. The samples are far too short or nonrepresentative to rank annual tariffs.

## What we can and cannot infer

The UCI excerpt has **2.741 kWh** observed in submeter 2 and **5.637 kWh** in submeter 3. These are *measured circuit submeters*, not separately identified EVs, solar systems or heat pumps. The 0 value for submeter 1 means zero energy observed in that submeter over this excerpt, not absence of the appliance.

The provisional OPSD mirror excerpt contains, *after counter differencing*, **7.18 kWh heat-pump channel**, **17.10 kWh EV channel** and **268.82 kWh PV channel** alongside 18.50 kWh grid imports. These quantities are **not additive**: grid imports and solar generation represent different flows; PV may feed domestic loads or be exported. The very different magnitudes make validating the reproduction against OPSD's original publisher CSV especially important before drawing physical or economic conclusions. This is *not* verified truth for UK households.

**Tariff illustration**: if a hypothetical day/night tariff charges a daytime premium, only 18.35% of observed LCL grid imports fell into local 00:00–07:00. The UCI and OPSD slices have around 35% overnight demand, but both are short non-UK extracts. Actual Economy 7 times vary by meter/region and season; do not assume every cheap-rate period is midnight to 7am.

## Experiment design for heating and technology questions

1. **Heating controls**: pair 30-minute gas/electric readings with temperature/boiler-operation measurements from the *same* IDEAL dwelling. Estimate thermal response with uncertainty, then simulate constant 20°C, night setback, morning/evening schedules and cheap-rate storage heating on matched weather days. Keep unseen days for validation.
2. **Technology fingerprinting**: use OPSD original labelled heat-pump/EV/PV subchannels (and REFIT/UK-DALE appliance channels) to evaluate load-shape classifiers; report false alarms and recall. The aggregate UKPN LCL traces lack independent EV/holiday labels.
3. **Forecast validation**: build holdouts grouped by **household and season**; compare an hourly/weekday calendar baseline to temperature-sensitive models. Never split overlapping days at random.
4. **Economics**: compare tariffs on exactly the same metered periods with valid interval rates, then compare future heating strategies using measured weather and calibrated building fabric; exclude strategies with unacceptable cold-hour penalties.
5. **Cross-source validity**: UKPN London (2012), UCI France (2006) and OPSD Germany (2016) have different populations and years. Pool them only as clearly stratified training/evaluation domains, not as one matched household dataset.

## Reproducibility and provenance

Original source information and download commands are in [PUBLIC_DATASETS.md](PUBLIC_DATASETS.md). The individual small excerpts and their licensing caveats are in [examples/real/DATA_PROVENANCE.md](../examples/real/DATA_PROVENANCE.md).

**Important qualification:** OPSD's *original* publisher file is interval energy in kWh; the small third-party *reproduction* behaves as cumulative counters and has not been independently audited against the original. Results from that third-party example must remain labelled provisional. Weather, room temperature, thermostat settings and household occupancy were not measured in any of these committed electricity excerpts.
