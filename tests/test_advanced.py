"""Regression tests for forecast, signatures, flexibility, and portfolio economics."""
import unittest
from datetime import date, datetime, timedelta, timezone
from math import cos, pi

from domestic_energy.forecast import (fit_daily_model, predict_daily,
    compare_weather_periods, feature_vector, _solve)
from domestic_energy.signatures import (detect_ev_candidates, detect_low_activity_days,
    detect_gas_heating_runs, interval_profile, expected_intervals_from_daily,
    identify_system_clues)
from domestic_energy.economics import (simulate_portfolio, compare_tariffs,
    investment_appraisal, _battery_optimize)
from domestic_energy.flexibility import schedule_ev_charge
from domestic_energy.data import fetch_open_meteo_daily, fetch_open_meteo_hourly


def stamp(d, hour=0, minute=0):
    return (datetime.fromisoformat(d).replace(tzinfo=timezone.utc) + timedelta(hours=hour, minutes=minute)).isoformat()


def samples(n_days=140):
    today = date(2025, 1, 1)
    rows = []
    for j in range(n_days):
        day = today + timedelta(days=j)
        t = 10 + 10 * cos(j * 2 * pi / 50)  # enough warm/cold in train/holdout
        away = j % 24 in (19,20,21)
        wfh = (j % 7 in (0, 1)) and not away
        energy = 8 + 2 * max(0, 16-t) + (4 if wfh else 0) - (3 if away else 0)
        rows.append({'date': day.isoformat(), 'temperature_c': t, 'consumption_kwh': energy,
                     'away': int(away), 'work_from_home': int(wfh)})
    return rows


def series(days=20, ev=False, vacation=False):
    start = datetime(2025, 2, 1, tzinfo=timezone.utc)
    readings = []
    for i in range(days * 48):
        t = start + timedelta(minutes=30*i)
        kwh = .14 + (.06 if 17 <= t.hour < 22 else 0)
        if ev and 2 <= t.hour < 5 and t.day % 4 == 0:
            kwh += 3.5
        if vacation and 8 <= (t.date()-start.date()).days <= 11:
            kwh = .03
        readings.append({'start_utc': t.isoformat(), 'consumption_kwh': kwh,
                         'duration_minutes': '30'})
    return readings


class WeatherForecastTests(unittest.TestCase):
    def test_fit_forecast_holdout_and_predict(self):
        fitted = fit_daily_model(samples(), fuel='gas', boiler_efficiency=.86, floor_area_m2=120)
        self.assertEqual(fitted['n_train'] + fitted['n_holdout'], 140)
        self.assertLess(fitted['holdout']['mae_kwh_day'], 4)
        self.assertGreater(fitted['indicative_heat_loss_coefficient_w_per_k'], 0)
        pred = predict_daily(fitted, samples()[:3])
        self.assertEqual(len(pred), 3)
        self.assertTrue(all(p['indicative_lower_kwh'] <= p['expected_kwh'] <= p['indicative_upper_kwh'] for p in pred))

    def test_electricity_not_claimed_insulation_hlc(self):
        fitted = fit_daily_model(samples(), fuel='electricity')
        self.assertIsNone(fitted['indicative_heat_loss_coefficient_w_per_k'])
        self.assertIsNone(fitted['indicative_heat_loss_w_per_k_m2'])

    def test_require_training_days_unique(self):
        with self.assertRaises(ValueError):
            fit_daily_model(samples(20))
        with self.assertRaises(ValueError):
            fit_daily_model(samples() + [samples()[0]])

    def test_weather_shift(self):
        model = fit_daily_model(samples())
        base = [{'date': f'2025-10-{i:02d}', 'temperature_c': 6} for i in range(1, 8)]
        warm = [dict(x, temperature_c=19) for x in base]
        r = compare_weather_periods(model, base, warm)
        self.assertLess(r['difference_kwh'], 0)
        with self.assertRaises(ValueError):
            compare_weather_periods(model, base, warm[:3])

    def test_bad_input_validation(self):
        d = samples()
        d[4]['temperature_c'] = 'nan'
        with self.assertRaises(ValueError):
            fit_daily_model(d)
        with self.assertRaises(ValueError):
            feature_vector({'date': '2025-01-01', 'temperature_c': 8, 'away': 'perhaps'}, 15)
        with self.assertRaises(ValueError):
            _solve([[0]], [1])


