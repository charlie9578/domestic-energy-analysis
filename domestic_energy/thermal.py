"""Thermal store / night-storage heating scheduling (simplified physics)."""
from __future__ import annotations

from math import floor, isfinite


def optimise_heat_storage(base_net_kwh: list[float], heat_demand_kwh_th: list[float],
                          import_p: list[float], export_p: list[float], minutes: list[int], *,
                          capacity_kwh_th: float, charge_power_kw: float = 7,
                          charge_efficiency: float = .95, heat_loss_fraction_per_hour: float = .01,
                          step_kwh_th: float = .5) -> tuple[list[float], dict]:
    """Price-aware electric resistance heating of a thermal store, perfect foresight.

    Assumes heat demand *must* be served in the same interval, zero initial and
    terminal stored heat; heat loss leaves the conditioned space (conservative).
    Not a room thermal-mass/comfort/heat-pump model. This is a storage heater,
    not an electrical battery. No free initial charge or impossible discharge.
    """
    capacity = float(capacity_kwh_th)
    power, eff, loss, step = map(float, (charge_power_kw, charge_efficiency,
                                       heat_loss_fraction_per_hour, step_kwh_th))
    n = len(base_net_kwh)
    if not (n and n == len(heat_demand_kwh_th) == len(import_p) == len(export_p) == len(minutes)):
        raise ValueError('Aligned non-empty interval arrays required')
    if not all(isfinite(v) and v >= 0 for v in heat_demand_kwh_th):
        raise ValueError('Heating demand must be finite and >=0')
    if not all(isfinite(v) for seq in (base_net_kwh, import_p, export_p) for v in seq):
        raise ValueError('Invalid net energy or price')
    if not all(isfinite(x) for x in (capacity, power, eff, loss, step)) or not (capacity >= 0 and power > 0 and 0 < eff <= 1 and 0 <= loss < 1 and step > 0):
        raise ValueError('Invalid heat-storage physical parameters')
    if capacity == 0:
        return [net + demand for net, demand in zip(base_net_kwh, heat_demand_kwh_th)], {
            'capacity_kwh_th': 0, 'electric_input_kwh': round(sum(heat_demand_kwh_th), 3),
            'perfect_foresight': False}
    levels = floor(capacity/step + 1e-9)
    if not 1 <= levels <= 160:
        raise ValueError('Storage/step requires between 1 and 160 SOC levels')
    states = [i*step for i in range(levels+1)]
    inf = float('inf')
    prev = [inf]*(levels+1)
    prev[0] = 0
    backpointers=[]
    for base, demand, pin, pout, mins in zip(base_net_kwh, heat_demand_kwh_th, import_p, export_p, minutes):
        factor = (1-loss)**(mins/60)
        limit = power * mins / 60
        scores = [inf]*(levels+1)
        backs = [-1]*(levels+1)
        for last_state, oldcost in enumerate(prev):
            if oldcost == inf:
                continue
            available = states[last_state]*factor
            for next_state in range(levels+1):
                input_kwh = (demand + states[next_state] - available)/eff
                if input_kwh < -1e-9 or input_kwh > limit + 1e-9:
                    continue
                input_kwh = max(0, input_kwh)
                net = base + input_kwh
                cost = max(0, net)*pin - max(0, -net)*pout
                trial = oldcost + cost + input_kwh*1e-7
                if trial < scores[next_state]-1e-9:
                    scores[next_state] = trial
                    backs[next_state] = last_state
        backpointers.append(backs)
        prev = scores
    if prev[0] == inf:
        raise ValueError('Heat demand infeasible with charge-power/time/capacity limits')
    state = 0
    grid = [0.]*n
    charged=0.
    lost=0.
    for i in reversed(range(n)):
        past = backpointers[i][state]
        if past < 0:
            raise RuntimeError('Thermal store reconstruction failed')
        factor = (1-loss)**(minutes[i]/60)
        input_kwh = max(0, (heat_demand_kwh_th[i]+states[state]-states[past]*factor)/eff)
        grid[i] = base_net_kwh[i] + input_kwh
        charged+=input_kwh
        lost+=states[past]*(1-factor)
        state = past
    assert state == 0
    return grid, {'capacity_kwh_th': states[-1], 'charge_power_kw': power,
                  'charge_efficiency': eff, 'heat_loss_fraction_per_hour': loss,
                  'electric_input_kwh': round(charged, 3), 'heat_lost_kwh_th': round(lost, 3),
                  'perfect_foresight': True, 'start_and_end_thermal_soc_kwh': 0,
                  'note': 'Simplified heater with storage losses, perfect future prices and heat demand. Does not assess comfort or real installation.'}
