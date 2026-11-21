import assert from "node:assert/strict";
import test from "node:test";
import { DAY, HOUR, demoSeries, detectPatterns, parseSeries } from "../docs/meter-analysis.js";

test("CSV preserves intervals, gaps, zeros and flagged values", () => {
  const rows = parseSeries([
    "start_utc,consumption_kwh,duration_minutes,publisher_interpolated",
    '"2025-10-26T01:00+01:00",0,15,0',
    "2025-10-26T01:00Z,1.5,,1",
    "2025-10-26T01:30Z,,,",
  ].join("\r\n"), "electricity", 30);
  assert.deepEqual(rows.map((row) => [row.amount, row.kw, row.flagged]), [[0, 0, false], [1.5, 3, true]]);
  assert.equal(rows[1].start - rows[0].start, HOUR);
  assert.equal(rows[1].end - rows[1].start, HOUR / 2);
});

test("CSV checks calendar dates, offsets, duplicates and overlaps", () => {
  const source = (lines) => ["start_utc,consumption_kwh", ...lines].join("\n");
  for (const invalid of [
    ["2025-02-30T00:00Z,1"],
    ["2025-02-28T00:00,1"],
    ["2025-02-28T00:00Z,1", "2025-02-28T01:00+01:00,2"],
    ["2025-02-28T00:00Z,1", "2025-02-28T00:15Z,2"],
  ]) {
    assert.throws(() => parseSeries(source(invalid), "gas", 30));
  }
});

test("synthetic data yields expected candidates with weather gating", () => {
  const demo = demoSeries();
  const result = detectPatterns(demo);
  const types = new Set(result.events.map((event) => event.type));
  for (const expected of ["Space-heating candidate", "Short gas burst", "Short electrical burst",
    "EV-like electrical load", "Sustained low use", "Unusually high daily use"]) {
    assert.ok(types.has(expected), expected);
  }
  const low = result.events.find((event) => event.type === "Sustained low use");
  assert.equal(low.end - low.start, 4 * DAY);
  const withoutWeather = detectPatterns({ ...demo, weather: [] });
  assert.ok(withoutWeather.events.some((event) => event.type === "Sustained gas use"));
  assert.ok(!withoutWeather.events.some((event) => event.type === "Space-heating candidate"));
});

test("one flagged reading breaks a heating run and missing days break a low-use spell", () => {
  const demo = demoSeries();
  const start = demo.gas[0].start;
  demo.gas[14].flagged = true;
  demo.electricity = demo.electricity.filter((row) => row.start !== start + 6 * DAY);
  const events = detectPatterns(demo).events;
  assert.ok(!events.some((event) => event.type === "Space-heating candidate" && event.start < start + DAY));
  assert.ok(!events.some((event) => event.type === "Sustained low use"));
});

test("electric heating hint needs complete mild and cold weather days", () => {
  const start = Date.UTC(2025, 0, 1);
  const electricity = Array.from({ length: 8 }, (_, i) => ({
    start: start + i * DAY, end: start + (i + 1) * DAY, amount: i === 7 ? 12 : 5, kw: 0.5,
  }));
  const weather = Array.from({ length: 8 * 24 }, (_, i) => ({
    start: start + i * HOUR, amount: i >= 7 * 24 ? 6 : 16,
  }));
  assert.equal(detectPatterns({ electricity, weather }).events.at(-1).type, "Cold-weather electrical demand");
  assert.equal(detectPatterns({ electricity, weather: weather.slice(1) }).events.length, 0);
});
