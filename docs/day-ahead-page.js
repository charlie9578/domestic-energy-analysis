import { analyseDayAheadCsv } from "./day-ahead.js";

const $ = (id) => document.getElementById(id);
const f = (x, digits = 3) => x == null ? "—" : Number(x).toFixed(digits);
const names = { era5: "ERA5 temperature regression", calendar: "Clock/calendar only", yesterday: "Yesterday = today", auto_ml: "Guarded AutoML (training-only selection)" };
const colours = { actual: "#132b2e", era5: "#12604c", calendar: "#286497", yesterday: "#af6d2c", auto_ml: "#853b86" };
let report = null, sourceLabel = "";

function populate(target, cells) {
  const row = document.createElement("tr");
  for (const value of cells) {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.append(cell);
  }
  target.append(row);
}
function draw(points) {
  const canvas = $("forecast-curve"), ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height, left = 54, right = 22, top = 18, bottom = 44;
  ctx.clearRect(0, 0, w, h);
  const max = Math.max(.1, ...points.flatMap((p) => Object.keys(colours).map((key) => p[key] ?? 0))) * 1.12;
  const x = (i) => left + i * (w - left - right) / 47;
  const y = (value) => top + (max - value) * (h - top - bottom) / max;
  ctx.lineWidth = 1; ctx.strokeStyle = "#d5dfd9"; ctx.fillStyle = "#43585a"; ctx.font = "13px system-ui";
  for (let t = 0; t <= 4; t++) {
    const yy = top + t * (h - top - bottom) / 4;
    ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(w - right, yy); ctx.stroke();
    ctx.fillText(f(max * (4 - t) / 4, 2), 3, yy + 4);
  }
  for (let hour = 0; hour <= 24; hour += 4) {
    ctx.fillText(String(hour).padStart(2, "0") + ":00", x(Math.min(47, 2 * hour)) - 16, h - 15);
  }
  for (const key of Object.keys(colours)) {
    ctx.beginPath(); ctx.strokeStyle = colours[key]; ctx.lineWidth = key === "actual" ? 3 : 2;
    ctx.setLineDash(key === "calendar" ? [5, 4] : key === "yesterday" ? [2, 4] : key === "auto_ml" ? [9, 3] : []);
    points.forEach((p, i) => { if (Number.isFinite(p[key])) i === 0 ? ctx.moveTo(x(i), y(p[key])) : ctx.lineTo(x(i), y(p[key])); });
    ctx.stroke();
  }
  ctx.setLineDash([]);
}
function displayDay() {
  if (!report) return;
  const day = report.days.find((d) => d.date === $("forecast-day").value);
  if (!day) return;
  draw(day.points);
  $("forecast-caption").textContent = "Local time · energy per half-hour (kWh), not instantaneous kW.";
  $("forecast-day-summary").textContent = "Observed " + f(day.totals.actual) + " kWh · ERA5 " +
    f(day.totals.era5) + " kWh · Calendar " + f(day.totals.calendar) +
    " kWh · Yesterday hold " + f(day.totals.yesterday) + " kWh · AutoML " + f(day.totals.auto_ml) + " kWh.";
  $("forecast-values").replaceChildren();
  for (const p of day.points) {
    const hh = String(Math.floor(p.slot / 2)).padStart(2, "0");
    populate($("forecast-values"), [hh + ":" + (p.slot % 2 ? "30" : "00"),
      f(p.actual), f(p.era5), f(p.calendar), f(p.yesterday), f(p.auto_ml), f(p.temperature_c, 1)]);
  }
}
function show(result, label) {
  report = result; sourceLabel = label;
  $("forecast-results").hidden = false;
  $("forecast-split").textContent = label + " · Training " + result.train_start + " to " +
    result.train_end + " (" + result.train_days + " days); test " + result.test_start + " to " +
    result.test_end + " (" + result.test_days + " comparable days, " +
    result.test_halfhours + " half-hours).";
  $("forecast-scores").replaceChildren();
  $("forecast-calibration").replaceChildren();
  for (const [key, name] of Object.entries(names)) {
    if (!result.methods[key]) continue;
    const interval = result.methods[key].interval, daily = result.methods[key].daily;
    populate($("forecast-scores"), [name, f(interval.mae_kwh), f(interval.rmse_kwh),
      f(interval.r2), f(daily.mae_kwh), f(daily.bias_kwh)]);
    populate($("forecast-calibration"), [name, f(interval.slope), f(interval.intercept_kwh),
      f(interval.calibration_r2), f(daily.slope), f(daily.calibration_r2)]);
  }
  const choice = result.auto_ml_selection;
  $("forecast-selection").textContent = choice
    ? "Training-only AutoML: " + choice.chosen_label + " (" + choice.chosen_id +
      "). Expanding-window validation: " + choice.folds + " blocks / " +
      choice.validation_days + " paired days; " + choice.reason + ". " +
      (choice.chosen_cv_improvement_pct == null ? "" :
       "Estimated validation gain vs best simple baseline: " +
       f(choice.chosen_cv_improvement_pct, 1) + "%. ") +
      "The selected model is evaluated on the untouched held-out days alongside the three baselines."
    : "This archived result predates the guarded AutoML search; regenerate to compare the selected model.";
  const e = result.excluded;
  $("forecast-exclusions").textContent = "Excluded local days: " + e.incomplete_or_dst +
    " incomplete/DST, " + e.flagged_or_invalid + " flagged or invalid, " + e.missing_era5_hour +
    " missing weather. Held-out days lacking a valid yesterday: " +
    result.skipped_missing_yesterday + ". Reanalysis proxy temperature coefficient: " +
    f(result.temperature_slope_kwh_per_halfhour_per_c, 4) + " kWh per half-hour per °C.";
  const selector = $("forecast-day");
  selector.replaceChildren();
  for (const day of result.days) {
    const option = document.createElement("option");
    option.value = day.date; option.textContent = day.date; selector.append(option);
  }
  selector.value = result.days.at(-1).date;
  displayDay();
  $("future-panel").hidden = !result.future;
  if (result.future) {
    const day = result.future;
    $("future-status").textContent = day.date + ": ERA5-weather proxy " +
      f(day.totals.era5) + " kWh, calendar " + f(day.totals.calendar) +
      " kWh, yesterday hold " + f(day.totals.yesterday) + " kWh, AutoML " + f(day.totals.auto_ml) + " kWh.";
  }
  $("forecast-status").textContent = "Backtest ready. ERA5 results are hindsight weather-proxy estimates, not real day-ahead weather forecast skill.";
}
$("forecast-day").addEventListener("change", displayDay);
$("forecast-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("forecast-status").textContent = "Reading local files…";
  try {
    const data = new FormData(event.currentTarget);
    const [meter, weather] = await Promise.all(["meter", "weather"].map((key) => data.get(key).text()));
    show(analyseDayAheadCsv(meter, weather, data.get("zone")), "Uploaded data");
  } catch (error) {
    $("forecast-results").hidden = true;
    $("forecast-status").textContent = "Could not run: " + error.message;
  }
});
$("forecast-demo").addEventListener("click", () => {
  try {
    const meter = ["start_utc,consumption_kwh,duration_minutes"];
    const weather = ["start_utc,temperature_c"];
    const first = Date.UTC(2025, 0, 1);
    // Exact, deterministic synthetic 90-day UTC test. Not a published meter observation.
    for (let d = 0; d < 90; d++) {
      const day = first + d * 86_400_000;
      const weekday = new Date(day).getUTCDay();
      const weekend = weekday === 0 || weekday === 6;
      for (let h = 0; h < 24; h++) {
        const temp = 9 + 8 * Math.sin(d / 15) + 2 * Math.sin(h * Math.PI / 12);
        weather.push(new Date(day + h * 3_600_000).toISOString() + "," + temp.toFixed(4));
        for (let half = 0; half < 2; half++) {
          const evening = h >= 17 && h < 21 ? .32 : 0;
          const morning = h >= 7 && h < 9 ? .12 : 0;
          const use = .16 + evening + morning + (weekend ? .08 : 0) +
            Math.max(0, 17 - temp) * .018 + .025 * Math.sin(d * 1.37 + h * 2 + half);
          meter.push(new Date(day + (h * 2 + half) * 1_800_000).toISOString() +
            "," + use.toFixed(5) + ",30");
        }
      }
    }
    show(analyseDayAheadCsv(meter.join("\n"), weather.join("\n"), "UTC"), "SYNTHETIC 90-day demonstration");
  } catch (error) {
    $("forecast-status").textContent = "Demo error: " + error.message;
  }
});
$("forecast-export").addEventListener("click", () => {
  if (!report) return;
  const rows = ["date,local_slot,observed_kwh,era5_kwh,calendar_kwh,yesterday_kwh,automl_kwh,era5_temperature_c"];
  for (const d of report.days) for (const p of d.points) rows.push([
    d.date, p.slot, p.actual, p.era5, p.calendar, p.yesterday, p.auto_ml, p.temperature_c].join(","));
  const url = URL.createObjectURL(new Blob([rows.join("\n") + "\n"], { type: "text/csv" }));
  const a = document.createElement("a");
  a.href = url; a.download = "day-ahead-backtest.csv"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
});


