"""Prepare an hourly HeatpumpMonitor and ERA5 example for the meter explorer."""
import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean
from urllib.parse import urlencode

from domestic_energy.core import timestamp_utc
from domestic_energy.data import fetch_open_meteo_hourly, get_text, write_csv, write_json

SYSTEM = 3
START = datetime(2024, 1, 8, tzinfo=timezone.utc)
END = datetime(2024, 1, 22, tzinfo=timezone.utc)
HOUR = timedelta(hours=1)
COORDINATES = (53.4808, -2.2426)  # Manchester city centre, regional proxy.
FEEDS = ("heatpump_roomT", "heatpump_outsideT", "heatpump_ch", "heatpump_dhw", "heatpump_elec")


def normalize(payload):
    expected = [START + i * HOUR for i in range((END - START) // HOUR)]
    values = {}
    for feed in FEEDS:
        series = {}
        for stamp, amount in payload[feed]:
            when = datetime.fromtimestamp(stamp / 1000, timezone.utc)
            if when in series or when < START or when > END or (when - START) % HOUR:
                raise ValueError(f"Unexpected {feed} timestamp: {when}")
            if amount is not None:
                if isinstance(amount, bool) or not isinstance(amount, (int, float)):
                    raise ValueError(f"Invalid {feed} value: {amount}")
                series[when] = amount
        values[feed] = series
    rows = []
    for when in expected:
        room, outdoor, heat, hot_water, watts = (values[feed].get(when) for feed in FEEDS)
        for value, low, high in ((room, -20, 60), (outdoor, -90, 65),
                                 (heat, 0, 1.01), (hot_water, 0, 1.01), (watts, 0, 30000)):
            if value is not None and not low <= value <= high:
                raise ValueError(f"Out-of-range monitored value at {when}: {value}")
        rows.append({
            "start_utc": when.isoformat(), "indoor_temperature_c": room,
            "site_outdoor_temperature_c": outdoor,
            "heating_fraction": None if heat is None else min(heat, 1),
            "hot_water_fraction": None if hot_water is None else min(hot_water, 1),
            "mean_electrical_kw": None if watts is None else watts / 1000,
        })
    return rows


def profile(rows, weather):
    era5 = {timestamp_utc(row["start_utc"]): row["temperature_c"] for row in weather}
    bins = [[] for _ in range(24)]
    for row in rows:
        stamp = timestamp_utc(row["start_utc"])
        outdoor = era5.get(stamp)
        indoor = row["indoor_temperature_c"]
        heating = row["heating_fraction"]
        if None not in (indoor, outdoor, heating):
            # This January window has the same UTC and Europe/London clock hours.
            bins[stamp.hour].append((indoor, outdoor, heating))
    return [{"hour": hour, "samples": len(points),
             "indoor_c": round(mean(x[0] for x in points), 2),
             "outdoor_c": round(mean(x[1] for x in points), 2),
             "heating_percent": round(100 * mean(x[2] for x in points), 1)}
            for hour, points in enumerate(bins) if points]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=Path("data/derived/monitored-home"))
    parser.add_argument("--profile", type=Path, help="Optional aggregate clock-hour profile JSON")
    args = parser.parse_args()
    query = urlencode({"id": SYSTEM, "feeds": ",".join(FEEDS),
                       "start": START.strftime("%d-%m-%Y"), "end": END.strftime("%d-%m-%Y"),
                       "interval": 3600, "average": 1})
    rows = normalize(json.loads(get_text(f"https://heatpumpmonitor.org/timeseries/data?{query}")))
    weather = fetch_open_meteo_hourly(*COORDINATES, str(START.date()), str((END - HOUR).date()))
    result = profile(rows, weather)
    for channel, value in (("indoor", "indoor_temperature_c"), ("heating", "heating_fraction"),
                           ("heatpump-electricity", "mean_electrical_kw")):
        target = "consumption_kwh" if channel == "heatpump-electricity" else value
        export = [{"start_utc": row["start_utc"], "duration_minutes": 60, target: row[value]}
                  for row in rows]
        write_csv(args.out_dir / f"{channel}.csv", export, list(export[0]))
    write_csv(args.out_dir / "site-hourly.csv", rows, list(rows[0]))
    write_csv(args.out_dir / "weather-era5.csv", weather, list(weather[0]))
    if args.profile:
        write_json(args.profile, {"system": SYSTEM, "start_utc": START.isoformat(),
                                  "end_exclusive_utc": END.isoformat(), "hours": result})
    print(f"{sum(row['samples'] for row in result)} matched hours in {args.out_dir}")


if __name__ == "__main__":
    main()
