"""Fit and test a one-zone heat balance against measured room temperatures."""
from collections import defaultdict
from datetime import timedelta
from math import log1p
from random import Random
from statistics import mean, quantiles

from .forecast import _solve

HOUR = timedelta(hours=1)


def fit(rows):
    """Exact hourly discretisation for constant inputs and a single thermal state."""
    pairs = [(row["outdoor"] - row["indoor"], row["heat_kw"]) for row in rows]
    centres = [mean(values) for values in zip(*pairs)]
    ys = [row["next_indoor"] - row["indoor"] for row in rows]
    cols = [[value - centre for value in values]
            for values, centre in zip(zip(*pairs), centres)]
    a, b = _solve([[sum(x * y for x, y in zip(left, right)) for right in cols]
                   for left in cols], [sum(x * y for x, y in zip(col, ys)) for col in cols])
    c = mean(ys) - a * centres[0] - b * centres[1]
    if not 0 < a < 1 or b <= 0:
        raise ValueError("Training fit does not identify a positive, stable heat balance")
    return a, b, c


def parameters(model):
    a, b, c = model
    loss = a / b
    return {"heat_loss_w_per_k": loss * 1000,
            "effective_capacity_kwh_per_k": -loss / log1p(-a),
            "constant_gain_kw": c / b}


def predict(model, indoor, outdoor, delivered_kw):
    a, b, c = model
    return indoor + a * (outdoor - indoor) + b * delivered_kw + c


def block_samples(days, rng, replicates):
    blocks = list(days.values())
    for _ in range(replicates):
        yield [row for block in rng.choices(blocks, k=len(blocks)) for row in block]


def by_day(rows):
    days = defaultdict(list)
    for row in rows:
        days[row["start"].date()].append(row)
    return days


def interval(values):
    bounds = quantiles(values, n=40, method="inclusive")
    return [round(bounds[0], 4), round(bounds[-1], 4)]


def validate(rows, *, split, replicates=1000):
    """Hold out the later period. Condition forecasts on actual heat and weather."""
    train = [row for row in rows if row["start"] + HOUR <= split]
    test = {row["start"]: row for row in rows if row["start"] >= split}
    train_days = by_day(train)
    if len(train_days) < 5 or len(by_day(test.values())) < 5:
        raise ValueError("Need at least five days in each partition")
    result = {"training_hours": len(train), "test_hours": len(test)}
    try:
        model = fit(train)
    except ValueError as error:
        return {**result, "status": str(error)}
    rng = Random(26)
    samples = []
    for sample in block_samples(train_days, rng, replicates):
        try:
            samples.append(parameters(fit(sample)))
        except ValueError:
            continue
    estimates = parameters(model)
    result.update({
        "training_parameters": {key: round(value, 4) for key, value in estimates.items()},
        "physically_admissible_bootstrap_fraction": round(len(samples) / replicates, 4),
        "training_parameter_95_interval": {key: interval([sample[key] for sample in samples])
                                           for key in estimates} if len(samples) >= .95 * replicates else None,
    })
    scores = {}
    for horizon in (1, 6):
        errors = []
        for stamp, first in sorted(test.items()):
            if stamp.hour % horizon:
                continue
            window = [test.get(stamp + i * HOUR) for i in range(horizon)]
            if any(row is None for row in window):
                continue
            room = first["indoor"]
            for row in window:
                room = predict(model, room, row["outdoor"], row["heat_kw"])
            actual = window[-1]["next_indoor"]
            errors.append({"start": stamp, "model": room - actual,
                           "persistence": first["indoor"] - actual})
        days = by_day(errors)
        scores[str(horizon)] = {"windows": len(errors), "days": len(days)}
        if not errors:
            continue
        deltas = [mean(abs(row["model"]) - abs(row["persistence"]) for row in sample)
                  for sample in block_samples(days, rng, replicates)] if len(days) >= 5 else []
        scores[str(horizon)].update({
            "model_mae_c": round(mean(abs(row["model"]) for row in errors), 4),
            "persistence_mae_c": round(mean(abs(row["persistence"]) for row in errors), 4),
            "model_bias_c": round(mean(row["model"] for row in errors), 4),
            "mae_difference_day_bootstrap_95_c": interval(deltas) if deltas else None,
        })
    return {**result, "status": "fitted", "holdout": scores}
