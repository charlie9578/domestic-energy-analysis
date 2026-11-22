"""Interpretable weather-aware daily consumption forecasts, no ML dependencies.

Dates are local civil days; source weather MUST already be aggregated to matching
local dates. Never treat absent readings as zero. This is conditional prediction,
not a causal occupancy or retrofit estimate.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import cos, isfinite, pi, sin
from statistics import mean, median


FEATURES = ('constant', 'heating_degree_days', 'cooling_degree_days', 'weekend',
            'work_from_home', 'away', 'heating_degree_days_x_away',
            'heating_degree_days_x_work_from_home', 'sin_year', 'cos_year')


def _float(value: object, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not isfinite(number):
        raise ValueError(f'{name} must be finite')
    return number


def _day(row: dict) -> date:
    try:
        return date.fromisoformat(str(row['date']))
    except (KeyError, ValueError) as exc:
        raise ValueError('date must be YYYY-MM-DD') from exc


def _flag(row: dict, name: str) -> float:
    value = row.get(name, '')
    if value is None or str(value).strip() == '':
        return 0.0
    v = str(value).strip().lower()
    if v in ('1', 'true', 'yes', 'y'):
        return 1.0
    if v in ('0', 'false', 'no', 'n'):
        return 0.0
    raise ValueError(f'{name} must be a boolean flag')


def feature_vector(row: dict, balance_c: float, cooling_c: float = 22) -> list[float]:
    d = _day(row)
    t = _float(row['temperature_c'], 'temperature_c')
    angle = 2 * pi * (d.timetuple().tm_yday - 1) / (366 if d.year % 4 == 0 and (d.year % 100 or d.year % 400 == 0) else 365)
    hdd = max(0., balance_c - t)
    away = _flag(row, 'away')
    wfh = _flag(row, 'work_from_home')
    return [1., hdd, max(0., t - cooling_c),
            float(d.weekday() >= 5), wfh, away, hdd*away, hdd*wfh,
            sin(angle), cos(angle)]


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with pivoting; regularisation applied by caller."""
    n = len(b)
    matrix = [list(a[i]) + [b[i]] for i in range(n)]
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: abs(matrix[j][i]))
        if abs(matrix[pivot][i]) < 1e-13:
            raise ValueError('Regression matrix singular; increase regularisation')
        matrix[i], matrix[pivot] = matrix[pivot], matrix[i]
        for j in range(i + 1, n):
            scale = matrix[j][i] / matrix[i][i]
            for k in range(i, n + 1):
                matrix[j][k] -= matrix[i][k] * scale
    result = [0.] * n
    for i in reversed(range(n)):
        result[i] = (matrix[i][n] - sum(matrix[i][j] * result[j] for j in range(i + 1, n))) / matrix[i][i]
    return result


def _fit(rows: list[dict], balance_c: float, ridge: float) -> list[float]:
    xs = [feature_vector(r, balance_c) for r in rows]
    ys = [_float(r['consumption_kwh'], 'consumption_kwh') for r in rows]
    if any(y < 0 for y in ys):
        raise ValueError('Daily consumption must be >= 0 (grid export belongs in its own column)')
    cols = len(FEATURES)
    scales = [1.] + [max(1., (sum(x[j] ** 2 for x in xs) / len(xs)) ** 0.5)
                     for j in range(1, cols)]
    xscaled = [[x[j] / scales[j] for j in range(cols)] for x in xs]
    gram = [[sum(x[i] * x[j] for x in xscaled) for j in range(cols)] for i in range(cols)]
    rhs = [sum(x[i] * y for x, y in zip(xscaled, ys)) for i in range(cols)]
    # Small ridge on features (not intercept), enough to stabilize missing categories.
    for i in range(1, cols):
        # Reduce annual-season/HDD collinearity: temperature sensitivity is
        # favoured over calendar harmonics for gas heating. This is a prior,
        # not an identification guarantee for building envelope heat loss.
        factor = (.02 if FEATURES[i] == 'heating_degree_days' else
                  .05 if FEATURES[i] == 'heating_degree_days_x_away' else
                  .5 if FEATURES[i].startswith('heating_degree_days_x_') else
                  10 if FEATURES[i] in ('sin_year', 'cos_year') else 1)
        gram[i][i] += ridge * len(rows) * factor
    gram[0][0] += 1e-12
    solution = _solve(gram, rhs)
    return [solution[i] / scales[i] for i in range(cols)]


def _estimate(row: dict, balance_c: float, coefficients: list[float]) -> float:
    return max(0., sum(a * b for a, b in zip(feature_vector(row, balance_c), coefficients)))


def _score(actual: list[float], predicted: list[float]) -> dict:
    if not actual:
        return {'mae_kwh_day': None, 'mean_bias_kwh_day': None, 'wape_fraction': None}
    residuals = [p - y for p, y in zip(predicted, actual)]
    return {'mae_kwh_day': round(mean(abs(x) for x in residuals), 4),
            'mean_bias_kwh_day': round(mean(residuals), 4),
            'wape_fraction': round(sum(abs(r) for r in residuals) / sum(actual), 4)
                if sum(actual) else None}


