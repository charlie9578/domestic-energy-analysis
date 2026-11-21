"""Download and normalize public household-energy datasets without extra dependencies.

Source catalog is intentionally allow-listed. Fetch is opt-in, bounded by size,
atomic and records SHA-256. Normalize readings into interval-start UTC and kWh.
Incomplete minutes / power telemetry are dropped, never silently zero-filled.
"""
from __future__ import annotations
import argparse
import csv
import gzip
import hashlib
import io
import json
import math
import os
import sys
import tempfile
import urllib.request
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCES = {
    "opsd-hourly": {
        "url": "https://data.open-power-system-data.org/household_data/2020-04-15/household_data_60min_singleindex.csv",
        "page": "https://data.open-power-system-data.org/household_data/2020-04-15/",
        "format": "opsd", "minutes": 60, "estimated_mb": 15, "licence": "CC BY 4.0"},
    "opsd-quarterhour": {
        "url": "https://data.open-power-system-data.org/household_data/2020-04-15/household_data_15min_singleindex.csv",
        "page": "https://data.open-power-system-data.org/household_data/2020-04-15/",
        "format": "opsd", "minutes": 15, "estimated_mb": 58, "licence": "CC BY 4.0"},
    "uci": {
        "url": "https://archive.ics.uci.edu/static/public/235/individual+household+electric+power+consumption.zip",
        "page": "https://archive.ics.uci.edu/dataset/235/individual+household+electric+power+consumption",
        "format": "uci", "minutes": 30, "estimated_mb": 20, "licence": "CC BY 4.0"},
    "refit-house1": {
        "url": "https://zenodo.org/records/5063428/files/CLEAN_House1.csv?download=1",
        "page": "https://zenodo.org/records/5063428",
        "format": "watts", "minutes": 30, "estimated_mb": 401, "licence": "Check Zenodo record terms"},
    "lcl": {
        "url": None, "page": "https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d",
        "format": "lcl", "minutes": 30, "estimated_mb": 10000, "licence": "Check original UKPN resource terms"},
    "ukdale": {
        "url": None, "page": "https://jack-kelly.com/data/",
        "format": "watts", "minutes": 30, "estimated_mb": None, "licence": "Check individual archive terms"},
    "ideal": {
        "url": None, "page": "https://datashare.ed.ac.uk/items/15e82917-56ed-4282-99ef-7f211bf87f9d",
        "format": None, "minutes": None, "estimated_mb": None, "licence": "Check Edinburgh Datashare file terms"},
}

def fetch(key, destination, max_mb=32, allow_large=False):
    item = SOURCES[key]
    if not item["url"]:
        raise ValueError("No direct downloader; obtain from " + item["page"])
    if not 1 <= max_mb <= 10000:
        raise ValueError("Invalid max-mb")
    if item["estimated_mb"] and item["estimated_mb"] > max_mb and not allow_large:
        raise ValueError("Large download: pass --allow-large --max-mb NUMBER")
    dest = Path(destination)
    if dest.exists():
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(item["url"], headers={"User-Agent": "domestic-energy-analysis/0.3"})
    name = None
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            length = response.headers.get("Content-Length")
            if length and int(length) > max_mb * 1024 * 1024:
                raise ValueError("Server size exceeds download cap")
            with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False) as f:
                name = f.name
                digest = hashlib.sha256()
                size = 0
                while True:
                    buf = response.read(1024 * 1024)
                    if not buf:
                        break
                    size += len(buf)
                    if size > max_mb * 1024 * 1024:
                        raise ValueError("Download size exceeds cap")
                    f.write(buf)
                    digest.update(buf)
        os.replace(name, dest)
    except BaseException:
        if name:
            Path(name).unlink(missing_ok=True)
        raise
    meta = {"key": key, "source": item["url"], "page": item["page"],
            "licence": item["licence"], "bytes": size, "sha256": digest.hexdigest()}
    dest.with_name(dest.name + ".source.json").write_text(json.dumps(meta, indent=2) + "\n")
    return meta

def open_source(path, member=None):
    """Return a context manager for a CSV/TXT, gzipped file or explicit ZIP member."""
    from contextlib import contextmanager
    @contextmanager
    def opener():
        p = Path(path)
        if p.suffix.lower() == ".zip":
            with zipfile.ZipFile(p) as archive:
                choices = [n for n in archive.namelist() if n.lower().endswith((".csv", ".txt"))]
                chosen = member or (choices[0] if len(choices) == 1 else None)
                if chosen not in choices:
                    raise ValueError("Specify --member; available: " + repr(choices[:20]))
                with archive.open(chosen) as b, io.TextIOWrapper(b, encoding="utf-8-sig", newline="") as f:
                    yield f
        elif p.suffix.lower() == ".gz":
            with gzip.open(p, "rt", encoding="utf-8-sig", newline="") as f:
                yield f
        else:
            with p.open("r", encoding="utf-8-sig", newline="") as f:
                yield f
    return opener()

