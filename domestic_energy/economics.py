"""Transparent tariff, PV, battery, insulation and heat-pump counterfactuals.

All inputs are interval *energy* kWh, not instantaneous power. No claims that
prices, generation, asset performance or demand forecasts are guaranteed.
"""
from __future__ import annotations

from datetime import timedelta
from math import floor, isfinite, sqrt
from zoneinfo import ZoneInfo

from .core import _canonical_interval, timestamp_utc
from .thermal import optimise_heat_storage


def _finite(value: object, name: str, *, minimum: float | None = None) -> float:
    try:
        n = float(value)
    except (ValueError, TypeError) as exc:
        raise ValueError(f'{name} must be numeric') from exc
    if not isfinite(n) or (minimum is not None and n < minimum):
        raise ValueError(f'{name} must be finite' + (f' and >= {minimum}' if minimum is not None else ''))
    return n


def _normalized(rows: list[dict]) -> list[dict]:
    if not rows:
        raise ValueError('Require meter interval rows')
    result = []
    last_end = None
    for r in sorted(rows, key=lambda r: timestamp_utc(r['start_utc'])):
        t, kwh, mins = _canonical_interval(r)
        if last_end is not None and t < last_end:
            raise ValueError('Overlapping or duplicate intervals')
        last_end = t + timedelta(minutes=mins)
        result.append({'t': t, 'minutes': mins, 'electricity': kwh,
                       'pv': _finite(r.get('pv_generation_kwh', 0) or 0, 'pv_generation_kwh', minimum=0),
                       'gas': _finite(r.get('gas_kwh', 0) or 0, 'gas_kwh', minimum=0),
                       'gas_heating': _finite(r.get('gas_heating_kwh', 0) or 0, 'gas_heating_kwh', minimum=0),
                       'electric_heating': _finite(r.get('electric_heating_kwh', 0) or 0, 'electric_heating_kwh', minimum=0),
                       'temperature_c': (_finite(r['temperature_c'], 'temperature_c')
                                         if str(r.get('temperature_c', '')).strip() else None)})
        if result[-1]['gas_heating'] > result[-1]['gas'] + 1e-8:
            raise ValueError('gas_heating_kwh cannot exceed total gas_kwh')
        if result[-1]['electric_heating'] > kwh + 1e-8:
            raise ValueError('electric_heating_kwh cannot exceed total consumption_kwh')
    return result


def _rates_for(rows: list[dict], tariff: dict, *, timezone_name: str) -> tuple[list[float], list[float]]:
    if not tariff.get('name'):
        raise ValueError('Each tariff needs a name')
    allowed = ('flat_import_p', 'schedule', 'interval_rates')
    if sum(tariff.get(k) is not None for k in allowed) != 1:
        raise ValueError('Specify exactly one of flat_import_p, schedule or interval_rates')
    tz = ZoneInfo(timezone_name)
    if tariff.get('schedule') is not None:
        slots = tariff['schedule']
        if not slots or not all(0 <= int(s['start_hour']) < 24 and 0 < int(s['end_hour']) <= 24
                                and int(s['start_hour']) < int(s['end_hour']) for s in slots):
            raise ValueError('Invalid hourly tariff schedule')
        covered = [0] * 24
        hourly = [0.] * 24
        for s in slots:
            for h in range(int(s['start_hour']), int(s['end_hour'])):
                covered[h] += 1
                hourly[h] = _finite(s['import_p'], 'import_p')
        if covered != [1] * 24:
            raise ValueError('Schedule must cover every local hour exactly once')
        import_prices = [hourly[r['t'].astimezone(tz).hour] for r in rows]
    elif tariff.get('interval_rates') is not None:
        source = tariff['interval_rates']
        # List-of-dicts or timestamp-to-price map. Reject duplicates and gaps.
        if isinstance(source, dict):
            mapping = {timestamp_utc(t): _finite(p, 'interval price') for t, p in source.items()}
        else:
            mapping = {}
            for x in source:
                stamp = timestamp_utc(x['start_utc'])
                if stamp in mapping:
                    raise ValueError('Duplicate tariff interval')
                mapping[stamp] = _finite(x['unit_rate_p_per_kwh'], 'interval price')
        if any(r['t'] not in mapping for r in rows):
            raise ValueError('Dynamic tariff lacks at least one meter timestamp')
        import_prices = [mapping[r['t']] for r in rows]
    else:
        import_prices = [_finite(tariff['flat_import_p'], 'flat_import_p')] * len(rows)
    export_price = _finite(tariff.get('export_p', 0), 'export_p')
    return import_prices, [export_price] * len(rows)


