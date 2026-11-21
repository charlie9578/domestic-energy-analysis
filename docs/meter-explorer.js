import { DAY, HOUR, dateLabel, dayStart, demoSeries, detectPatterns, parseSeries } from "./meter-analysis.js";

const get = (id) => document.getElementById(id);
const form = get("meter-form");
const channels = {
  electricity: { name: "Electricity", unit: "kWh", colour: "#12604c" },
  gas: { name: "Gas", unit: "kWh", colour: "#9a4b23" },
  weather: { name: "Outdoor temperature", unit: "°C", colour: "#286497" },
};
const timestamp = (stamp) => new Date(stamp).toISOString().slice(0, 19).replace("T", " ");
const hourLabel = (stamp) => timestamp(stamp).slice(11, 16);
const format = (amount) => new Intl.NumberFormat("en-GB", { maximumFractionDigits: 3 }).format(amount);
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
    const weather = key === "weather";
    const figure = elements("figure", "", target);
    const units = weather ? "°C" : "kW interval average";
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
    const values = rows.map((row) => weather ? row.amount : row.kw);
    const lo = weather ? Math.floor(Math.min(...values)) : 0;
    const hi = Math.max(lo + 1, Math.ceil(Math.max(...values)));
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
      if (weather) {
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
        ctx.fillRect(position, y(row.kw), Math.max(1, x(Math.min(end, row.end)) - position - 0.5),
          row.kw === 0 ? 1 : y(0) - y(row.kw));
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
      `${(row.end - row.start) / (HOUR / 60)} min`, `${format(row.amount)} ${channels[key].unit}`,
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
    : events.length ? `${events.length} candidate pattern${events.length === 1 ? "" : "s"} in this window.`
      : "No candidates matched in this window.";
}

function show(data, label, demo = false) {
  const meter = [...(data.gas ?? []), ...(data.electricity ?? [])];
  const min = dayStart(meter.reduce((value, row) => Math.min(value, row.start), Infinity));
  const max = dayStart(meter.reduce((value, row) => Math.max(value, row.end), -Infinity) - 1);
  state = { data, min, max, ...detectPatterns(data) };
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
  get("baseline-note").textContent = state.baselineDays < 14
    ? `Daily anomaly rules need at least 14 complete, unflagged UTC days. Found ${state.baselineDays}.`
    : `${state.baselineDays} complete, unflagged UTC days available for the daily baseline.`;
  get("status").textContent = label;
  get("results").hidden = false;
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
    if (!data.electricity && !data.gas) throw new Error("Choose at least one gas or electricity CSV.");
    if (request === current) show(data, "Loaded your files. All analysis is local to this tab.");
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
  show(demoSeries(), "Synthetic demo · 28 days of invented readings and weather.", true);
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
