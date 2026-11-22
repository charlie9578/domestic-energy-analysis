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


/** Fixed, intentionally small candidate list: no unconstrained model discovery.
 * Each candidate is interpretable and uses only weather and prior-day readings
 * that could be available when issuing a day-ahead forecast.
 */
export const DAY_AHEAD_CANDIDATES = Object.freeze([
  { id: "calendar", label: "Calendar-only", complexity: 0 },
  { id: "era5", label: "ERA5 temperature regression", complexity: 1 },
  { id: "yesterday", label: "Yesterday persistence", complexity: 0 },
  { id: "calendar_yesterday_50", label: "Calendar / yesterday 50:50", complexity: 2 },
  { id: "era5_yesterday_25", label: "ERA5 75% / yesterday 25%", complexity: 2 },
  { id: "era5_yesterday_50", label: "ERA5 / yesterday 50:50", complexity: 2 },
  { id: "era5_yesterday_75", label: "ERA5 25% / yesterday 75%", complexity: 2 },
  { id: "era5_calendar_50", label: "ERA5 / calendar 50:50", complexity: 2 },
  { id: "yesterday_weather_50", label: "Yesterday + half temperature adjustment", complexity: 2 },
  { id: "yesterday_weather_100", label: "Yesterday + full temperature adjustment", complexity: 2 },
  { id: "era5_weather_yesterday_50", label: "ERA5 / weather-adjusted yesterday 50:50", complexity: 3 },
]);

function candidateValue(id, row, previousTemp, slope) {
  const yesterdayWeather = (factor) => Math.max(0,
    row.yesterday + factor * slope * (row.temperature_c - previousTemp));
  switch (id) {
    case "calendar": return row.calendar;
    case "era5": return row.era5;
    case "yesterday": return row.yesterday;
    case "calendar_yesterday_50": return .5 * row.calendar + .5 * row.yesterday;
    case "era5_yesterday_25": return .75 * row.era5 + .25 * row.yesterday;
    case "era5_yesterday_50": return .5 * row.era5 + .5 * row.yesterday;
    case "era5_yesterday_75": return .25 * row.era5 + .75 * row.yesterday;
    case "era5_calendar_50": return .5 * row.era5 + .5 * row.calendar;
    case "yesterday_weather_50": return yesterdayWeather(.5);
    case "yesterday_weather_100": return yesterdayWeather(1);
    case "era5_weather_yesterday_50": return .5 * row.era5 + .5 * yesterdayWeather(1);
    default: throw new Error("Unknown prespecified candidate");
  }
}

/** Training-only blocked expanding-window validation.
 * All candidate scores on each fold use exactly the same days/slots.
 * Candidates are paired with the best simple baseline, not with the final holdout.
 */
export function selectDayAheadModel(training) {
  if (!Array.isArray(training) || training.length < 30) {
    return { chosen_id: "yesterday", chosen_label: "Yesterday persistence",
      reason: "Insufficient training days for expanding-window validation",
      tuned: false, folds: 0, validation_days: 0,
      candidate_count: DAY_AHEAD_CANDIDATES.length };
  }
  const n = training.length;
  const bounds = [Math.floor(n * .50), Math.floor(n * .67), Math.floor(n * .84), n];
  const byDate = new Map(training.map((d) => [d.date, d]));
  const foldScores = Object.fromEntries(DAY_AHEAD_CANDIDATES.map((m) => [m.id, []]));
  let days = 0;
  const foldDetails = [];
  for (let i = 0; i < 3; i++) {
    const fitted = fit(training.slice(0, bounds[i]));
    const paired = training.slice(bounds[i], bounds[i + 1])
      .map((day) => ({ day, previous: byDate.get(shiftDate(day.date, -1)) }))
      .filter(({ previous }) => previous);
    if (paired.length < 5) continue;
    const errors = Object.fromEntries(DAY_AHEAD_CANDIDATES.map((m) => [m.id, 0]));
    for (const { day, previous } of paired) {
      const base = predict(fitted, day, previous);
      for (const row of base) {
        for (const method of DAY_AHEAD_CANDIDATES) {
          errors[method.id] += Math.abs(candidateValue(method.id, row,
            previous.points[row.slot].temperature, fitted.slope) - row.actual);
        }
      }
    }
    for (const method of DAY_AHEAD_CANDIDATES) {
      foldScores[method.id].push(errors[method.id] / (paired.length * SLOTS));
    }
    days += paired.length;
    foldDetails.push({ train_days: bounds[i], validation_start: paired[0].day.date,
      validation_end: paired.at(-1).day.date, validation_days: paired.length });
  }
  if (foldDetails.length < 2 || days < 20) {
    return { chosen_id: "yesterday", chosen_label: "Yesterday persistence",
      reason: "Too few paired expanding-window validation days; safe persistence fallback",
      tuned: false, folds: foldDetails.length, validation_days: days,
      candidate_count: DAY_AHEAD_CANDIDATES.length };
  }
  const average = (array) => array.reduce((sum, x) => sum + x, 0) / array.length;
  const ranked = (candidates) => [...candidates].sort((a, b) =>
    average(foldScores[a.id]) - average(foldScores[b.id]) ||
    a.complexity - b.complexity || a.id.localeCompare(b.id));
  const baseline = ranked(DAY_AHEAD_CANDIDATES.filter((c) =>
    ["calendar", "era5", "yesterday"].includes(c.id)))[0];
  const baselineMae = average(foldScores[baseline.id]);
  const eligible = DAY_AHEAD_CANDIDATES.filter((candidate) => {
    if (candidate.complexity < 2) return false;
    const deltas = foldScores[baseline.id].map((v, index) =>
      v - foldScores[candidate.id][index]);
    const gain = average(deltas);
    const variance = deltas.reduce((total, delta) =>
      total + (delta - gain) ** 2, 0) / (deltas.length - 1);
    const pairedSe = Math.sqrt(variance / deltas.length);
    // Guard against noise and repeated hyperparameter comparisons: a candidate
    // must beat the best simple baseline by >=3% AND >one paired-fold SE.
    return gain > Math.max(.03 * baselineMae, pairedSe) &&
      deltas.filter((value) => value > 0).length >= 2;
  });
  const chosen = ranked([baseline, ...eligible])[0];
  const chosenMae = average(foldScores[chosen.id]);
  return { chosen_id: chosen.id, chosen_label: chosen.label, tuned: true,
    folds: foldDetails.length, validation_days: days, fold_details: foldDetails,
    candidate_count: DAY_AHEAD_CANDIDATES.length,
    baseline_id: baseline.id, baseline_cv_mae_kwh: baselineMae,
    chosen_cv_mae_kwh: chosenMae,
    chosen_cv_improvement_pct: 100 * (baselineMae - chosenMae) / baselineMae,
    selection_guard: "3% MAE and one paired-fold SE over best simple baseline; >=2 improving folds",
    candidates_cv_mae_kwh: Object.fromEntries(DAY_AHEAD_CANDIDATES.map((m) =>
      [m.id, average(foldScores[m.id])])),
    reason: chosen.id === baseline.id ?
      "No blend cleared the predeclared validation improvement guard; use simpler baseline" :
      "Blend improved past validation blocks enough to clear the predeclared guard",
  };
}

