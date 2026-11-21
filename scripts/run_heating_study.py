"""Reproducible SYNTHETIC weather/physical-parameter thermostat sensitivity sweep.

No actual property is claimed to have these physical characteristics.
"""
import argparse
import json
import math
from dataclasses import replace
from datetime import datetime, timedelta, timezone, date
from pathlib import Path

from domestic_energy.heating_controls import House, strategy_grid
from domestic_energy.data import write_csv, write_json


def generated_weather(start=date(2025,1,1), days=62):
    start_utc=datetime(start.year,start.month,start.day,tzinfo=timezone.utc)
    output=[]
    for slot in range(days*48):
        elapsed=slot/48
        hour=(slot%48)/2
        # Assumed rather than observed London winter, mild/wet spells and cold nights.
        outside=4.0 + 3.0*math.sin(2*math.pi*(elapsed/13)) + 3.2*math.sin(2*math.pi*(hour-13)/24)
        output.append({'start_utc':(start_utc+timedelta(minutes=slot*30)).isoformat(),
                       'temperature_c':round(outside,3)})
    return output


def run(out: Path):
    root=Path(__file__).resolve().parent.parent
    tariffs=json.loads((root/'examples/hypothetical_heating_tariffs.json').read_text())
    weather=generated_weather()
    wfh={datetime.fromisoformat(row['start_utc']).date() for row in weather
         if datetime.fromisoformat(row['start_utc']).weekday() in (1,3)}
    away={date(2025,1,d) for d in range(13,17)}
    archetypes={
        'insulated_lightweight':House(heat_loss_w_per_k=95,thermal_capacity_kwh_per_k=5),
        'insulated_heavyweight':House(heat_loss_w_per_k=95,thermal_capacity_kwh_per_k=16),
        'average_house':House(heat_loss_w_per_k=200,thermal_capacity_kwh_per_k=10),
        'leaky_house':House(heat_loss_w_per_k=325,thermal_capacity_kwh_per_k=9,max_heat_kw=11),
    }
    results=[]
    for name,home in archetypes.items():
        grid=strategy_grid(weather,tariffs,house=home,away_dates=away,wfh_dates=wfh,
                           storage_backup_heat_kw=7)
        for item in grid['results']:
            results.append({**{k:item[k] for k in ('strategy','source','tariff','comfort_feasible',
                'heating_only_cost_gbp','electricity_heating_kwh','gas_heating_kwh',
                'occupied_unmet_degree_hours_c','occupied_hours_below_threshold',
                'lowest_indoor_c','night_charge_electricity_kwh','backup_heating_kwh_th')},
                'archetype':name})
    out.mkdir(parents=True,exist_ok=True)
    write_csv(out/'SYNTHETIC_heating_strategy_grid.csv', results, list(results[0]))
    write_csv(out/'SYNTHETIC_winter_weather.csv',weather,list(weather[0]))
    write_json(out/'study_metadata.json',{'simulation_period_days':62,
        'synthetic_weather':True, 'measured_household_data_used_for_heating':False,
        'tariffs_are_hypothetical':True, 'property_specs_are_assumed':True,
        'scenarios':len(results), 'archetypes':list(archetypes),
        'weather_source':'Deterministic periodic mathematical example, not meteorological observations',
        'cold_day_weather_not_optimised_to_realistic_climatology':True})
    viable=[r for r in results if r['comfort_feasible']]
    print('SYNTHETIC winter physical comparison:',len(results),'runs;',len(viable),'meet comfort screening')
    for archetype in archetypes:
        for tariff in (x['name'] for x in tariffs):
            subset=sorted((r for r in viable if r['archetype']==archetype and r['tariff']==tariff),
                          key=lambda x:x['heating_only_cost_gbp'])
            if subset:
                best=subset[0]
                print(archetype,'|',tariff,':',best['source'],best['strategy'],'£'+str(best['heating_only_cost_gbp']))
    return results


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--out',default='reports/heating_study')
    args=p.parse_args()
    run(Path(args.out))