def fit_daily_model(rows: list[dict], *, fuel: str = 'gas', ridge: float = 0.02,
                    candidate_balance_c: tuple[int, ...] = (12, 14, 15, 16, 18),
                    holdout_fraction: float = 0.2, boiler_efficiency: float | None = None,
                    floor_area_m2: float | None = None) -> dict:
    """Fit an HDD model with an inner chronological split for base selection.

    The outer holdout is used only for final evaluation.
    Positive gas heating gradient can be turned into an *indicative* HLC when
    boiler efficiency is provided; it does NOT measure a building fabric U value.
    """
    if fuel not in ('gas', 'electricity', 'delivered_heat'):
        raise ValueError('fuel must be gas, electricity or delivered_heat')
    if not isfinite(ridge) or ridge <= 0:
        raise ValueError('ridge must be positive and finite')
    if not 0.1 <= holdout_fraction <= 0.4:
        raise ValueError('holdout_fraction must be 0.1..0.4')
    if boiler_efficiency is not None and not 0 < boiler_efficiency <= 1:
        raise ValueError('boiler efficiency must be in (0,1]')
    if floor_area_m2 is not None and not 1 <= floor_area_m2 <= 2000:
        raise ValueError('floor area must be between 1 and 2000 m2')
    if not candidate_balance_c or any(not 5 <= b <= 25 for b in candidate_balance_c):
        raise ValueError('Balance temperatures must be 5..25 C')
    ordered = sorted(rows, key=_day)
    if len(ordered) < 42 or len({_day(r) for r in ordered}) != len(ordered):
        raise ValueError('Require at least 42 distinct daily readings (no duplicate dates)')
    for r in ordered:
        if _float(r['consumption_kwh'], 'consumption_kwh') < 0:
            raise ValueError('Daily consumption must be >= 0')
        feature_vector(r, 15)
    cut = len(ordered) - max(10, round(len(ordered) * holdout_fraction))
    train, holdout = ordered[:cut], ordered[cut:]
    actual = [float(r['consumption_kwh']) for r in holdout]
    tune_cut = len(train) - max(7, round(len(train) * .2))
    fit_rows, tuning = train[:tune_cut], train[tune_cut:]
    candidates = []
    for base in candidate_balance_c:
        params = _fit(fit_rows, float(base), ridge)
        error = mean(abs(_estimate(row, float(base), params) - float(row['consumption_kwh']))
                     for row in tuning)
        candidates.append((error, base))
    _, balance_c = min(candidates)
    params = _fit(train, float(balance_c), ridge)
    predictions = [_estimate(row, float(balance_c), params) for row in holdout]
    errors = sorted(abs(p - y) for p, y in zip(predictions, actual))
    holdout_p90_abs_error = errors[min(len(errors)-1, int(0.9 * len(errors)))]
    heating_gradient = max(0, params[1])
    # gas kWh/(C.day) * boiler output efficiency / 24h gives kW/K.
    # Delivered heat input directly, no boiler efficiency conversion.
    hc = heating_gradient * ((boiler_efficiency or 1.) if fuel == 'gas' else 1.) * 1000 / 24
    # Electricity includes non-space-heating and unknown heating tech: refuse to claim HLC.
    if fuel == 'electricity' or (fuel == 'gas' and boiler_efficiency is None):
        hc = None
    result = {
        'model': 'daily_HDD_ridge_time_ordered_holdout', 'fuel': fuel,
        'n_train': len(train), 'n_holdout': len(holdout),
        'train_first_date': str(_day(train[0])), 'train_last_date': str(_day(train[-1])),
        'holdout_first_date': str(_day(holdout[0])), 'holdout_last_date': str(_day(holdout[-1])),
        'balance_temperature_c': balance_c,
        'coefficients_kwh_day': dict(zip(FEATURES, (round(p, 6) for p in params))),
        'holdout': _score(actual, predictions),
        'holdout_p90_absolute_error_kwh_day': round(holdout_p90_abs_error, 3),
        'indicative_heat_loss_coefficient_w_per_k': round(hc, 1) if hc is not None else None,
        'indicative_heat_loss_w_per_k_m2': round(hc / floor_area_m2, 2) if hc is not None and floor_area_m2 else None,
        'note': 'Weather/behaviour correlations, not causal insulation measurement. True HLC needs internal temperature, gains, heating system efficiency, ventilation, and dedicated monitoring.',
    }
    return result


def predict_daily(model: dict, rows: list[dict]) -> list[dict]:
    if not model.get('coefficients_kwh_day'):
        raise ValueError('No fitted model parameters')
    coeff = [float(model['coefficients_kwh_day'][name]) for name in FEATURES]
    base = float(model['balance_temperature_c'])
    err = float(model.get('holdout_p90_absolute_error_kwh_day', 0))
    return [{'date': str(_day(r)), 'expected_kwh': round(_estimate(r, base, coeff), 3),
             'indicative_lower_kwh': round(max(0, _estimate(r, base, coeff) - err), 3),
             'indicative_upper_kwh': round(_estimate(r, base, coeff) + err, 3)}
            for r in rows]


def compare_weather_periods(model: dict, reference_days: list[dict], alternative_days: list[dict]) -> dict:
    """Contrast expected demand under two weather/occupancy sets of matching length.

    A controlled weather normalisation uses identical holiday/WFH flags in both sets.
    """
    if len(reference_days) != len(alternative_days):
        raise ValueError('Periods must have same number of days')
    ref = sum(x['expected_kwh'] for x in predict_daily(model, reference_days))
    alt = sum(x['expected_kwh'] for x in predict_daily(model, alternative_days))
    return {'reference_expected_kwh': round(ref, 2), 'alternative_expected_kwh': round(alt, 2),
            'difference_kwh': round(alt - ref, 2),
            'note': 'Forecast comparison assumes fitted relationships stable; not a causal impact estimate.'}
