"""Generate reproducible SYNTHETIC change-of-behaviour examples (never field data)."""
from __future__ import annotations
import argparse
import csv
import json
import math
from datetime import date, timedelta
from pathlib import Path
from domestic_energy.behaviour_change import (
    evaluate_intervention, evaluate_timeline, find_usage_shifts,
    simple_setpoint_scenario,
)


def make_household(kind: str, *, n: int=580, event: int=365):
    if kind not in ('thermostat','ev','solar'):
        raise ValueError('Unknown scenario')
    origin=date(2023,10,1)
    rows=[]
    for i in range(n):
        d=origin+timedelta(days=i)
        temp=8-8*math.cos(2*math.pi*(i-70)/365)+1.2*math.sin(i*.18)
        hdd=max(0,15.5-temp)
        if kind=='thermostat':
            # Logged thermostat 25 -> 22 C at event, with a simplified
            # heating-temperature response. This is not an RC simulation.
            setpoint=25 if i<event else 22
            kwh=3+1.35*max(0,16.5-(25-setpoint)-temp)
            row_extra={'setpoint_c':setpoint}
        else:
            charging=6.3 if kind=='ev' and i>=event and d.weekday() in (0,3,5) else 0.
            generation=max(0,7.5+4.5*math.sin(2*math.pi*(i-50)/365)) if kind=='solar' and i>=event else 0.
            self_used=min(generation*.45,4.5) if generation else 0.
            kwh=5+.27*hdd+charging-self_used
            row_extra={'ev_submeter_kwh':charging,'pv_generation_kwh':round(generation,5),
                       'pv_self_used_kwh':round(self_used,5)}
        kwh+=(.7 if d.weekday()>=5 else 0)+.22*math.sin(i*2.7)+.12*math.sin(i*.41)
        rows.append({'date':d.isoformat(),'consumption_kwh':round(max(0,kwh),5),
                     'temperature_c':round(temp,4),'coverage_fraction':1,
                     'work_from_home':'false','away':'false',**row_extra})
    return rows,(origin+timedelta(days=event)).isoformat()


def run_study(out: Path) -> dict:
    out.mkdir(parents=True,exist_ok=True)
    results={'dataset_classification':'SYNTHETIC model test – not observed households',
             'method':'pre-event weather-normalised descriptive association, no causal claim',
             'examples':{}}
    for kind in ('thermostat','ev','solar'):
        rows,event=make_household(kind)
        boundary='gas_input' if kind=='thermostat' else 'electricity_import'
        with (out/f'synthetic_{kind}_daily.csv').open('w',newline='',encoding='utf-8') as f:
            w=csv.DictWriter(f,fieldnames=rows[0].keys());w.writeheader();w.writerows(rows)
        results['examples'][kind]=evaluate_intervention(rows,event_date=event,
             event_type=kind,meter_boundary=boundary,documented=True,
             unit_price_p_per_kwh=8 if kind=='thermostat' else 26)
    rows,event=make_household('ev',n=800,event=365)
    solar_day=(date(2023,10,1)+timedelta(days=620)).isoformat()
    for row in rows:
        if row['date']>=solar_day:
            d=date.fromisoformat(row['date'])
            generation=max(0,7.5+4.5*math.sin(2*math.pi*(d.timetuple().tm_yday)/365))
            row['pv_generation_kwh']=round(generation,5)
            row['pv_self_used_kwh']=round(min(4.5,generation*.45),5)
            row['consumption_kwh']=round(max(0,row['consumption_kwh']-row['pv_self_used_kwh']),5)
    changes=[{'date':event,'event_type':'ev','documented':True},
             {'date':solar_day,'event_type':'solar','documented':True}]
    with (out/'synthetic_ev_then_solar_daily.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=['date','consumption_kwh','temperature_c','coverage_fraction','work_from_home','away',
                                     'ev_submeter_kwh','pv_generation_kwh','pv_self_used_kwh'])
        w.writeheader();w.writerows([{key:r.get(key,'') for key in w.fieldnames} for r in rows])
    (out/'synthetic_ev_then_solar_events.json').write_text(json.dumps(changes,indent=2)+'\n')
    results['sequential']=evaluate_timeline(rows,changes,meter_boundary='electricity_import')
    results['unverified_scan']=find_usage_shifts(rows,meter_boundary='electricity_import')
    results['physical_setpoint']=simple_setpoint_scenario(old_c=25,new_c=22,
         outside_c=5,heat_loss_w_per_k=200,hours_per_day=14,fuel='gas',
         efficiency_or_cop=.85,price_p_per_kwh=8)
    (out/'results.json').write_text(json.dumps(results,indent=2)+'\n')
    return results


def main():
    p=argparse.ArgumentParser(description='SYNTHETIC before/after intervention examples')
    p.add_argument('--out',type=Path,default=Path('reports/behaviour_changes'))
    args=p.parse_args();data=run_study(args.out)
    for kind,v in data['examples'].items():
        print(kind,'adjusted deviation kWh/day:',v['deviation_kwh_per_observed_day'],
              '| weather outside training support:',v['weather_out_of_training_support_days'])
    print('Saved',args.out)


if __name__=='__main__':
    main()