class SignatureTests(unittest.TestCase):
    def test_ev_flat_runs(self):
        flagged = detect_ev_candidates(series(ev=True))
        self.assertGreaterEqual(len(flagged), 3)
        self.assertTrue(all(f['duration_hours'] >= 1.5 for f in flagged))
        self.assertTrue(all(f['confidence'] == 'unverified candidate' for f in flagged))

    def test_no_ev(self):
        self.assertEqual(detect_ev_candidates(series()), [])

    def test_low_activity_streak(self):
        result = detect_low_activity_days(series(vacation=True))
        self.assertEqual(len(result), 1)
        self.assertGreaterEqual(result[0]['days'], 4)
        self.assertIn('possibility', result[0]['hypothesis'])

    def test_dst_local_profile(self):
        rows = [{'start_utc': stamp('2026-10-25', 0), 'consumption_kwh': '1'},
                {'start_utc': stamp('2026-10-25', 1), 'consumption_kwh': '1'}]
        prof = interval_profile(rows)
        one = [x for x in prof['buckets'] if x['day_type'] == 'weekend' and x['hour'] == 1][0]
        self.assertEqual(one['samples'], 2)  # same local hour occurs twice on DST reversal

    def test_fallback_profiles_allocate_daily_energy(self):
        hist = series(2)
        future = series(1)
        res = expected_intervals_from_daily([{'date': '2025-02-01', 'expected_kwh': 20}], hist, future)
        self.assertAlmostEqual(sum(x['expected_kwh'] for x in res), 20, places=3)

    def test_heating_run_is_hypothesis(self):
        gas = [{'start_utc': stamp('2025-01-02', 8), 'consumption_kwh': '1.5'}]
        weather = [{'date': '2025-01-02', 'temperature_c': '3'}]
        self.assertEqual(len(detect_gas_heating_runs(gas, weather)), 1)
        clue = identify_system_clues(series(), gas_rows=gas, weather_daily=weather)
        self.assertIn('ambiguous', clue['technology_clues'][0]['status'])

    def test_solar_export_not_proven(self):
        exp = [{'start_utc': stamp('2025-02-01'), 'consumption_kwh': '2'}]
        clues = identify_system_clues(series(), export_rows=exp)['technology_clues']
        self.assertIn('solar NOT proven', clues[-1]['status'])


