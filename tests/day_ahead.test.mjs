import test from "node:test";
import assert from "node:assert/strict";
import { analyseDayAheadCsv } from "../docs/day-ahead.js";

function fixture({ days = 70, missing = -1, flagged = -1, futureWeather = false } = {}) {
  const meter = ["start_utc,consumption_kwh,duration_minutes,publisher_interpolated"];
  const weather = ["start_utc,temperature_c"];
  for (let d = 0; d < days + Number(futureWeather); d++) {
    const start = Date.UTC(2025, 0, 1 + d);
    for (let h = 0; h < 24; h++) {
      const t = 10 + 8 * Math.cos(d / 9) + Math.sin(h);
      weather.push(new Date(start + h * 3600000).toISOString() + "," + t);
      if (d === days) continue;
      for (let half = 0; half < 2; half++) {
        if (d === missing && h === 4 && half === 0) continue;
        const slot = h * 2 + half;
        const actual = .3 + .01 * slot + .04 * Math.max(0, 18 - t);
        meter.push(new Date(start + slot * 1800000).toISOString() +
          "," + actual + ",30," + (d === flagged && slot === 5 ? "1" : "0"));
      }
    }
  }
  return { meter: meter.join("\n"), weather: weather.join("\n") };
}

test("ERA5 regression and persistence use identical held-out half-hours", () => {
  const { meter, weather } = fixture();
  const r = analyseDayAheadCsv(meter, weather, "UTC");
  assert.ok(r.test_days >= 10);
  assert.equal(r.test_halfhours, 48 * r.test_days);
  assert.ok(r.methods.era5.interval.mae_kwh < r.methods.calendar.interval.mae_kwh);
  for (const d of r.days) {
    assert.equal(d.points.length, 48);
    assert.ok(d.points.every((p) => p.actual >= 0 && p.era5 >= 0));
  }
});

test("zero order hold copies the preceding civil day's meter profile", () => {
  const { meter, weather } = fixture();
  const r = analyseDayAheadCsv(meter, weather, "UTC");
  const last = r.days.at(-1);
  const first = last.points[0];
  const previous = Date.parse(last.date + "T00:00:00Z") - 86400000;
  const source = meter.split("\n").find((line) => line.startsWith(new Date(previous).toISOString()));
  assert.ok(source);
  assert.equal(first.yesterday, Number(source.split(",")[1]));
});

test("holdout readings cannot influence fitted coefficients or predictions", () => {
  const { meter, weather } = fixture();
  const base = analyseDayAheadCsv(meter, weather, "UTC");
  const changed = meter.split("\n").map((line) => {
    if (line.startsWith(base.test_end)) {
      const columns = line.split(","); columns[1] = "25"; return columns.join(",");
    }
    return line;
  }).join("\n");
  const result = analyseDayAheadCsv(changed, weather, "UTC");
  assert.equal(result.temperature_slope_kwh_per_halfhour_per_c,
    base.temperature_slope_kwh_per_halfhour_per_c);
  assert.deepEqual(result.days.at(-1).points.map((p) => p.era5),
    base.days.at(-1).points.map((p) => p.era5));
});

test("missing and flagged days excluded instead of being zero-filled", () => {
  const { meter, weather } = fixture({ missing: 8, flagged: 11 });
  const result = analyseDayAheadCsv(meter, weather, "UTC");
  assert.equal(result.excluded.incomplete_or_dst, 1);
  assert.equal(result.excluded.flagged_or_invalid, 1);
});

test("preview requires next-day weather, not next-day readings", () => {
  const { meter, weather } = fixture({ futureWeather: true });
  const result = analyseDayAheadCsv(meter, weather, "UTC");
  assert.equal(result.future.date, "2025-03-12");
  assert.equal(result.future.points.length, 48);
  assert.ok(result.future.points.every((p) => p.actual === null));
  const noWeather = analyseDayAheadCsv(meter, weather.split("\n").slice(0, -1).join("\n"), "UTC");
  assert.equal(noWeather.future, null);
});

test("DST transition days cannot masquerade as 48 local half-hours", () => {
  const { meter, weather } = fixture({ days: 110 });
  const result = analyseDayAheadCsv(meter, weather, "Europe/London");
  assert.ok(result.excluded.incomplete_or_dst >= 1);
  assert.ok(result.days.every((day) => day.points.length === 48));
});

test("short data fails with an informative error", () => {
  const { meter, weather } = fixture({ days: 10 });
  assert.throws(() => analyseDayAheadCsv(meter, weather, "UTC"), /at least/);
});
