"""Regression tests: longitudinal energy changes and honest uncertainty labels."""
import copy
import math
import unittest
from datetime import date,datetime,time,timedelta,timezone
from zoneinfo import ZoneInfo
from domestic_energy.behaviour_change import (
    aggregate_meter_weather, evaluate_intervention, evaluate_timeline,
    find_usage_shifts, simple_setpoint_scenario,
)


def make_days(length=280, change=145, step=-4., boundary='gas'):
    origin=date(2024,1,1)
    rows=[]
    for i in range(length):
        d=origin+timedelta(days=i)
        outdoor=9+8*math.sin(i*2*math.pi/365)
        kwh=(8+1.4*max(0,15.5-outdoor) if boundary=='gas'
             else 5+.25*max(0,15.5-outdoor))
        kwh+=(.75 if d.weekday()>=5 else 0)+.3*math.sin(i*1.7)
        if i>=change:kwh+=step
        rows.append({'date':d.isoformat(),'consumption_kwh':max(0,kwh),
                     'temperature_c':outdoor,'coverage_fraction':1})
    return rows,(origin+timedelta(days=change)).isoformat()


def day_intervals(day):
    zone=ZoneInfo('Europe/London')
    a=datetime.combine(day,time.min,tzinfo=zone).astimezone(timezone.utc)
    b=datetime.combine(day+timedelta(days=1),time.min,tzinfo=zone).astimezone(timezone.utc)
    meters=[];weather=[];current=a
    while current<b:
        meters.append({'start_utc':current.isoformat(),'duration_minutes':30,'consumption_kwh':.2})
        if current.minute==0:
            weather.append({'start_utc':current.isoformat(),'temperature_c':5})
        current+=timedelta(minutes=30)
    return meters,weather