class TariffAndPortfolioTests(unittest.TestCase):
    def setUp(self):
        self.rows = []
        for i in range(48):
            t = datetime(2025, 2, 1, tzinfo=timezone.utc) + timedelta(minutes=30*i)
            self.rows.append({'start_utc': t.isoformat(), 'consumption_kwh': '1.0',
                'gas_kwh': '.4', 'gas_heating_kwh': '.4', 'electric_heating_kwh': '.1',
                'pv_generation_kwh': '2' if 10 <= t.hour < 14 else '0',
                'temperature_c': str(3 + t.hour / 3)})
        self.flat = {'name': 'flat', 'flat_import_p': 25, 'export_p': 5,
            'electricity_standing_p_per_day': 50, 'gas_p': 8,
            'gas_standing_p_per_day': 30}

    def test_tariff_math_and_pv_export(self):
        no_pv = simulate_portfolio(self.rows, self.flat)
        pv = simulate_portfolio(self.rows, self.flat, pv_scale=1)
        self.assertLess(pv['with_battery']['total_bill_gbp'], no_pv['with_battery']['total_bill_gbp'])
        self.assertGreater(pv['with_battery']['grid_export_kwh'], 0)
        self.assertEqual(no_pv['calendar_days'], 1)

    def test_battery_works_cannot_make_free_energy(self):
        battery = simulate_portfolio(self.rows, self.flat, pv_scale=1, battery_kwh=3,
                                     battery_power_kw=3, battery_efficiency=.9)
        pv = simulate_portfolio(self.rows, self.flat, pv_scale=1)
        self.assertLessEqual(battery['with_battery']['total_bill_gbp'], pv['with_battery']['total_bill_gbp'])
        self.assertEqual(battery['battery_dispatch']['start_and_end_soc_kwh'], 0)
        self.assertGreaterEqual(battery['battery_dispatch']['grid_energy_to_battery_kwh'], 0)

    def test_battery_zero_spread_loses_energy(self):
        nets = [1., 1., 1., 1.]
        adjusted, stats = _battery_optimize(nets, [20]*4, [0]*4, [30]*4,
            capacity_kwh=2, power_kw=3, round_trip_efficiency=.8)
        self.assertEqual(adjusted, nets)
        self.assertEqual(stats['cycle_count_equivalent'], 0)

    def test_gas_disconnection_requires_no_gas(self):
        with self.assertRaises(ValueError):
            extra_gas = [dict(r, gas_kwh='.5') for r in self.rows]
            simulate_portfolio(extra_gas, self.flat, heat_pump_spf=3, disconnect_gas=True)
        after = simulate_portfolio(self.rows, self.flat, heat_pump_spf=3, disconnect_gas=True,
                                   insulation_heat_reduction=0.2)
        self.assertEqual(after['gas_kwh'], 0)
        self.assertEqual(after['resulting_heat_pump_spf'], 3.)
        self.assertLess(after['with_battery']['gas_total_gbp'], 1e-9)

    def test_cop_curve_differs_by_weather(self):
        after = simulate_portfolio(self.rows, self.flat,
            heat_pump_cop_curve=[[-3, 2.0], [7, 3.5], [15, 4.2]])
        self.assertGreater(after['resulting_heat_pump_spf'], 2)
        self.assertLess(after['resulting_heat_pump_spf'], 4)
        with self.assertRaises(ValueError):
            simulate_portfolio(self.rows, self.flat, heat_pump_cop_curve=[[0, 2.5], [10, 3.4]], heat_pump_spf=3)

    def test_insulation_requires_submeter(self):
        stripped = [dict(r, electric_heating_kwh='0', gas_heating_kwh='0') for r in self.rows]
        with self.assertRaises(ValueError):
            simulate_portfolio(stripped, self.flat, insulation_heat_reduction=.2)

    def test_weather_norm_tariff_local_hour_and_coverage(self):
        tou = {'name': 'tou', 'schedule': [{'start_hour': 0, 'end_hour': 7, 'import_p': 10},
              {'start_hour': 7, 'end_hour': 24, 'import_p': 50}]}
        result = compare_tariffs(self.rows, [self.flat, tou])
        self.assertEqual(result['coverage_fraction'], 1.)
        self.assertEqual(len(result['ranked']), 2)
        with self.assertRaises(ValueError):
            simulate_portfolio(self.rows, {'name': 'bad', 'schedule': [{'start_hour': 0, 'end_hour': 6, 'import_p': 1}]})

    def test_missing_dynamic_price_fails(self):
        with self.assertRaises(ValueError):
            simulate_portfolio(self.rows, {'name': 'dynamic', 'interval_rates': []})

    def test_annual_equivalent_investment_screen(self):
        s = investment_appraisal(200, capex_gbp=3000, lifetime_years=20, discount_rate=.035)
        self.assertIsNotNone(s['undiscounted_payback_years'])
        self.assertGreater(s['npv_gbp'], -3000)
        self.assertIsNone(investment_appraisal(-10, capex_gbp=1000)['undiscounted_payback_years'])