def _bill(net_grid_kwh: list[float], import_p: list[float], export_p: list[float],
          import_standing_p: float, gas_kwh: float, gas_p: float, gas_standing_p: float,
          days: int) -> dict:
    imp = sum(max(0., k) for k in net_grid_kwh)
    exp = sum(max(0., -k) for k in net_grid_kwh)
    cost_import = sum(max(0., k) * p for k, p in zip(net_grid_kwh, import_p)) / 100
    income_export = sum(max(0., -k) * p for k, p in zip(net_grid_kwh, export_p)) / 100
    gas_cost = gas_kwh * gas_p / 100 + days * gas_standing_p / 100
    standing = days * import_standing_p / 100
    return {'grid_import_kwh': round(imp, 3), 'grid_export_kwh': round(exp, 3),
            'import_variable_gbp': round(cost_import, 2), 'export_credit_gbp': round(income_export, 2),
            'electricity_standing_gbp': round(standing, 2), 'gas_total_gbp': round(gas_cost, 2),
            'total_bill_gbp': round(cost_import - income_export + standing + gas_cost, 2)}


def _battery_optimize(nets: list[float], prices: list[float], exports: list[float],
                      minutes: list[int], *, capacity_kwh: float, power_kw: float,
                      round_trip_efficiency: float, step_kwh: float = 0.5) -> tuple[list[float], dict]:
    """Perfect-foresight *optimistic lower bound* on grid bill; discrete SOC DP.

    Initial and final state of charge are exactly ZERO, eliminating free stored
    energy. Does not export battery energy; export remains possible for surplus
    PV. Uses charge/discharge efficiency sqrt(RTE), no degradation/fees.
    """
    capacity = _finite(capacity_kwh, 'battery capacity', minimum=0)
    if capacity == 0:
        return list(nets), {'capacity_effective_kwh': 0., 'cycle_count_equivalent': 0.,
                            'charge_from_grid_allowed': True, 'perfect_foresight': True}
    power = _finite(power_kw, 'battery power', minimum=0.001)
    rte = _finite(round_trip_efficiency, 'round_trip_efficiency', minimum=0.001)
    step = _finite(step_kwh, 'step_kwh', minimum=0.001)
    if rte > 1 or capacity / step > 200:
        raise ValueError('RTE must be <=1 and capacity/step <=200 for computational safety')
    nstate = floor(capacity / step + 1e-9) + 1
    if nstate < 2:
        raise ValueError('Capacity must be at least one discretization step')
    eta = sqrt(rte)
    states = [j * step for j in range(nstate)]
    inf = float('inf')
    previous = [inf] * nstate
    previous[0] = 0.
    backpointers = []
    for net, p_in, p_out, duration in zip(nets, prices, exports, minutes):
        limit = power * duration / 60
        now = [inf] * nstate
        back = [-1] * nstate
        for prev_id, prev_score in enumerate(previous):
            if prev_score == inf:
                continue
            for nxt_id in range(nstate):
                delta = states[nxt_id] - states[prev_id]
                flow = delta / eta if delta >= 0 else delta * eta
                if abs(flow) > limit + 1e-9:
                    continue
                grid = net + flow
                # Disallow battery discharge creating EXTRA export (no battery selling).
                if delta < 0 and grid < min(net, 0.) - 1e-9:
                    continue
                cost = max(0, grid) * p_in - max(0, -grid) * p_out
                trial = prev_score + cost + (abs(delta) * 1e-7)
                if trial < now[nxt_id] - 1e-9:
                    now[nxt_id] = trial
                    back[nxt_id] = prev_id
        previous = now
        backpointers.append(back)
    if previous[0] == inf:
        raise ValueError('No feasible zero-to-zero battery path')
    state = 0
    nets_with_battery = [0.] * len(nets)
    throughput = 0.
    grid_charging_kwh = 0.
    pv_charging_kwh = 0.
    for i in reversed(range(len(nets))):
        old = backpointers[i][state]
        if old < 0:
            raise RuntimeError('Battery optimization reconstruction failed')
        delta = states[state] - states[old]
        flow = delta / eta if delta >= 0 else delta * eta
        nets_with_battery[i] = nets[i] + flow
        if delta > 0:
            throughput += delta
            pv_charging_kwh += min(flow, max(0, -nets[i]))
            grid_charging_kwh += max(0, flow - max(0, -nets[i]))
        state = old
    assert state == 0
    return nets_with_battery, {
        'capacity_effective_kwh': round(states[-1], 3),
        'power_kw': power, 'round_trip_efficiency': rte,
        'cycle_count_equivalent': round(throughput / states[-1], 2),
        'grid_energy_to_battery_kwh': round(grid_charging_kwh, 3),
        'surplus_pv_to_battery_kwh': round(pv_charging_kwh, 3),
        'perfect_foresight': True, 'start_and_end_soc_kwh': 0,
        'optimistic_lower_bound': 'Future prices/PV/load are known perfectly; control/aging/cycles/inverter standby omitted.'}