function addSelected(points, previous, model, selected) {
  return points.map((row) => ({ ...row, auto_ml: candidateValue(selected.chosen_id,
    row, previous.points[row.slot].temperature, model.slope) }));
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
  const selection = selectDayAheadModel(training);
  const tested = [];
  let skippedYesterday = 0;
  for (const date of candidateDates) {
    const previous = days.get(shiftDate(date, -1));
    if (!previous) { skippedYesterday++; continue; }
    const points = addSelected(predict(model, days.get(date), previous), previous, model, selection);
    tested.push({ date, points, totals: {
      actual: sum(points, "actual"), era5: sum(points, "era5"),
      calendar: sum(points, "calendar"), yesterday: sum(points, "yesterday"),
      auto_ml: sum(points, "auto_ml"),
    } });
  }
  if (!tested.length) throw new Error("No held-out days have an unflagged, complete previous day.");
  const intervals = tested.flatMap((d) => d.points);
  const totals = tested.map((d) => d.totals);
  const methods = Object.fromEntries(["era5", "calendar", "yesterday", "auto_ml"].map((key) => [key, {
    interval: metrics(intervals, key), daily: metrics(totals, key),
  }]));
  const latest = dates[dates.length - 1];
  const tomorrow = shiftDate(latest, 1);
  const futureWeather = raw.has(tomorrow) ? null : nextWeatherDay(hourly, zone, tomorrow);
  const future = futureWeather ? (() => {
    const futureModel = fit(dates.map((d) => days.get(d)));
    const points = addSelected(predict(futureModel, futureWeather, days.get(latest)),
      days.get(latest), futureModel, selection);
    return { date: tomorrow, points, totals: {
      era5: sum(points, "era5"), calendar: sum(points, "calendar"),
      yesterday: sum(points, "yesterday"), auto_ml: sum(points, "auto_ml"),
    } };
  })() : null;
  return { zone, interpretation: "ERA5 retrospective perfect-weather proxy; not a genuine day-ahead forecast",
    train_start: dates[0], train_end: dates[cut - 1], test_start: candidateDates[0],
    test_end: candidateDates[candidateDates.length - 1], train_days: training.length,
    candidate_test_days: candidateDates.length, test_days: tested.length,
    test_halfhours: intervals.length, skipped_missing_yesterday: skippedYesterday,
    excluded, temperature_slope_kwh_per_halfhour_per_c: model.slope,
    methods, days: tested, future, auto_ml_selection: selection };
}

/** Read the standard repository CSV format, used by the browser and offline CLI. */
export function analyseDayAheadCsv(meterCsv, era5Csv, zone, options) {
  return analyseDayAhead(parseSeries(meterCsv, "electricity", 30),
    parseSeries(era5Csv, "weather", 60), zone, options);
}
