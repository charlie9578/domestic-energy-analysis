/** Day-ahead half-hourly grid import hindcast. No dependencies or browser globals.
 *
 * Training uses only earlier, complete local days. ERA5 temperature is
 * reanalysis (a perfect-weather proxy), NOT an archived weather forecast.
 */
import { HOUR, parseSeries } from "./meter-analysis.js";

const DAY = 24 * HOUR;
const SLOTS = 48;
const formatters = new Map();

function local(stamp, zone) {
  if (!formatters.has(zone)) {
    formatters.set(zone, new Intl.DateTimeFormat("en-GB", {
      timeZone: zone, year: "numeric", month: "2-digit", day: "2-digit",
      hour: "2-digit", minute: "2-digit", hourCycle: "h23",
    }));
  }
  const p = Object.fromEntries(formatters.get(zone).formatToParts(new Date(stamp))
    .filter((x) => x.type !== "literal").map((x) => [x.type, x.value]));
  return { date: p.year + "-" + p.month + "-" + p.day,
    slot: Number(p.hour) * 2 + Number(p.minute) / 30 };
}

function shiftDate(day, offset) {
  return new Date(Date.parse(day + "T12:00:00Z") + offset * DAY).toISOString().slice(0, 10);
}

function group(day, slot) {
  const weekday = new Date(day + "T12:00:00Z").getUTCDay();
  return (weekday === 0 || weekday === 6 ? 48 : 0) + slot;
}

function fit(days) {
  const sums = Array.from({ length: 96 }, () => ({ n: 0, energy: 0, temp: 0 }));
  const slots = Array.from({ length: SLOTS }, () => ({ n: 0, energy: 0, temp: 0 }));
  for (const day of days) {
    for (const point of day.points) {
      for (const s of [sums[group(day.date, point.slot)], slots[point.slot]]) {
        s.n++; s.energy += point.actual; s.temp += point.temperature;
      }
    }
  }
  const averages = (s) => ({ energy: s.energy / s.n, temp: s.temp / s.n });
  const means = sums.map((s, index) => averages(s.n ? s : slots[index % SLOTS]));
  let covariance = 0, variance = 0;
  for (const day of days) {
    for (const point of day.points) {
      const m = means[group(day.date, point.slot)];
      const centred = point.temperature - m.temp;
      covariance += centred * (point.actual - m.energy);
      variance += centred * centred;
    }
  }
  // Pooled temperature slope after de-meaning by half-hour and weekend.
  // Ridge penalty in C^2 discourages an unstable slope on mild-only samples.
  const slope = covariance / (variance + 20);
  return { means, slope };
}

function predict(model, day, yesterday) {
  return day.points.map((point) => {
    const m = model.means[group(day.date, point.slot)];
    return { slot: point.slot, temperature_c: point.temperature,
      actual: point.actual ?? null,
      era5: Math.max(0, m.energy + model.slope * (point.temperature - m.temp)),
      calendar: Math.max(0, m.energy),
      yesterday: yesterday.points[point.slot].actual };
  });
}

function sum(rows, key) {
  return rows.reduce((total, row) => total + row[key], 0);
}

function regression(rows, key) {
  const n = rows.length;
  const x = sum(rows, key) / n, y = sum(rows, "actual") / n;
  let sxx = 0, syy = 0, sxy = 0;
  for (const row of rows) {
    const dx = row[key] - x, dy = row.actual - y;
    sxx += dx * dx; syy += dy * dy; sxy += dx * dy;
  }
  return {
    slope: sxx > 1e-12 ? sxy / sxx : null,
    intercept_kwh: sxx > 1e-12 ? y - sxy * x / sxx : null,
    calibration_r2: sxx > 1e-12 && syy > 1e-12 ? sxy * sxy / (sxx * syy) : null,
  };
}

function metrics(rows, key) {
  if (!rows.length) return null;
  const n = rows.length, avg = sum(rows, "actual") / n;
  const squared = rows.reduce((s, r) => s + (r[key] - r.actual) ** 2, 0);
  const abs = rows.reduce((s, r) => s + Math.abs(r[key] - r.actual), 0);
  const denominator = rows.reduce((s, r) => s + (r.actual - avg) ** 2, 0);
  return { count: n, mae_kwh: abs / n, rmse_kwh: Math.sqrt(squared / n),
    bias_kwh: (sum(rows, key) - sum(rows, "actual")) / n,
    r2: denominator > 1e-12 ? 1 - squared / denominator : null,
    ...regression(rows, key) };
}

function weatherMap(weather) {
  const lookup = new Map();
  for (const row of weather) {
    if (!Number.isFinite(row.start) || row.start % HOUR || row.end - row.start !== HOUR ||
        !Number.isFinite(row.amount) || row.flagged || lookup.has(row.start)) {
      throw new Error("Weather needs unique unflagged UTC-hour temperature readings.");
    }
    lookup.set(row.start, row.amount);
  }
  return lookup;
}

