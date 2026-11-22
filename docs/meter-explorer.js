import { DAY, HOUR, clockProfile, dateLabel, dayStart, demoSeries, detectPatterns, parseSeries, scheduledTarget } from "./meter-analysis.js";

const get = (id) => document.getElementById(id);
const form = get("meter-form");
const channels = {
  electricity: { name: "Electricity", unit: "kWh", colour: "#12604c" },
  gas: { name: "Gas", unit: "kWh", colour: "#9a4b23" },
  weather: { name: "Outdoor temperature", unit: "°C", colour: "#286497" },
  indoor: { name: "Indoor temperature", unit: "°C", colour: "#6e4183" },
  heating: { name: "Space-heating activation", unit: "%", colour: "#957420" },
};
const timestamp = (stamp) => new Date(stamp).toISOString().slice(0, 19).replace("T", " ");
const hourLabel = (stamp) => timestamp(stamp).slice(11, 16);
const decimals = new Intl.NumberFormat("en-GB", { maximumFractionDigits: 3 });
const format = (amount) => decimals.format(amount);
const plotValue = (key, row) => key === "heating" ? row.amount * 100 : row.kw ?? row.amount;
let state = null;

function elements(tag, text, parent) {
  const element = document.createElement(tag);
  element.textContent = text;
  parent.append(element);
  return element;
}

function drawPlots(series, start, end) {
  const target = get("plots");
  target.replaceChildren();
  for (const [key, rows] of Object.entries(series)) {
    const channel = channels[key];
    const temperature = channel.unit === "°C";
    const figure = elements("figure", "", target);
    const units = temperature || key === "heating" ? channel.unit : "kW interval average";
    elements("h3", `${channel.name} · ${units}`, figure);
    if (!rows.length) {
      elements("p", "No data in this window.", figure);
      continue;
    }
    const canvas = elements("canvas", "", figure);
    canvas.setAttribute("aria-hidden", "true");
    const width = Math.max(240, Math.floor(figure.clientWidth));
    const height = 115;
    const scale = window.devicePixelRatio || 1;
    canvas.width = width * scale;
    canvas.height = height * scale;
    canvas.style.height = `${height}px`;
    const ctx = canvas.getContext("2d");
    ctx.scale(scale, scale);
    const values = rows.map((row) => plotValue(key, row));
    const lo = temperature ? Math.floor(Math.min(...values)) : 0;
    const hi = key === "heating" ? 100 : Math.max(lo + 1, Math.ceil(Math.max(...values)));
    const x = (stamp) => 32 + (stamp - start) * (width - 42) / (end - start);
    const y = (value) => 84 - (value - lo) * 70 / (hi - lo);
    ctx.font = "11px system-ui";
    ctx.fillStyle = "#43585a";
    for (const value of [lo, hi]) {
      ctx.fillText(value, 0, y(value) + 3);
      ctx.fillRect(32, y(value), width - 42, 1);
    }
    ctx.fillText(end - start === DAY ? "00:00" : dateLabel(start), 32, 105);
    ctx.textAlign = "right";
    ctx.fillText(end - start === DAY ? "24:00" : dateLabel(end - DAY), width - 10, 105);
    rows.forEach((row, i) => {
      const position = x(Math.max(start, row.start));
      if (temperature) {
        if (row.flagged) return;
        ctx.fillStyle = channel.colour;
        ctx.fillRect(position - 1, y(row.amount) - 1, 3, 3);
        const before = rows[i - 1];
        if (before && before.end === row.start && !before.flagged) {
          ctx.strokeStyle = channel.colour;
          ctx.beginPath();
          ctx.moveTo(x(Math.max(start, before.start)), y(before.amount));
          ctx.lineTo(position, y(row.amount));
          ctx.stroke();
        }
      } else {
        ctx.fillStyle = row.flagged ? "#8f9a96" : channel.colour;
        const value = plotValue(key, row);
        ctx.fillRect(position, y(value), Math.max(1, x(Math.min(end, row.end)) - position - 0.5),
          value === 0 ? 1 : y(0) - y(value));
      }
    });
  }
}

