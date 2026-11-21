import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from domestic_energy.cli import main
from domestic_energy.data import fetch_octopus_unit_rates, get_text


class CLITests(unittest.TestCase):
    def test_benchmark_json(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(main(['benchmark']), 0)
        self.assertEqual(json.loads(out.getvalue())['domestic_gas_kwh']['median'], 10000)

    def test_invalid_scenario_reports_error(self):
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['scenario', '--spf', '0']), 2)

    def test_reject_unsafe_url_without_network(self):
        with self.assertRaises(ValueError):
            get_text('http://heatpumpmonitor.org/system/stats/last365')
        with self.assertRaises(ValueError):
            get_text('https://example.com/whatever')

    def test_rate_window_requires_utc_slots(self):
        with self.assertRaises(ValueError):
            fetch_octopus_unit_rates('AGILE-XXX', 'E-1R-AGILE-XXX-A',
                '2026-01-01T00:10:00Z', '2026-01-02T00:00:00Z')

    def test_demo(self):
        with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(['demo', '--out-dir', td]), 0)
            results = json.loads((Path(td) / 'results.json').read_text())
            self.assertGreater(results['meter_flat_26_32p']['total_kwh'], 0)
            self.assertEqual(len((Path(td) / 'sensitivity.csv').read_text().splitlines()), 37)


if __name__ == '__main__':
    unittest.main()