def number(s):
    if s is None or str(s).strip().lower() in ("", "nan", "null", "?"):
        return None
    n = float(s)
    if not math.isfinite(n) or n < 0:
        raise ValueError("Negative/non-finite reading: " + str(s))
    return n

def utc_local_time(naive, zone_name):
    z = ZoneInfo(zone_name)
    a = naive.replace(tzinfo=z, fold=0).astimezone(timezone.utc)
    b = naive.replace(tzinfo=z, fold=1).astimezone(timezone.utc)
    if a != b or a.astimezone(z).replace(tzinfo=None) != naive:
        return None
    return a

def opsd(path, household, minutes, mode, member=None):
    if household not in {f"residential{i}" for i in range(1, 7)}:
        raise ValueError("Use residential1 through residential6")
    if mode not in ("interval", "counter"):
        raise ValueError("Invalid value mode")
    base = "DE_KN_" + household + "_"
    mapping = {"grid_import": "consumption_kwh", "heat_pump": "heat_pump_kwh",
               "ev": "ev_kwh", "pv": "pv_kwh"}
    with open_source(path, member) as f:
        rdr = csv.DictReader(f)
        if not rdr.fieldnames or "utc_timestamp" not in rdr.fieldnames or base + "grid_import" not in rdr.fieldnames:
            raise ValueError("Invalid OPSD header/household")
        previous = None
        for row in rdr:
            t = datetime.fromisoformat(row["utc_timestamp"].strip().replace("Z", "+00:00"))
            if t.tzinfo is None:
                raise ValueError("OPSD timestamps require UTC offset")
            t = t.astimezone(timezone.utc)
            values = {name: number(row.get(base + name)) for name in mapping}
            if mode == "interval":
                if values["grid_import"] is None:
                    continue
                result = {"start_utc": t.isoformat(), "duration_minutes": minutes}
                result.update({target: values[source] for source, target in mapping.items() if values[source] is not None})
                yield result
            else:
                if previous is not None:
                    old_t, old = previous
                    if t <= old_t:
                        raise ValueError("Counter timestamps must increase")
                    if t - old_t == timedelta(minutes=minutes) and old["grid_import"] is not None and values["grid_import"] is not None:
                        diff = {k: values[k] - old[k] if values[k] is not None and old[k] is not None else None for k in mapping}
                        if diff["grid_import"] is not None and diff["grid_import"] >= -1e-6:
                            out = {"start_utc": old_t.isoformat(), "duration_minutes": minutes}
                            out.update({target: max(0, diff[source]) for source, target in mapping.items()
                                        if diff[source] is not None and diff[source] >= -1e-6})
                            yield out
                previous = (t, values)

