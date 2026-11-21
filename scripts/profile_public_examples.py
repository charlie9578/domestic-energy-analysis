"""Offline measured-example profiler: coverage, load shape, labelled channels.

Run:
  python scripts/profile_public_examples.py
  python scripts/profile_public_examples.py --output reports/public_examples.json
No annualisation, weather, occupancy or appliance guesses are performed.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = {
    "low_carbon_london": (ROOT/"examples/real_lcl_mac000002_2012_part.csv", "Europe/London", "measured native interval energy"),
    "uci_france": (ROOT/"examples/real/uci_2006_power_30min.csv", "Europe/Paris", "minute-average measured power resampled into complete half-hours"),
    "opsd_third_party_mirror": (ROOT/"examples/real/opsd_residential4_counters_15min.csv", "Europe/Berlin", "PROVISIONAL: third-party cumulative-counter reproduction, not independently checked against publisher"),
}

def profile(path, timezone_name):
    zone = ZoneInfo(timezone_name)
    with Path(path).open(newline="", encoding="utf-8") as file:
        rows = csv.DictReader(file)
        required = {"start_utc", "consumption_kwh", "duration_minutes"}
        if not required.issubset(rows.fieldnames or []):
            raise ValueError("Missing canonical interval columns")
        n, energy, observed, overnight = 0, 0., 0, 0.
        first, end, previous_end, gaps = None, None, None, 0
        channels = defaultdict(float)
        hours = defaultdict(float)
        for row in rows:
            start = datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00"))
            if start.tzinfo is None:
                raise ValueError("Timestamp without UTC offset")
            start = start.astimezone(timezone.utc)
            duration = int(row["duration_minutes"])
            value = float(row["consumption_kwh"])
            if value < 0 or duration not in (15, 30, 60):
                raise ValueError("Invalid measured interval")
            if previous_end is not None:
                if start < previous_end:
                    raise ValueError("Overlapping or duplicate intervals")
                if start > previous_end:
                    gaps += 1
            local_hour = start.astimezone(zone).hour
            hours[local_hour] += value
            if 0 <= local_hour < 7:
                overnight += value
            for k, v in row.items():
                if k not in required and k.endswith("_kwh") and v not in (None, ""):
                    channels[k] += float(v)
            if first is None:
                first = start
            previous_end = start + timedelta(minutes=duration)
            end = previous_end
            observed += duration
            energy += value
            n += 1
    if not n:
        raise ValueError("No measured data")
    span_minutes = (end-first).total_seconds()/60
    return {
        "measured": True, "first_interval_utc": first.isoformat(),
        "last_end_utc": end.isoformat(), "intervals": n,
        "observed_hours": round(observed/60, 4),
        "span_hours": round(span_minutes/60, 4),
        "coverage_fraction": round(observed/span_minutes, 6),
        "gaps": gaps, "observed_grid_import_kwh": round(energy, 6),
        "overnight_00_to_07_local_fraction_of_observed_import": round(overnight/energy, 6) if energy else None,
        "timezone": timezone_name,
        "other_separately_metered_channel_kwh": {k: round(v, 6) for k,v in sorted(channels.items())},
        "interpretation": "Never add EV/HP/PV channels to grid imports: PV may be self-consumed. This is an observed partial trace, not an annualised forecast or measured thermostat experiment.",
    }

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", help="Write JSON report to path, default print to stdout")
    args = p.parse_args(argv)
    result = {}
    for name, (path, zone, provenance) in EXAMPLES.items():
        result[name] = {"provenance": provenance, "path": str(path.relative_to(ROOT)), **profile(path, zone)}
    payload = json.dumps(result, indent=2)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload + "\n")
    else:
        print(payload)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
