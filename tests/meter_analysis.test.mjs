import assert from "node:assert/strict";
import test from "node:test";
import { DAY, HOUR, clockProfile, demoSeries, detectPatterns, parseSeries, scheduledTarget } from "../docs/meter-analysis.js";

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

test("activation log takes precedence and annotates exact indoor boundary readings", () => {
  const start = Date.UTC(2025, 0, 1);
  const gas = [0, 1, 2].map((slot) => ({
    start: start + slot * HOUR / 2, end: start + (slot + 1) * HOUR / 2, kw: 3,
  }));
  const weather = [{ start, amount: 4 }, { start: start + HOUR, amount: 4 }];
  const heating = parseSeries(
    "start_utc,heating_fraction,duration_minutes\n2025-01-01T00:00Z,0.5,60\n2025-01-01T01:00Z,0,60",
    "heating", 30);
  const indoor = parseSeries(
    "start_utc,indoor_temperature_c,duration_minutes\n2025-01-01T00:00Z,19.0,60\n2025-01-01T01:00Z,19.1,60",
    "indoor", 30);
  const { events } = detectPatterns({ gas, weather, heating, indoor });
  assert.deepEqual(events.map((event) => event.type), ["Recorded heating activation"]);
  assert.match(events[0].evidence, /30 active minutes.*19.0°C and 19.1°C/);
  assert.throws(() => parseSeries("start_utc,heating_fraction\n2025-01-01T00:00Z,1.1", "heating", 30));
});

test("clock-hour profiles retain local summer time and weight native durations", () => {
  const start = Date.UTC(2025, 6, 1, 5);
  const indoor = [
    { start, end: start + HOUR / 4, amount: 17 },
    { start: start + HOUR / 4, end: start + HOUR, amount: 21 },
  ];
  const profile = clockProfile({ indoor }, "Europe/London");
  assert.deepEqual(profile[6], { hour: 6, indoor_c: 20, indoor_hours: 1 });
  const targets = { dayStart: 7, nightStart: 22, dayTarget: 20, nightTarget: 17 };
  assert.equal(scheduledTarget(6, targets), 17);
  assert.equal(scheduledTarget(7, targets), 20);
  assert.equal(scheduledTarget(22, targets), 17);
  assert.equal(scheduledTarget(0, { ...targets, dayStart: 22, nightStart: 7 }), 20);
});

test("recorded-mode display excludes inferred activity", () => {
  const data = demoSeries();
  data.heating = [{ start: data.gas[0].start, end: data.gas[0].start + HOUR, amount: .5 }];
  const result = detectPatterns({ ...data, exploratory: false });
  assert.deepEqual(result.events.map((event) => event.type), ["Recorded heating activation"]);
  assert.equal(result.baselineDays, null);
});
