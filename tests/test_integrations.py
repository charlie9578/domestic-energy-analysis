"""Mocked public API contracts and end-to-end commands; never connects to network."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from domestic_energy.cli import main
from domestic_energy.data import fetch_open_meteo_daily, fetch_open_meteo_hourly, get_text


class WeatherParserTests(unittest.TestCase):
    @patch('domestic_energy.data.get_text')
    def test_local_daily_contract(self, fake):
        fake.return_value = json.dumps({'daily': {
            'time': ['2025-01-01', '2025-01-02'],
            'temperature_2m_mean': [4.1, 3.5],
            'temperature_2m_min': [1., 0.],
            'temperature_2m_max': [8., 6.],
            'precipitation_sum': [0.2, 2.0]}})
        rows = fetch_open_meteo_daily(51.5, -0.1, '2025-01-01', '2025-01-02')
        self.assertEqual(rows[0]['temperature_c'], 4.1)
        self.assertEqual(len(rows), 2)
        url = fake.call_args.args[0]
        self.assertIn('archive-api.open-meteo.com', url)
        self.assertIn('timezone=Europe%2FLondon', url)

    @patch('domestic_energy.data.get_text')
    def test_missing_weather_not_zero(self, fake):
        fake.return_value = json.dumps({'daily': {'time':['2025-01-01'],
          'temperature_2m_mean': [None], 'temperature_2m_min': [0],
          'temperature_2m_max': [6], 'precipitation_sum': [1]}})
        with self.assertRaises(ValueError):
            fetch_open_meteo_daily(51.5, -0.1, '2025-01-01', '2025-01-01')

    def hourly_payload(self):
        midnight = datetime(2025, 3, 30)
        return {'hourly_units': {
            'temperature_2m': '°C', 'shortwave_radiation': 'W/m²',
            'precipitation': 'mm', 'wind_speed_10m': 'm/s',
        }, 'hourly': {
            'time': [(midnight + timedelta(hours=i)).isoformat(timespec='minutes')
                     for i in range(48)],
            'temperature_2m': list(range(48)),
            'wind_speed_10m': [i / 10 for i in range(48)],
            'precipitation': [i / 100 for i in range(48)],
            'shortwave_radiation': [i * 10 for i in range(48)],
        }}

    @patch('domestic_energy.data.get_text')
    def test_hourly_utc_contract(self, fake):
        fake.return_value = json.dumps(self.hourly_payload())
        out = fetch_open_meteo_hourly(51.5, -0.1, '2025-03-30', '2025-03-30')
        self.assertEqual(len(out), 24)
        self.assertEqual(out[0], {'start_utc': '2025-03-30T00:00+00:00', 'temperature_c': 0,
                                 'wind_speed_m_s': 0, 'precipitation_mm': .01, 'shortwave_w_m2': 10})
        self.assertEqual(out[-1]['start_utc'], '2025-03-30T23:00+00:00')
        self.assertEqual(out[-1]['temperature_c'], 23)
        self.assertEqual(out[-1]['wind_speed_m_s'], 2.3)
        self.assertEqual(out[-1]['precipitation_mm'], .24)
        self.assertEqual(out[-1]['shortwave_w_m2'], 240)
        url = fake.call_args.args[0]
        self.assertIn('end_date=2025-03-31', url)
        self.assertIn('timezone=UTC', url)
        self.assertIn('models=era5', url)
        self.assertIn('wind_speed_unit=ms', url)

    @patch('domestic_energy.data.get_text')
    def test_hourly_rejects_missing_data_wrong_units_and_duplicate_time(self, fake):
        for section, name, value, message in (
            ('hourly', 'precipitation', [0] * 24 + [None] + [0] * 23, 'invalid hourly'),
            ('hourly_units', 'wind_speed_10m', 'km/h', 'variable or units'),
            ('hourly', 'time', ['2025-03-30T00:00'] * 48, 'timestamps'),
        ):
            with self.subTest(name=name):
                payload = self.hourly_payload()
                payload[section][name] = value
                fake.return_value = json.dumps(payload)
                with self.assertRaisesRegex(ValueError, message):
                    fetch_open_meteo_hourly(51.5, -0.1, '2025-03-30', '2025-03-30')

    def test_reject_unapproved_host(self):
        with self.assertRaises(ValueError):
            get_text('http://example.com/not-https')
        with self.assertRaises(ValueError):
            get_text('https://www.evil-example.com/')


class CLIEndToEndTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.repo = Path(__file__).resolve().parent.parent

    def tearDown(self):
        self._tmp.cleanup()

    def call(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(list(args))
        return code, out.getvalue(), err.getvalue()

    def test_compare_tariffs_with_daily_sample(self):
        # Existing sample needs no private data.
        result = self.root/'result.json'
        code, _, error = self.call('compare-tariffs', '--csv',
            str(self.repo/'examples/synthetic_smart_meter.csv'), '--tariffs',
            str(self.repo/'examples/hypothetical_tariffs.json'), '--out', str(result))
        self.assertEqual(code, 0, error)
        data = json.loads(result.read_text())
        self.assertEqual(len(data['ranked']), 2)

    def test_detect_existing_sample(self):
        code, stdout, err = self.call('detect', '--electricity',
            str(self.repo/'examples/synthetic_smart_meter.csv'))
        self.assertEqual(code, 0, err)
        x = json.loads(stdout)
        self.assertIn('cannot_reliably_identify', x)

    def test_ev_plan_existing_rates(self):
        code, out, err = self.call('ev-plan', '--rates',
            str(self.repo/'examples/synthetic_tou_rates.csv'),
            '--arrival', '2026-11-01T00:00:00+00:00',
            '--departure', '2026-11-02T00:00:00+00:00',
            '--battery-energy-kwh', '7')
        self.assertEqual(code, 0, err)
        self.assertGreaterEqual(json.loads(out)['price_aware_saving_gbp'], 0)

    def test_portfolio_grid_requires_explicit_gas_heat(self):
        code, _, err = self.call('portfolio-grid', '--csv',
            str(self.repo/'examples/synthetic_smart_meter.csv'),
            '--tariffs', str(self.repo/'examples/hypothetical_tariffs.json'),
            '--scenarios', str(self.repo/'examples/retrofit_portfolios.json'))
        self.assertEqual(code, 2)
        self.assertIn('Insulation model requires', err)


if __name__ == '__main__':
    unittest.main()