async function loadPublishedStudy() {
  try {
    const response = await fetch("docs/assets/day-ahead/summary.json", { cache: "no-store" });
    if (!response.ok) throw new Error("Study dataset has not been published yet (HTTP " + response.status + ").");
    const study = await response.json();
    const available = [];
    $("published-rows").replaceChildren();
    $("published-home").replaceChildren();
    for (const [home, entry] of Object.entries(study.homes)) {
      if (!entry.methods) {
        populate($("published-rows"), [home, "Not evaluable", "—", "—", "—", "—", "—", entry.reason ?? "Excluded"]);
        continue;
      }
      const a = entry.methods.era5.interval.mae_kwh;
      const b = entry.methods.yesterday.interval.mae_kwh;
      const c = entry.methods.calendar.interval.mae_kwh;
      const auto = entry.methods.auto_ml?.interval.mae_kwh;
      populate($("published-rows"), [home, entry.test_days, f(a, 4), f(b, 4),
        f(c, 4), f(auto, 4), entry.auto_ml_selection?.chosen_label ?? "Not yet generated",
        a < b ? "ERA5 lower error" : a > b ? "Yesterday lower error" : "Tie"]);
      available.push({ home, file: entry.file });
      const option = document.createElement("option");
      option.value = entry.file; option.textContent = home;
      $("published-home").append(option);
    }
    $("published-table").hidden = false;
    $("published-home").disabled = available.length === 0;
    $("published-open").disabled = available.length === 0;
    $("published-status").textContent = available.length + " of " + Object.keys(study.homes).length +
      " measured household traces have comparable backtest days. Lower MAE is better.";
    $("published-provenance").textContent = "Meter: " + study.provenance.source +
      " (SHA-256 " + study.provenance.opsd_sha256.slice(0, 16) + "…) · Weather: " +
      study.provenance.weather + " (SHA-256 " +
      study.provenance.era5_sha256.slice(0, 16) + "…). The regression was fitted on historical training data only.";
  } catch (error) {
    $("published-status").textContent = "Measured study is not currently available: " + error.message +
      " Reproduction commands are in the linked methodology.";
  }
}
$("published-open").addEventListener("click", async () => {
  try {
    const file = $("published-home").value;
    if (!/^residential[1-6]\.json$/.test(file)) throw new Error("Invalid household reference");
    $("published-status").textContent = "Loading measured household trace…";
    const response = await fetch("docs/assets/day-ahead/" + file, { cache: "no-store" });
    if (!response.ok) throw new Error("Household file unavailable");
    const report = await response.json();
    show(report, "Measured OPSD " + report.home + " · ERA5 hindcast");
    $("forecast-results").scrollIntoView({ behavior: "smooth", block: "start" });
    $("published-status").textContent = report.home + " loaded. Curve and scores are shown below.";
  } catch (error) {
    $("published-status").textContent = "Cannot open measured household: " + error.message;
  }
});
loadPublishedStudy();
