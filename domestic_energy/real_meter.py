"""Streaming import of *measured* UK Power Networks Low Carbon London readings.

Raw archive: https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d
One public fixture: https://github.com/rtdip/core/.../CC_LCL-FullData.csv

IMPORTANT: the trial's time-zone labelling is not sufficiently self-describing for
blind conversion. Caller MUST select a documented timestamp convention. No
imputed missing data, no invented household occupancy or appliance ground truth.
"""
from __future__ import annotations

import csv
import gzip
import io
import zipfile
from collections import Counter
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from math import isfinite
from pathlib import Path
from typing import Iterator

from .core import summarize_meter, timestamp_utc


@contextmanager
def _source(path: Path) -> Iterator[Iterator[tuple[str, io.TextIOBase]]]:
    """Yield text streams for a CSV, CSV.GZ, or ZIP of CSV files, one at a time."""
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as arc:
            files = [n for n in arc.namelist() if n.lower().endswith('.csv') and not n.startswith('__MACOSX/')]
            if not files:
                raise ValueError(f'No CSV files in {path}')
            def streams():
                for name in sorted(files):
                    with arc.open(name) as raw:
                        with io.TextIOWrapper(raw, encoding='utf-8-sig', newline='') as text:
                            yield name, text
            yield streams()
    elif path.name.lower().endswith('.csv.gz'):
        with gzip.open(path, 'rt', encoding='utf-8-sig', newline='') as text:
            yield iter([(path.name, text)])
    elif path.suffix.lower() in ('.csv', '.txt'):
        with path.open(encoding='utf-8-sig', newline='') as text:
            yield iter([(path.name, text)])
    else:
        raise ValueError('Expected .csv, .txt, .csv.gz or .zip')


def _raw_time(value: str, timestamp_mode: str) -> datetime:
    """Always parse explicitly as UTC; raw LCL often has GMT-labelled naive times.

    Source data timestamps are commonly interval END. Conversion from Europe/London
    civil timestamps is deliberately NOT guessed around DST folds/nonexistent times.
    Users must use a source with UTC/GMT documented for this conversion.
    """
    if timestamp_mode not in ('utc_end', 'utc_start'):
        raise ValueError('timestamp_mode must be utc_end or utc_start; verify source documentation')
    raw = value.strip()
    try:
        naive = datetime.fromisoformat(raw)
    except ValueError:
        naive = datetime.strptime(raw, '%d/%m/%Y %H:%M:%S')
    if naive.tzinfo is not None:
        raise ValueError('Expected documented UTC/GMT naive LCL times, not mixed offsets')
    moment = naive.replace(tzinfo=timezone.utc)
    if timestamp_mode == 'utc_end':
        moment -= timedelta(minutes=30)
    if moment.minute not in (0, 30) or moment.second:
        raise ValueError(f'Meter timestamp is not a half-hour boundary: {raw}')
    return moment


