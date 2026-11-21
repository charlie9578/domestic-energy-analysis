"""Smoke-test the actual committed measured excerpts (no network calls)."""
import unittest
from scripts.profile_public_examples import EXAMPLES, profile


class PublishedMeasuredExamples(unittest.TestCase):
    def test_lcl_measured_household(self):
        p, zone, caveat = EXAMPLES["low_carbon_london"]
        r = profile(p, zone)
        self.assertEqual(r["intervals"], 2020)
        self.assertAlmostEqual(r["observed_grid_import_kwh"], 546.956, places=3)
        self.assertEqual(r["observed_hours"], 1010)
        self.assertTrue(0.97 < r["coverage_fraction"] < .99)
        self.assertAlmostEqual(r["overnight_00_to_07_local_fraction_of_observed_import"], .183518, places=4)

    def test_uci_partial_overnight(self):
        p, zone, caveat = EXAMPLES["uci_france"]
        r = profile(p, zone)
        self.assertEqual(r["intervals"], 33)
        self.assertAlmostEqual(r["observed_grid_import_kwh"], 39.751, places=3)
        self.assertEqual(r["observed_hours"], 16.5)
        self.assertAlmostEqual(r["other_separately_metered_channel_kwh"]["submeter_2_kwh"], 2.741, places=3)

    def test_opsd_provisional_counter_excerpt(self):
        p, zone, caveat = EXAMPLES["opsd_third_party_mirror"]
        r = profile(p, zone)
        self.assertEqual(r["intervals"], 479)
        self.assertAlmostEqual(r["observed_grid_import_kwh"], 18.5, places=3)
        self.assertAlmostEqual(r["other_separately_metered_channel_kwh"]["ev_kwh"], 17.1, places=3)
        self.assertAlmostEqual(r["other_separately_metered_channel_kwh"]["heat_pump_kwh"], 7.18, places=3)
        self.assertIn("PROVISIONAL", caveat)


if __name__ == "__main__":
    unittest.main()
