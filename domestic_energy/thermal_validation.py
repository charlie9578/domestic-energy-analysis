"""Daily heat signatures and chronological validation on co-monitored heat pumps."""
from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta, timezone
from math import isfinite
from random import Random
from statistics import mean, quantiles
from zoneinfo import ZoneInfo

from .forecast import _score

UK = ZoneInfo("Europe/London")


def monitored_days(rows, *, start: date, end: date):
    """Return October–April civil days with aligned, quality-filtered channels."""
    if start >= end:
        raise ValueError("Start must precede end")
    accepted, excluded, seen = [], Counter(), set()
    for row in rows:
        instant = datetime.fromtimestamp(float(row["timestamp"]), timezone.utc)
        local = instant.astimezone(UK)
        day = local.date()
        if not start <= day < end or 5 <= day.month <= 9:
            continue
        if local.time() != time() or day in seen:
            raise ValueError(f"Expected one local-midnight record for {day}")
        seen.add(day)
        next_day = datetime.combine(day + timedelta(days=1), time(), UK)
        hours = (next_day.astimezone(timezone.utc) - instant).total_seconds() / 3600
        try:
            indoor, outdoor, heat, electricity, duration = (
                float(row[key]) for key in ("combined_roomT_mean", "combined_outsideT_mean",
                                             "space_heat_kwh", "space_elec_kwh",
                                             "combined_data_length")
            )
            quality = [float(row[f"quality_{key}"]) for key in
                       ("elec", "heat", "roomT", "outsideT")]
            if not all(map(isfinite, [indoor, outdoor, heat, electricity, duration, *quality])):
                raise ValueError("Nonfinite value")
        except (KeyError, TypeError, ValueError):
            excluded["missing_or_nonfinite"] += 1
            continue
        if not .95 * hours * 3600 <= duration <= hours * 3600 or any(
            not 95 <= value <= 100 for value in quality
        ):
            excluded["coverage_or_quality"] += 1
            continue
        if not (5 <= indoor <= 35 and -35 <= outdoor <= 40 and heat >= 0 and electricity > 0):
            excluded["implausible_or_inactive"] += 1
            continue
        accepted.append({
            "date": day, "hours": hours, "indoor_c": indoor, "outdoor_c": outdoor,
            "space_heat_kwh": heat, "space_electricity_kwh": electricity,
        })
    expected = sum(
        not 5 <= (start + timedelta(days=offset)).month <= 9
        for offset in range((end - start).days)
    )
    excluded["no_source_day"] = expected - len(seen)
    return sorted(accepted, key=lambda row: row["date"]), dict(excluded)


def _fit(points):
    xs, ys = zip(*points)
    xbar, ybar = mean(xs), mean(ys)
    variation = sum((x - xbar)**2 for x in xs)
    if variation <= 1e-12:
        raise ValueError("No training temperature variation")
    slope = sum((x - xbar) * (y - ybar) for x, y in points) / variation
    return ybar - slope * xbar, slope


def _weeks(rows, values):
    grouped = defaultdict(list)
    for row, value in zip(rows, values, strict=True):
        day = row["date"]
        grouped[day - timedelta(days=day.weekday())].append(value)
    return list(grouped.values())


def _interval(weeks, statistic, *, seed, resamples):
    rng = Random(seed)
    draws = []
    for _ in range(resamples):
        sample = [value for week in rng.choices(weeks, k=len(weeks)) for value in week]
        try:
            draws.append(statistic(sample))
        except ValueError:  # A resample can have no temperature variation.
            continue
    if len(draws) < .95 * resamples:
        raise ValueError("Too many unidentifiable bootstrap samples")
    bounds = quantiles(draws, n=40, method="inclusive")
    return [round(bounds[0], 4), round(bounds[-1], 4)]


def validate_signature(days, *, split: date, resamples=1000, seed=26):
    """Fit average delivered heat power vs temperature difference on earlier days."""
    if resamples < 100:
        raise ValueError("At least 100 bootstrap replicates required")
    days = sorted(days, key=lambda row: row["date"])
    if len({row["date"] for row in days}) != len(days):
        raise ValueError("Duplicate day in validation input")
    train = [row for row in days if row["date"] < split]
    test = [row for row in days if row["date"] >= split]
    train_weeks = _weeks(train, train)
    test_weeks = _weeks(test, test)
    if min(len(train), len(test)) < 30 or min(len(train_weeks), len(test_weeks)) < 8:
        raise ValueError("Need at least 30 days and eight calendar weeks per partition")

    def delta(row):
        return row["indoor_c"] - row["outdoor_c"]

    def average_power(row):
        return row["space_heat_kwh"] / row["hours"]

    actual = [row["space_heat_kwh"] for row in test]
    baseline_power = mean(map(average_power, train))
    baseline = [baseline_power * row["hours"] for row in test]
    signatures, absolute_errors = {}, {}
    for name, feature in (("outdoor_only", lambda row: -row["outdoor_c"]),
                          ("indoor_outdoor", delta)):
        points = [(feature(row), average_power(row)) for row in train]
        intercept, slope = _fit(points)
        predicted = [max(0, intercept + slope * feature(row)) * row["hours"] for row in test]
        errors = [abs(y - p) for y, p in zip(actual, predicted, strict=True)]
        absolute_errors[name] = errors
        paired = [error - abs(y - b)
                  for error, y, b in zip(errors, actual, baseline, strict=True)]
        low, high = min(x for x, _ in points), max(x for x, _ in points)
        signatures[name] = {
            "intercept_kw": round(intercept, 5),
            "slope_w_per_k": round(slope * 1000, 4),
            "training_slope_week_bootstrap_95": _interval(
                _weeks(train, points), lambda values: _fit(values)[1] * 1000,
                seed=seed, resamples=resamples),
            "holdout": _score(actual, predicted),
            "holdout_mae_delta_vs_mean_week_bootstrap_95": _interval(
                _weeks(test, paired), mean, seed=seed, resamples=resamples),
            "holdout_days_outside_training_temperature_range": sum(
                not low <= feature(row) <= high for row in test),
        }
    paired_indoor = [indoor - outdoor for indoor, outdoor in zip(
        absolute_errors["indoor_outdoor"], absolute_errors["outdoor_only"], strict=True)]
    holdout_electricity = sum(row["space_electricity_kwh"] for row in test)
    return {
        "train_days": len(train), "test_days": len(test),
        "train_weeks": len(train_weeks), "test_weeks": len(test_weeks),
        "split_local_date": split.isoformat(),
        "training_mean_power_baseline_holdout": _score(actual, baseline),
        "signatures": signatures,
        "holdout_mae_delta_indoor_vs_outdoor_week_bootstrap_95": _interval(
            _weeks(test, paired_indoor), mean, seed=seed, resamples=resamples),
        "holdout_observed_space_heat_kwh": round(sum(actual), 3),
        "holdout_observed_space_electricity_kwh": round(holdout_electricity, 3),
        "holdout_observed_space_heat_to_electricity_ratio": round(sum(actual) / holdout_electricity, 4),
    }