def import_lcl(paths: list[str | Path], household_id: str, *, timestamp_mode: str,
               max_selected_rows: int = 50000) -> dict:
    """Filter potentially huge LCL raw files in a memory-bounded streaming pass.

    `max_selected_rows` raises instead of silently giving a misleading partial
    profile. The 50k default covers ~2.85 years for one household.
    """
    if not household_id or not household_id.startswith('MAC'):
        raise ValueError('Select one explicit LCL household ID, e.g. MAC000002')
    if timestamp_mode not in ('utc_end', 'utc_start'):
        raise ValueError('Explicit UTC timestamp_mode is required')
    if not paths or max_selected_rows < 1:
        raise ValueError('Provide paths and a positive selected row limit')
    selected = {}
    sources = []
    counters = Counter()
    for p in paths:
        path = Path(p)
        if not path.is_file():
            raise FileNotFoundError(path)
        with _source(path) as streams:
            for filename, handle in streams:
                sources.append(f'{path.name}:{filename}')
                reader = csv.DictReader(handle)
                cols = {x.strip().lower(): x for x in (reader.fieldnames or [])}
                id_col = cols.get('lclid')
                time_col = cols.get('datetime')
                kwh_col = next((v for k, v in cols.items() if k.startswith('kwh/hh') or k == 'kwh_per_hh'), None)
                if not id_col or not time_col or not kwh_col:
                    raise ValueError(f'Missing LCL columns in {filename}: {reader.fieldnames}')
                for record in reader:
                    counters['rows_examined'] += 1
                    if record[id_col].strip() != household_id:
                        continue
                    counters['household_rows'] += 1
                    value = record[kwh_col].strip()
                    if value.lower() in ('', 'null', 'nan'):
                        counters['null_dropped'] += 1
                        continue
                    kwh = float(value)
                    if not 0 <= kwh < 1e6:
                        raise ValueError('Invalid consumption, cannot infer missing/negative readings')
                    start = _raw_time(record[time_col], timestamp_mode)
                    if start in selected:
                        if selected[start] != kwh:
                            raise ValueError(f'Conflicting duplicate meter slot: {start}')
                        counters['exact_duplicates_dropped'] += 1
                        continue
                    if len(selected) >= max_selected_rows:
                        raise ValueError('Selected row limit reached; split the analysis window')
                    selected[start] = kwh
    if not selected:
        raise ValueError(f'No valid measured readings for {household_id}')
    rows = [{'start_utc': t.isoformat(), 'consumption_kwh': kwh, 'duration_minutes': 30}
            for t, kwh in sorted(selected.items())]
    summary = summarize_meter(rows)
    return {'rows': rows, 'qa': {**dict(counters), 'selected_intervals': len(rows),
        'source_files': len(sources), 'source_names': sources[:12],
        'household_id': household_id, 'timestamp_mode': timestamp_mode,
        'first_start_utc': rows[0]['start_utc'], 'last_start_utc': rows[-1]['start_utc'],
        'coverage_fraction': summary['coverage_fraction'], 'observed_total_kwh': summary['total_kwh'],
        'measured_data': True,
        'limitations': 'Historical (2011-2014) electricity only; individual appliance types, indoor temperature, presence, gas and heating state are not measured. UTC/GMT timestamp interpretation is a source assumption; check provenance.'}}


def measured_profile(rows: list[dict]) -> dict:
    """Observed only: coverage, weekday/weekend split, evening peak and night share."""
    from zoneinfo import ZoneInfo
    tz = ZoneInfo('Europe/London')
    summary = summarize_meter(rows)
    by_hour = Counter()
    by_weekend = Counter()
    night = 0.0
    for row in rows:
        dt = datetime.fromisoformat(row['start_utc']).astimezone(tz)
        val = float(row['consumption_kwh'])
        by_hour[dt.hour] += val
        by_weekend['weekend' if dt.weekday() >= 5 else 'weekday'] += val
        if 0 <= dt.hour < 7:
            night += val
    return {**summary, 'night_00_07_fraction_of_observed_kwh': round(night / summary['total_kwh'], 4)
            if summary['total_kwh'] else None, 'weekday_observed_kwh': round(by_weekend['weekday'], 3),
            'weekend_observed_kwh': round(by_weekend['weekend'], 3),
            'by_local_hour_total_kwh': {str(k): round(by_hour[k], 4) for k in range(24)},
            'note': 'Measured half-hourly total electricity; no claim of appliance or occupancy ground truth.'}