function render() {
  if (!state) return;
  const start = Date.parse(get("view-date").value);
  if (!Number.isFinite(start) || start < state.min || start > state.max) return;
  const days = Number(get("range").value);
  const end = start + days * DAY;
  get("previous").disabled = start <= state.min;
  get("next").disabled = end > state.max;
  const view = Object.fromEntries(Object.entries(state.data)
    .map(([key, rows]) => [key, rows.filter((row) => row.start < end && row.end > start)]));
  drawPlots(view, start, end);

  const details = get("intervals");
  details.replaceChildren();
  // The chart can span a week, while the readings table follows its first day.
  const dayRows = Object.entries(view).flatMap(([key, rows]) => rows
    .filter((row) => row.start < start + DAY)
    .map((row) => [key, row])).sort((a, b) => a[1].start - b[1].start);
  for (const [key, row] of dayRows) {
    const tr = elements("tr", "", details);
    for (const cell of [timestamp(row.start), channels[key].name,
      `${(row.end - row.start) / (HOUR / 60)} min`, `${format(key === "heating" ? row.amount * 100 : row.amount)} ${channels[key].unit}`,
      row.flagged ? "Publisher interpolated" : "Unflagged"]) elements("td", cell, tr);
  }
  if (!dayRows.length) {
    const cell = elements("td", "No readings for this day.", elements("tr", "", details));
    cell.colSpan = 5;
  }

  const filter = get("pattern").value;
  const events = state.events.filter((event) => event.start < end && event.end > start &&
    (!filter || event.type === filter));
  const tbody = get("events");
  tbody.replaceChildren();
  for (const event of events.slice(0, 100)) {
    const tr = elements("tr", "", tbody);
    elements("th", event.type, tr).scope = "row";
    elements("td", `${dateLabel(event.start)} ${hourLabel(event.start)} → ${dateLabel(event.end)} ${hourLabel(event.end)}`, tr);
    elements("td", event.evidence, tr);
  }
  get("event-table").hidden = !events.length;
  get("pattern-status").textContent = events.length > 100 ? `Showing 100 of ${events.length} candidates. Narrow the window or filter by pattern.`
    : events.length ? `${events.length} pattern${events.length === 1 ? "" : "s"} in this window.`
      : "No recorded or inferred patterns in this window.";
}

function show(data, label, demo = false, submeter = false, exploratory = false) {
  const meter = [...(data.gas ?? []), ...(data.electricity ?? []),
    ...(data.indoor ?? []), ...(data.heating ?? [])];
  const min = dayStart(meter.reduce((value, row) => Math.min(value, row.start), Infinity));
  const max = dayStart(meter.reduce((value, row) => Math.max(value, row.end), -Infinity) - 1);
  // Keep the submeter in the readings but avoid household-level inference from it.
  const patternData = { ...data, exploratory, electricity: submeter ? [] : data.electricity };
  state = { data, min, max, ...detectPatterns(patternData) };
  const date = get("view-date");
  date.min = dateLabel(min);
  date.max = dateLabel(max);
  date.value = dateLabel(demo ? min + 3 * DAY : min);
  get("range").value = demo ? "7" : "1";
  get("pattern").replaceChildren(new Option("All patterns", ""));
  for (const type of new Set(state.events.map((event) => event.type))) {
    get("pattern").add(new Option(type, type));
  }
  get("series-summary").textContent = Object.entries(data).map(([key, rows]) => {
    const flagged = rows.filter((row) => row.flagged).length;
    return `${channels[key].name}: ${format(rows.length)} readings${flagged ? ` (${format(flagged)} interpolated)` : ""}`;
  }).join(" · ");
  get("baseline-note").textContent = state.baselineDays === null
    ? "Recorded mode shows supplied activation data. Enable exploratory flags and analyse again to run unvalidated meter heuristics."
    : state.baselineDays < 14
    ? `Daily anomaly rules need at least 14 complete, unflagged UTC days. Found ${state.baselineDays}.`
    : `${state.baselineDays} complete, unflagged UTC days available for the daily baseline.`;
  get("status").textContent = label + (submeter
    ? " Heat-pump electricity is shown in the readings and excluded from household pattern rules." : "");
  get("results").hidden = false;
  if (data.indoor?.length || data.heating?.length) setProfile({ data }, demo
    ? "Synthetic inputs · unflagged values grouped by the local hour at interval start."
    : "Local files · unflagged values grouped by the local hour at interval start. Each channel uses its available readings.");
  render();
}

