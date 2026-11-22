from datetime import datetime, timedelta, timezone
from math import exp
import unittest

from domestic_energy.hourly_heat_balance import fit, parameters, predict, validate


def generated_rows():
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    loss, capacity, gain = .2, 10, .4
    a = 1 - exp(-loss / capacity)
    b = a / loss
    indoor = 19
    result = []
    for hour in range(24 * 12):
        outdoor = 2 + hour % 13
        power = (hour * 5 % 11) / 2
        nxt = predict((a, b, b * gain), indoor, outdoor, power)
        result.append({"start": start + timedelta(hours=hour), "indoor": indoor,
                       "next_indoor": nxt, "outdoor": outdoor, "heat_kw": power})
        indoor = nxt
    return result


class HourlyHeatBalanceTests(unittest.TestCase):
    def test_exact_hourly_coefficients_recover_synthetic_parameters(self):
        values = parameters(fit(generated_rows()))
        self.assertAlmostEqual(values["heat_loss_w_per_k"], 200)
        self.assertAlmostEqual(values["effective_capacity_kwh_per_k"], 10)
        self.assertAlmostEqual(values["constant_gain_kw"], .4)

    def test_holdout_keeps_training_parameters_and_fails_closed_on_gaps(self):
        rows = generated_rows()
        split = rows[6 * 24]["start"]
        full = validate(rows, split=split, replicates=100)
        self.assertEqual(full["holdout"]["6"]["model_mae_c"], 0)
        self.assertEqual(full["holdout"]["6"]["windows"], 24)
        rows[6 * 24 + 1]["next_indoor"] = 30
        del rows[6 * 24 + 2]
        changed = validate(rows, split=split, replicates=100)
        self.assertEqual(full["training_parameters"], changed["training_parameters"])
        self.assertEqual(changed["holdout"]["6"]["windows"], 23)
        self.assertGreater(changed["holdout"]["1"]["model_mae_c"], 0)

    def test_does_not_force_nonphysical_coefficients(self):
        rows = generated_rows()
        for row in rows:
            row["next_indoor"] = row["indoor"] - (row["next_indoor"] - row["indoor"])
        with self.assertRaisesRegex(ValueError, "positive, stable"):
            fit(rows)