def expected_halfhourly_profile(rows: list[dict], *, test_fraction: float = .25,
                                timezone_name: str = 'Europe/London') -> dict:
    """Historical half-hour calendar baseline with time-ordered holdout (not weather).

    The expected values are trained on earlier complete local days. A day with
    missing intervals is dropped, not filled with zeros. Daylight-saving dates
    have 46 or 50 local half-hours, counted by actual UTC duration.
    """
    from statistics import median
    from datetime import date, time, timezone
    from zoneinfo import ZoneInfo
    if not .1 <= test_fraction <= .4:
        raise ValueError('test_fraction must be 0.1..0.4')
    tz = ZoneInfo(timezone_name)
    daily = {}
    for row in rows:
        t, kwh, duration = (timestamp_utc(row['start_utc']),
                            float(row['consumption_kwh']), int(row.get('duration_minutes') or 30))
        if not isfinite(kwh) or kwh < 0 or duration != 30:
            raise ValueError('Expected unique, 30-minute non-negative meter intervals')
        local=t.astimezone(tz)
        datekey=local.date()
        if t in daily.setdefault(datekey, {}):
            raise ValueError('Duplicate meter interval')
        daily[datekey][t]=(local, kwh)
    valid=[]
    for day, records in sorted(daily.items()):
        local_start=datetime.combine(day, time(), tzinfo=tz)
        next_start=datetime.combine(day+timedelta(days=1), time(), tzinfo=tz)
        expected=int((next_start.astimezone(timezone.utc)-local_start.astimezone(timezone.utc)).total_seconds()/1800)
        if len(records)!=expected:
            continue
        starts=[t for t in records]
        expected_starts={local_start.astimezone(timezone.utc)+timedelta(minutes=30*i) for i in range(expected)}
        if set(starts)!=expected_starts:
            continue
        valid.append((day,[records[t] for t in sorted(records)]))
    if len(valid)<21:
        raise ValueError(f'Only {len(valid)} complete meter days; >=21 required for held-out calendar expectations')
    cut=max(14,len(valid)-max(5,round(len(valid)*test_fraction)))
    train,test=valid[:cut],valid[cut:]
    if not test:
        raise ValueError('Not enough held-out days')
    hh={}
    wh={}
    for day, obs in train:
        for t,k in obs:
            slot=t.hour*2+t.minute//30
            hh.setdefault(slot,[]).append(k)
            wh.setdefault((day.weekday(),slot),[]).append(k)
    halfhour={key:median(vals) for key, vals in hh.items()}
    all_mean=sum(sum(ls) for ls in hh.values()) / sum(len(ls) for ls in hh.values())
    # A weekday/half-hour estimate is trusted only with 3 independent training samples.
    predict=lambda day, local: (median(wh[(day.weekday(),local.hour*2+local.minute//30)])
        if len(wh.get((day.weekday(),local.hour*2+local.minute//30),[]))>=3
        else halfhour.get(local.hour*2+local.minute//30, all_mean))
    residual=[]
    actual_total=0.
    expected_total=0.
    by_day=[]
    for day, obs in test:
        real=sum(k for _,k in obs)
        est=sum(predict(day,t) for t,_ in obs)
        by_day.append({'date':str(day),'observed_kwh':round(real,3),
                       'expected_kwh':round(est,3),'deviation_kwh':round(real-est,3)})
        actual_total+=real
        expected_total+=est
        residual.extend(abs(k-predict(day,t)) for t,k in obs)
    return {'model':'non_weather_halfhourly_calendar_median',
            'n_full_days':len(valid),'n_partial_days_excluded':len(daily)-len(valid),
            'n_train_days':len(train),'n_test_days':len(test),
            'holdout_mae_kwh_per_halfhour':round(sum(residual)/len(residual),4),
            'holdout_total_observed_kwh':round(actual_total,3),
            'holdout_total_expected_kwh':round(expected_total,3),
            'holdout_daily':by_day,
            'hour_slot_expected_kwh':{f'{slot//2:02d}:{slot%2*30:02d}':round(halfhour.get(slot,all_mean),3) for slot in range(48)},
            'note':'Measured electricity, time-ordered heldout; no weather or occupancy inference, no guaranteed future accuracy. Sparse weekday cells fall back to time-of-day median.'}
