"""EV charging scheduling against an explicitly provided public tariff rate series."""
from __future__ import annotations

from datetime import timedelta
from math import isfinite

from .core import timestamp_utc


def schedule_ev_charge(rate_rows: list[dict], *, arrival_utc: str, departure_utc: str,
                       battery_energy_needed_kwh: float, charger_kw: float = 7,
                       charging_efficiency: float = .9, slot_minutes: int = 30) -> dict:
    """Perfect-foresight cheapest slots in a known parking window.

    `battery_energy_needed_kwh` is energy added to EV BATTERY, not metered input.
    No vehicle-to-grid, demand charges, calendar constraints, or idle losses.
    The result is a counterfactual; do not claim a vehicle is actually present.
    """
    arrival, depart = timestamp_utc(arrival_utc), timestamp_utc(departure_utc)
    if depart <= arrival or charger_kw <= 0 or battery_energy_needed_kwh < 0:
        raise ValueError('Invalid charging window/power/energy')
    if not 0 < charging_efficiency <= 1 or slot_minutes not in (15, 30, 60):
        raise ValueError('Invalid charging efficiency or slot duration')
    if not all(isfinite(float(x)) for x in (charger_kw, battery_energy_needed_kwh)):
        raise ValueError('Non-finite EV inputs')
    rates = {}
    for r in rate_rows:
        stamp = timestamp_utc(r['start_utc'])
        if stamp in rates:
            raise ValueError('Duplicate EV price slot')
        rate = float(r['unit_rate_p_per_kwh'])
        if not isfinite(rate):
            raise ValueError('Nonfinite tariff rate')
        rates[stamp] = rate
    candidates = []
    t = arrival
    while t < depart:
        duration_minutes = min(slot_minutes, (depart - t).total_seconds() / 60)
        if t not in rates:
            raise ValueError(f'Missing EV tariff rate at {t.isoformat()}')
        candidates.append((t, rates[t], charger_kw * duration_minutes / 60))
        t += timedelta(minutes=slot_minutes)
    required_grid_kwh = battery_energy_needed_kwh / charging_efficiency
    if sum(x[2] for x in candidates) + 1e-8 < required_grid_kwh:
        raise ValueError('Insufficient plugged-in charging window to meet requested energy')
    selected = {}
    remaining = required_grid_kwh
    for t, p, cap in sorted(candidates, key=lambda x: (x[1], x[0])):
        kwh = min(cap, remaining)
        if kwh > 1e-8:
            selected[t] = kwh
            remaining -= kwh
    optimum = sum(selected.get(t, 0) * p for t, p, _ in candidates) / 100
    # Baseline: charge immediately on arrival, same total and power constraints.
    immediate = {}
    remaining = required_grid_kwh
    for t, p, cap in candidates:
        kwh = min(cap, remaining)
        immediate[t] = kwh
        remaining -= kwh
    baseline = sum(immediate[t] * p for t, p, _ in candidates) / 100
    return {'arrival_utc': arrival.isoformat(), 'departure_utc': depart.isoformat(),
            'battery_energy_added_kwh': battery_energy_needed_kwh,
            'grid_energy_kwh': round(required_grid_kwh, 4),
            'charge_immediately_cost_gbp': round(baseline, 2),
            'optimised_cost_gbp': round(optimum, 2),
            'price_aware_saving_gbp': round(baseline - optimum, 2),
            'schedule': [{'start_utc': t.isoformat(), 'grid_kwh': round(kwh, 4),
                          'rate_p_per_kwh': rates[t]} for t, kwh in sorted(selected.items())],
            'note': 'Optimistic perfect-foresight scheduling; requires access to charger controls and vehicle availability.'}
