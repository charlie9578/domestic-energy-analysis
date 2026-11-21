"""Auditable single-zone thermostat and night-storage *scenario* simulator.

Meter traces may supply measured non-heating baseline electricity; envelope,
indoor temperature, COP, gains, heater sizing and occupant wishes MUST be
supplied/assumed. Meter data alone cannot recover these physical parameters.
One thermal zone; no hot water, defrost, emitters, solar gains, moisture,
ventilation dynamics or multi-zone comfort. Not installer sizing advice.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from math import exp, isfinite
from zoneinfo import ZoneInfo

from .core import timestamp_utc


@dataclass(frozen=True)
class House:
    heat_loss_w_per_k: float = 200
    thermal_capacity_kwh_per_k: float = 10
    max_heat_kw: float = 9
    internal_gains_kw: float = .35
    initial_indoor_c: float = 19
    boiler_efficiency: float = .87
    cop_at_7c: float = 3.3
    cop_slope_per_outdoor_c: float = .055
    store_capacity_kwh_th: float = 16
    store_charge_kw: float = 3.5
    store_discharge_kw: float = 4
    store_efficiency: float = .95
    store_loss_fraction_per_hour: float = .008
    store_loss_to_room_fraction: float = 1
    backup_heat_kw: float = 0

    def __post_init__(self):
        positive = ('heat_loss_w_per_k', 'thermal_capacity_kwh_per_k', 'max_heat_kw',
                    'boiler_efficiency', 'store_efficiency')
        bounded = ('internal_gains_kw', 'store_capacity_kwh_th', 'store_charge_kw',
                   'store_discharge_kw', 'store_loss_fraction_per_hour', 'backup_heat_kw')
        for key in positive + bounded:
            value = getattr(self, key)
            if not isfinite(value) or value < 0 or (key in positive and value == 0):
                raise ValueError(f'Invalid house property: {key}')
        for key in ('boiler_efficiency', 'store_efficiency', 'store_loss_fraction_per_hour',
                    'store_loss_to_room_fraction'):
            value = getattr(self, key)
            if not isfinite(value) or value < 0 or value > 1:
                raise ValueError(f'{key} must be in [0,1]')
        if not 0 < self.boiler_efficiency <= 1 or not 0 < self.store_efficiency <= 1:
            raise ValueError('Efficiency must be in (0,1]')
        if not -15 <= self.initial_indoor_c <= 40 or not 1 <= self.cop_at_7c <= 8:
            raise ValueError('Invalid initial temperature or nominal COP')
        if not isfinite(self.cop_slope_per_outdoor_c) or not -0.2 <= self.cop_slope_per_outdoor_c <= .2:
            raise ValueError('Invalid COP slope')


@dataclass(frozen=True)
class Settings:
    occupied_c: float = 20
    setback_c: float = 17
    off_c: float = 14
    away_c: float = 12
    comfort_threshold_c: float = 18
    night_start_hour: int = 22
    night_end_hour: int = 6
    morning_start_hour: int = 6
    morning_end_hour: int = 9
    evening_start_hour: int = 17
    evening_end_hour: int = 22
    charge_start_hour: int = 0
    charge_end_hour: int = 7

    def __post_init__(self):
        for k, v in asdict(self).items():
            if k.endswith('_hour'):
                if not isinstance(v, int) or not 0 <= v <= 24:
                    raise ValueError(f'Invalid schedule hour: {k}')
            elif not isfinite(v) or not 5 <= v <= 28:
                raise ValueError(f'Invalid thermostat temperature: {k}')
        if self.setback_c > self.occupied_c or self.off_c > self.occupied_c:
            raise ValueError('Setback/off must not exceed occupied setpoint')
        if self.morning_end_hour <= self.morning_start_hour or self.evening_end_hour <= self.evening_start_hour:
            raise ValueError('Invalid active windows')


def in_window(hour: float, start: int, end: int) -> bool:
    """Supports windows crossing midnight, e.g. 22:00–06:00."""
    if start == end:
        return False
    return start <= hour < end if start < end else (hour >= start or hour < end)


def setpoint(strategy: str, when: datetime, settings: Settings, *,
             away_dates: set[date] | None = None,
             wfh_dates: set[date] | None = None) -> float:
    if away_dates and when.date() in away_dates:
        return settings.away_c
    h = when.hour + when.minute / 60
    if strategy in ('constant', 'storage_constant'):
        return settings.occupied_c
    if strategy in ('setback', 'storage_setback'):
        return settings.setback_c if in_window(h, settings.night_start_hour, settings.night_end_hour) else settings.occupied_c
    if strategy in ('timed', 'storage_timed', 'wfh_aware'):
        if strategy == 'wfh_aware' and wfh_dates and when.date() in wfh_dates:
            return settings.occupied_c
        active = (in_window(h, settings.morning_start_hour, settings.morning_end_hour) or
                  in_window(h, settings.evening_start_hour, settings.evening_end_hour))
        return settings.occupied_c if active else settings.off_c
    if strategy == 'preheat':
        return settings.occupied_c + .8 if 1 <= h < 6 else settings.occupied_c - .5
    raise ValueError(f'Unknown thermostat strategy: {strategy}')


def _occupied(when: datetime, away_dates: set[date], wfh_dates: set[date]) -> bool:
    if when.date() in away_dates:
        return False
    h = when.hour + when.minute / 60
    return ((when.weekday() >= 5 or when.date() in wfh_dates) and 7 <= h < 23 or
            6 <= h < 9 or 17 <= h < 23)


def _elec_rate(tariff: dict, when: datetime) -> float:
    if 'flat_p_per_kwh' in tariff:
        return float(tariff['flat_p_per_kwh'])
    if not all(k in tariff for k in ('day_p_per_kwh', 'night_p_per_kwh')):
        raise ValueError('Tariff needs flat rate or both day/night prices')
    start, end = int(tariff.get('night_start_hour', 0)), int(tariff.get('night_end_hour', 7))
    return float(tariff['night_p_per_kwh'] if in_window(when.hour+when.minute/60, start, end)
                 else tariff['day_p_per_kwh'])


def _step_input(rows: list[dict]) -> list[tuple[datetime, float, float]]:
    """Require a contiguous grid, 30 or 60 minute, no gap-filling or DST loss."""
    if len(rows) < 2:
        raise ValueError('At least two weather intervals needed')
    ordered = sorted((timestamp_utc(r['start_utc']), float(r['temperature_c'])) for r in rows)
    minutes = int((ordered[1][0] - ordered[0][0]).total_seconds() / 60)
    if minutes not in (30, 60):
        raise ValueError('Weather must have 30- or 60-minute UTC spacing')
    for (a, t), (b, _) in zip(ordered, ordered[1:]):
        if (b-a).total_seconds() != minutes * 60 or not isfinite(t) or not -50 < t < 60:
            raise ValueError('Weather has missing, overlapping or invalid temperature intervals')
    if not isfinite(ordered[-1][1]) or not -50 < ordered[-1][1] < 60:
        raise ValueError('Invalid last outdoor temperature')
    return [(start, temp, minutes/60) for start, temp in ordered]


def align_meter_baseload(weather_rows: list[dict], meter_rows: list[dict]) -> list[float]:
    """Exact UTC join: no assigning a whole-house meter's heating energy to baseload.

    This is valid only if metered electricity is verified NON-SPACE-HEATING load,
    or a separately measured base-load channel. Refuse missing/duplicate slots.
    """
    from .core import _canonical_interval
    weather = _step_input(weather_rows)
    meter = {}
    for row in meter_rows:
        t, kwh, duration = _canonical_interval(row)
        if t in meter:
            raise ValueError('Duplicate baseload interval')
        meter[t] = (kwh, duration)
    missing = [t.isoformat() for t, _, _ in weather if t not in meter]
    if missing:
        raise ValueError(f'No baseload for {len(missing)} weather steps, first {missing[0]}')
    output=[]
    for t, _, hrs in weather:
        value, mins = meter[t]
        if mins != round(hrs*60):
            raise ValueError('Baseload/weather interval durations differ')
        output.append(value)
    return output


def simulate_heating(weather_rows: list[dict], *, strategy: str, heat_source: str,
                     tariff: dict, house: House | None = None, settings: Settings | None = None,
                     timezone_name: str = 'Europe/London',
                     away_dates: set[date] | None = None,
                     wfh_dates: set[date] | None = None,
                     baseload_kwh: list[float] | None = None,
                     record_intervals: bool = False) -> dict:
    """Exact RC heat balance, proportional ideal thermostat, storage physics.

    Storage chargers charge in their allowed night window; heat available at
    all hours via controlled discharge. Resistive daytime backup is optional;
    without it, empty stores cause discomfort, NOT a free heating saving.
    """
    if heat_source not in ('gas', 'heatpump', 'resistive', 'storage'):
        raise ValueError('Unknown heat source')
    if strategy not in ('constant','setback','timed','wfh_aware','preheat',
                        'storage_constant','storage_setback','storage_timed'):
        raise ValueError('Unknown strategy')
    if (heat_source == 'storage') != strategy.startswith('storage_'):
        raise ValueError('Storage strategies require storage source and vice versa')
    h = house or House()
    s = settings or Settings()
    away_dates = away_dates or set()
    wfh_dates = wfh_dates or set()
    try:
        tz = ZoneInfo(timezone_name)
    except KeyError as e:
        raise ValueError('Unknown timezone') from e
    steps = _step_input(weather_rows)
    if baseload_kwh is None:
        baseload_kwh = [0.] * len(steps)
    if len(baseload_kwh) != len(steps) or any(not isfinite(v) or v < 0 for v in baseload_kwh):
        raise ValueError('Baseload must be a non-negative, aligned electricity series')
    if 'gas_p_per_kwh' not in tariff:
        raise ValueError('Tariff requires gas_p_per_kwh')
    gas_p = float(tariff['gas_p_per_kwh'])
    if not isfinite(gas_p) or gas_p < 0:
        raise ValueError('Invalid gas price')
    indoors = h.initial_indoor_c
    store = 0.
    totals = {key: 0. for key in ('delivered_heat_kwh_th', 'electricity_heating_kwh',
             'gas_heating_kwh', 'base_electric_kwh', 'electricity_heating_cost_gbp',
             'gas_heating_cost_gbp', 'baseload_cost_gbp', 'occupied_unmet_degree_hours_c',
             'occupied_hours', 'occupied_hours_below_threshold',
             'all_hours_below_12c', 'storage_loss_kwh_th', 'backup_heating_kwh_th',
             'night_charge_electricity_kwh')}
    peak_input_kw = 0.
    peak_thermal_kw = 0.
    lowest = indoors
    trace=[]
    U = h.heat_loss_w_per_k / 1000
    C = h.thermal_capacity_kwh_per_k
    for (utc, outdoor, dt), base in zip(steps, baseload_kwh):
        local = utc.astimezone(tz)
        target = setpoint(strategy, local, s, away_dates=away_dates, wfh_dates=wfh_dates)
        occupied = _occupied(local, away_dates, wfh_dates)
        rate = _elec_rate(tariff, local)
        if not isfinite(rate):
            raise ValueError('Non-finite electricity rate')
        charge_electric=0.
        leak=0.
        if heat_source == 'storage':
            decay = 1 - (1 - h.store_loss_fraction_per_hour) ** dt
            leak = store * decay
            store -= leak
            if in_window(local.hour+local.minute/60, s.charge_start_hour, s.charge_end_hour):
                # Charge at controlled power, clipping accurately at storage capacity.
                charge_electric = min(h.store_charge_kw * dt,
                                      (h.store_capacity_kwh_th - store) / h.store_efficiency)
                store += charge_electric * h.store_efficiency
                totals['night_charge_electricity_kwh'] += charge_electric
            totals['storage_loss_kwh_th'] += leak
        room_leak_kw = (leak * h.store_loss_to_room_fraction / dt) if heat_source == 'storage' else 0.
        gains = h.internal_gains_kw + room_leak_kw
        factor = exp(-U * dt / C)
        equilibrium = outdoor + gains/U
        free_temp = equilibrium + (indoors-equilibrium)*factor
        request_kw = max(0., (target - free_temp) * U/(1-factor))
        gas_kwh=0.
        heating_electric=0.
        supplied_kw=0.
        backup_kw=0.
        if heat_source == 'storage':
            discharge_kw = min(request_kw, h.store_discharge_kw, store/dt)
            store -= discharge_kw*dt
            backup_kw = min(h.backup_heat_kw, max(0., request_kw-discharge_kw))
            supplied_kw = discharge_kw + backup_kw
            heating_electric = charge_electric + backup_kw*dt
            totals['backup_heating_kwh_th'] += backup_kw*dt
        else:
            supplied_kw = min(request_kw, h.max_heat_kw)
            if heat_source == 'gas':
                gas_kwh = supplied_kw*dt/h.boiler_efficiency
            elif heat_source == 'resistive':
                heating_electric = supplied_kw*dt
            else:
                # Heating-season COP proxy, NOT a measured COP or defrost model.
                cop = max(1.3, min(6., h.cop_at_7c + h.cop_slope_per_outdoor_c * (outdoor - 7)))
                heating_electric = supplied_kw*dt/cop
        previous = indoors
        indoors = free_temp + supplied_kw/U*(1-factor)
        lowest = min(lowest, indoors)
        peak_thermal_kw = max(peak_thermal_kw, supplied_kw)
        peak_input_kw = max(peak_input_kw, (heating_electric + base)/dt)
        totals['delivered_heat_kwh_th'] += supplied_kw*dt + room_leak_kw*dt
        totals['gas_heating_kwh'] += gas_kwh
        totals['electricity_heating_kwh'] += heating_electric
        totals['base_electric_kwh'] += base
        totals['electricity_heating_cost_gbp'] += heating_electric*rate/100
        totals['gas_heating_cost_gbp'] += gas_kwh*gas_p/100
        totals['baseload_cost_gbp'] += base*rate/100
        if occupied:
            totals['occupied_hours'] += dt
            deficit = max(0., s.comfort_threshold_c - indoors)
            totals['occupied_unmet_degree_hours_c'] += deficit*dt
            if deficit > .05:
                totals['occupied_hours_below_threshold'] += dt
        if indoors < 12:
            totals['all_hours_below_12c'] += dt
        if record_intervals:
            trace.append({'start_utc': utc.isoformat(), 'local_time': local.isoformat(),
                'outside_c': round(outdoor, 3), 'indoor_start_c': round(previous, 3),
                'indoor_end_c': round(indoors, 3), 'setpoint_c': target,
                'occupied': occupied, 'heat_delivered_kwh_th': round(supplied_kw*dt, 4),
                'heating_electricity_kwh': round(heating_electric, 4),
                'gas_kwh': round(gas_kwh, 4), 'base_electricity_kwh': round(base, 4),
                'storage_soc_kwh_th': round(store, 4), 'unit_rate_p_per_kwh': rate})
    totals['heating_only_cost_gbp'] = totals['electricity_heating_cost_gbp'] + totals['gas_heating_cost_gbp']
    totals['total_variable_cost_gbp'] = totals['heating_only_cost_gbp'] + totals['baseload_cost_gbp']
    result = {'strategy': strategy, 'source': heat_source, 'tariff': tariff.get('name', '(unnamed)'),
              'n_intervals': len(steps), 'first_utc': steps[0][0].isoformat(),
              'last_utc': (steps[-1][0]+timedelta(hours=steps[-1][2])).isoformat(),
              'lowest_indoor_c': round(lowest, 3), 'last_indoor_c': round(indoors, 3),
              'peak_electrical_import_kw_without_other_loads': round(peak_input_kw, 3),
              'peak_heating_output_kw_th': round(peak_thermal_kw, 3),
              'end_store_kwh_th': round(store, 3),
              'hours': round(sum(row[2] for row in steps), 3),
              'comfort_feasible': totals['occupied_unmet_degree_hours_c'] <= 0.5 and totals['all_hours_below_12c'] == 0,
              'model_assumptions': 'Single-zone RC heat balance; static gains; ideal proportional controller; outdoor-dependent illustrative COP; storage leakage partly to room; no hot water, defrost, variable flow temperatures, dynamic occupancy or solar gains.',
              'standing_charge_note': 'Energy charges only. Standing charges, gas connection, heat pump installation and capital costs omitted.'}
    for key, value in totals.items():
        result[key] = round(value, 4)
    if record_intervals:
        result['intervals'] = trace
    return result


def strategy_grid(weather_rows: list[dict], tariffs: list[dict], *,
                  house: House | None = None, settings: Settings | None = None,
                  away_dates: set[date] | None = None,
                  wfh_dates: set[date] | None = None,
                  baseload_kwh: list[float] | None = None,
                  storage_backup_heat_kw: float = 0) -> dict:
    """Compare schedules, heat source and tariff; flag comfort-infeasible options."""
    from dataclasses import replace
    base = house or House()
    menu = [('gas', x) for x in ('constant','setback','timed','wfh_aware')]
    menu += [('heatpump', x) for x in ('constant','setback','timed','wfh_aware','preheat')]
    menu += [('resistive', x) for x in ('constant','setback','timed')]
    menu += [('storage', x) for x in ('storage_constant','storage_setback','storage_timed')]
    results=[]
    for tariff in tariffs:
        for source, strategy in menu:
            record = simulate_heating(weather_rows, strategy=strategy, heat_source=source,
                tariff=tariff, house=replace(base, backup_heat_kw=storage_backup_heat_kw),
                settings=settings, away_dates=away_dates, wfh_dates=wfh_dates,
                baseload_kwh=baseload_kwh)
            results.append(record)
    feasible = sorted((r for r in results if r['comfort_feasible']),
                      key=lambda r: r['total_variable_cost_gbp'])
    return {'results': results, 'cheapest_comfort_feasible': feasible[0] if feasible else None,
        'comparability': 'Only comparable at like-for-like building parameters, weather, occupancy, delivered comfort and energy boundaries. Infeasible cheap storage is NOT a recommendation. Tariff offers and retrofit CAPEX not included.',
        'data_is_simulated': True}
