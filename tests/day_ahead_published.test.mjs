import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const root = new URL("../docs/assets/day-ahead/", import.meta.url);
const summary = JSON.parse(await readFile(new URL("summary.json", root), "utf8"));

test("public ERA5 hindcast is source-attributed and evaluated on paired intervals", () => {
  assert.match(summary.provenance.opsd_sha256, /^[0-9a-f]{64}$/);
  assert.match(summary.provenance.era5_sha256, /^[0-9a-f]{64}$/);
  assert.match(summary.method.weather, /NOT issued day-ahead forecast/);
  assert.equal(Object.keys(summary.homes).length, 5);
  for (const entry of Object.values(summary.homes)) {
    if (!entry.methods) continue;
    assert.equal(entry.test_halfhours, entry.test_days * 48);
    for (const method of ["era5", "calendar", "yesterday", ...(entry.methods.auto_ml ? ["auto_ml"] : [])]) {
      assert.equal(entry.methods[method].interval.count, entry.test_halfhours);
      assert.equal(entry.methods[method].daily.count, entry.test_days);
    }
  }
});

test("public per-home day profiles reproduce published MAE within rounding", async () => {
  for (const [home, entry] of Object.entries(summary.homes)) {
    if (!entry.methods) continue;
    const detail = JSON.parse(await readFile(new URL(entry.file, root), "utf8"));
    assert.equal(detail.home, home);
    assert.equal(detail.days.length, entry.test_days);
    const flattened = detail.days.flatMap((day) => day.points);
    assert.equal(flattened.length, entry.test_halfhours);
    for (const method of ["era5", "calendar", "yesterday", ...(entry.methods.auto_ml ? ["auto_ml"] : [])]) {
      const mae = flattened.reduce((s, row) => s + Math.abs(row[method] - row.actual), 0) / flattened.length;
      assert.ok(Math.abs(mae - entry.methods[method].interval.mae_kwh) < 0.00002,
        home + " " + method + " summary MAE inconsistent with published trace");
      assert.ok(flattened.every((r) => Number.isFinite(r[method]) && r[method] >= 0));
    }
    const dates = detail.days.map((day) => day.date);
    assert.equal(dates.length, new Set(dates).size);
    assert.ok(dates.every((day) => day >= detail.test_start && day <= detail.test_end));
  }
});

test("AutoML was selected using historical folds and saved per household", () => {
  for (const entry of Object.values(summary.homes)) {
    if (!entry.methods?.auto_ml) continue;
    assert.ok(entry.auto_ml_selection);
    assert.ok(entry.auto_ml_selection.candidate_count === 11);
    assert.ok(entry.auto_ml_selection.fold_details.every((fold) =>
      fold.validation_end <= entry.train_end));
    assert.ok(entry.auto_ml_selection.chosen_id);
  }
});