def uci(path, minutes=30, member=None):
    """UCI global active power is minute-average kW, NOT minute kWh."""
    with open_source(path, member) as f:
        rdr = csv.DictReader(f, delimiter=";")
        if not {"Date", "Time", "Global_active_power"}.issubset(rdr.fieldnames or []):
            raise ValueError("Invalid UCI header")
        bucket, samples = None, {}
        for row in rdr:
            try:
                naive = datetime.strptime(row["Date"] + " " + row["Time"], "%d/%m/%Y %H:%M:%S")
            except ValueError:
                continue
            t = utc_local_time(naive, "Europe/Paris")
            v = number(row.get("Global_active_power"))
            if t is None or v is None:
                continue
            start = t.replace(minute=(t.minute // minutes)*minutes, second=0, microsecond=0)
            if bucket is not None and start < bucket:
                raise ValueError("Unordered UCI data")
            if bucket is not None and start != bucket:
                if len(samples) == minutes:
                    yield {"start_utc": bucket.isoformat(), "duration_minutes": minutes,
                           "consumption_kwh": sum(samples.values()) / 60}
                samples = {}
            bucket = start
            if t not in samples:
                samples[t] = v
        if bucket is not None and len(samples) == minutes:
            yield {"start_utc": bucket.isoformat(), "duration_minutes": minutes,
                   "consumption_kwh": sum(samples.values()) / 60}

def watts(path, minutes=30, member=None, headerless=False, max_gap=16, min_coverage=.95):
    """Integrate stepwise W until next reading, only where observed gaps <= max_gap."""
    bins = defaultdict(lambda: [0., 0.])
    previous = None
    with open_source(path, member) as f:
        rows = (dict(zip(("Unix", "Aggregate"), line.split())) for line in f if line.strip()) if headerless else csv.DictReader(f)
        for row in rows:
            try:
                t = int(float(row["Unix"]))
                power = number(row.get("Aggregate"))
            except (TypeError, ValueError, KeyError):
                previous = None
                continue
            if power is None:
                previous = None
                continue
            if previous is not None:
                prev_t, prev_power = previous
                if t <= prev_t:
                    raise ValueError("Unordered power telemetry")
                if t-prev_t <= max_gap:
                    current = prev_t
                    while current < t:
                        key = current // (minutes*60) * (minutes*60)
                        end = min(t, key + minutes*60)
                        seconds = end-current
                        bins[key][0] += prev_power*seconds/3600000
                        bins[key][1] += seconds
                        current = end
            previous = t, power
    for key, (energy, seconds) in sorted(bins.items()):
        if seconds >= min_coverage * minutes*60:
            yield {"start_utc": datetime.fromtimestamp(key, timezone.utc).isoformat(),
                   "duration_minutes": minutes, "consumption_kwh": energy}

def write_intervals(rows, destination):
    dest = Path(destination)
    if dest.exists():
        raise FileExistsError(str(dest))
    dest.parent.mkdir(parents=True, exist_ok=True)
    fields = ("start_utc", "consumption_kwh", "duration_minutes",
              "heat_pump_kwh", "ev_kwh", "pv_kwh")
    tmp = None
    n, total, end_prior = 0, 0., None
    try:
        with tempfile.NamedTemporaryFile(dir=dest.parent, mode="w", encoding="utf-8", newline="", delete=False) as f:
            tmp = f.name
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                t = datetime.fromisoformat(row["start_utc"].replace("Z", "+00:00"))
                if t.tzinfo is None:
                    raise ValueError("Missing timestamp offset")
                t = t.astimezone(timezone.utc)
                duration = int(row["duration_minutes"])
                if duration not in (15, 30, 60):
                    raise ValueError("Invalid interval duration")
                if end_prior and t < end_prior:
                    raise ValueError("Duplicate/overlapping intervals")
                energy = number(row["consumption_kwh"])
                if energy is None:
                    raise ValueError("Blank energy")
                writer.writerow({**row, "start_utc": t.isoformat(), "consumption_kwh": round(energy, 9)})
                n += 1
                total += energy
                end_prior = t + timedelta(minutes=duration)
        if not n:
            raise ValueError("No complete valid intervals")
        os.replace(tmp, dest)
    except BaseException:
        if tmp:
            Path(tmp).unlink(missing_ok=True)
        raise
    summary = {"interval_count": n, "observed_kwh": round(total, 6),
               "warning": "Observed periods only; no annualization or missing-period zero filling."}
    dest.with_name(dest.name + ".metadata.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    subs = p.add_subparsers(dest="command", required=True)
    subs.add_parser("list")
    d = subs.add_parser("fetch")
    d.add_argument("dataset", choices=list(SOURCES))
    d.add_argument("--out", required=True)
    d.add_argument("--max-mb", type=int, default=32)
    d.add_argument("--allow-large", action="store_true")
    c = subs.add_parser("convert")
    c.add_argument("dataset", choices=list(SOURCES))
    c.add_argument("--input", required=True)
    c.add_argument("--out", required=True)
    c.add_argument("--household", default="residential4")
    c.add_argument("--minutes", type=int)
    c.add_argument("--member")
    c.add_argument("--value-mode", choices=("interval", "counter"), default="counter",
                   help="OPSD publisher CSVs use cumulative counters (default)")
    args = p.parse_args(argv)
    try:
        if args.command == "list":
            print(json.dumps(SOURCES, indent=2))
            return 0
        if args.command == "fetch":
            info = fetch(args.dataset, args.out, args.max_mb, args.allow_large)
        else:
            item = SOURCES[args.dataset]
            minutes = args.minutes or item["minutes"]
            if minutes not in (15, 30, 60):
                raise ValueError("Unsupported interval length")
            if item["format"] == "opsd":
                rows = opsd(args.input, args.household, minutes, args.value_mode, args.member)
            elif item["format"] == "uci":
                rows = uci(args.input, minutes, args.member)
            elif item["format"] == "watts":
                rows = watts(args.input, minutes, args.member, headerless=args.dataset == "ukdale")
            elif item["format"] == "lcl":
                from domestic_energy.real_meter import import_lcl
                bundle = import_lcl([args.input], args.household, timestamp_mode="utc_end")
                rows = bundle["rows"]
            else:
                raise ValueError("IDEAL requires matched-sensor selection; see research/PUBLIC_DATASETS.md")
            info = write_intervals(rows, args.out)
        print(json.dumps(info, indent=2))
        return 0
    except (ValueError, FileNotFoundError, FileExistsError, OSError, zipfile.BadZipFile) as err:
        print("public-data: " + str(err), file=sys.stderr)
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
