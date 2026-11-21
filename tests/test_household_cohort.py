from datetime import datetime, timezone
from io import StringIO
import unittest

from domestic_energy.household_cohort import opsd_halfhours


class OpsdCohortTests(unittest.TestCase):
    def test_preserves_zero_interpolation_and_drops_incomplete_half_hours(self):
        source = StringIO(
            "utc_timestamp,DE_KN_residential1_grid_import,DE_KN_residential2_grid_import,interpolated\n"
            "2016-01-01T00:00Z,10,20,\n"
            "2016-01-01T00:15Z,10,21,unrelated | DE_KN_residential2_grid_import\n"
            "2016-01-01T00:30Z,10,23,\n"
            "2016-01-01T00:45Z,,24,\n"
            "2016-01-01T01:00Z,12,2,\n"
            "2016-01-01T01:30Z,13,3,\n"
        )
        start = datetime(2016, 1, 1, tzinfo=timezone.utc)
        end = start.replace(hour=1, minute=30)
        result = opsd_halfhours(source, ("residential1", "residential2"), start=start, end=end)
        self.assertEqual(result["residential1"], [{
            "start_utc": start.isoformat(), "duration_minutes": 30, "consumption_kwh": 0,
            "publisher_interpolated": 0,
        }])
        self.assertEqual(result["residential2"], [{
            "start_utc": start.isoformat(), "duration_minutes": 30, "consumption_kwh": 3,
            "publisher_interpolated": 1,
        }])