def _interpolated_cop(temperature_c: float, curve: list[list[float]]) -> float:
    points = sorted((float(x), float(y)) for x, y in curve)
    if len(points) < 2 or len({x for x, _ in points}) != len(points) or any(not isfinite(x) or not isfinite(y) or y <= 0 for x, y in points):
        raise ValueError('COP curve must have 2+ distinct temperatures and positive finite COPs')
    if temperature_c <= points[0][0]:
        return points[0][1]
    if temperature_c >= points[-1][0]:
        return points[-1][1]
    for (low, a), (high, b) in zip(points, points[1:]):
        if low <= temperature_c <= high:
            return a + (b-a)*(temperature_c-low)/(high-low)
    raise RuntimeError('COP curve interpolation failed')


def simulate_portfolio(rows: list[dict], tariff: dict, *, pv_scale: float = 0,
                       battery_kwh: float = 0, battery_power_kw: float = 3,
                       battery_efficiency: float = 0.9, battery_step_kwh: float = 0.5,
                       insulation_heat_reduction: float = 0,
                       heat_pump_spf: float | None = None, heat_pump_cop_curve: list[list[float]] | None = None, boiler_efficiency: float = 0.85,
                       direct_electric_from_gas: bool = False,
                       storage_heater_kwh_th: float = 0, storage_heater_power_kw: float = 7,
                       storage_heater_efficiency: float = .95,
                       storage_heater_loss_fraction_per_hour: float = .01,
                       disconnect_gas: bool = False,
                       remaining_gas_to_electric_kwh_per_kwh: float | None = None,
                       timezone_name: str = 'Europe/London') -> dict:
    """Replay ONE named tariff with optional explicitly metered thermal subloads.

    `gas_heating_kwh` is the GAS INPUT assigned to space heating, not useful heat.
    `electric_heating_kwh` is the electricity specifically used by heating.
    Insulation reduces both known heating components by same illustrative fraction;
    it must NOT be applied to unclassified whole-house demand.
    """
    records = _normalized(rows)
    if not 0 <= insulation_heat_reduction < 1:
        raise ValueError('Insulation reduction must be >=0 and <1')
    if pv_scale < 0 or not isfinite(pv_scale):
        raise ValueError('Invalid solar scale')
    if remaining_gas_to_electric_kwh_per_kwh is not None:
        factor = _finite(remaining_gas_to_electric_kwh_per_kwh, 'remaining_gas_to_electric_kwh_per_kwh', minimum=0.001)
        if factor > 5:
            raise ValueError('Unreasonable residual gas conversion factor')
        if not disconnect_gas:
            raise ValueError('Remaining gas conversion factor requires disconnect_gas=True')
    if not 0 < boiler_efficiency <= 1:
        raise ValueError('Invalid boiler efficiency')
    if direct_electric_from_gas and (heat_pump_spf is not None or heat_pump_cop_curve is not None):
        raise ValueError('Choose a heat pump or direct electric gas replacement, not both')
    if direct_electric_from_gas and not any(r['gas_heating'] > 0 for r in records):
        raise ValueError('Direct electric gas conversion requires gas_heating_kwh observations')
    if heat_pump_spf is not None and heat_pump_cop_curve is not None:
        raise ValueError('Provide SPF or outdoor-temperature COP curve, not both')
    if heat_pump_cop_curve is not None:
        _interpolated_cop(7, heat_pump_cop_curve)
        if any(r['temperature_c'] is None for r in records):
            raise ValueError('COP curve requires temperature_c for every interval')
    if heat_pump_spf is not None and not 0 < heat_pump_spf <= 10:
        raise ValueError('Heat pump SPF must be (0,10]')
    if (heat_pump_spf is not None or heat_pump_cop_curve is not None) and not any(r['gas_heating'] > 0 for r in records):
        raise ValueError('Heat pump conversion requires explicit gas_heating_kwh rows')
    if insulation_heat_reduction and not any(r['gas_heating'] > 0 or r['electric_heating'] > 0 for r in records):
        raise ValueError('Insulation model requires explicit space heating submeter/allocations')
    total_thermal_hp = 0.
    total_electric_hp = 0.
    gas = []
    electric = []
    nets = []
    solar = []
    direct_heat_electric = []
    for r in records:
        gas_heating_after = r['gas_heating'] * (1 - insulation_heat_reduction)
        electric_use = r['electricity'] - r['electric_heating'] * insulation_heat_reduction
        gas_use = r['gas'] - r['gas_heating'] * insulation_heat_reduction
        storage_heat = r['electric_heating'] * (1-insulation_heat_reduction)
        if direct_electric_from_gas:
            gas_use -= gas_heating_after
            new_electric_heat = gas_heating_after * boiler_efficiency
            electric_use += new_electric_heat
            storage_heat += new_electric_heat
        if heat_pump_spf is not None or heat_pump_cop_curve is not None:
            gas_use -= gas_heating_after
            useful_heat = gas_heating_after * boiler_efficiency
            cop = (_interpolated_cop(r['temperature_c'], heat_pump_cop_curve)
                   if heat_pump_cop_curve is not None else heat_pump_spf)
            hp_energy = useful_heat / cop
            electric_use += hp_energy
            total_thermal_hp += useful_heat
            total_electric_hp += hp_energy
        if remaining_gas_to_electric_kwh_per_kwh is not None:
            electric_use += max(0, gas_use) * remaining_gas_to_electric_kwh_per_kwh
            gas_use = 0
        pv = r['pv'] * pv_scale
        solar.append(pv)
        direct_heat_electric.append(storage_heat)
        electric.append(electric_use)
        gas.append(max(0, gas_use))
        nets.append(electric_use - pv)
    total_gas = sum(gas)
    gas_p = _finite(tariff.get('gas_p', 0), 'gas_p', minimum=0)
    gas_standing = _finite(tariff.get('gas_standing_p_per_day', 0), 'gas_standing_p_per_day', minimum=0)
    elec_standing = _finite(tariff.get('electricity_standing_p_per_day', 0), 'electricity_standing_p_per_day', minimum=0)
    if disconnect_gas:
        if total_gas > 1e-7:
            raise ValueError('Cannot disconnect gas with residual gas use')
        gas_standing = 0
    rate_in, rate_out = _rates_for(records, tariff, timezone_name=timezone_name)
    dates = {r['t'].astimezone(ZoneInfo(timezone_name)).date() for r in records}
    # Bill standing charge over entire *calendar span*, even on missing data days.
    calendar_days = (max(dates) - min(dates)).days + 1
    duration = sum(r['minutes'] for r in records)
    span_hours = ((records[-1]['t'] + timedelta(minutes=records[-1]['minutes'])) - records[0]['t']).total_seconds() / 3600
    # Full interval coverage important: do not silently annualize holes.
    coverage = duration / 60 / span_hours
    raw_bill = _bill(nets, rate_in, rate_out, elec_standing, total_gas, gas_p, gas_standing, calendar_days)
    heat_storage_summary = None
    if storage_heater_kwh_th > 0:
        if not any(v > 0 for v in direct_heat_electric):
            raise ValueError('Storage heater requires direct-resistive electric_heating_kwh or direct_electric_from_gas')
        nets, heat_storage_summary = optimise_heat_storage(
            [net - heat for net, heat in zip(nets, direct_heat_electric)], direct_heat_electric,
            rate_in, rate_out, [r['minutes'] for r in records],
            capacity_kwh_th=storage_heater_kwh_th, charge_power_kw=storage_heater_power_kw,
            charge_efficiency=storage_heater_efficiency,
            heat_loss_fraction_per_hour=storage_heater_loss_fraction_per_hour)
    elif storage_heater_kwh_th < 0:
        raise ValueError('Storage heater capacity must be non-negative')
    dispatch = {'capacity_effective_kwh': 0, 'perfect_foresight': False}
    if battery_kwh > 0:
        dispatch_nets, dispatch = _battery_optimize(nets, rate_in, rate_out,
            [r['minutes'] for r in records], capacity_kwh=battery_kwh, power_kw=battery_power_kw,
            round_trip_efficiency=battery_efficiency, step_kwh=battery_step_kwh)
        final_bill = _bill(dispatch_nets, rate_in, rate_out, elec_standing, total_gas, gas_p, gas_standing, calendar_days)
    else:
        final_bill = _bill(nets, rate_in, rate_out, elec_standing, total_gas, gas_p, gas_standing, calendar_days)
    return {
        'tariff_name': tariff['name'],
        'intervals': len(records), 'calendar_days': calendar_days,
        'coverage_fraction': round(coverage, 5),
        'warning_if_gappy': 'Incomplete interval coverage: costs understate demand and do not represent a full bill.' if coverage < .9999 else None,
        'electricity_demand_kwh': round(sum(electric), 3),
        'pv_generation_kwh': round(sum(solar), 3), 'gas_kwh': round(total_gas, 3),
        'resulting_heat_pump_spf': round(total_thermal_hp / total_electric_hp, 3) if total_electric_hp else None,
        'before_storage_or_battery': raw_bill, 'with_battery': final_bill,
        'thermal_storage_dispatch': heat_storage_summary,
        'battery_dispatch': dispatch, 'portfolio': {
            'pv_scale_of_input_series': pv_scale, 'battery_kwh': battery_kwh,
            'insulation_heat_reduction': insulation_heat_reduction,
            'heat_pump_spf': heat_pump_spf, 'heat_pump_cop_curve': heat_pump_cop_curve,
            'direct_electric_from_gas': direct_electric_from_gas,
            'storage_heater_kwh_th': storage_heater_kwh_th,
            'remaining_gas_to_electric_kwh_per_kwh': remaining_gas_to_electric_kwh_per_kwh,
            'disconnect_gas': disconnect_gas},
        'assumptions': 'Weather/occupancy/space-heating attribution are inputs, not inferred here. Electricity price series is held fixed; PV series must already align to UTC meter intervals.',
    }