function completeMeterDays(meter, hourly, zone) {
  const raw = new Map();
  for (const row of meter) {
    if (!Number.isFinite(row.start)) throw new Error("Invalid meter timestamp.");
    const civil = local(row.start, zone);
    if (!raw.has(civil.date)) raw.set(civil.date, []);
    raw.get(civil.date).push({ slot: civil.slot, stamp: row.start, end: row.end,
      actual: row.amount, flagged: row.flagged });
  }
  const days = new Map();
  const excluded = { incomplete_or_dst: 0, flagged_or_invalid: 0, missing_era5_hour: 0 };
  for (const [date, rows] of [...raw].sort(([a], [b]) => a.localeCompare(b))) {
    if (rows.some((r) => r.flagged || !Number.isFinite(r.actual) || r.actual < 0 ||
        r.end - r.stamp !== HOUR / 2 || r.stamp % (HOUR / 2) || !Number.isInteger(r.slot) ||
        r.slot < 0 || r.slot >= SLOTS)) {
      excluded.flagged_or_invalid++;
      continue;
    }
    const bySlot = new Map(rows.map((r) => [r.slot, r]));
    if (rows.length !== SLOTS || bySlot.size !== SLOTS) {
      // Includes 23/25-hour DST days, which cannot be compared by a 48-slot local clock.
      excluded.incomplete_or_dst++;
      continue;
    }
    const points = [...bySlot].sort(([a], [b]) => a - b).map(([slot, r]) => ({
      slot, actual: r.actual, temperature: hourly.get(Math.floor(r.stamp / HOUR) * HOUR),
    }));
    if (points.some((p) => !Number.isFinite(p.temperature))) {
      excluded.missing_era5_hour++;
      continue;
    }
    days.set(date, { date, points });
  }
  return { days, raw, excluded };
}

function nextWeatherDay(hourly, zone, date) {
  const points = new Map();
  for (const [stamp, temperature] of hourly) {
    for (const half of [0, HOUR / 2]) {
      const civil = local(stamp + half, zone);
      if (civil.date === date && Number.isInteger(civil.slot)) {
        if (points.has(civil.slot)) return null;
        points.set(civil.slot, { slot: civil.slot, temperature });
      }
    }
  }
  if (points.size !== SLOTS) return null;
  return { date, points: [...points].sort((a, b) => a.slot - b.slot).map((x) => x[1]) };
}

/** Inputs are parseSeries() outputs; all predictions use kWh per half-hour. */
export function analyseDayAhead(meter, weather, zone = "Europe/London", options = {}) {
  if (!["Europe/London", "Europe/Berlin", "UTC"].includes(zone)) {
    throw new Error("Select UK local, Central European local, or UTC time.");
  }
  const fraction = options.holdoutFraction ?? 0.2;
  const minTrain = options.minTrainDays ?? 28;
  if (!(fraction > 0 && fraction < .5) || !Number.isInteger(minTrain) || minTrain < 14) {
    throw new Error("Invalid chronological split settings.");
  }
  const hourly = weatherMap(weather);
  const { days, raw, excluded } = completeMeterDays(meter, hourly, zone);
  const dates = [...days.keys()].sort();
  if (dates.length < minTrain + 5) {
    throw new Error("Need at least " + (minTrain + 5) +
      " complete, weather-matched 48-slot days; found " + dates.length +
      ". Check coverage, timezone and interpolated intervals.");
  }
  const cut = Math.max(minTrain, Math.floor(dates.length * (1 - fraction)));
  const training = dates.slice(0, cut).map((d) => days.get(d));
  const candidateDates = dates.slice(cut);
  const model = fit(training);
  const tested = [];
  let skippedYesterday = 0;
  for (const date of candidateDates) {
    const previous = days.get(shiftDate(date, -1));
    if (!previous) { skippedYesterday++; continue; }
    const points = predict(model, days.get(date), previous);
    tested.push({ date, points, totals: {
      actual: sum(points, "actual"), era5: sum(points, "era5"),
      calendar: sum(points, "calendar"), yesterday: sum(points, "yesterday"),
    } });
  }
  if (!tested.length) throw new Error("No held-out days have an unflagged, complete previous day.");
  const intervals = tested.flatMap((d) => d.points);
  const totals = tested.map((d) => d.totals);
  const methods = Object.fromEntries(["era5", "calendar", "yesterday"].map((key) => [key, {
    interval: metrics(intervals, key), daily: metrics(totals, key),
  }]));
  const latest = dates[dates.length - 1];
  const tomorrow = shiftDate(latest, 1);
  const futureWeather = raw.has(tomorrow) ? null : nextWeatherDay(hourly, zone, tomorrow);
  const future = futureWeather ? (() => {
    const points = predict(fit(dates.map((d) => days.get(d))), futureWeather, days.get(latest));
    return { date: tomorrow, points, totals: {
      era5: sum(points, "era5"), calendar: sum(points, "calendar"),
      yesterday: sum(points, "yesterday"),
    } };
  })() : null;
  return { zone, interpretation: "ERA5 retrospective perfect-weather proxy; not a genuine day-ahead forecast",
    train_start: dates[0], train_end: dates[cut - 1], test_start: candidateDates[0],
    test_end: candidateDates[candidateDates.length - 1], train_days: training.length,
    candidate_test_days: candidateDates.length, test_days: tested.length,
    test_halfhours: intervals.length, skipped_missing_yesterday: skippedYesterday,
    excluded, temperature_slope_kwh_per_halfhour_per_c: model.slope,
    methods, days: tested, future };
}

/** Read the standard repository CSV format, used by the browser and offline CLI. */
export function analyseDayAheadCsv(meterCsv, era5Csv, zone, options) {
  return analyseDayAhead(parseSeries(meterCsv, "electricity", 30),
    parseSeries(era5Csv, "weather", 60), zone, options);
}
