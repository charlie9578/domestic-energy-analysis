import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from math import isclose

from domestic_energy.core import (OFGEM_Q4_2026, HeatPumpScenario, Tariff,
    aggregate_heatpump_days, evaluate_heat_pump, gas_volume_to_kwh, price_meter_rows,
    summarize_meter, timestamp_utc)


class ConversionTests(unittest.TestCase):
    def test_m3_calorific(self):
        self.assertAlmostEqual(gas_volume_to_kwh(1), 1.02264 * 39.5 / 3.6)

    def test_imperial_units(self):
        self.assertAlmostEqual(gas_volume_to_kwh(1, unit='hundred_ft3'),
                               gas_volume_to_kwh(100, unit='ft3'))

    def test_reject_bad_units(self):
        with self.assertRaises(ValueError):
            gas_volume_to_kwh(1, unit='kwh')
        with self.assertRaises(ValueError):
            gas_volume_to_kwh(float('nan'))

    def test_explicit_utc(self):
        with self.assertRaises(ValueError):
            timestamp_utc('2026-01-01T12:00:00')
        self.assertEqual(timestamp_utc('2026-01-01T12:00:00+01:00').hour, 11)


class ScenarioTests(unittest.TestCase):
    def test_break_even(self):
        s = HeatPumpScenario()
        result = evaluate_heat_pump(s)
        self.assertAlmostEqual(result['variable_cost_break_even_spf'], 0.85 * 26.32 / 7.97)
        self.assertAlmostEqual(result['delivered_heat_kwh'], 7225)
        self.assertAlmostEqual(result['additional_hp_electricity_kwh'], 7225 / 3)
        self.assertAlmostEqual(result['annual_saving_gbp'],
                8500 * 0.0797 - (7225 / 3) * 0.2632, places=2)

    def test_no_gas_disconnection_with_unconverted_usage(self):
        with self.assertRaises(ValueError):
            HeatPumpScenario(disconnect_gas=True)

    def test_disconnection_saves_standing_charge(self):
        s = HeatPumpScenario(gas_heating_fraction=1)
        a = evaluate_heat_pump(s)
        b = evaluate_heat_pump(replace(s, disconnect_gas=True))
        self.assertAlmostEqual(b['annual_saving_gbp'] - a['annual_saving_gbp'],
                               365 * 29.68 / 100, places=2)

    def test_capex_no_fake_payback_when_negative_saving(self):
        result = evaluate_heat_pump(HeatPumpScenario(heat_pump_spf=1, retrofit_capex_gbp=15000))
        self.assertIsNone(result['simple_payback_years'])

    def test_no_negative_tariff(self):
        with self.assertRaises(ValueError):
            Tariff(-1, 8, 50, 30)


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.m = [
            {'start_utc': '2026-10-25T00:00:00Z', 'consumption_kwh': '1'},
            {'start_utc': '2026-10-25T00:30:00Z', 'consumption_kwh': '2'},
            {'start_utc': '2026-10-25T01:00:00Z', 'consumption_kwh': '3'},
        ]

    def test_total_coverage_peak(self):
        d = summarize_meter(self.m)
        self.assertEqual(d['total_kwh'], 6)
        self.assertEqual(d['coverage_fraction'], 1)
        self.assertEqual(d['peak_interval_kw'], 6)

    def test_utc_dst_fall_back_safely(self):
        d = price_meter_rows(self.m, [
            {'start_utc': r['start_utc'], 'unit_rate_p_per_kwh': '20'} for r in self.m],
            standing_p_per_day=50)
        self.assertEqual(d['standing_charge_days'], 1)
        self.assertEqual(d['total_cost_gbp'], 1.7)

    def test_missing_price_is_error(self):
        with self.assertRaises(ValueError):
            price_meter_rows(self.m, [])

    def test_missing_intervals_coverage(self):
        d = summarize_meter(self.m[:1] + self.m[2:])
        self.assertAlmostEqual(d['coverage_fraction'], 2 / 3, places=3)

    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):
            summarize_meter(self.m + [self.m[0]])

    def test_negative_dynamic_rate_is_allowed(self):
        d = price_meter_rows(self.m, [
            {'start_utc': r['start_utc'], 'unit_rate_p_per_kwh': '-5'} for r in self.m])
        self.assertEqual(d['variable_cost_gbp'], -0.3)


class HeatPumpTests(unittest.TestCase):
    def test_weighted_cop_and_quality_filter(self):
        def day(e, h, q, t, ts):
            return dict(combined_elec_kwh=str(e), combined_heat_kwh=str(h),
                quality_elec=str(q), quality_heat=str(q), combined_data_length='86400',
                timestamp=str(ts), combined_outsideT_mean=str(t))
        rows = [day(1, 4, 100, 2, 1760000000), day(9, 18, 100, 12, 1760086400),
                day(2, 100, 40, -2, 1760172800)]
        result = aggregate_heatpump_days(rows)
        self.assertEqual(result['accepted_days'], 2)
        self.assertEqual(result['observed_spf'], 2.2)  # NOT simple average of 4 and 2.
        self.assertEqual(result['rejections']['poor_coverage_or_quality'], 1)
        self.assertEqual(result['temperature_bins'][1]['days'], 1)

    def test_missing_values_do_not_become_zero(self):
        result = aggregate_heatpump_days([{'timestamp': '1'}])
        self.assertIsNone(result['observed_spf'])
        self.assertEqual(result['rejections']['missing_values'], 1)


if __name__ == '__main__':
    unittest.main()
