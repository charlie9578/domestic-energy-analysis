from datetime import date, datetime, timedelta, timezone
import unittest

from domestic_energy.thermal_validation import monitored_days, validate_signature


class MonitoredThermalValidation(unittest.TestCase):
    def test_quality_missing_days_and_autumn_clock_change(self):
        timestamp = datetime(2023, 10, 28, 23, tzinfo=timezone.utc).timestamp()
        row = {
            "timestamp": timestamp, "combined_roomT_mean": "20",
            "combined_outsideT_mean": "7", "space_heat_kwh": "50",
            "space_elec_kwh": "15", "combined_data_length": str(25 * 3600),
            "quality_elec": "100", "quality_heat": "100", "quality_roomT": "99",
            "quality_outsideT": "100",
        }
        bad_quality = {**row, "timestamp": timestamp + 25 * 3600,
                       "combined_data_length": str(24 * 3600), "quality_roomT": "94"}
        malformed = {**bad_quality, "timestamp": timestamp + 49 * 3600,
                     "combined_roomT_mean": "nan"}
        start, end = date(2023, 10, 29), date(2023, 11, 2)
        rows, exclusions = monitored_days([row, bad_quality, malformed], start=start, end=end)
        self.assertEqual([(r["date"], r["hours"]) for r in rows], [(start, 25)])
        self.assertEqual(exclusions, {"coverage_or_quality": 1, "missing_or_nonfinite": 1,
                                      "no_source_day": 1})
        with self.assertRaisesRegex(ValueError, "one local-midnight record"):
            monitored_days([row, row], start=start, end=end)

    def test_holdout_cannot_change_training_fit_or_interval(self):
        start = date(2023, 1, 1)
        days = []
        for offset in range(140):
            outdoor = 5 + offset % 10
            indoor = 19 + offset % 3
            hours = 25 if offset % 17 == 0 else 24
            heat = (.2 * (indoor - outdoor) - .3) * hours
            days.append({"date": start + timedelta(days=offset), "hours": hours,
                         "indoor_c": indoor, "outdoor_c": outdoor, "space_heat_kwh": heat,
                         "space_electricity_kwh": heat / 3})
        split = start + timedelta(days=70)
        clean = validate_signature(days, split=split, resamples=100)
        changed = validate_signature(
            [{**row, "space_heat_kwh": row["space_heat_kwh"] + 20}
             if row["date"] >= split else row for row in reversed(days)],
            split=split, resamples=100)
        fitted = clean["signatures"]["indoor_outdoor"]
        modified = changed["signatures"]["indoor_outdoor"]
        self.assertEqual((clean["train_days"], clean["test_days"]), (70, 70))
        self.assertEqual(fitted["slope_w_per_k"], 200)
        self.assertEqual(fitted["training_slope_week_bootstrap_95"], [200, 200])
        self.assertEqual(fitted["training_slope_week_bootstrap_95"],
                         modified["training_slope_week_bootstrap_95"])
        self.assertEqual(fitted["holdout"]["mae_kwh_day"], 0)
        self.assertEqual(modified["holdout"]["mean_bias_kwh_day"], -20)
        self.assertEqual(clean["holdout_observed_space_heat_to_electricity_ratio"], 3)

    def test_rejects_insufficient_holdout(self):
        with self.assertRaisesRegex(ValueError, "Need at least"):
            validate_signature([], split=date(2024, 1, 1), resamples=100)
