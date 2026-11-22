/** Generate measured day-ahead scores and full-day traces from public data.
 * Run after: python -m scripts.prepare_day_ahead
 */
import { readFile, writeFile, mkdir } from "node:fs/promises";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { analyseDayAheadCsv } from "../docs/day-ahead.js";

const homes = ["residential1", "residential2", "residential4", "residential5", "residential6"];
const folder = process.argv[2] ?? "data/derived";
const weatherFile = process.argv[3] ?? "data/raw/konstanz_era5.csv";
const destination = process.argv[4] ?? "docs/assets/day-ahead";
const weather = await readFile(weatherFile, "utf8");
const manifest = JSON.parse(await readFile(join(folder, "day_ahead_sources.json"), "utf8"));
const digest = (data) => createHash("sha256").update(data).digest("hex");
if (digest(weather) !== manifest.era5_sha256) {
  throw new Error("ERA5 CSV hash does not match manifest");
}
await mkdir(destination, { recursive: true });

const round = (v) => v == null ? null : Number(v.toFixed(5));
const compactMetric = (m) => Object.fromEntries(Object.entries(m).map(([key, value]) => [key, round(value)]));
const summary = {
  provenance: manifest,
  method: {
    name: "Frozen 80/20 chronological split; additive within-slot temperature regression",
    weather: "Historical ERA5 reanalysis, NOT issued day-ahead forecast (perfect-weather proxy)",
    zone: "Europe/Berlin",
    interval: "Unflagged complete 48-slot local days; excludes DST 23/25h days",
    baseline: "Prior complete local day's matching 48 half-hour readings",
    comparison: "All models evaluated on identical holdout days with a complete yesterday",
    prediction_unit: "kWh per 30 minutes; grid import not gross household load",
    training: "Train on earlier complete days only; no target or future values in coefficients",
    note: "Households with insufficient paired days are marked ineligible rather than assigned artificial scores",
  },
  homes: {},
};
for (const home of homes) {
  const meter = await readFile(join(folder, "opsd_2016_" + home + ".csv"), "utf8");
  try {
    const report = analyseDayAheadCsv(meter, weather, "Europe/Berlin");
    const compact = {
      home, train_start: report.train_start, train_end: report.train_end,
      test_start: report.test_start, test_end: report.test_end,
      train_days: report.train_days, test_days: report.test_days,
      candidate_test_days: report.candidate_test_days, test_halfhours: report.test_halfhours,
      skipped_missing_yesterday: report.skipped_missing_yesterday,
      excluded: report.excluded,
      temperature_slope_kwh_per_halfhour_per_c: round(report.temperature_slope_kwh_per_halfhour_per_c),
      methods: Object.fromEntries(Object.entries(report.methods).map(([key, m]) => [key, {
        interval: compactMetric(m.interval), daily: compactMetric(m.daily),
      }])),
      days: report.days.map((day) => ({
        date: day.date,
        totals: Object.fromEntries(Object.entries(day.totals).map(([k, v]) => [k, round(v)])),
        points: day.points.map((point) => Object.fromEntries(Object.entries(point)
          .map(([k, v]) => [k, round(v)]))),
      })),
    };
    await writeFile(join(destination, home + ".json"), JSON.stringify(compact) + "\n");
    summary.homes[home] = Object.fromEntries(Object.entries(compact)
      .filter(([key]) => key !== "days"));
    summary.homes[home].file = home + ".json";
    console.log(home + ": " + report.test_days + " paired days; ERA5 MAE " +
      round(report.methods.era5.interval.mae_kwh) + "; yesterday MAE " +
      round(report.methods.yesterday.interval.mae_kwh));
  } catch (error) {
    summary.homes[home] = { status: "not_evaluable", reason: error.message };
    console.warn(home + ": ineligible (" + error.message + ")");
  }
}
if (Object.values(summary.homes).every((home) => home.status === "not_evaluable")) {
  throw new Error("All households ineligible: refusing to publish an empty study");
}
await writeFile(join(destination, "summary.json"), JSON.stringify(summary, null, 2) + "\n");
console.log("Report written: " + destination + "/summary.json");
