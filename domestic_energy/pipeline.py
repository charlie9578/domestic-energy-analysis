"""Align meter periods, local-day weather, and *declared* household schedules."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .core import _canonical_interval


def join_daily_meter_weather(meter_rows: list[dict], weather_rows: list[dict], *,
                             occupancy_rows: list[dict] | None = None,
                             timezone_name: str = 'Europe/London',
                             min_coverage: float = .95) -> dict:
    """Join local *civil* days. Missing/partial days excluded and separately reported.

    Check DST day duration in UTC (23h/25h). Meter must have offset-aware
    timestamps; intervals crossing local midnight are split by duration.
    """
    if not 0 < min_coverage <= 1:
        raise ValueError('coverage threshold must be (0,1]')
    tz = ZoneInfo(timezone_name)
    weather = {}
    for r in weather_rows:
        d = r['date']
        if d in weather:
            raise ValueError('Duplicate weather local date')
        temp = float(r['temperature_c'])
        if not -100 < temp < 70:
            raise ValueError('Implausible weather temperature')
        weather[d] = temp
    occupancy = {}
    for r in occupancy_rows or []:
        day = r['date']
        if day in occupancy:
            raise ValueError('Duplicate occupancy local date')
        occupancy[day] = {'away': r.get('away', ''), 'work_from_home': r.get('work_from_home', '')}
    days = defaultdict(lambda: {'energy': 0., 'hours': 0.})
    ordered = sorted((_canonical_interval(r) for r in meter_rows), key=lambda x: x[0])
    if not ordered:
        raise ValueError('No meter data')
    for j in range(1, len(ordered)):
        if ordered[j][0] < ordered[j-1][0] + timedelta(minutes=ordered[j-1][2]):
            raise ValueError('Overlap or duplicate meter intervals')
    for start, energy, duration in ordered:
        end = start + timedelta(minutes=duration)
        cursor = start
        while cursor < end:
            day = cursor.astimezone(tz).date()
            local_midnight_next = datetime.combine(day+timedelta(days=1), time(), tzinfo=tz)
            cut = min(local_midnight_next.astimezone(timezone.utc), end)
            hours = (cut-cursor).total_seconds()/3600
            key = day.isoformat()
            days[key]['energy'] += energy * hours / (duration/60)
            days[key]['hours'] += hours
            cursor = cut
    accepted, excluded = [], []
    for day in sorted(days):
        d = datetime.fromisoformat(day).date()
        start_day = datetime.combine(d, time(), tzinfo=tz)
        end_day = datetime.combine(d+timedelta(days=1), time(), tzinfo=tz)
        expected_hours = (end_day.astimezone(timezone.utc)-start_day.astimezone(timezone.utc)).total_seconds()/3600
        covered = days[day]['hours']/expected_hours
        if covered > 1.00001:
            raise ValueError(f'Overlapping meter data for local date {day}')
        if covered < min_coverage or day not in weather:
            excluded.append({'date': day, 'observed_coverage_fraction': round(covered, 4),
                             'reason': 'missing_weather' if day not in weather else 'partial_day'})
            continue
        row = {'date': day, 'temperature_c': weather[day],
               'consumption_kwh': round(days[day]['energy'], 6),
               'coverage_fraction': round(covered, 5)}
        row.update(occupancy.get(day, {}))
        accepted.append(row)
    # Include completely missing days in range, even though no intervals represented them.
    start = min(days)
    finish = max(days)
    current = datetime.fromisoformat(start).date()
    last = datetime.fromisoformat(finish).date()
    while current <= last:
        if current.isoformat() not in days:
            excluded.append({'date': current.isoformat(), 'observed_coverage_fraction': 0.,
                             'reason': 'no_meter_intervals'})
        current += timedelta(days=1)
    excluded.sort(key=lambda r: r['date'])
    return {'daily_rows': accepted, 'excluded_dates': excluded,
            'accepted_days': len(accepted), 'excluded_days': len(excluded),
            'timezone': timezone_name,
            'note': 'Occupancy flags are known/declared only. Missing occupancy is NOT an observed resident-at-home state.'}
