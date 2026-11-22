"""Reproduce the public 2016 Konstanz five-home ERA5-proxy day-ahead study.

Downloads the original publisher's quarter-hour cumulative meter CSV and ERA5
hourly temperatures, converts to half-hour import, then writes browser-ready
validation via scripts/run_day_ahead.mjs. This never fabricates measurements.
"""
from __future__ import annotations

import argparse
import csv
import json
import hashlib
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from domestic_energy.data import fetch_open_meteo_hourly, write_csv
from domestic_energy.dataset_hub import fetch
from domestic_energy.household_cohort import opsd_halfhours

HOMES = ("residential1", "residential2", "residential4", "residential5", "residential6")
ZONE = ZoneInfo("Europe/Berlin")
START = datetime(2016, 1, 1, tzinfo=ZONE).astimezone(timezone.utc)
END = datetime(2017, 1, 1, tzinfo=ZONE).astimezone(timezone.utc)
LATITUDE, LONGITUDE = 47.6603, 9.1758


def sha256(path):
    with Path(path).open("rb") as fp:
        return hashlib.file_digest(fp, "sha256").hexdigest()


def prepare(raw: Path, derived: Path, *, refresh: bool = False):
    raw.mkdir(parents=True, exist_ok=True)
    derived.mkdir(parents=True, exist_ok=True)
    meter = raw / "opsd_15min.csv"
    weather = raw / "konstanz_era5.csv"
    if refresh or not meter.exists():
        fetch("opsd-quarterhour", meter, max_mb=100, allow_large=True)
    if refresh or not weather.exists():
        # Include the preceding/following UTC day for local-day coverage.
        day, stop = date(2015, 12, 31), date(2017, 1, 1)
        records = []
        while day <= stop:
            final = min(day + timedelta(days=30), stop)
            records.extend(fetch_open_meteo_hourly(
                LATITUDE, LONGITUDE, day.isoformat(), final.isoformat()
            ))
            day = final + timedelta(days=1)
        write_csv(weather, records, list(records[0]))

    with meter.open(newline="", encoding="utf-8-sig") as fp:
        homes = opsd_halfhours(fp, HOMES, start=START, end=END)
    for home in HOMES:
        records = homes.get(home, [])
        if not records:
            raise ValueError(f"No usable data from OPSD for {home}")
        write_csv(derived / f"opsd_2016_{home}.csv", records, list(records[0]))
    manifest = {
        "source": "OPSD Household Data 2020-04-15 quarter-hour singleindex, CoSSMic",
        "source_url": "https://data.open-power-system-data.org/household_data/2020-04-15/",
        "source_license": "CC BY 4.0",
        "opsd_sha256": sha256(meter),
        "weather": "Open-Meteo historical ERA5 hourly reanalysis, 47.6603 N, 9.1758 E",
        "weather_url": "https://open-meteo.com/en/docs/historical-weather-api",
        "era5_sha256": sha256(weather),
        "range": "Europe/Berlin 2016",
        "households": HOMES,
        "meter_counts": {home: len(homes[home]) for home in HOMES},
    }
    out = derived / "day_ahead_sources.json"
    out.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--derived", type=Path, default=Path("data/derived"))
    parser.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    print(json.dumps(prepare(args.raw, args.derived, refresh=args.refresh), indent=2))


if __name__ == "__main__":
    main()
