"""Chronological half-hourly import benchmarks and an energy-conserving replay."""
from collections import defaultdict
from datetime import timedelta
from itertools import groupby
from math import isfinite
from random import Random
from statistics import mean, median, quantiles
from zoneinfo import ZoneInfo

from .core import timestamp_utc

HALF_HOUR = timedelta(minutes=30)
WEEK = timedelta(days=7)
BERLIN = ZoneInfo("Europe/Berlin")


def eligible_intervals(rows):
    result = {}
    seen = set()
    for row in rows:
        stamp = timestamp_utc(row["start_utc"])
        value = float(row["consumption_kwh"])
        flag = str(row.get("publisher_interpolated", 0))
        if (stamp in seen or stamp.minute not in (0, 30) or stamp.second or stamp.microsecond
                or int(row["duration_minutes"]) != 30 or not isfinite(value) or value < 0
                or flag not in ("0", "1")):
            raise ValueError("Expected distinct, nonnegative, aligned half-hour readings")
        seen.add(stamp)
        if flag == "0":
            result[stamp] = value
    return result


def tariff_pence(stamp):
    hour = stamp.astimezone(BERLIN).hour
    return 10 if hour < 5 else 30


def compare_forecasts(meter, *, start, end, draws=1000):
    """Day-ahead forecasts using only prior same-weekday UTC slots."""
    if start >= end or draws < 2:
        raise ValueError("Expected an increasing test window and at least two bootstrap draws")
    rows = []
    for stamp, actual in sorted(meter.items()):
        if not start <= stamp < end or stamp - WEEK not in meter:
            continue
        previous = [meter[stamp - k * WEEK] for k in range(1, 5) if stamp - k * WEEK in meter]
        rows.append((stamp, actual, previous[0], median(previous), mean(previous)))
    if not rows:
        raise ValueError("No shared forecast test slots")
    costs = [sum(row[i] * tariff_pence(row[0]) for row in rows) / 100 for i in (1, 2, 3, 4)]
    by_week = defaultdict(list)
    for stamp, actual, baseline, candidate, _ in rows:
        key = stamp.date() - timedelta(days=stamp.weekday())
        by_week[key].append(abs(candidate - actual) - abs(baseline - actual))
    blocks = list(by_week.values())
    rng = Random(26)
    samples = [mean(x for block in rng.choices(blocks, k=len(blocks)) for x in block)
               for _ in range(draws)] if len(blocks) >= 5 else []
    bounds = quantiles(samples, n=40, method="inclusive") if samples else None
    return {
        "shared_test_intervals": len(rows),
        "test_intervals_without_baseline": sum(start <= stamp < end for stamp in meter) - len(rows),
        "weekly_persistence_mae_kwh": round(mean(abs(base - y) for _, y, base, _, _ in rows), 4),
        "four_week_median_mae_kwh": round(mean(abs(pred - y) for _, y, _, pred, _ in rows), 4),
        "mae_difference_week_bootstrap_95_kwh": [round(bounds[0], 4), round(bounds[-1], 4)] if bounds else None,
        "priced_observed_test_slots_gbp": round(costs[0], 2),
        "priced_weekly_persistence_gbp": round(costs[1], 2),
        "priced_four_week_median_gbp": round(costs[2], 2),
        "priced_four_week_mean_gbp": round(costs[3], 2),
        "priced_observed_flat_27p_gbp": round(sum(row[1] for row in rows) * .27, 2),
    }


def shift_metered_charge(import_kwh, ev_kwh, price_pence):
    """Shift exactly the observed charge without exceeding observed peak powers.

    All slots represent equal-duration intervals. The caller must verify
    availability, import attribution, weather/solar conditions and tariff scope.
    """
    if not import_kwh or not (len(import_kwh) == len(ev_kwh) == len(price_pence)):
        raise ValueError("Import, charging and prices need the same non-empty window")
    if any(not isfinite(x) for x in (*import_kwh, *ev_kwh, *price_pence)):
        raise ValueError("Finite replay inputs required")
    if any(e < 0 or e > g for g, e in zip(import_kwh, ev_kwh)):
        raise ValueError("Charging must be bounded by observed import")
    peak = max(import_kwh)
    charger = max(ev_kwh)
    base = [g - e for g, e in zip(import_kwh, ev_kwh)]
    shifted = [0.] * len(base)
    energy = remaining = sum(ev_kwh)
    # Preserve the original schedule as far as the tariff optimum allows.
    ordered = sorted(range(len(base)), key=price_pence.__getitem__)
    for _, indices in groupby(ordered, key=price_pence.__getitem__):
        group = list(indices)
        for i in group:
            shifted[i] = min(remaining, ev_kwh[i])
            remaining -= shifted[i]
        for i in group:
            added = min(remaining, max(0, min(charger, peak - base[i]) - shifted[i]))
            shifted[i] += added
            remaining -= added
    if remaining > 1e-9:
        raise ValueError("Charging cannot be fulfilled within the window and caps")
    savings = sum((old - new) * price for old, new, price in zip(ev_kwh, shifted, price_pence)) / 100
    return {"grid_kwh": energy, "shifted_kwh": sum(max(0, a - b) for a, b in zip(ev_kwh, shifted)),
            "saving_gbp": savings, "original_ev_schedule_kwh": ev_kwh,
            "shifted_ev_schedule_kwh": shifted}
