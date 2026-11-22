from datetime import datetime, timedelta, timezone
import unittest

from domestic_energy.demand_decisions import compare_forecasts, eligible_intervals, shift_metered_charge


class DemandDecisionTests(unittest.TestCase):
    def test_forecast_uses_only_previous_weeks(self):
        begin = datetime(2016, 1, 1, tzinfo=timezone.utc)
        meter = {begin + timedelta(weeks=i): x for i, x in enumerate([1, 10, 1, 1, 3, 1000])}
        start = begin + timedelta(weeks=4)
        report = compare_forecasts(meter, start=start, end=start + timedelta(hours=1))
        self.assertEqual(report["shared_test_intervals"], 1)
        self.assertEqual(report["four_week_median_mae_kwh"], 2)
        del meter[start - timedelta(weeks=1)]
        with self.assertRaisesRegex(ValueError, "No shared"):
            compare_forecasts(meter, start=start, end=start + timedelta(hours=1))

    def test_eligible_intervals_omit_flagged_and_reject_normalized_duplicates(self):
        row = {"start_utc": "2016-01-01T00:00Z", "duration_minutes": 30,
               "consumption_kwh": 1, "publisher_interpolated": 1}
        self.assertEqual(eligible_intervals([row]), {})
        with self.assertRaises(ValueError):
            eligible_intervals([row, {**row, "start_utc": "2016-01-01T01:00+01:00",
                                      "publisher_interpolated": 0}])

    def test_replay_preserves_charge_and_observed_peak(self):
        load, ev = [3, 2.5, 1], [2, 0, 0]
        result = shift_metered_charge(load, ev, [30, 10, 10])
        shifted = result["shifted_ev_schedule_kwh"]
        self.assertEqual(sum(shifted), 2)
        self.assertAlmostEqual(result["saving_gbp"], .40)
        self.assertTrue(all(g - original + scheduled <= max(load)
                            for g, original, scheduled in zip(load, ev, shifted)))
        same = shift_metered_charge(load, ev, [10, 10, 10])
        self.assertEqual(same["shifted_ev_schedule_kwh"], ev)
        with self.assertRaises(ValueError):
            shift_metered_charge([1], [2], [10])


class DailyForecastLeakageTests(unittest.TestCase):
    def test_outer_holdout_does_not_select_balance_temperature(self):
        from domestic_energy.forecast import fit_daily_model

        start = datetime(2016, 1, 1, tzinfo=timezone.utc)
        rows = [{"date": (start + timedelta(days=i)).date().isoformat(),
                 "temperature_c": i % 22, "consumption_kwh": 3 + 2 * max(0, 15 - i % 22)}
                for i in range(100)]
        first = fit_daily_model(rows)
        for row in rows[-20:]:
            row["consumption_kwh"] = 80
        second = fit_daily_model(rows)
        self.assertEqual(first["balance_temperature_c"], second["balance_temperature_c"])
        self.assertEqual(first["coefficients_kwh_day"], second["coefficients_kwh_day"])
        self.assertNotEqual(first["holdout"], second["holdout"])
