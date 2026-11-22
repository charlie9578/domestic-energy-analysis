"""Evaluate half-hourly forecasts and replay a measured EV channel under a sample tariff."""
import argparse
import hashlib
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

from domestic_energy.data import read_csv, write_json
from domestic_energy.demand_decisions import (
    BERLIN, HALF_HOUR, compare_forecasts, eligible_intervals, shift_metered_charge, tariff_pence,
)
from domestic_energy.household_cohort import opsd_halfhour_channels

START = datetime(2016, 1, 1, tzinfo=BERLIN).astimezone(timezone.utc)
TEST = datetime(2016, 10, 1, tzinfo=BERLIN).astimezone(timezone.utc)
END = datetime(2017, 1, 1, tzinfo=BERLIN).astimezone(timezone.utc)
HOMES = ("residential1", "residential2", "residential4", "residential5", "residential6")


def replay(source):
    columns = {key: f"DE_KN_residential4_{key}" for key in ("grid_import", "ev", "grid_export", "pv")}
    data = {key: eligible_intervals(rows) for key, rows in
            opsd_halfhour_channels(source, columns, start=START, end=END).items()}
    summaries = {}
    for deadline in (5, 7):
        exclusions = Counter()
        cases = []
        for i in range((date(2016, 12, 31) - date(2016, 1, 1)).days):
            evening = date(2016, 1, 1) + timedelta(days=i)
            start = datetime.combine(evening, time(20), BERLIN).astimezone(timezone.utc)
            end = datetime.combine(evening + timedelta(days=1), time(deadline), BERLIN).astimezone(timezone.utc)
            stamps = [start + k * HALF_HOUR for k in range((end - start) // HALF_HOUR)]
            if any(t not in data[key] for key in columns for t in stamps):
                exclusions["missing_or_flagged_channel"] += 1
                continue
            imports, ev, exports, pv = ([data[key][t] for t in stamps] for key in columns)
            if sum(ev) < 1:
                exclusions["less_than_one_kwh_observed"] += 1
                continue
            # This is a replay of window energy. Charge outside the window stays fixed.
            runs = sum(value > 0 and last == 0 for value, last in zip(ev, [0, *ev]))
            if runs != 1:
                exclusions["multiple_charging_blocks"] += 1
                continue
            if any(exports) or any(pv) or any(e > g for e, g in zip(ev, imports)):
                exclusions["solar_export_or_ev_exceeds_import"] += 1
                continue
            first = next(i for i, value in enumerate(ev) if value > 0)
            prices = [tariff_pence(t) for t in stamps[first:]]
            cases.append(shift_metered_charge(imports[first:], ev[first:], prices))
        summaries[str(deadline)] = {
            "eligible_windows": len(cases), "excluded_windows": dict(exclusions),
            "windows_with_lower_cost": sum(row["saving_gbp"] > 1e-8 for row in cases),
            "observed_ev_kwh_in_eligible_windows": round(sum(row["grid_kwh"] for row in cases), 3),
            "shifted_kwh": round(sum(row["shifted_kwh"] for row in cases), 3),
            "modelled_variable_cost_reduction_gbp": round(sum(row["saving_gbp"] for row in cases), 2),
        }
    return summaries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--derived", type=Path, default=Path("data/derived"))
    parser.add_argument("--opsd", type=Path, default=Path("data/raw/opsd_15min.csv"))
    parser.add_argument("--out", type=Path, default=Path("reports/demand_decisions.json"))
    args = parser.parse_args()
    models = {home: compare_forecasts(
        eligible_intervals(read_csv(args.derived / f"opsd_2016_{home}.csv")), start=TEST, end=END
    ) for home in HOMES}
    with args.opsd.open(newline="", encoding="utf-8-sig") as source:
        shifts = replay(source)
    with args.opsd.open("rb") as data:
        digest = hashlib.file_digest(data, "sha256").hexdigest()
    write_json(args.out, {"opsd_source_sha256": digest, "evaluation_start_utc": TEST.isoformat(), "end_exclusive_utc": END.isoformat(),
                          "illustrative_prices_p_per_kwh": {"00_to_05_local": 10, "05_to_24_local": 30},
                          "households": models, "ev_charge_replay_by_local_deadline": shifts})


if __name__ == "__main__":
    main()