class EVTests(unittest.TestCase):
    def test_ev_finds_cheap_slots(self):
        rows = [{'start_utc': stamp('2025-02-01', i//2, (i%2)*30),
                 'unit_rate_p_per_kwh': 5 if i >= 6 else 30} for i in range(12)]
        out = schedule_ev_charge(rows, arrival_utc=stamp('2025-02-01'),
              departure_utc=stamp('2025-02-01', 6), battery_energy_needed_kwh=7,
              charger_kw=3.5, charging_efficiency=1.)
        self.assertGreater(out['price_aware_saving_gbp'], 0)
        self.assertAlmostEqual(sum(x['grid_kwh'] for x in out['schedule']), 7.)

    def test_ev_refuses_infeasible_and_missing(self):
        rows = [{'start_utc': stamp('2025-02-01'), 'unit_rate_p_per_kwh': 10}]
        with self.assertRaises(ValueError):
            schedule_ev_charge(rows, arrival_utc=stamp('2025-02-01'),
                departure_utc=stamp('2025-02-01', 1), battery_energy_needed_kwh=10)


class WeatherAPITests(unittest.TestCase):
    def test_validation_without_network(self):
        with self.assertRaises(ValueError):
            fetch_open_meteo_daily(200, -1, '2024-01-01', '2024-01-02')
        with self.assertRaises(ValueError):
            fetch_open_meteo_hourly(52, -1, '2024-03-03', '2024-01-02')


if __name__ == '__main__':
    unittest.main()

class PipelineTests(unittest.TestCase):
    def test_dst_autumn_local_day_25h(self):
        from domestic_energy.pipeline import join_daily_meter_weather
        from datetime import datetime, timezone, timedelta
        begin = datetime(2026,10,24,23,tzinfo=timezone.utc)
        rows = [{'start_utc': (begin+timedelta(minutes=30*i)).isoformat(),
                 'consumption_kwh': '1.0'} for i in range(50)]
        joined = join_daily_meter_weather(rows,
            [{'date':'2026-10-25', 'temperature_c':'8.0'}])
        self.assertEqual(joined['accepted_days'], 1)
        self.assertEqual(joined['daily_rows'][0]['consumption_kwh'], 50)

    def test_dst_spring_local_day_23h(self):
        from domestic_energy.pipeline import join_daily_meter_weather
        from datetime import datetime, timezone, timedelta
        begin = datetime(2026,3,29,0,tzinfo=timezone.utc)
        rows = [{'start_utc': (begin+timedelta(minutes=30*i)).isoformat(),
                 'consumption_kwh': '1.0'} for i in range(46)]
        joined = join_daily_meter_weather(rows,
            [{'date':'2026-03-29', 'temperature_c':'8.0'}])
        self.assertEqual(joined['accepted_days'], 1)
        self.assertEqual(joined['daily_rows'][0]['consumption_kwh'], 46)

    def test_gap_is_not_zero(self):
        from domestic_energy.pipeline import join_daily_meter_weather
        from datetime import datetime,timezone,timedelta
        begin = datetime(2025,1,1,tzinfo=timezone.utc)
        rows=[]
        for shift in (0,2):
            rows += [{'start_utc':(begin+timedelta(days=shift,minutes=i*30)).isoformat(),
                      'consumption_kwh':'1'} for i in range(48)]
        weather=[{'date':f'2025-01-0{i}', 'temperature_c':10} for i in range(1,4)]
        joined = join_daily_meter_weather(rows,weather)
        self.assertEqual(joined['accepted_days'],2)
        self.assertEqual(joined['excluded_dates'][0]['date'],'2025-01-02')
        self.assertEqual(joined['excluded_dates'][0]['reason'],'no_meter_intervals')

class ThermalStorageTests(unittest.TestCase):
    def test_shift_into_offpeak_with_heat_conservation(self):
        from domestic_energy.thermal import optimise_heat_storage
        loads=[1]*12
        heating=[0, 0, 0, 0, 0, 0, 1,1,1,1,1,1]
        rates=[5]*6+[50]*6
        baseline=sum((b+h)*p for b,h,p in zip(loads,heating,rates))/100
        shifted, facts=optimise_heat_storage(loads,heating,rates,[0]*12,[30]*12,
            capacity_kwh_th=6,charge_power_kw=3, charge_efficiency=1,
            heat_loss_fraction_per_hour=0,step_kwh_th=.5)
        paid=sum(s*p for s,p in zip(shifted,rates))/100
        self.assertLess(paid, baseline)
        self.assertEqual(facts['start_and_end_thermal_soc_kwh'], 0)
        self.assertAlmostEqual(facts['electric_input_kwh'], sum(heating))

    def test_flat_rate_storage_loss_not_free(self):
        from domestic_energy.thermal import optimise_heat_storage
        base=[.1]*8
        demand=[.5]*8
        shifted, facts=optimise_heat_storage(base,demand,[25]*8,[0]*8,[30]*8,
            capacity_kwh_th=3, charge_power_kw=4, step_kwh_th=.5,
            charge_efficiency=.9,heat_loss_fraction_per_hour=.02)
        self.assertGreaterEqual(sum(shifted),sum(base)+sum(demand))
        self.assertGreater(facts['electric_input_kwh'], sum(demand))

    def test_storage_portfolio_requires_direct_heat(self):
        rows = [{'start_utc':stamp('2025-01-01',i//2,i%2*30),
                 'consumption_kwh':'.5', 'gas_kwh':'1', 'gas_heating_kwh':'.8'} for i in range(48)]
        tariff={'name':'example','flat_import_p':30}
        with self.assertRaises(ValueError):
            simulate_portfolio(rows,tariff,storage_heater_kwh_th=5)
        result=simulate_portfolio(rows,tariff,direct_electric_from_gas=True,
            storage_heater_kwh_th=5,remaining_gas_to_electric_kwh_per_kwh=.85,
            disconnect_gas=True)
        self.assertEqual(result['gas_kwh'],0)
        self.assertIsNotNone(result['thermal_storage_dispatch'])
