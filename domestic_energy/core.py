"""Transparent household energy accounting. All prices in pence; energy in kWh."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from math import ceil, isfinite
from statistics import mean
from zoneinfo import ZoneInfo


def _number(value: float, name: str, *, minimum: float = 0) -> float:
    x = float(value)
    if not isfinite(x) or x < minimum:
        raise ValueError(f"{name} must be finite and >= {minimum}")
    return x


def timestamp_utc(value: str) -> datetime:
    """Parse an ISO8601 timestamp with explicit offset and normalize to UTC."""
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"Timestamp must have UTC offset: {value!r}")
    return dt.astimezone(timezone.utc)


def gas_volume_to_kwh(volume: float, *, unit: str = 'm3', calorific_mj_per_m3: float = 39.5,
                      correction: float = 1.02264) -> float:
    """Convert gas-meter volume to kWh; use calorific value on the bill."""
    _number(volume, 'volume')
    _number(calorific_mj_per_m3, 'calorific_mj_per_m3', minimum=0.001)
    _number(correction, 'correction', minimum=0.001)
    if unit not in ('m3', 'ft3', 'hundred_ft3'):
        raise ValueError('unit must be m3, ft3 or hundred_ft3')
    metres_cubed = volume * {'m3': 1, 'ft3': 0.028316846592,
                             'hundred_ft3': 2.8316846592}[unit]
    return metres_cubed * correction * calorific_mj_per_m3 / 3.6


@dataclass(frozen=True)
class Tariff:
    electricity_p_per_kwh: float
    gas_p_per_kwh: float
    electricity_standing_p_per_day: float
    gas_standing_p_per_day: float

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            _number(value, name)


# GB average across regions/payment method; Ofgem Q4 2026 direct debit, not a tariff offer.
OFGEM_Q4_2026 = Tariff(26.32, 7.97, 54.83, 29.68)


@dataclass(frozen=True)
class HeatPumpScenario:
    gas_kwh: float = 10_000
    gas_heating_fraction: float = 0.85
    boiler_efficiency: float = 0.85
    heat_pump_spf: float = 3.0
    other_electricity_kwh: float = 2_500
    days: int = 365
    disconnect_gas: bool = False
    retrofit_capex_gbp: float = 0

    def __post_init__(self) -> None:
        for name in ('gas_kwh', 'other_electricity_kwh', 'retrofit_capex_gbp'):
            _number(getattr(self, name), name)
        for name in ('gas_heating_fraction', 'boiler_efficiency'):
            value = _number(getattr(self, name), name)
            if value > 1:
                raise ValueError(f'{name} must be <= 1')
        _number(self.heat_pump_spf, 'heat_pump_spf', minimum=0.001)
        if not isinstance(self.days, int) or self.days <= 0:
            raise ValueError('days must be a positive integer')
        if self.disconnect_gas and self.gas_heating_fraction < 1:
            raise ValueError('Cannot disconnect gas while unconverted gas uses remain; model their replacement first')


def evaluate_heat_pump(s: HeatPumpScenario, tariff: Tariff = OFGEM_Q4_2026) -> dict:
    """Equal delivered heat before/after; no assumed behaviour change or installation costs."""
    displaced_gas_kwh = s.gas_kwh * s.gas_heating_fraction
    delivered_heat_kwh = displaced_gas_kwh * s.boiler_efficiency
    hp_electricity_kwh = delivered_heat_kwh / s.heat_pump_spf
    remaining_gas_kwh = s.gas_kwh - displaced_gas_kwh
    gas_standing_before = s.days * tariff.gas_standing_p_per_day / 100
    gas_standing_after = 0 if s.disconnect_gas else gas_standing_before
    electricity_standing = s.days * tariff.electricity_standing_p_per_day / 100
    electricity_before = s.other_electricity_kwh * tariff.electricity_p_per_kwh / 100
    electricity_after = (s.other_electricity_kwh + hp_electricity_kwh) * tariff.electricity_p_per_kwh / 100
    gas_before = s.gas_kwh * tariff.gas_p_per_kwh / 100
    gas_after = remaining_gas_kwh * tariff.gas_p_per_kwh / 100
    before = electricity_before + gas_before + electricity_standing + gas_standing_before
    after = electricity_after + gas_after + electricity_standing + gas_standing_after
    annual_saving = before - after
    if annual_saving > 0 and s.retrofit_capex_gbp > 0:
        payback_years = s.retrofit_capex_gbp / annual_saving
    else:
        payback_years = None
    return {
        'scenario': asdict(s), 'tariff': asdict(tariff),
        'displaced_gas_kwh': displaced_gas_kwh, 'delivered_heat_kwh': delivered_heat_kwh,
        'additional_hp_electricity_kwh': hp_electricity_kwh,
        'remaining_gas_kwh': remaining_gas_kwh,
        'electricity_before_kwh': s.other_electricity_kwh,
        'electricity_after_kwh': s.other_electricity_kwh + hp_electricity_kwh,
        'baseline_annual_bill_gbp': round(before, 2), 'heat_pump_annual_bill_gbp': round(after, 2),
        'annual_saving_gbp': round(annual_saving, 2),
        'simple_payback_years': round(payback_years, 2) if payback_years is not None else None,
        'variable_cost_break_even_spf': (s.boiler_efficiency * tariff.electricity_p_per_kwh /
                                         tariff.gas_p_per_kwh) if tariff.gas_p_per_kwh else None,
    }


def _canonical_interval(row: dict) -> tuple[datetime, float, int]:
    start = timestamp_utc(row['start_utc'])
    kwh = _number(float(row['consumption_kwh']), 'consumption_kwh')
    duration = int(row.get('duration_minutes') or 30)
    if duration not in (15, 30, 60):
        raise ValueError('duration_minutes must be 15, 30 or 60')
    return start, kwh, duration


def summarize_meter(rows: list[dict], *, timezone_name: str = 'Europe/London') -> dict:
    """Report coverage separately from averages so missing readings are not zero-filled."""
    if not rows:
        raise ValueError('Meter CSV has no rows')
    tz = ZoneInfo(timezone_name)
    intervals = sorted(_canonical_interval(row) for row in rows)
    seen = set()
    for start, _, duration in intervals:
        if start in seen:
            raise ValueError(f'Duplicate interval at {start.isoformat()}')
        seen.add(start)
    for (start, _, mins), (next_start, _, _) in zip(intervals, intervals[1:]):
        if start + timedelta(minutes=mins) > next_start:
            raise ValueError('Overlapping intervals')
    total = sum(kwh for _, kwh, _ in intervals)
    hours_observed = sum(minutes for _, _, minutes in intervals) / 60
    span_hours = (max(start + timedelta(minutes=minutes) for start, _, minutes in intervals) -
                  intervals[0][0]).total_seconds() / 3600
    coverage = hours_observed / span_hours
    powers = sorted(kwh * 60 / minutes for _, kwh, minutes in intervals)
    p95 = powers[ceil(0.95 * len(powers)) - 1]
    by_local_hour = {hour: [0.0, 0] for hour in range(24)}
    for start, kwh, _ in intervals:
        hour = start.astimezone(tz).hour
        by_local_hour[hour][0] += kwh
        by_local_hour[hour][1] += 1
    return {
        'intervals': len(intervals), 'first_start_utc': intervals[0][0].isoformat(),
        'last_end_utc': max(start + timedelta(minutes=m) for start, _, m in intervals).isoformat(),
        'observed_hours': round(hours_observed, 3), 'span_hours': round(span_hours, 3),
        'coverage_fraction': round(coverage, 5), 'total_kwh': round(total, 4),
        'peak_interval_kw': round(max(powers), 3), 'p95_interval_kw': round(p95, 3),
        'mean_observed_kw': round(total / hours_observed, 3),
        'local_hour_mean_interval_kwh': {str(h): round(total_kwh / n, 4) if n else None
                                         for h, (total_kwh, n) in by_local_hour.items()},
        'timezone': timezone_name,
    }


def price_meter_rows(rows: list[dict], rate_rows: list[dict], *, standing_p_per_day: float = 0,
                     timezone_name: str = 'Europe/London') -> dict:
    """Exact UTC timestamp join; fails closed if any interval lacks a price."""
    _number(standing_p_per_day, 'standing_p_per_day')
    tz = ZoneInfo(timezone_name)
    rates = {}
    for row in rate_rows:
        t = timestamp_utc(row['start_utc'])
        if t in rates:
            raise ValueError(f'Duplicate tariff rate at {t}')
        rates[t] = float(row['unit_rate_p_per_kwh'])
        if not isfinite(rates[t]):
            raise ValueError('Tariff rate must be finite')  # Negative Agile rates are valid.
    if not rows:
        raise ValueError('Meter CSV has no rows')
    summary = summarize_meter(rows, timezone_name=timezone_name)
    cost_pence = 0.0
    local_dates = set()
    for row in rows:
        t, kwh, _ = _canonical_interval(row)
        if t not in rates:
            raise ValueError(f'No price for {t.isoformat()}; no silent assumptions or interpolation')
        cost_pence += kwh * rates[t]
        local_dates.add(t.astimezone(tz).date())
    standing = len(local_dates) * standing_p_per_day / 100
    return {
        **summary, 'matched_intervals': len(rows),
        'variable_cost_gbp': round(cost_pence / 100, 2),
        'standing_charge_gbp': round(standing, 2),
        'total_cost_gbp': round(cost_pence / 100 + standing, 2),
        'standing_charge_days': len(local_dates),
        'effective_variable_rate_p_per_kwh': round(cost_pence / summary['total_kwh'], 4) if summary['total_kwh'] else None,
    }


def aggregate_heatpump_days(rows: list[dict], *, min_quality: float = 95, min_data_hours: float = 23) -> dict:
    """Quality-filtered observed SPF, heat-weighted/energy-weighted rather than averaging COP."""
    if not 0 <= min_quality <= 100 or not 0 <= min_data_hours <= 24:
        raise ValueError('quality must be 0..100 and hours 0..24')
    accepted = []
    rejected = {'missing_values': 0, 'poor_coverage_or_quality': 0, 'nonpositive_energy': 0}
    for row in rows:
        try:
            elec, heat = float(row['combined_elec_kwh']), float(row['combined_heat_kwh'])
            qelec, qheat = float(row['quality_elec']), float(row['quality_heat'])
            length = float(row['combined_data_length'])
            t = datetime.fromtimestamp(float(row['timestamp']), tz=timezone.utc)
            if not all(map(isfinite, (elec, heat, qelec, qheat, length))):
                raise ValueError('nonfinite')
        except (KeyError, ValueError, TypeError, OverflowError):
            rejected['missing_values'] += 1
            continue
        if elec <= 0 or heat < 0:
            rejected['nonpositive_energy'] += 1
            continue
        if min(qelec, qheat) < min_quality or length < min_data_hours * 3600:
            rejected['poor_coverage_or_quality'] += 1
            continue
        temp_raw = row.get('combined_outsideT_mean')
        try:
            temp = float(temp_raw)
            if not isfinite(temp):
                temp = None
        except (TypeError, ValueError):
            temp = None
        accepted.append((t, elec, heat, temp))
    electric = sum(r[1] for r in accepted)
    heat = sum(r[2] for r in accepted)
    bins = [(-100, 0, '<0 C'), (0, 5, '0-5 C'), (5, 10, '5-10 C'),
            (10, 15, '10-15 C'), (15, 100, '>=15 C')]
    temperature_bins = []
    for low, high, label in bins:
        in_bin = [r for r in accepted if r[3] is not None and low <= r[3] < high]
        e = sum(r[1] for r in in_bin)
        h = sum(r[2] for r in in_bin)
        temperature_bins.append({'outside_temperature_bin': label, 'days': len(in_bin),
                                 'electricity_kwh': round(e, 3), 'heat_kwh': round(h, 3),
                                 'observed_cop': round(h / e, 3) if e else None})
    dates = [r[0] for r in accepted]
    return {
        'rows_total': len(rows), 'accepted_days': len(accepted), 'rejections': rejected,
        'observed_electricity_kwh': round(electric, 3), 'observed_heat_kwh': round(heat, 3),
        'observed_spf': round(heat / electric, 3) if electric else None,
        'first_accepted_utc': min(dates).date().isoformat() if dates else None,
        'last_accepted_utc': max(dates).date().isoformat() if dates else None,
        'temperature_bins': temperature_bins,
        'note': 'Observed, quality-filtered subset only; not a full-year SPF unless year-long complete coverage is established.',
    }
