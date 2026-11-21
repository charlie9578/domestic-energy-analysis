"""Conservative, explainable clues from half-hourly *aggregate* meters.

Signals are hypotheses, not a claim to identify an appliance or a resident's
location. Designed for opt-in, local analysis of the household's own data.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from math import isfinite
from statistics import mean, median
from zoneinfo import ZoneInfo

from .core import _canonical_interval, timestamp_utc


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.
    return ordered[round((len(ordered) - 1) * fraction)]


def _intervals(rows: list[dict]) -> list[tuple]:
    items = sorted(_canonical_interval(r) for r in rows)
    for i in range(1, len(items)):
        if items[i][0] < items[i-1][0] + timedelta(minutes=items[i-1][2]):
            raise ValueError('Overlapping or duplicate meter intervals')
    return items


def interval_profile(rows: list[dict], *, timezone_name: str = 'Europe/London') -> dict:
    """Typical observed 30m equivalent by day-type/hour, local clock with DST handled in UTC.

    No pretending a non-contiguous sample is complete; low-count buckets noted.
    """
    tz = ZoneInfo(timezone_name)
    observations = defaultdict(list)
    for start, kwh, minutes in _intervals(rows):
        local = start.astimezone(tz)
        key = ('weekend' if local.weekday() >= 5 else 'weekday', local.hour)
        observations[key].append(kwh * 30 / minutes)
    return {'timezone': timezone_name, 'units': 'kWh per 30-minute-equivalent interval',
            'buckets': [{'day_type': day, 'hour': hour,
                         'median_kwh': round(median(observations[day, hour]), 5)
                             if observations[day, hour] else None,
                         'samples': len(observations[day, hour])}
                        for day in ('weekday', 'weekend') for hour in range(24)],
            'note': 'Unobserved time slots have null medians, not zero usage.'}


def expected_intervals_from_daily(daily_forecasts: list[dict], historical_intervals: list[dict],
                                  target_slots: list[dict], *, timezone_name: str = 'Europe/London') -> list[dict]:
    """Distribute weather-conditioned daily kWh using weekday/weekend local-hour shapes.

    Requires a list of UTC slots; weights normalised within each local day,
    so 23/25-hour DST days receive the right number of intervals. Missing days
    are errors rather than guesses. This gives EXPECTED shapes, not billable data.
    """
    profile = interval_profile(historical_intervals, timezone_name=timezone_name)
    buckets = {(r['day_type'], r['hour']): r['median_kwh'] for r in profile['buckets']}
    all_medians = [v for v in buckets.values() if v is not None]
    if not all_medians:
        raise ValueError('Need historical intervals to estimate a profile')
    fallback = median(all_medians)
    forecast = {r['date']: float(r['expected_kwh']) for r in daily_forecasts}
    tz = ZoneInfo(timezone_name)
    days = defaultdict(list)
    for slot in _intervals(target_slots):
        t, _, duration = slot
        d = t.astimezone(tz)
        key = d.date().isoformat()
        if key not in forecast:
            raise ValueError(f'Missing daily weather forecast for {key}')
        bucket = ('weekend' if d.weekday() >= 5 else 'weekday', d.hour)
        weight = buckets[bucket] if buckets[bucket] is not None else fallback
        days[key].append((t, duration, max(0., weight * duration / 30)))
    output = []
    for day, slots in days.items():
        total_weight = sum(x[2] for x in slots)
        for t, minutes, weight in slots:
            output.append({'start_utc': t.isoformat(), 'duration_minutes': minutes,
                           'expected_kwh': round(forecast[day] * (weight / total_weight if total_weight else 1 / len(slots)), 5),
                           'date': day})
    return sorted(output, key=lambda r: r['start_utc'])


def _events_for_runs(slots: list[tuple], predicate, *, min_slots: int) -> list[list[tuple]]:
    events, current = [], []
    for entry in slots:
        if predicate(entry):
            if current and current[-1][0] + timedelta(minutes=current[-1][2]) != entry[0]:
                if len(current) >= min_slots:
                    events.append(current)
                current = []
            current.append(entry)
        else:
            if len(current) >= min_slots:
                events.append(current)
            current = []
    if len(current) >= min_slots:
        events.append(current)
    return events


def detect_ev_candidates(rows: list[dict], *, timezone_name: str = 'Europe/London',
                         min_power_kw: float = 2.5, max_power_kw: float = 12,
                         min_hours: float = 1.5, max_variability_fraction: float = 0.35) -> list[dict]:
    """Detect sustained, fairly flat *excess load* that could be EV charging.

    A cooker, immersion heater or storage heater can look identical. Does not
    infer EV ownership, movement, or identity. Solar export can obscure loads.
    """
    if min_power_kw <= 0 or max_power_kw <= min_power_kw or min_hours < 0.5:
        raise ValueError('Invalid EV candidate thresholds')
    tz = ZoneInfo(timezone_name)
    slots = _intervals(rows)
    by_hour = defaultdict(list)
    for t, kwh, minutes in slots:
        by_hour[t.astimezone(tz).hour].append(kwh * 60 / minutes)
    low = {h: _percentile(v, .2) for h, v in by_hour.items()}
    candidates = []
    processed = [(t, max(0., kwh * 60 / minutes - low[t.astimezone(tz).hour]), minutes)
                 for t, kwh, minutes in slots]
    for run in _events_for_runs(processed, lambda s: min_power_kw <= s[1] <= max_power_kw, min_slots=1):
        hours = sum(s[2] for s in run) / 60
        if hours < min_hours:
            continue
        powers = [s[1] for s in run]
        if (max(powers) - min(powers)) / max(mean(powers), 0.001) > max_variability_fraction:
            continue
        candidates.append({
            'start_utc': run[0][0].isoformat(),
            'end_utc': (run[-1][0] + timedelta(minutes=run[-1][2])).isoformat(),
            'duration_hours': round(hours, 2),
            'mean_excess_kw': round(mean(powers), 2),
            'estimated_excess_kwh': round(sum(p * m / 60 for _, p, m in run), 2),
            'hypothesis': 'EV charging OR another sustained high-power load',
            'evidence': 'Near-flat elevated electricity demand relative to same-local-hour low quantile',
            'confidence': 'unverified candidate',
        })
    return candidates


def detect_gas_heating_runs(gas_rows: list[dict], weather_daily: list[dict], *,
                            timezone_name: str = 'Europe/London',
                            cold_below_c: float = 14, min_kw: float = 1.0) -> list[dict]:
    """Gas-use runs on cool days. Not boiler-on timestamps: gas includes DHW/cooking."""
    tz = ZoneInfo(timezone_name)
    temperatures = {r['date']: float(r['temperature_c']) for r in weather_daily}
    slots = _intervals(gas_rows)
    tagged = [(t, kwh * 60 / mins, mins) for t, kwh, mins in slots]
    cold = lambda e: (temperatures.get(e[0].astimezone(tz).date().isoformat(), 100) < cold_below_c
                      and e[1] >= min_kw)
    runs = _events_for_runs(tagged, cold, min_slots=1)
    return [{'start_utc': r[0][0].isoformat(),
             'end_utc': (r[-1][0] + timedelta(minutes=r[-1][2])).isoformat(),
             'hours': round(sum(e[2] for e in r) / 60, 2),
             'gas_kwh': round(sum(e[1] * e[2] / 60 for e in r), 2),
             'hypothesis': 'possible boiler space-heating activity',
             'confidence': 'unverified candidate',
             'warning': 'Could be hot water or cooking; half-hour aggregation cannot establish burner on/off.'}
            for r in runs]


def detect_low_activity_days(rows: list[dict], *, timezone_name: str = 'Europe/London',
                             min_consecutive_days: int = 3, fraction_of_typical: float = 0.45) -> list[dict]:
    """Identify multi-day unusually-low demand; NEVER asserts holiday or vacancy.

    Requires at least 14 distinct days, >=95% measured duration per day.
    Suppresses false absences for a low-consumption winter day by stating
    alternative explanations; weather normalisation should be applied separately.
    """
    if not 0 < fraction_of_typical < 1 or min_consecutive_days < 2:
        raise ValueError('Invalid low activity thresholds')
    tz = ZoneInfo(timezone_name)
    day_values = defaultdict(lambda: [0., 0.])
    for t, kwh, minutes in _intervals(rows):
        day = t.astimezone(tz).date()
        day_values[day][0] += kwh
        day_values[day][1] += minutes / 60
    full = {d: e for d, (e, hours) in day_values.items() if hours >= 22.8}
    if len(full) < 14:
        return []
    typical = median(full.values())
    if typical <= 0:
        return []
    low_days = sorted(d for d, e in full.items() if e <= typical * fraction_of_typical)
    groups: list[list] = []
    for day in low_days:
        if groups and groups[-1][-1] + timedelta(days=1) == day:
            groups[-1].append(day)
        else:
            groups.append([day])
    return [{'first_day': g[0].isoformat(), 'last_day': g[-1].isoformat(),
             'days': len(g), 'mean_kwh_day': round(mean(full[d] for d in g), 2),
             'typical_kwh_day': round(typical, 2),
             'hypothesis': 'unusually low activity; absence/holiday is one possibility',
             'confidence': 'unverified candidate',
             'alternatives': ['solar generation masking import', 'heating switched off',
                              'tariff/occupancy change', 'meter or data issue', 'mild weather']}
            for g in groups if len(g) >= min_consecutive_days]


def cold_weather_load_clue(rows: list[dict], weather_daily: list[dict], *,
                          timezone_name: str = 'Europe/London',
                          balance_temperature_c: float = 15.5) -> dict:
    """Univariate descriptive relationship, not appliance/system identification.

    Uses complete days and weather. Multi-sensor and occupancy/weather regression
    are needed to estimate physical loss rather than seasonal correlation.
    """
    tz = ZoneInfo(timezone_name)
    weather = {r['date']: float(r['temperature_c']) for r in weather_daily}
    daily = defaultdict(lambda: [0., 0.])
    for t, kwh, mins in _intervals(rows):
        local = t.astimezone(tz).date().isoformat()
        daily[local][0] += kwh
        daily[local][1] += mins / 60
    matched = [(max(0., balance_temperature_c-weather[d]), e)
               for d, (e, hours) in daily.items() if d in weather and hours >= 22.8]
    if len(matched) < 28 or len({round(x, 1) for x, _ in matched}) < 7:
        return {'status': 'insufficient_evidence', 'paired_complete_days': len(matched)}
    xx = [x for x, _ in matched]
    yy = [y for _, y in matched]
    xmean, ymean = mean(xx), mean(yy)
    varx = sum((x-xmean)**2 for x in xx)
    vary = sum((y-ymean)**2 for y in yy)
    slope = sum((x-xmean)*(y-ymean) for x,y in matched)/varx if varx else 0
    r2 = (sum((x-xmean)*(y-ymean) for x,y in matched)**2/(varx*vary)
          if varx and vary else 0)
    return {'status': 'temperature_responsive' if slope > .5 and r2 > .35 else 'not_conclusive',
            'paired_complete_days': len(matched), 'correlation_r_squared': round(r2, 3),
            'additional_kwh_per_heating_degree_day': round(slope, 3),
            'hypothesis': 'Space heating could contribute to aggregate cold-weather load',
            'warning': 'Weather sensitivity alone cannot establish gas/electric heating type, insulation level, or causality.'}


def daytime_activity_clues(rows: list[dict], *, timezone_name: str = 'Europe/London') -> dict:
    """Daytime electricity variation on weekdays; WFH/occupancy NOT established."""
    tz = ZoneInfo(timezone_name)
    daily = defaultdict(list)
    for t, kwh, mins in _intervals(rows):
        local = t.astimezone(tz)
        if local.weekday() < 5 and 9 <= local.hour < 17:
            daily[local.date().isoformat()].append((kwh*60/mins, mins))
    workdays = {d: mean(p for p,_ in items) for d,items in daily.items()
                if sum(m for _,m in items) >= 7.6*60}
    if len(workdays) < 14:
        return {'status':'insufficient_evidence', 'covered_weekdays':len(workdays)}
    baseline = median(workdays.values())
    raised = sorted(d for d,avg in workdays.items() if avg > max(.3,baseline*1.45))
    return {'status':'descriptive_only', 'typical_daytime_kw': round(baseline,3),
            'unusually_high_weekday_dates':raised,
            'hypothesis':'Possible daytime presence, appliances, EV, heating or charging',
            'warning':'Cannot infer who is at home or working from home from whole-home meter load.'}


def identify_system_clues(electric_rows: list[dict], *, gas_rows: list[dict] | None = None,
                          export_rows: list[dict] | None = None, weather_daily: list[dict] | None = None,
                          timezone_name: str = 'Europe/London') -> dict:
    """Explain evidence, and technologies NOT reliably identifiable from a single meter."""
    ev = detect_ev_candidates(electric_rows, timezone_name=timezone_name)
    absence = detect_low_activity_days(electric_rows, timezone_name=timezone_name)
    heating = detect_gas_heating_runs(gas_rows, weather_daily, timezone_name=timezone_name) if gas_rows and weather_daily else []
    electric_weather = cold_weather_load_clue(electric_rows, weather_daily, timezone_name=timezone_name) if weather_daily else None
    gas_weather = cold_weather_load_clue(gas_rows, weather_daily, timezone_name=timezone_name) if gas_rows and weather_daily else None
    daytime = daytime_activity_clues(electric_rows, timezone_name=timezone_name)
    clues = []
    if ev:
        clues.append({'technology': 'EV charger / immersion / storage heater / other flat high load',
                      'evidence': f'{len(ev)} sustained flat high-power runs', 'status': 'ambiguous'})
    if heating:
        clues.append({'technology': 'gas-fired heating possible',
                      'evidence': f'{len(heating)} gas use periods on cold days', 'status': 'ambiguous'})
    if export_rows:
        positive_export = sum(_canonical_interval(r)[1] for r in export_rows)
        if positive_export > 0:
            clues.append({'technology': 'export-capable generation or battery',
                          'evidence': f'{positive_export:.2f} kWh recorded exported',
                          'status': 'generation/export hardware suggested; solar NOT proven'})
    if electric_weather and electric_weather['status'] == 'temperature_responsive':
        clues.append({'technology': 'possible weather-responsive electric heating',
                      'evidence': electric_weather, 'status': 'ambiguous'})
    if gas_weather and gas_weather['status'] == 'temperature_responsive':
        clues.append({'technology': 'possible gas space heating',
                      'evidence': gas_weather, 'status': 'ambiguous'})
    return {'technology_clues': clues, 'ev_like_sessions': ev,
            'electricity_weather_sensitivity': electric_weather,
            'gas_weather_sensitivity': gas_weather, 'daytime_activity': daytime,
            'low_activity_spells': absence, 'gas_on_cold_days_runs': heating,
            'cannot_reliably_identify': ['heat-pump vs resistive heater from half-hour import only',
                'EV vs immersion heater/storage heating from flat demand only',
                'solar panels from reduced daytime import without generation/export telemetry',
                'battery presence, capacity or state of charge from import alone',
                'working from home, holiday or exact occupancy without corroboration'],
            'privacy': 'Only infer for opt-in local research. Do not use this for surveillance or high-stakes decisions.'}
