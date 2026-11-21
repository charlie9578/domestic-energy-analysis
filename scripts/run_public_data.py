"""One-command local ingestion/analysis of approved public datasets.

Examples:
 python scripts/run_public_data.py --dataset opsd-hourly --fetch --household residential4
 python scripts/run_public_data.py --dataset uci --fetch
 python scripts/run_public_data.py --dataset refit-house1 --fetch --allow-large --max-mb 650
 python scripts/run_public_data.py --dataset lcl --input /path/to/block.csv --household MAC000002
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domestic_energy.dataset_hub import SOURCES, fetch, opsd, uci, watts, write_intervals


def run(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", choices=list(SOURCES), required=True)
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--fetch", action="store_true", help="Opt-in network fetch from allow-listed publisher")
    group.add_argument("--input", help="Previously downloaded dataset file; offline operation")
    p.add_argument("--out-dir", default="data/public")
    p.add_argument("--household", default="residential4")
    p.add_argument("--member", help="ZIP member to read, if more than one candidate")
    p.add_argument("--minutes", type=int)
    p.add_argument("--value-mode", choices=("interval", "counter"), default="interval")
    p.add_argument("--max-mb", type=int, default=32)
    p.add_argument("--allow-large", action="store_true")
    args = p.parse_args(argv)
    item = SOURCES[args.dataset]
    directory = Path(args.out_dir)
    raw = directory / "raw"
    processed = directory / "processed"
    if not args.household.isascii() or not args.household.isalnum():
        p.error("household IDs must contain letters/digits only")
    if item["format"] is None:
        p.error("IDEAL requires mapping sensors and metadata; follow the manual workflow in research/PUBLIC_DATASETS.md")
    if args.fetch:
        if not item["url"]:
            p.error("This dataset needs manual download; visit " + item["page"])
        filename = {
            "opsd-hourly": "household_data_60min_singleindex.csv",
            "opsd-quarterhour": "household_data_15min_singleindex.csv",
            "uci": "individual_household_electric_power_consumption.zip",
            "refit-house1": "CLEAN_House1.csv",
        }[args.dataset]
        src = raw / filename
        if src.exists():
            mf = Path(str(src) + ".source.json")
            if not mf.exists():
                p.error("Existing unverified source; use --input to opt in to locally supplied data")
            manifest = json.loads(mf.read_text())
            with src.open("rb") as f:
                digest = hashlib.file_digest(f, "sha256").hexdigest()
            if manifest.get("sha256") != digest or manifest.get("key") != args.dataset:
                p.error("Existing download checksum or source does not match manifest")
        else:
            fetch(args.dataset, src, max_mb=args.max_mb, allow_large=args.allow_large)
    else:
        src = Path(args.input)
        if not src.is_file():
            p.error(f"Missing source: {src}")
    minutes = args.minutes or item["minutes"]
    if minutes not in (15, 30, 60):
        p.error("Interval resolution must be 15, 30 or 60 minutes")
    processed.mkdir(parents=True, exist_ok=True)
    path = processed / f"{args.dataset}_{args.household}.csv"
    if path.exists():
        p.error(f"Output exists; refusing overwrite: {path}")
    if item["format"] == "opsd":
        rows = opsd(src, args.household, minutes, args.value_mode, args.member)
    elif item["format"] == "uci":
        rows = uci(src, minutes, args.member)
    elif item["format"] == "watts":
        rows = watts(src, minutes, args.member, headerless=args.dataset == "ukdale")
    elif item["format"] == "lcl":
        from domestic_energy.real_meter import import_lcl
        rows = import_lcl([src], args.household, timestamp_mode="utc_end")["rows"]
    result = write_intervals(rows, path)
    result.update(dataset=args.dataset, source_page=item["page"], input=str(src), output=str(path))
    report = processed / f"{args.dataset}_{args.household}.analysis.json"
    report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    print(f"Next: python -m domestic_energy meter --csv {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