let request = 0;
form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const current = ++request;
  const data = {};
  const inputs = new FormData(form);
  const minutes = Number(inputs.get("minutes"));
  get("status").textContent = "Reading files locally…";
  try {
    for (const [key, channel] of Object.entries(channels)) {
      const file = inputs.get(key);
      if (!file?.name) continue;
      try {
        if (file.size > 25 * 1024 * 1024) throw new Error("Choose a CSV no larger than 25 MiB.");
        data[key] = parseSeries(await file.text(), key, minutes);
      } catch (error) {
        throw new Error(`${channel.name}: ${error.message}`);
      }
    }
    if (!data.electricity && !data.gas && !data.indoor && !data.heating) {
      throw new Error("Choose a meter, indoor-temperature or activation CSV.");
    }
    if (request === current) show(data, "Loaded your files. All analysis is local to this tab.", false,
      Boolean(data.electricity && inputs.has("submeter")), inputs.has("exploratory"));
  } catch (error) {
    if (request === current) {
      state = null;
      get("results").hidden = true;
      get("status").textContent = error.message;
    }
  }
});

get("demo").addEventListener("click", () => {
  request++;
  show(demoSeries(), "Synthetic demo · 28 days of invented readings and weather.", true, false,
    form.elements.exploratory.checked);
});
for (const id of ["view-date", "range", "pattern"]) get(id).addEventListener("change", render);
for (const [id, direction] of [["previous", -1], ["next", 1]]) {
  get(id).addEventListener("click", () => {
    const start = Date.parse(get("view-date").value);
    get("view-date").value = dateLabel(Math.max(state.min, Math.min(state.max,
      start + direction * Number(get("range").value) * DAY)));
    render();
  });
}
window.addEventListener("resize", render);

const schedule = get("schedule");
let profileSource = null;
let profileRequest = 0;

function drawClock(canvas, lines, lower, upper, unit) {
  const width = canvas.clientWidth;
  if (!width) return;
  const height = 135;
  const density = window.devicePixelRatio || 1;
  canvas.width = Math.round(width * density);
  canvas.height = Math.round(height * density);
  const ctx = canvas.getContext("2d");
  ctx.scale(density, density);
  const x = (hour) => 43 + hour / 24 * (width - 55);
  const y = (value) => 105 - (value - lower) / (upper - lower) * 87;
  ctx.font = "11px system-ui";
  for (let tick = 0; tick <= 3; tick++) {
    const value = lower + tick * (upper - lower) / 3;
    ctx.fillStyle = "#d5dfd9";
    ctx.fillRect(x(0), y(value), x(24) - x(0), 1);
    ctx.fillStyle = "#43585a";
    ctx.fillText(`${Number(value.toFixed(1))}${unit}`, 0, y(value) + 4);
  }
  for (let hour = 0; hour <= 24; hour += 6) {
    ctx.textAlign = hour === 24 ? "right" : "center";
    ctx.fillText(`${String(hour).padStart(2, "0")}:00`, x(hour), 126);
  }
  for (const { key, rows, colour, step } of lines) {
    ctx.strokeStyle = colour;
    ctx.fillStyle = colour;
    ctx.lineWidth = 2;
    const positions = new Map(rows.map((row) => [row.hour, row[key]]));
    for (const [hour, value] of positions) {
      if (!Number.isFinite(value)) continue;
      ctx.fillRect(x(hour) - 1.5, y(value) - 1.5, 3, 3);
      const next = positions.get(hour + 1);
      ctx.beginPath();
      ctx.moveTo(x(hour), y(value));
      if (step) ctx.lineTo(x(hour + 1), y(value));
      if (Number.isFinite(next)) ctx.lineTo(x(hour + 1), y(next));
      ctx.stroke();
    }
  }
}