class TestBehaviourChange(unittest.TestCase):
    def test_documented_thermostat_reduction_is_an_association(self):
        rows,event=make_days()
        r=evaluate_intervention(rows,event_date=event,event_type='thermostat',
                                meter_boundary='gas_input',documented=True)
        self.assertLess(r['deviation_kwh_per_observed_day'],-2)
        self.assertGreater(r['deviation_kwh_per_observed_day'],-6)
        self.assertIn('Association only',r['interpretation'])
        self.assertTrue(any('setpoint' in x for x in r['warnings']))
        self.assertEqual(sum(b['n_observed_days'] for b in r['change_over_time_30_day_bins']),r['n_post_days'])
        self.assertTrue(r['validation']['n_validation_days']>=14)

    def test_no_new_change_close_to_zero(self):
        rows,event=make_days(step=0)
        r=evaluate_intervention(rows,event_date=event,event_type='other',meter_boundary='gas_input')
        self.assertLess(abs(r['deviation_kwh_per_observed_day']),2)

    def test_post_data_does_not_leak_into_pre_model(self):
        rows,event=make_days()
        a=evaluate_intervention(rows,event_date=event,event_type='other',meter_boundary='gas_input')
        later=copy.deepcopy(rows)
        for r in later:
            if r['date']>=event:r['consumption_kwh']+=3
        b=evaluate_intervention(later,event_date=event,event_type='other',meter_boundary='gas_input')
        self.assertEqual(a['weather_adjusted_expected_post_kwh'],b['weather_adjusted_expected_post_kwh'])
        self.assertAlmostEqual(b['deviation_kwh_per_observed_day']-a['deviation_kwh_per_observed_day'],3,places=3)

    def test_ev_and_solar_not_automatically_identified(self):
        rows,event=make_days(boundary='electricity',step=4)
        r=evaluate_intervention(rows,event_date=event,event_type='ev',meter_boundary='electricity_import')
        self.assertTrue(any('without separately metered charging' in w for w in r['warnings']))
        rows,event=make_days(boundary='electricity',step=-2)
        r=evaluate_intervention(rows,event_date=event,event_type='solar',meter_boundary='electricity_import')
        self.assertTrue(any('IMPORT' in w for w in r['warnings']))

    def test_duplicate_or_negative_readings_rejected(self):
        rows,event=make_days()
        with self.assertRaises(ValueError):
            evaluate_intervention(rows+[dict(rows[0])],event_date=event,event_type='other',meter_boundary='gas_input')
        rows[0]['consumption_kwh']=-1
        with self.assertRaises(ValueError):
            evaluate_intervention(rows,event_date=event,event_type='other',meter_boundary='gas_input')

    def test_missing_days_are_not_zero(self):
        rows,event=make_days()
        rows[100]['coverage_fraction']=.2
        rows.pop(101)
        r=evaluate_intervention(rows,event_date=event,event_type='other',meter_boundary='gas_input')
        self.assertEqual(r['n_low_coverage_days_excluded'],1)
        self.assertTrue(any('Missing' in w for w in r['warnings']))

    def test_sequential_event_regimes(self):
        rows,event=make_days(length=350,change=110)
        later_date=(date(2024,1,1)+timedelta(days=250)).isoformat()
        for r in rows:
            if r['date']>=later_date:r['consumption_kwh']+=6
        events=[{'date':event,'event_type':'solar','documented':True},
                {'date':later_date,'event_type':'ev','documented':True}]
        report=evaluate_timeline(rows,events,meter_boundary='electricity_import')
        self.assertEqual([x['status'] for x in report['results']],['estimated_association_only']*2)
        self.assertLess(report['results'][0]['deviation_kwh_per_observed_day'],0)
        self.assertGreater(report['results'][1]['deviation_kwh_per_observed_day'],0)

    def test_simultaneous_event_not_attributed(self):
        rows,event=make_days()
        results=evaluate_timeline(rows,[{'date':event,'event_type':'solar'},
               {'date':event,'event_type':'ev'}],meter_boundary='electricity_import')
        self.assertEqual(results['results'][0]['status'],'not_attributable')

    def test_scan_only_calls_changes_candidates(self):
        rows,_=make_days(length=270,change=140,step=8)
        result=find_usage_shifts(rows,meter_boundary='gas_input')
        self.assertTrue(result['candidates'])
        self.assertTrue(all('cause unknown' in x['label'] for x in result['candidates']))

    def test_setpoint_heat_difference(self):
        r=simple_setpoint_scenario(old_c=25,new_c=22,outside_c=5,
            heat_loss_w_per_k=200,hours_per_day=14,fuel='gas',
            efficiency_or_cop=.85,price_p_per_kwh=8)
        self.assertAlmostEqual(r['input_reduction_kwh_per_day'],8.4/.85,places=3)
        self.assertAlmostEqual(r['variable_cost_reduction_gbp_per_day'],8.4/.85*.08,places=3)

    def test_setpoint_below_outside_saves_nothing(self):
        r=simple_setpoint_scenario(old_c=25,new_c=22,outside_c=28,
            heat_loss_w_per_k=200,hours_per_day=14,fuel='heatpump',
            efficiency_or_cop=3,price_p_per_kwh=25)
        self.assertEqual(r['input_reduction_kwh_per_day'],0)

    def test_dst_23_and_25_hour_local_days(self):
        for d,expected in ((date(2024,3,31),46),(date(2024,10,27),50)):
            m,w=day_intervals(d)
            self.assertEqual(len(m),expected)
            out=aggregate_meter_weather(m,w)
            self.assertEqual(len(out['days']),1)
            self.assertAlmostEqual(out['days'][0]['consumption_kwh'],expected*.2)

    def test_missing_interval_drops_unreliable_day(self):
        m,w=day_intervals(date(2024,3,15))
        r=aggregate_meter_weather(m[1:],w,min_coverage=1)
        self.assertFalse(r['days'])
        self.assertTrue(r['excluded_days'])

    def test_overlapping_interval_rejected(self):
        m,w=day_intervals(date(2024,3,15))
        with self.assertRaisesRegex(ValueError,'overlapping'):
            aggregate_meter_weather(m+[dict(m[0])],w)

    def test_naive_timestamp_rejected(self):
        m,w=day_intervals(date(2024,3,15))
        m[0]['start_utc']='2024-03-15T00:00:00'
        with self.assertRaisesRegex(ValueError,'explicit offset'):
            aggregate_meter_weather(m,w)


if __name__=='__main__':unittest.main()
