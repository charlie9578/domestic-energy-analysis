"""Weather-adjusted monitoring of documented household changes.

Daily model and weather normalization provide *associations*, not causal effects.
The counterfactual is trained only before each event, with chronological pre-event
validation. Missing readings are not zero. Logged interventions are distinct
from unexplained residual shifts. Standard-library only (Python 3.11+).

The consumption channel must be declared: import is NOT gross household demand
when PV or storage sits behind the meter. Thermostat settings are externally
supplied metadata, never inferred from whole-home smart-meter traces.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
from bisect import bisect_right
from datetime import date, datetime, time, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from .forecast import _solve


BOUNDARIES = {'gas_input', 'electricity_import', 'electricity_export',
              'gross_electricity', 'delivered_heat'}
KINDS = {'thermostat', 'ev', 'solar', 'heat_pump', 'insulation',
         'working_from_home', 'absence', 'tariff', 'other'}


def _number(value: object, name: str, *, minimum: float | None = None) -> float:
    try:
        x = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not math.isfinite(x) or (minimum is not None and x < minimum):
        raise ValueError(f'{name} must be finite' + (f' and >= {minimum}' if minimum is not None else ''))
    return x


def _date(value: object) -> date:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError('date must be YYYY-MM-DD') from exc


def _utc(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError('start_utc must be an ISO8601 timestamp')
    try:
        parsed = datetime.fromisoformat(value.strip().replace('Z', '+00:00'))
    except ValueError as exc:
        raise ValueError('start_utc must be ISO8601 with offset') from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('start_utc must have an explicit offset')
    return parsed.astimezone(timezone.utc)


def _bool_flag(value: object, name: str) -> float:
    v = str(value).strip().lower()
    if v in ('true', '1', 'yes'):
        return 1.0
    if v in ('false', '0', 'no'):
        return 0.0
    raise ValueError(f'{name} must be an explicit true/false value if supplied')


def _checked_days(rows: list[dict], *, min_coverage: float = .95) -> tuple[list[dict], list[str]]:
    if not 0 < min_coverage <= 1:
        raise ValueError('min_coverage must be in (0,1]')
    seen = set()
    clean = []
    excluded = []
    for raw in rows:
        day = _date(raw['date'])
        if day in seen:
            raise ValueError(f'duplicate civil day: {day}')
        seen.add(day)
        coverage = _number(raw.get('coverage_fraction', 1), 'coverage_fraction', minimum=0)
        if coverage > 1 + 1e-8:
            raise ValueError('coverage_fraction cannot exceed 1')
        if coverage < min_coverage:
            excluded.append(day.isoformat())
            continue
        entry = {'date': day.isoformat(),
                 'consumption_kwh': _number(raw['consumption_kwh'], 'consumption_kwh', minimum=0),
                 'temperature_c': _number(raw['temperature_c'], 'temperature_c'),
                 'coverage_fraction': coverage}
        for channel in ('ev_submeter_kwh', 'pv_generation_kwh',
                        'pv_self_used_kwh', 'heatpump_electric_kwh'):
            if channel in raw and str(raw[channel]).strip() not in ('', 'None'):
                entry[channel] = _number(raw[channel], channel, minimum=0)
        if 'setpoint_c' in raw and str(raw['setpoint_c']).strip() not in ('', 'None'):
            setpoint = _number(raw['setpoint_c'], 'setpoint_c')
            if not 5 <= setpoint <= 35:
                raise ValueError('setpoint_c must be 5..35')
            entry['setpoint_c'] = setpoint
        for flag in ('work_from_home', 'away'):
            if flag in raw and raw[flag] is not None and str(raw[flag]).strip():
                entry[flag] = _bool_flag(raw[flag], flag)
        clean.append(entry)
    clean.sort(key=lambda r: r['date'])
    return clean, excluded


def _feature(row: dict, *, balance_c: float, flags: tuple[str, ...]) -> list[float]:
    day = _date(row['date'])
    temp = row['temperature_c']
    angle = 2 * math.pi * (day.timetuple().tm_yday - 1) / (366 if (
        day.year % 4 == 0 and (day.year % 100 != 0 or day.year % 400 == 0)) else 365)
    features = [1., max(0., balance_c - temp), max(0., temp - 22.),
                float(day.weekday() >= 5), math.sin(angle), math.cos(angle)]
    features += [row[k] for k in flags]
    return features


def _fit(rows: list[dict], *, balance_c: float, flags: tuple[str, ...]) -> dict:
    if len(rows) < 21:
        raise ValueError('At least 21 training days required')
    xs = [_feature(r, balance_c=balance_c, flags=flags) for r in rows]
    ys = [r['consumption_kwh'] for r in rows]
    ncols = len(xs[0]); n = len(xs)
    scales = [1.] + [max(1., (sum(x[j] ** 2 for x in xs)/n) ** .5)
                     for j in range(1, ncols)]
    xx = [[v/scales[j] for j, v in enumerate(row)] for row in xs]
    gram = [[sum(x[i]*x[j] for x in xx) for j in range(ncols)] for i in range(ncols)]
    rhs = [sum(x[j]*y for x, y in zip(xx, ys)) for j in range(ncols)]
    for i in range(1, ncols):
        # Regularise calendar seasonality more heavily than measured HDD.
        gram[i][i] += n * (.04 if i == 1 else 1.5 if i in (4, 5) else .15)
    gram[0][0] += 1e-10
    beta = _solve(gram, rhs)
    return {'coefficients': [beta[j]/scales[j] for j in range(ncols)],
            'balance_c': balance_c, 'flags': flags}


def _predict(model: dict, row: dict) -> float:
    return max(0., sum(a*b for a,b in zip(model['coefficients'], _feature(
        row, balance_c=model['balance_c'], flags=model['flags']))))


def _train_model(days: list[dict]) -> tuple[dict, dict]:
    if len(days) < 42:
        raise ValueError('At least 42 usable pre-event days needed')
    flags = tuple(k for k in ('work_from_home', 'away') if all(k in r for r in days))
    validation_count = max(14, round(.2*len(days)))
    development, validation = days[:-validation_count], days[-validation_count:]
    # Inner tuning split is distinct from the untouched pre-event validation.
    tune_count = max(7, round(.2*len(development)))
    tuning_fit, tuning = development[:-tune_count], development[-tune_count:]
    options = (12., 14., 15.5, 17., 19.)
    ranked = []
    for balance in options:
        candidate = _fit(tuning_fit, balance_c=balance, flags=flags)
        inner_mae = mean(abs(_predict(candidate, row)-row['consumption_kwh']) for row in tuning)
        ranked.append((inner_mae, balance))
    _, choice = min(ranked)
    outer_model = _fit(development, balance_c=choice, flags=flags)
    residuals = [row['consumption_kwh'] - _predict(outer_model, row) for row in validation]
    predicted = [_predict(outer_model, row) for row in validation]
    diagnostic = {'n_validation_days': len(validation), 'validation_first_date': validation[0]['date'],
                  'validation_last_date': validation[-1]['date'],
                  'validation_mae_kwh_day': round(mean(abs(e) for e in residuals), 4),
                  'validation_bias_kwh_day': round(mean(residuals), 4),
                  'validation_wape': round(sum(abs(e) for e in residuals) / sum(r['consumption_kwh'] for r in validation), 4)
                        if sum(r['consumption_kwh'] for r in validation) else None,
                  'balance_temperature_c': choice,
                  'flags_modelled': list(flags),
                  'residuals': residuals,
                  'mean_validation_forecast': mean(predicted)}
    return _fit(days, balance_c=choice, flags=flags), diagnostic


def _percentile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered)-1, max(0, int(q * (len(ordered)-1))))]


def _sensitivity(effect: float, residuals: list[float], horizon: int, *, seed: int = 26,
                 replicates: int = 800) -> tuple[float, float]:
    """Week-block residual sensitivity, NOT a causal confidence interval."""
    rng = random.Random(seed)
    length = min(7, len(residuals))
    possibilities = [residuals[i:i+length] for i in range(len(residuals)-length+1)]
    draws = []
    for _ in range(replicates):
        samples = []
        while len(samples) < horizon:
            samples.extend(possibilities[rng.randrange(len(possibilities))])
        draws.append(effect - sum(samples[:horizon]))
    return round(_percentile(draws, .05), 3), round(_percentile(draws, .95), 3)


def evaluate_intervention(rows: list[dict], *, event_date: str, event_type: str,
                          meter_boundary: str, washout_days: int = 0,
                          lookback_days: int = 365, min_coverage: float = .95,
                          documented: bool = False, competing_events: list[str] | None = None,
                          unit_price_p_per_kwh: float | None = None) -> dict:
    """Compare post-event measured energy to a *pre-only* weather baseline.

    Reported deviation is association, NOT causally attributed savings: other
    changes, temperature extrapolation and selection are alternative causes.
    Week-block uncertainty measures pre-event model error only.
    """
    if event_type not in KINDS or meter_boundary not in BOUNDARIES:
        raise ValueError('Unknown event_type or meter_boundary')
    if not isinstance(washout_days, int) or not 0 <= washout_days <= 365:
        raise ValueError('washout_days must be 0..365')
    if not isinstance(lookback_days, int) or lookback_days < 42:
        raise ValueError('lookback_days must be >= 42')
    change = _date(event_date)
    days, excluded = _checked_days(rows, min_coverage=min_coverage)
    pre = [r for r in days if _date(r['date']) < change and _date(r['date']) >= change-timedelta(days=lookback_days)]
    post = [r for r in days if _date(r['date']) >= change+timedelta(days=washout_days)]
    if len(pre) < 42 or len(post) < 14:
        raise ValueError('At least 42 valid pre days and 14 valid post days are required')
    model, validation = _train_model(pre)
    missing_flags = [flag for flag in ('away', 'work_from_home') if
                     any(flag in r for r in pre+post) and flag not in model['flags']]
    if any(any(flag not in r for flag in model['flags']) for r in post):
        raise ValueError('Post-event rows must supply the same declared occupancy flags as pre-event model')
    expected = [_predict(model, row) for row in post]
    observed = [row['consumption_kwh'] for row in post]
    deviation = sum(observed)-sum(expected)
    q05,q95 = _sensitivity(deviation, validation['residuals'], len(post))
    # Show whether a change persists, grows or fades: observed 30-calendar-day bins.
    # The pre-event model remains frozen; no refit to post observations.
    bins = {}
    for row, counterfactual in zip(post, expected):
        bucket = (_date(row['date'])-change).days // 30
        bins.setdefault(bucket,[]).append((row['consumption_kwh'],counterfactual))
    time_profile = []
    for bucket, values in sorted(bins.items()):
        impact = sum(ob-exp for ob,exp in values)
        time_profile.append({'days_since_event_start':bucket*30,
                             'days_since_event_end_exclusive':(bucket+1)*30,
                             'n_observed_days':len(values),
                             'observed_kwh':round(sum(ob for ob,_ in values),3),
                             'expected_kwh':round(sum(exp for _,exp in values),3),
                             'deviation_kwh_per_observed_day':round(impact/len(values),3)})
    pretemps = [r['temperature_c'] for r in pre]
    far_weather = sum(r['temperature_c'] < min(pretemps)-2 or
                      r['temperature_c'] > max(pretemps)+2 for r in post)
    pre_span = (_date(pre[-1]['date'])-_date(pre[0]['date'])).days+1
    post_span = (_date(post[-1]['date'])-_date(post[0]['date'])).days+1
    notes=[]
    if far_weather:
        notes.append(f'{far_weather} post dates have outdoor temperatures beyond pre-event training range ±2°C')
    if len(pre)<pre_span or len(post)<post_span:
        notes.append('Missing or below-coverage civil days may bias the before/after comparison')
    if validation['validation_wape'] is None or validation['validation_wape'] > .3:
        notes.append('Weak pre-event backtest; magnitude unreliable')
    if abs(validation['validation_bias_kwh_day']) > max(1., validation['mean_validation_forecast']*.12):
        notes.append('Pre-event validation already shows forecast drift/bias')
    if missing_flags:
        notes.append('Occupancy/WFH covariates are incompletely reported and not modelled')
    if not documented:
        notes.append('Intervention date/type not independently documented: do not attribute a cause')
    if competing_events:
        notes.append('Competing events reported; single-event attribution is not identifiable')
    direct_channels = {}
    for channel in ('ev_submeter_kwh','pv_generation_kwh','pv_self_used_kwh',
                    'heatpump_electric_kwh'):
        if all(channel in row for row in post):
            direct_channels[channel] = round(sum(row[channel] for row in post),3)
    if all('setpoint_c' in row for row in pre) and all('setpoint_c' in row for row in post):
        direct_channels['pre_mean_logged_setpoint_c']=round(mean(r['setpoint_c'] for r in pre),3)
        direct_channels['post_mean_logged_setpoint_c']=round(mean(r['setpoint_c'] for r in post),3)
    if far_weather > max(3, .1*len(post)):
        reliability='extrapolation_unsafe'
    elif validation['validation_wape'] is None or validation['validation_wape']>.3:
        reliability='forecast_quality_poor'
    elif not documented or competing_events:
        reliability='confounded_or_unverified_event'
    else:
        reliability='descriptive_association_only'
    if event_type == 'solar' and meter_boundary == 'electricity_import':
        notes.append('Solar can lower grid IMPORT without lowering appliance demand; export/PV generation needed')
    if event_type == 'ev' and meter_boundary == 'electricity_import':
        notes.append('Extra imports cannot be assigned to EV without separately metered charging')
    if event_type == 'thermostat':
        notes.append('Setpoint change requires thermostat/user log; whole-home meter data cannot reveal the setpoint')
    if event_type == 'tariff':
        notes.append('Tariff or price shifts can change behaviour: historical re-pricing alone cannot quantify adaptation')
    cost_delta = None
    if unit_price_p_per_kwh is not None:
        price = _number(unit_price_p_per_kwh, 'unit_price_p_per_kwh', minimum=0)
        cost_delta = round(deviation * price/100., 2)
    baseline = sum(expected)
    return {
        'event_date': change.isoformat(), 'event_type': event_type, 'documented_event': bool(documented),
        'meter_boundary': meter_boundary, 'method': 'weather_adjusted_pre_event_counterfactual',
        'reliability_flag': reliability, 'directly_metered_post_channels':direct_channels,
        'pre_period': [pre[0]['date'], pre[-1]['date']],
        'post_period': [post[0]['date'], post[-1]['date']],
        'n_pre_days': len(pre), 'n_post_days': len(post),
        'n_low_coverage_days_excluded': len(excluded),
        'n_other_events': len(competing_events or []), 'washout_days': washout_days,
        'pre_mean_kwh_per_day': round(mean(r['consumption_kwh'] for r in pre), 3),
        'post_mean_kwh_per_day': round(mean(observed), 3),
        'naive_post_minus_pre_kwh_per_day': round(mean(observed)-mean(r['consumption_kwh'] for r in pre), 3),
        'weather_adjusted_expected_post_kwh': round(baseline, 3),
        'observed_post_kwh': round(sum(observed), 3),
        'deviation_observed_minus_expected_kwh': round(deviation, 3),
        'deviation_kwh_per_observed_day': round(deviation/len(post), 3),
        'deviation_fraction_of_expected': round(deviation/baseline, 4) if baseline else None,
        'model_error_sensitivity_p05_p95_kwh': [q05,q95],
        'change_over_time_30_day_bins': time_profile,
        'sensitivity_warning': '90% empirical week-block residual sensitivity only; NOT causal confidence interval, excludes unrelated structural changes, extrapolation and model drift',
        'variable_cost_deviation_gbp_if_fixed_rate': cost_delta,
        'validation': {k:v for k,v in validation.items() if k not in ('residuals','mean_validation_forecast')},
        'weather_out_of_training_support_days': far_weather,
        'warnings': notes,
        'interpretation': 'Association only: counterfactual fitted to pre-event data. No causal attribution or verified equipment identification.'
    }



def evaluate_timeline(rows: list[dict], events: list[dict], *, meter_boundary: str,
                      min_coverage: float=.95, lookback_days: int=365) -> dict:
    """Evaluate a known sequence of interventions; never pool different regimes.

    Each event's pre is after the prior event's change date, and its post ends
    before the following event. If observation is too short to identify an
    association, return an explicit unassessable item instead of fake savings.
    Simultaneous events are reported jointly as not individually identifiable.
    """
    if meter_boundary not in BOUNDARIES:
        raise ValueError('Unknown meter_boundary')
    if not events:
        return {'meter_boundary':meter_boundary,'results':[],
                'note':'No declared intervention events; shift detection is separate.'}
    parsed=[]
    for item in events:
        d=_date(item['date'])
        kind=item['event_type']
        if kind not in KINDS:
            raise ValueError('Unknown event_type')
        if item.get('meter_boundary',meter_boundary)!=meter_boundary:
            raise ValueError('Event uses a different meter boundary')
        parsed.append((d,kind,bool(item.get('documented',False))))
    parsed.sort()
    unique_dates=sorted(set(d for d,_,_ in parsed))
    answers=[]
    for index,d in enumerate(unique_dates):
        kinds=[k for day,k,_ in parsed if day==d]
        known=all(verified for day,_,verified in parsed if day==d)
        previous=unique_dates[index-1] if index else None
        following=unique_dates[index+1] if index+1<len(unique_dates) else None
        # Previous event may have introduced a new heating/EV/PV baseline.
        subset=[r for r in rows if (previous is None or _date(r['date'])>previous)
                and (following is None or _date(r['date'])<following)]
        if len(kinds)>1:
            answers.append({'event_date':d.isoformat(),'event_types':kinds,
                            'status':'not_attributable',
                            'explanation':'Concurrent changes in same meter channel cannot be individually separated by whole-home readings.'})
            continue
        try:
            result=evaluate_intervention(subset,event_date=d.isoformat(),event_type=kinds[0],
                meter_boundary=meter_boundary,min_coverage=min_coverage,
                lookback_days=lookback_days,documented=known)
        except ValueError as exc:
            # Input validation remains fatal, but sparse event segments are
            # expected to lack identification; do not fabricate a point estimate.
            if 'At least 42 valid pre days' not in str(exc):
                raise
            answers.append({'event_date':d.isoformat(),'event_types':kinds,
                            'status':'insufficient_data','explanation':str(exc),
                            'regime_start':previous.isoformat() if previous else None,
                            'regime_end':following.isoformat() if following else None})
            continue
        result['status']='estimated_association_only'
        result['regime_start']=previous.isoformat() if previous else None
        result['regime_end']=following.isoformat() if following else None
        answers.append(result)
    return {'meter_boundary':meter_boundary,'results':answers,
            'note':'Sequential pre-only model per regime; changes, rebound and confounding remain possible. Different meter boundaries must be evaluated separately.'}


def find_usage_shifts(rows: list[dict], *, meter_boundary: str,
                      min_history_days: int = 84, window_days: int = 14,
                      min_coverage: float = .95, max_candidates: int = 8) -> dict:
    """Screen for persistent *unexplained* meter residual changes, not EV/holiday labels.

    The first history window is a fixed reference. Subsequent shifted behaviour
    is not continuously 'learnt away'. Selected break dates invalidate naive p-values.
    """
    if meter_boundary not in BOUNDARIES:
        raise ValueError('Unknown meter boundary')
    if min_history_days < 42 or window_days < 7 or max_candidates < 1:
        raise ValueError('Invalid shift scan dimensions')
    days, excluded = _checked_days(rows, min_coverage=min_coverage)
    if len(days) < min_history_days+2*window_days:
        raise ValueError('Need fixed training history and at least two post-history windows')
    history = days[:min_history_days]
    model, validation = _train_model(history)
    follow = days[min_history_days:]
    if any(any(flag not in r for flag in model['flags']) for r in follow):
        raise ValueError('Missing post-history occupancy flags')
    residuals = [r['consumption_kwh']-_predict(model,r) for r in follow]
    predicted = [_predict(model,r) for r in follow]
    noise = max(.5, validation['validation_mae_kwh_day'])
    results=[]
    for i in range(window_days, len(follow)-window_days+1):
        before = residuals[i-window_days:i]
        after = residuals[i:i+window_days]
        magnitude = mean(after)-mean(before)
        scale = max(2.5*noise, .15*mean(predicted[i:i+window_days]))
        if abs(magnitude)<scale:
            continue
        # Continuous windows require the actual daily series, not sparse points.
        segment = follow[i-window_days:i+window_days]
        if (_date(segment[-1]['date'])-_date(segment[0]['date'])).days != 2*window_days-1:
            continue
        results.append({'candidate_date': follow[i]['date'],
                        'change_kwh_per_day': round(magnitude, 3),
                        'direction': 'increased' if magnitude > 0 else 'decreased',
                        'screening_score': round(abs(magnitude)/scale, 3),
                        'label': 'unexplained usage-shift candidate; cause unknown'})
    picked=[]
    for entry in sorted(results, key=lambda x:-x['screening_score']):
        if all(abs((_date(entry['candidate_date'])-_date(other['candidate_date'])).days) >= window_days
               for other in picked):
            picked.append(entry)
            if len(picked)>=max_candidates:
                break
    return {'meter_boundary':meter_boundary,'n_days':len(days), 'excluded_days':len(excluded),
            'candidates':sorted(picked,key=lambda x:x['candidate_date']),
            'method':'unverified fixed-reference rolling residual contrasts',
            'warning':'Exploratory change-point screen only; dates, causes, occupancy, installed equipment and statistical significance cannot be inferred.'}


def simple_setpoint_scenario(*, old_c: float, new_c: float, outside_c: float,
                             heat_loss_w_per_k: float, hours_per_day: float,
                             fuel: str, efficiency_or_cop: float,
                             price_p_per_kwh: float) -> dict:
    """Steady-state per-day sensitivity, NOT thermostat trial or dynamic control."""
    old = _number(old_c,'old_c'); new = _number(new_c,'new_c')
    outside = _number(outside_c, 'outside_c')
    loss = _number(heat_loss_w_per_k, 'heat_loss_w_per_k',minimum=1)
    hours = _number(hours_per_day,'hours_per_day',minimum=0)
    if hours > 24:
        raise ValueError('hours_per_day cannot exceed 24')
    efficiency = _number(efficiency_or_cop,'efficiency_or_cop',minimum=.01)
    rate = _number(price_p_per_kwh,'price_p_per_kwh',minimum=0)
    if fuel not in ('gas','heatpump','direct_electric'):
        raise ValueError('fuel must be gas, heatpump, direct_electric')
    if fuel == 'gas' and efficiency > 1:
        raise ValueError('Gas efficiency cannot exceed 1')
    if fuel == 'direct_electric' and abs(efficiency-1)>1e-9:
        raise ValueError('Direct electric efficiency must be 1')
    qbefore = loss*hours*max(0.,old-outside)/1000
    qafter = loss*hours*max(0.,new-outside)/1000
    use_before = qbefore/efficiency
    use_after = qafter/efficiency
    return {'scenario':'steady_state_setpoint_only','fuel':fuel,
            'old_c':old,'new_c':new,'outdoor_c':outside,
            'delivered_heat_before_kwh_per_day':round(qbefore,4),
            'delivered_heat_after_kwh_per_day':round(qafter,4),
            'fuel_input_before_kwh_per_day':round(use_before,4),
            'fuel_input_after_kwh_per_day':round(use_after,4),
            'input_reduction_kwh_per_day':round(use_before-use_after,4),
            'variable_cost_reduction_gbp_per_day':round((use_before-use_after)*rate/100,4),
            'caveat':'Assumes constant outdoor temperature, whole-house uniform setpoint, fixed heat-loss and efficiency, no gains, no warm-up/transients, DHW or comfort effect. Not estimated from meter data.'}


def aggregate_meter_weather(meter_rows: list[dict], weather_rows: list[dict], *,
                             timezone_name: str='Europe/London', min_coverage: float=.95) -> dict:
    """Aggregate UTC meter intervals and **historic** hourly outdoor weather to local days.

    Weather is held at the last observed timestamp within 60 minutes. Never
    interpolate missing energy; reject overlap, duplicate meter starts or data
    outside hourly weather support. All time arithmetic uses UTC, not naive DST.
    """
    if not 0 < min_coverage <= 1:
        raise ValueError('min_coverage must be in (0,1]')
    try:
        tz=ZoneInfo(timezone_name)
    except (KeyError, ValueError) as exc:
        raise ValueError('Unknown timezone') from exc
    points = sorted((_utc(r['start_utc']),_number(r['temperature_c'],'temperature_c'))
                    for r in weather_rows)
    if not points or len({t for t,_ in points}) != len(points):
        raise ValueError('Require nonduplicate timestamped weather')
    times=[t for t,_ in points]
    intervals=[]
    for r in meter_rows:
        t = _utc(r['start_utc'])
        mins = _number(r['duration_minutes'],'duration_minutes',minimum=1)
        if mins not in (15,30,60):
            raise ValueError('Meter interval duration must be 15, 30 or 60 minutes')
        intervals.append((t, t+timedelta(minutes=mins), _number(r['consumption_kwh'],'consumption_kwh',minimum=0)))
    intervals.sort()
    if not intervals:
        raise ValueError('Empty meter file')
    for left,right in zip(intervals,intervals[1:]):
        if right[0] < left[1]:
            raise ValueError('Duplicate or overlapping meter intervals')
    by_day={}
    missing_weather=0
    for start,end,energy in intervals:
        d=start.astimezone(tz).date()
        next_date=(d+timedelta(days=1))
        midnight=datetime.combine(next_date,time.min,tzinfo=tz).astimezone(timezone.utc)
        if end>midnight:
            raise ValueError('Interval crosses local civil day; split at boundary before aggregation')
        pos=bisect_right(times,start)-1
        if pos<0 or start-times[pos]>=timedelta(minutes=60):
            missing_weather+=1
            continue
        dur=(end-start).total_seconds()/3600
        row=by_day.setdefault(d,{'energy':0., 'hours':0., 'temp_wsum':0.})
        row['energy']+=energy
        row['hours']+=dur
        row['temp_wsum']+=points[pos][1]*dur
    result=[];excluded=[]
    all_days={t.astimezone(tz).date() for t,_,_ in intervals}
    for d in sorted(all_days):
        row=by_day.get(d,{'energy':0,'hours':0,'temp_wsum':0})
        midnight=datetime.combine(d,time.min,tzinfo=tz).astimezone(timezone.utc)
        tomorrow=datetime.combine(d+timedelta(days=1),time.min,tzinfo=tz).astimezone(timezone.utc)
        expected=(tomorrow-midnight).total_seconds()/3600
        coverage=row['hours']/expected
        if coverage>1+1e-8:
            raise ValueError('Civil day has more energy intervals than hours')
        if coverage<min_coverage or row['hours']==0:
            excluded.append({'date':d.isoformat(),'coverage_fraction':round(coverage,6)})
            continue
        result.append({'date':d.isoformat(),'consumption_kwh':round(row['energy'],8),
                       'temperature_c':round(row['temp_wsum']/row['hours'],5),
                       'coverage_fraction':round(min(1,coverage),6)})
    return {'days':result,'excluded_days':excluded,'missing_weather_intervals':missing_weather,
            'timezone':timezone_name,
            'note':'Only complete-enough local civil days; hours computed across DST. Weather hourly value held at most 60min; never zero-fill missing energy.'}


def _read_csv(path: str) -> list[dict]:
    with open(path, newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def main(argv: list[str] | None = None) -> None:
    parser=argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub=parser.add_subparsers(dest='command',required=True)
    e=sub.add_parser('evaluate',help='weather-adjusted reported event, from daily CSV')
    e.add_argument('--csv',required=True)
    e.add_argument('--event-date',required=True)
    e.add_argument('--event-type',choices=sorted(KINDS),required=True)
    e.add_argument('--meter-boundary',choices=sorted(BOUNDARIES),required=True)
    e.add_argument('--documented',action='store_true',help='only if external log establishes date/type')
    e.add_argument('--washout-days',type=int,default=0)
    e.add_argument('--lookback-days',type=int,default=365)
    e.add_argument('--price-p-per-kwh',type=float)
    l=sub.add_parser('timeline',help='evaluate JSON event log sequentially, without pooling regimes')
    l.add_argument('--csv',required=True)
    l.add_argument('--events',required=True,help='JSON list of date,event_type,documented and optional meter_boundary')
    l.add_argument('--meter-boundary',choices=sorted(BOUNDARIES),required=True)
    s=sub.add_parser('scan',help='candidate unexplained changes, not identified equipment')
    s.add_argument('--csv',required=True)
    s.add_argument('--meter-boundary',choices=sorted(BOUNDARIES),required=True)
    a=sub.add_parser('aggregate',help='UTC meter + hourly weather CSV -> complete local daily rows')
    a.add_argument('--meter',required=True);a.add_argument('--weather',required=True)
    a.add_argument('--timezone',default='Europe/London')
    a.add_argument('--output',required=True)
    p=sub.add_parser('setpoint',help='steady-state thermostat scenario (NOT observed savings)')
    p.add_argument('--old-c',type=float,required=True)
    p.add_argument('--new-c',type=float,required=True)
    p.add_argument('--outside-c',type=float,required=True)
    p.add_argument('--heat-loss-w-per-k',type=float,required=True)
    p.add_argument('--hours-per-day',type=float,default=14)
    p.add_argument('--fuel',choices=['gas','heatpump','direct_electric'],default='gas')
    p.add_argument('--efficiency-or-cop',type=float,default=.85)
    p.add_argument('--price-p-per-kwh',type=float,required=True)
    args=parser.parse_args(argv)
    if args.command=='aggregate':
        data=aggregate_meter_weather(_read_csv(args.meter),_read_csv(args.weather),timezone_name=args.timezone)
        with open(args.output,'w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=['date','consumption_kwh','temperature_c','coverage_fraction'])
            w.writeheader();w.writerows(data['days'])
        print(json.dumps({k:v for k,v in data.items() if k!='days'},indent=2))
        return
    if args.command=='evaluate':
        data=evaluate_intervention(_read_csv(args.csv),event_date=args.event_date,
            event_type=args.event_type,meter_boundary=args.meter_boundary,
            documented=args.documented,washout_days=args.washout_days,
            lookback_days=args.lookback_days,unit_price_p_per_kwh=args.price_p_per_kwh)
    elif args.command=='timeline':
        with open(args.events,encoding='utf-8') as source:
            event_log=json.load(source)
        if not isinstance(event_log,list):
            raise ValueError('Event log must be a JSON list')
        data=evaluate_timeline(_read_csv(args.csv),event_log,meter_boundary=args.meter_boundary)
    elif args.command=='scan':
        data=find_usage_shifts(_read_csv(args.csv),meter_boundary=args.meter_boundary)
    else:
        data=simple_setpoint_scenario(old_c=args.old_c,new_c=args.new_c,
            outside_c=args.outside_c,heat_loss_w_per_k=args.heat_loss_w_per_k,
            hours_per_day=args.hours_per_day,fuel=args.fuel,
            efficiency_or_cop=args.efficiency_or_cop,price_p_per_kwh=args.price_p_per_kwh)
    print(json.dumps(data,indent=2))


if __name__=='__main__':
    main()