function renderClockChart(profile) {
  const chart = get("clock-chart");
  chart.hidden = false;
  const values = profile.flatMap((row) => [row.indoor_c, row.target]).filter(Number.isFinite);
  const plot = get("clock-temperature");
  plot.hidden = !values.length;
  if (values.length) {
    const min = Math.floor(Math.min(...values));
    const high = Math.max(min + 3, Math.ceil(Math.max(...values)));
    drawClock(plot, [
      { key: "indoor_c", rows: profile, colour: "#6e4183" },
      { key: "target", rows: profile, colour: "#12604c", step: true },
    ], min, high, "°C");
  }
  const heating = profile.some((row) => Number.isFinite(row.heating_percent));
  get("clock-heating").hidden = !heating;
  if (heating) drawClock(get("clock-duty"),
    [{ key: "heating_percent", rows: profile, colour: "#957420" }], 0, 100, "%");
}

function renderSchedule() {
  if (!profileSource) return;
  const inputs = new FormData(schedule);
  const options = Object.fromEntries(["dayStart", "nightStart", "dayTarget", "nightTarget"]
    .map((key) => [key, Number(inputs.get(key))]));
  schedule.elements.nightStart.setCustomValidity(options.dayStart === options.nightStart
    ? "Choose different hours for day and night." : "");
  const valid = schedule.checkValidity();
  const zone = inputs.get("zone");
  if (profileSource.data && profileSource.zone !== zone) {
    profileSource.hours = clockProfile(profileSource.data, zone);
    profileSource.zone = zone;
  }
  const profile = profileSource.hours.map((row) => ({
    ...row, target: valid ? scheduledTarget(row.hour, options) : NaN,
  }));
  renderClockChart(profile);
  const fixed = (value, digits = 1) => Number.isFinite(value) ? value.toFixed(digits) : "—";
  const body = get("clock-rows");
  body.replaceChildren();
  for (const row of profile) {
    const target = row.target;
    const tr = elements("tr", "", body);
    elements("th", `${String(row.hour).padStart(2, "0")}:00`, tr).scope = "row";
    for (const cell of [fixed(row.indoor_c), fixed(row.outdoor_c),
      Number.isFinite(row.heating_percent) ? `${fixed(row.heating_percent)}%` : "—",
      fixed(target), fixed(row.indoor_c - target), fixed(row.indoor_hours ?? row.samples)]) {
      elements("td", cell, tr);
    }
  }
}

function setProfile(source, message) {
  profileRequest++;
  profileSource = source;
  schedule.elements.zone.disabled = Boolean(source.hours);
  if (source.hours) schedule.elements.zone.value = "Europe/London";
  schedule.hidden = false;
  get("clock-details").hidden = false;
  get("profile-status").textContent = message;
  renderSchedule();
}

window.addEventListener("resize", renderSchedule);
schedule.addEventListener("submit", (event) => event.preventDefault());
schedule.addEventListener("input", renderSchedule);
get("monitored-profile").addEventListener("click", async () => {
  const current = ++profileRequest;
  get("profile-status").textContent = "Loading the monitored clock-hour profile…";
  try {
    const response = await fetch("docs/assets/monitored-heating-profile.json");
    if (!response.ok) throw new Error("Profile unavailable");
    const profile = await response.json();
    if (current === profileRequest) setProfile(profile,
      "HeatpumpMonitor system 3 · 8–21 January 2024 · 336 matched hourly observations. Outdoor temperatures are Manchester-area ERA5. Clock hours are UK local.");
  } catch {
    if (current === profileRequest) get("profile-status").textContent =
      "The monitored profile could not be loaded. Try again or use the hourly CSV instructions.";
  }
});
