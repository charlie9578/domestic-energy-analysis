"""Meter import contracts and RC/thermal-store conservation/comfort tests."""
import csv
import gzip
import json
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from dataclasses import replace

from domestic_energy.real_meter import import_lcl, measured_profile, expected_halfhourly_profile
from domestic_energy.heating_controls import (House, Settings, align_meter_baseload,
                                              in_window, setpoint, simulate_heating, strategy_grid)


START = datetime(2025, 1, 5, tzinfo=timezone.utc)


def weather(days=4, degrees=2, minutes=30):
    return [{'start_utc': (START + timedelta(minutes=i * minutes)).isoformat(),
             'temperature_c': degrees}
            for i in range(days*24*60//minutes)]


FLAT = {'name': 'HYPOTHETICAL flat', 'flat_p_per_kwh': 27, 'gas_p_per_kwh': 8}
TOU = {'name':'HYPOTHETICAL E7', 'day_p_per_kwh':35, 'night_p_per_kwh':9,
       'night_start_hour':0, 'night_end_hour':7, 'gas_p_per_kwh':8}


class RealMeterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.raw = 'LCLid,stdorToU,DateTime,KWH/hh (per half hour) \n' + '\n'.join([
            'MAC000002,Std,2012-11-01 00:30:00.0000000, 0.25 ',
            'MAC000002,Std,2012-11-01 01:00:00.0000000, 0.15 ',
            'MAC000003,Std,2012-11-01 01:30:00.0000000, 0.40 ',
            'MAC000002,Std,2012-11-01 01:30:00.0000000, Null ',
            'MAC000002,Std,2012-11-01 01:00:00.0000000, 0.15 ',
        ]) + '\n'
        self.path = self.folder / 'lcl.csv'
        self.path.write_text(self.raw)

    def tearDown(self):
        self.tmp.cleanup()

    def test_streaming_selection_qa(self):
        result = import_lcl([self.path], 'MAC000002', timestamp_mode='utc_end')
        self.assertEqual(result['qa']['household_rows'], 4)
        self.assertEqual(result['qa']['null_dropped'], 1)
        self.assertEqual(result['qa']['exact_duplicates_dropped'], 1)
        self.assertEqual(result['qa']['selected_intervals'], 2)
        self.assertAlmostEqual(result['qa']['observed_total_kwh'], .40)
        self.assertTrue(result['rows'][0]['start_utc'].startswith('2012-11-01T00:00:00'))

    def test_reject_contradictory_duplicate(self):
        self.path.write_text(self.raw + 'MAC000002,Std,2012-11-01 01:00:00.0000000,0.16\n')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            import_lcl([self.path], 'MAC000002', timestamp_mode='utc_end')

    def test_utc_start_convention_explicit(self):
        r = import_lcl([self.path], 'MAC000002', timestamp_mode='utc_start')
        self.assertTrue(r['rows'][0]['start_utc'].startswith('2012-11-01T00:30:00'))
        with self.assertRaises(ValueError):
            import_lcl([self.path], 'MAC000002', timestamp_mode='local_end')

    def test_gzip_and_zip(self):
        gp = self.folder/'a.csv.gz'
        with gzip.open(gp, 'wt') as f:
            f.write(self.raw)
        zp = self.folder/'b.zip'
        with zipfile.ZipFile(zp, 'w') as z:
            z.writestr('blocks/block_0.csv', self.raw)
        self.assertEqual(import_lcl([gp], 'MAC000002', timestamp_mode='utc_end')['qa']['selected_intervals'], 2)
        self.assertEqual(import_lcl([zp], 'MAC000002', timestamp_mode='utc_end')['qa']['selected_intervals'], 2)

    def test_bad_rows_and_unknown_household(self):
        with self.assertRaises(ValueError):
            import_lcl([self.path], 'MAC999999', timestamp_mode='utc_end')
        self.path.write_text('LCLid,DateTime,KWH/hh (per half hour)\nMAC000002,2012-11-01 00:30:00,-1\n')
        with self.assertRaises(ValueError):
            import_lcl([self.path], 'MAC000002', timestamp_mode='utc_end')

    def test_measured_profile_conserves_energy(self):
        rows = import_lcl([self.path], 'MAC000002', timestamp_mode='utc_end')['rows']
        self.assertEqual(measured_profile(rows)['total_kwh'], .4)

    def test_expected_meter_holdout_requires_complete_days(self):
        from datetime import datetime, timezone, timedelta
        start=datetime(2025, 2, 1, tzinfo=timezone.utc)
        rows=[]
        for n in range(30*48):
            dt=start+timedelta(minutes=30*n)
            rows.append({'start_utc':dt.isoformat(), 'consumption_kwh':0.1+0.01*(dt.weekday()>=5), 'duration_minutes':30})
        outcome=expected_halfhourly_profile(rows)
        self.assertEqual(outcome['n_full_days'],30)
        self.assertGreaterEqual(outcome['n_test_days'],5)
        self.assertLess(outcome['holdout_mae_kwh_per_halfhour'],.02)
        rows.pop(17)
        outcome=expected_halfhourly_profile(rows)
        self.assertEqual(outcome['n_partial_days_excluded'],1)

    def test_one_household_limit_fail_closed(self):
        with self.assertRaises(ValueError):
            import_lcl([self.path], 'MAC000002', timestamp_mode='utc_end', max_selected_rows=1)


class HeatingControlTests(unittest.TestCase):
    def test_windows_across_midnight(self):
        self.assertTrue(in_window(1,22,6))
        self.assertFalse(in_window(14,22,6))
        self.assertFalse(in_window(14,2,2))

    def test_setpoint_schedule_and_known_away(self):
        time = datetime(2025,1,6,2,0)
        self.assertEqual(setpoint('setback',time,Settings()),17)
        self.assertEqual(setpoint('constant',time,Settings()),20)
        self.assertEqual(setpoint('timed',time,Settings()),14)
        self.assertEqual(setpoint('constant',time,Settings(),away_dates={date(2025,1,6)}),12)
        self.assertEqual(setpoint('wfh_aware',datetime(2025,1,6,13),Settings(),wfh_dates={date(2025,1,6)}),20)

    def test_constant_vs_setback_delivered_heat(self):
        data = weather(10)
        a = simulate_heating(data, strategy='constant', heat_source='gas', tariff=FLAT)
        b = simulate_heating(data, strategy='setback', heat_source='gas', tariff=FLAT)
        self.assertLess(b['gas_heating_kwh'], a['gas_heating_kwh'])
        self.assertGreater(a['gas_heating_kwh'], 0)
        self.assertGreater(b['gas_heating_kwh'], 0)

    def test_outdoor_temperature_responds_physical(self):
        cold = simulate_heating(weather(5, -3), strategy='constant', heat_source='gas', tariff=FLAT)
        mild = simulate_heating(weather(5, 10), strategy='constant', heat_source='gas', tariff=FLAT)
        self.assertGreater(cold['gas_heating_kwh'], mild['gas_heating_kwh'])

    def test_insulation_reduces_heat_demand(self):
        a = simulate_heating(weather(5), strategy='constant', heat_source='gas', tariff=FLAT)
        b = simulate_heating(weather(5), strategy='constant', heat_source='gas', tariff=FLAT,
                             house=House(heat_loss_w_per_k=100))
        self.assertLess(b['gas_heating_kwh'], a['gas_heating_kwh'])

    def test_heatpump_uses_less_electricity_than_resistance(self):
        data=weather(5)
        a=simulate_heating(data,strategy='constant',heat_source='heatpump',tariff=FLAT)
        b=simulate_heating(data,strategy='constant',heat_source='resistive',tariff=FLAT)
        self.assertLess(a['electricity_heating_kwh'],b['electricity_heating_kwh'])

    def test_storage_energy_conserved_without_losses(self):
        h=House(store_capacity_kwh_th=50,store_charge_kw=8,store_discharge_kw=8,
                store_loss_fraction_per_hour=0,store_efficiency=1)
        a=simulate_heating(weather(5,10),strategy='storage_setback',heat_source='storage',
                           tariff=TOU,house=h)
        self.assertAlmostEqual(a['electricity_heating_kwh'],a['delivered_heat_kwh_th']+a['end_store_kwh_th'],places=2)
        self.assertGreater(a['night_charge_electricity_kwh'],0)
        self.assertEqual(a['backup_heating_kwh_th'],0)

    def test_underpowered_storage_is_not_cheap_winner(self):
        h=House(store_capacity_kwh_th=1,store_charge_kw=.3,store_discharge_kw=.5)
        result=simulate_heating(weather(4,-5),strategy='storage_constant',heat_source='storage',
                                tariff=TOU,house=h)
        self.assertFalse(result['comfort_feasible'])
        self.assertGreater(result['occupied_unmet_degree_hours_c'],0)
        grid=strategy_grid(weather(4,-5),[TOU],house=h)
        best=grid['cheapest_comfort_feasible']
        self.assertTrue(best is None or best['source']!='storage')

    def test_no_forced_equivalence_when_heater_max_limited(self):
        r=simulate_heating(weather(4,-10),strategy='constant',heat_source='gas',
                           tariff=FLAT,house=House(max_heat_kw=.4))
        self.assertGreater(r['occupied_unmet_degree_hours_c'],0)

    def test_tariff_night_rate_changes_storage_cost(self):
        data=weather(4,7)
        h=House(store_capacity_kwh_th=40,store_charge_kw=7,store_discharge_kw=8,
                store_loss_fraction_per_hour=0)
        low=simulate_heating(data,strategy='storage_setback',heat_source='storage',tariff=TOU,house=h)
        high=simulate_heating(data,strategy='storage_setback',heat_source='storage',tariff=FLAT,house=h)
        self.assertAlmostEqual(low['electricity_heating_kwh'],high['electricity_heating_kwh'],places=2)
        self.assertLess(low['heating_only_cost_gbp'],high['heating_only_cost_gbp'])

    def test_fail_on_weather_gap(self):
        data=weather(2)
        data.pop(5)
        with self.assertRaises(ValueError):
            simulate_heating(data,strategy='constant',heat_source='gas',tariff=FLAT)

    def test_baseload_join_fails_on_partial_and_double_count_gate(self):
        data=weather(2)
        meter=[{'start_utc':r['start_utc'],'consumption_kwh':.1,'duration_minutes':30} for r in data]
        self.assertAlmostEqual(sum(align_meter_baseload(data,meter)),len(data)*.1,places=10)
        with self.assertRaises(ValueError):
            align_meter_baseload(data,meter[:-1])

    def test_zero_baseload_does_not_count_fuel_twice(self):
        data=weather(3)
        no_base=simulate_heating(data,strategy='constant',heat_source='gas',tariff=FLAT)
        with_base=simulate_heating(data,strategy='constant',heat_source='gas',tariff=FLAT,
                                   baseload_kwh=[.1]*len(data))
        self.assertEqual(no_base['gas_heating_kwh'],with_base['gas_heating_kwh'])
        self.assertAlmostEqual(with_base['base_electric_kwh'],len(data)*.1)

    def test_hourly_input_and_DST(self):
        data=weather(4,3,minutes=60)
        x=simulate_heating(data,strategy='setback',heat_source='heatpump',tariff=TOU)
        self.assertEqual(x['n_intervals'],96)

    def test_incorrect_store_source_pair(self):
        with self.assertRaises(ValueError):
            simulate_heating(weather(),strategy='storage_constant',heat_source='gas',tariff=FLAT)

    def test_invalid_capacities(self):
        with self.assertRaises(ValueError):
            House(heat_loss_w_per_k=0)
        with self.assertRaises(ValueError):
            Settings(setback_c=21)


if __name__=='__main__':
    unittest.main()
