"""Deterministic synthetic full-year UK home study; no outside data or credentials.

Creates load, weather, meter tariff results, weather forecast validation,
EV/absence signatures, and a full archetype/technology/tariff scenario grid.
Every output is explicitly synthetic; never cite it as measured UK household data.
Run: python scripts/run_study.py --out reports/synthetic_study
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from domestic_energy.economics import simulate_portfolio, investment_appraisal
from domestic_energy.forecast import fit_daily_model, predict_daily
from domestic_energy.signatures import identify_system_clues
from domestic_energy.flexibility import schedule_ev_charge


# These are ILLUSTRATIVE variables, NOT externally verified property-type norms.
ARCHETYPES = {
    'older_detached': {'heat_loss_w_k': 260., 'electric_base_kwh_day': 7.2},
    'efficient_flat': {'heat_loss_w_k': 80., 'electric_base_kwh_day': 5.},
    'mid_terrace': {'heat_loss_w_k': 160., 'electric_base_kwh_day': 6.2},
    'older_semi': {'heat_loss_w_k': 210., 'electric_base_kwh_day': 6.8},
}

TARIFFS = [
    {'name': 'Ofgem_Q4_2026_rates_held_12mo', 'flat_import_p': 26.32,
     'electricity_standing_p_per_day': 54.83, 'gas_p': 7.97,
     'gas_standing_p_per_day': 29.68, 'export_p': 5},
    {'name': 'HYPOTHETICAL_TOU_cheap_overnight',
     'schedule': [{'start_hour': 0, 'end_hour': 6, 'import_p': 10},
                  {'start_hour': 6, 'end_hour': 16, 'import_p': 31},
                  {'start_hour': 16, 'end_hour': 19, 'import_p': 41},
                  {'start_hour': 19, 'end_hour': 24, 'import_p': 31}],
     'electricity_standing_p_per_day': 54.83, 'gas_p': 7.97,
     'gas_standing_p_per_day': 29.68, 'export_p': 5},
]

# Battery tested on a manageable fixed subset; no free initial stored energy.
PORTFOLIOS = {
    'gas_base': {},
    'solar_4kWp': {'pv_scale': 1},
    'insulation_heat_20pct': {'insulation_heat_reduction': .2},
    'hp_spf_2p4': {'heat_pump_spf': 2.4, 'disconnect_gas': True, 'remaining_gas_to_electric_kwh_per_kwh': .85},
    'hp_spf_3p4': {'heat_pump_spf': 3.4, 'disconnect_gas': True, 'remaining_gas_to_electric_kwh_per_kwh': .85},
    'solar_plus_hp_3p4': {'pv_scale': 1, 'heat_pump_spf': 3.4, 'disconnect_gas': True, 'remaining_gas_to_electric_kwh_per_kwh': .85},
    'insulation_solar_hp': {'insulation_heat_reduction': .2, 'pv_scale': 1,
                             'heat_pump_spf': 3.4, 'disconnect_gas': True, 'remaining_gas_to_electric_kwh_per_kwh': .85},
    'direct_electric_gas_replacement': {'direct_electric_from_gas': True, 'disconnect_gas': True,
         'remaining_gas_to_electric_kwh_per_kwh': .85},
    'electric_storage_heater_12kWh': {'direct_electric_from_gas': True, 'disconnect_gas': True,
         'remaining_gas_to_electric_kwh_per_kwh': .85, 'storage_heater_kwh_th': 12,
         'storage_heater_power_kw': 7, 'storage_heater_efficiency': .95},
    'solar_battery_5kWh': {'pv_scale': 1, 'battery_kwh': 5, 'battery_power_kw': 3},
    'all_measures_with_battery': {'insulation_heat_reduction': .2, 'pv_scale': 1,
                                  'heat_pump_spf': 3.4, 'disconnect_gas': True, 'remaining_gas_to_electric_kwh_per_kwh': .85,
                                  'battery_kwh': 5, 'battery_power_kw': 3},
}


def make_house(name: str, *, year: int = 2025, location: str = 'London',
               work_from_home: bool = True, holiday: bool = True,
               ev_charging: bool = True) -> tuple[list[dict], list[dict], dict]:
    """Synthesize climate + 30min heat/electric load; weather and activity are KNOWN.

    Simplified outdoor temperature cycles are NOT weather observations. Daily
    space-heat gas fractions and PV generation are constructed synthetic truths.
    """
    p = ARCHETYPES[name]
    if location not in ('London', 'Glasgow', 'Plymouth'):
        raise ValueError('Unknown illustrative region')
    loc_offset = {'London': 0, 'Glasgow': -2.5, 'Plymouth': 1.5}[location]
    rng = random.Random(1002)
    start = datetime(year, 1, 1, tzinfo=timezone.utc)
    end = datetime(year+1, 1, 1, tzinfo=timezone.utc)
    records, days = [], []
    when = start
    day_counter = 0
    total_charging = 0.
    while when < end:
        d = when.date()
        hdd_temp = 10.5 + 7.5 * math.cos(2 * math.pi * ((d.timetuple().tm_yday-1) - 207) / 365)
        outdoor = hdd_temp + loc_offset + rng.uniform(-2.2, 2.2)
        away = holiday and (125 <= day_counter < 134 or 220 <= day_counter < 228)
        wfh = work_from_home and (d.weekday() in (0, 2, 4)) and not away
        day_heat_kwh = max(0, 16-outdoor) * p['heat_loss_w_k'] * 24/1000
        # Thermal setback on holiday is KNOWN, but house remains frost-protected.
        if away:
            day_heat_kwh *= .30
        daily_electric = p['electric_base_kwh_day'] * (0.33 if away else 1.22 if wfh else 1.0)
        gas_dhw = 1.2 if away else 3.0
        daily_gas = day_heat_kwh / .85 + gas_dhw
        days.append({'date': str(d), 'temperature_c': round(outdoor, 3),
                     'consumption_kwh': round(daily_gas, 4), 'away': int(away),
                     'work_from_home': int(wfh)})
        hw = [2.5 if 6 <= hr < 9 else 1.5 if 17 <= hr < 23 else 0.4 for hr in range(24)]
        w = [hw[hr] for hr in range(24) for _ in range(2)]
        total_heat_weights = sum(w)
        electric_weights = [1.8 if 7 <= hr < 9 or 18 <= hr < 23 else .65 for hr in range(24) for _ in range(2)]
        e_total = sum(electric_weights)
        for i in range(48):
            t = when + timedelta(minutes=i*30)
            hour = i / 2
            gas_heating = (day_heat_kwh / .85) * w[i] / total_heat_weights
            gas = gas_heating + gas_dhw / 48
            general_e = daily_electric * electric_weights[i] / e_total
            # Actual EV load is additional kWh on Tue/Fri/Sun after 01:00.
            charge = 3.5 if (ev_charging and not away and d.weekday() in (1,4,6) and 1 <= hour < 3) else 0.
            total_charging += charge
            # Synthetic 4kWp PV, seasonal daylight and deterministic clouds.
            day_length = 9 + 7 * math.cos(2 * math.pi * (d.timetuple().tm_yday - 172) / 365)
            solar_hour = max(0., math.sin(math.pi * (hour - (12-day_length/2)) / day_length))
            cloud = .65 + .2 * math.cos(day_counter * .3)
            pv = 4 * solar_hour * cloud * .25
            records.append({'start_utc': t.isoformat(), 'duration_minutes': 30,
                'consumption_kwh': round(general_e + charge, 5),
                'gas_kwh': round(gas, 5), 'gas_heating_kwh': round(gas_heating, 5),
                'electric_heating_kwh': 0,
                'pv_generation_kwh': round(pv, 5), 'temperature_c': round(outdoor, 3)})
        when += timedelta(days=1)
        day_counter += 1
    truth = {'scenario': 'SYNTHETIC', 'archetype': name, 'location': location,
             'gas_kwh': round(sum(float(r['gas_kwh']) for r in records), 1),
             'baseline_electricity_kwh': round(sum(float(r['consumption_kwh']) for r in records), 1),
             'known_ev_grid_kwh': round(total_charging, 1), 'holiday_days': sum(r['away'] for r in days),
             'assumed_heat_loss_w_per_k': p['heat_loss_w_k'],
             'synthetic_possible_pv_kwh': round(sum(float(r['pv_generation_kwh']) for r in records),1)}
    return records, days, truth


def write_csv(path: Path, rows: list[dict]):
    with path.open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(output: Path):
    output.mkdir(parents=True, exist_ok=True)
    scenarios = []
    truths = []
    for archetype in ARCHETYPES:
        intervals, days, truth = make_house(archetype)
        truths.append(truth)
        if archetype == 'mid_terrace':
            write_csv(output / 'SYNTHETIC_mid_terrace_2025_intervals.csv', intervals)
            write_csv(output / 'SYNTHETIC_mid_terrace_2025_daily_gas.csv', days)
            forecast = fit_daily_model(days, fuel='gas', boiler_efficiency=.85, floor_area_m2=110)
            detection = identify_system_clues(
                [{'start_utc': r['start_utc'], 'consumption_kwh': r['consumption_kwh']} for r in intervals])
            (output / 'forecast_and_detection.json').write_text(json.dumps({
                'data_type': 'ENTIRELY SYNTHETIC', 'forecast': forecast,
                'ev_like_sessions_count': len(detection['ev_like_sessions']),
                'low_activity_spells': detection['low_activity_spells']}, indent=2))
        for plan in TARIFFS:
            baseline_cost = simulate_portfolio(intervals, plan)['with_battery']['total_bill_gbp']
            for portfolio_name, params in PORTFOLIOS.items():
                # Battery grids take longer; still run complete year.
                outcome = simulate_portfolio(intervals, plan, **params)
                yearly = outcome['with_battery']['total_bill_gbp']
                scenarios.append({'data_type': 'SYNTHETIC', 'archetype': archetype,
                    'tariff': plan['name'], 'portfolio': portfolio_name,
                    'annual_bill_gbp': yearly, 'saving_vs_same_tariff_gas_base_gbp': round(baseline_cost-yearly, 2),
                    'grid_import_kwh': outcome['with_battery']['grid_import_kwh'],
                    'export_kwh': outcome['with_battery']['grid_export_kwh'],
                    'heat_pump_achieved_spf': outcome['resulting_heat_pump_spf'],
                    'meter_coverage': outcome['coverage_fraction']})
    write_csv(output / 'SYNTHETIC_scenario_grid.csv', scenarios)
    (output / 'SYNTHETIC_truth.json').write_text(json.dumps(truths, indent=2) + '\n')
    (output / 'SYNTHETIC_sample_tariffs.json').write_text(json.dumps(TARIFFS, indent=2) + '\n')
    # Full-year example baseline+measure affordability: CAPEX is a user assumption.
    selected = [s for s in scenarios if s['archetype'] == 'mid_terrace' and
                s['tariff'] == 'Ofgem_Q4_2026_rates_held_12mo' and s['portfolio'] == 'solar_4kWp'][0]
    appraisal = investment_appraisal(selected['saving_vs_same_tariff_gas_base_gbp'],
                                    capex_gbp=6500, lifetime_years=20, discount_rate=.035)
    (output / 'SYNTHETIC_example_investment.json').write_text(json.dumps(appraisal, indent=2)+'\n')
    print(json.dumps({'total_full_year_scenarios': len(scenarios),
       'archetypes': len(ARCHETYPES), 'tariffs': len(TARIFFS), 'retrofit_cases': len(PORTFOLIOS),
       'first_examples': scenarios[:3], 'illustrative_solar_project': appraisal}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', default='reports/synthetic_study')
    args = parser.parse_args()
    run(Path(args.out))
