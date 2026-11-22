"""Run the measured system 3 hourly heat-balance experiment."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from urllib.parse import urlencode

from domestic_energy.core import timestamp_utc
from domestic_energy.data import get_text, read_csv, write_json
from domestic_energy.hourly_heat_balance import validate
from scripts.fetch_monitored_home import END, HOUR, START, SYSTEM

SPLIT = datetime(2024, 1, 16, tzinfo=timezone.utc)
REQUESTS = {"power": ("heatpump_heat,heatpump_dhw", 1),
            "room": ("heatpump_roomT,heatpump_outsideT", 0)}


def feed_map(values):
    result = {}
    for stamp, value in values:
        when = datetime.fromtimestamp(stamp / 1000, timezone.utc)
        if not START <= when <= END or (when - START) % HOUR or when in result:
            raise ValueError(f"Unexpected or duplicate sample at {when}")
        if value is not None and (type(value) not in (float, int) or not isfinite(value)):
            raise ValueError(f"Invalid sample at {when}")
        result[when] = value
    return result


def assemble(power, room, weather):
    inputs = {key: feed_map(series) for key, series in {**power, **room}.items()}
    era5 = {}
    for row in weather:
        stamp = timestamp_utc(row["start_utc"])
        temperature = float(row["temperature_c"])
        if stamp in era5 or (stamp - START) % HOUR or not -90 <= temperature <= 65:
            raise ValueError(f"Invalid ERA5 sample at {stamp}")
        era5[stamp] = temperature
    accepted, rejected = [], Counter()
    for i in range((END - START) // HOUR):
        stamp = START + i * HOUR
        current = inputs["heatpump_roomT"].get(stamp)
        later = inputs["heatpump_roomT"].get(stamp + HOUR)
        heat = inputs["heatpump_heat"].get(stamp)
        dhw = inputs["heatpump_dhw"].get(stamp)
        onsite = inputs["heatpump_outsideT"].get(stamp)
        regional = era5.get(stamp)
        if None in (current, later, heat, dhw, onsite, regional):
            rejected["missing"] += 1
        elif not (-20 <= current <= 60 and -20 <= later <= 60 and -90 <= onsite <= 65):
            rejected["temperature_out_of_range"] += 1
        elif dhw != 0:
            rejected["hot_water_signal_nonzero"] += 1
        else:
            accepted.append({"start": stamp, "indoor": current, "next_indoor": later,
                             "heat_kw": heat / 1000, "onsite": onsite, "era5": regional})
    return accepted, dict(rejected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=Path("data/raw"))
    parser.add_argument("--weather", type=Path, default=Path("data/derived/monitored-home/weather-era5.csv"))
    parser.add_argument("--out", type=Path, default=Path("reports/hourly_heat_balance.json"))
    parser.add_argument("--download", action="store_true", help="Refresh monitored source files")
    args = parser.parse_args()
    payloads, hashes = {}, {"era5": hashlib.sha256(args.weather.read_bytes()).hexdigest()}
    for name, (feeds, average) in REQUESTS.items():
        path = args.raw / f"thermal_{name}.json"
        if args.download:
            args.raw.mkdir(parents=True, exist_ok=True)
            query = urlencode(dict(id=SYSTEM, feeds=feeds, start=START.strftime("%d-%m-%Y"),
                                   end=END.strftime("%d-%m-%Y"), interval=3600, average=average))
            write_json(path, json.loads(get_text(f"https://heatpumpmonitor.org/timeseries/data?{query}")))
        payloads[name] = json.loads(path.read_text())
        hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    rows, exclusions = assemble(payloads["power"], payloads["room"], read_csv(args.weather))
    write_json(args.out, {
        "system": SYSTEM, "source_sha256": hashes,
        "start_utc": START.isoformat(), "end_exclusive_utc": END.isoformat(), "split_utc": SPLIT.isoformat(),
        "excluded_hours": exclusions,
        "models": {key: validate([{**row, "outdoor": row[key]} for row in rows], split=SPLIT)
                   for key in ("onsite", "era5")},
    })


if __name__ == "__main__":
    main()