def compare_tariffs(rows: list[dict], tariffs: list[dict], **portfolio) -> dict:
    if not tariffs or len({t['name'] for t in tariffs}) != len(tariffs):
        raise ValueError('Tariffs required with distinct names')
    results = [simulate_portfolio(rows, t, **portfolio) for t in tariffs]
    ranked = sorted(results, key=lambda x: x['with_battery']['total_bill_gbp'])
    return {'ranked': [{'name': r['tariff_name'],
                        'cost_gbp': r['with_battery']['total_bill_gbp'],
                        'grid_import_kwh': r['with_battery']['grid_import_kwh'],
                        'grid_export_kwh': r['with_battery']['grid_export_kwh']}
                       for r in ranked],
            'savings_best_vs_worst_gbp': round(ranked[-1]['with_battery']['total_bill_gbp'] - ranked[0]['with_battery']['total_bill_gbp'], 2),
            'coverage_fraction': ranked[0]['coverage_fraction'],
            'note': 'Historical replay is not future price prediction; tariff availability, eligibility, contract exit fees, export qualification, VAT and standing days must be verified.'}


def investment_appraisal(annual_bill_saving_gbp: float, *, capex_gbp: float,
                         lifetime_years: int = 15, discount_rate: float = 0.035,
                         yearly_maintenance_gbp: float = 0,
                         saving_degradation_fraction: float = 0) -> dict:
    """Discounted-cash-flow screen (not a quote); zero residual asset value."""
    save = _finite(annual_bill_saving_gbp, 'saving')
    cost = _finite(capex_gbp, 'capex', minimum=0)
    upkeep = _finite(yearly_maintenance_gbp, 'maintenance', minimum=0)
    rate = _finite(discount_rate, 'discount_rate', minimum=0)
    loss = _finite(saving_degradation_fraction, 'saving_degradation_fraction', minimum=0)
    if lifetime_years < 1 or lifetime_years > 50 or loss >= 1:
        raise ValueError('Invalid project lifetime or annual degradation')
    cashflows = [save * (1-loss) ** (year-1) - upkeep for year in range(1, lifetime_years + 1)]
    npv = -cost + sum(cf / (1+rate) ** year for year, cf in enumerate(cashflows, 1))
    cumulative = -cost
    payback = None
    for i, cf in enumerate(cashflows, 1):
        if cumulative < 0 and cumulative + cf >= 0 and cf > 0:
            payback = i - 1 + (-cumulative / cf)
        cumulative += cf
    return {'capex_gbp': cost, 'year1_net_saving_gbp': round(cashflows[0], 2),
            'lifetime_years': lifetime_years, 'discount_rate': rate,
            'npv_gbp': round(npv, 2),
            'undiscounted_payback_years': round(payback, 2) if payback is not None else None,
            'assumptions': 'Constant real tariffs, zero financing/residual value, specified degradation and upkeep; no grant assumed.'}
