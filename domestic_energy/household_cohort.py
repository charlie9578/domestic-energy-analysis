"""Convert publisher OPSD cumulative readings to aligned half-hourly import."""
import csv
from collections import defaultdict
from datetime import timedelta

from .core import timestamp_utc
from .dataset_hub import number


def opsd_halfhours(source, households, *, start, end):
    """Read three consecutive quarter-hour boundaries per half-hour.

    Preserve the publisher's interpolation flag so study callers can exclude
    those intervals while retaining the downloadable full-coverage series.
    """
    columns = {home: f"DE_KN_{home}_grid_import" for home in households}
    records = defaultdict(list)
    quarter = timedelta(minutes=15)
    rows = csv.DictReader(source)
    if not {"utc_timestamp", "interpolated", *columns.values()}.issubset(rows.fieldnames or []):
        raise ValueError("Missing OPSD timestamp, interpolation flag or household column")
    previous_time = None
    boundaries = []
    for row in rows:
        stamp = timestamp_utc(row["utc_timestamp"])
        if stamp < start:
            continue
        if stamp > end:
            break
        if previous_time is not None and stamp <= previous_time:
            raise ValueError("OPSD timestamps must be strictly increasing")
        previous_time = stamp
        flags = {item.strip() for item in row["interpolated"].split("|")}
        boundaries.append((stamp, row, flags))
        boundaries = boundaries[-3:]
        if len(boundaries) < 3 or stamp.minute not in (0, 30) or stamp.second or stamp.microsecond:
            continue
        first, middle, last = boundaries
        if middle[0] - first[0] != quarter or last[0] - middle[0] != quarter:
            continue
        for home, column in columns.items():
            left, midpoint, right = (number(boundary[1][column]) for boundary in boundaries)
            if None in (left, midpoint, right) or not left <= midpoint <= right:
                continue
            records[home].append({
                "start_utc": first[0].isoformat(), "duration_minutes": 30,
                "consumption_kwh": round(right - left, 6),
                "publisher_interpolated": int(any(column in boundary[2] for boundary in boundaries)),
            })
    return dict(records)
