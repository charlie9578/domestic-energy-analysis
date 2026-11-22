const palette = ["#526776", "#12604c", "#9a5029"];
const withUnit = (number, unit) => unit === "£" ? `£${number}` : `${number} ${unit}`;

function append(parent, tag, className, text = "") {
  const node = document.createElement(tag);
  node.className = className;
  node.textContent = text;
  parent.append(node);
  return node;
}

function frame(target, legend, maximum, unit) {
  target.replaceChildren();
  target.setAttribute("aria-hidden", "true");
  if (legend.length) {
    const key = append(target, "div", "chart-legend");
    legend.forEach((label, index) => {
      const item = append(key, "span", "chart-key", label);
      item.style.setProperty("--series", palette[index]);
    });
  }
  const axis = append(target, "div", "chart-axis");
  for (let step = 0; step <= 4; step++) {
    const tick = Number((maximum * step / 4).toPrecision(4)).toLocaleString("en-GB");
    append(axis, "span", "", step === 4 ? withUnit(tick, unit) : tick);
  }
}

export function bars(target, { labels, series, maximum, unit }) {
  frame(target, series.map((item) => item.label), maximum, unit);
  labels.forEach((label, row) => {
    const group = append(target, "div", "chart-group");
    append(group, "div", "chart-label", label);
    const stack = append(group, "div", "chart-stack");
    series.forEach((item, index) => {
      const lane = append(stack, "div", "chart-lane");
      const bar = append(lane, "span", "chart-bar");
      bar.style.width = `${100 * item.values[row] / maximum}%`;
      bar.style.backgroundColor = palette[index];
      const value = item.values[row].toLocaleString("en-GB", { maximumFractionDigits: 4 });
      bar.title = `${label} · ${item.label || "Value"} · ${withUnit(value, unit)}`;
    });
  });
}

function intervals(target, labels, estimates, range, maximum, unit) {
  frame(target, ["Estimate and 95% interval"], maximum, unit);
  labels.forEach((label, index) => {
    const group = append(target, "div", "chart-group");
    append(group, "div", "chart-label", label);
    const lane = append(group, "div", "chart-lane chart-range-lane");
    const [low, high] = range[index];
    const whisker = append(lane, "span", "chart-whisker");
    whisker.style.left = `${100 * low / maximum}%`;
    whisker.style.width = `${100 * (high - low) / maximum}%`;
    const dot = append(lane, "span", "chart-dot");
    dot.style.left = `${100 * estimates[index] / maximum}%`;
    lane.title = `${label} · ${withUnit(estimates[index], unit)} · 95% interval ${withUnit(`${low}–${high}`, unit)}`;
  });
}

for (const table of document.querySelectorAll("table[data-chart]")) {
  if (!table.tBodies[0]?.rows.length) continue;
  const config = table.dataset;
  const details = table.closest("details");
  const rows = [...table.tBodies[0].rows];
  const labels = rows.map((row) => row.cells[0].textContent.trim());
  const maximum = Number(config.max);
  const unit = config.unit;
  const target = document.createElement("div");
  target.className = "research-chart";
  details.before(target);
  if (config.chart === "intervals") {
    const estimates = rows.map((row) => Number(row.cells[1].textContent));
    const ranges = rows.map((row) => row.cells[2].textContent.trim().split("–").map(Number));
    intervals(target, labels, estimates, ranges, maximum, unit);
  } else {
    const columns = config.columns.split(",").map(Number);
    const series = columns.map((column) => ({
      label: table.tHead.rows[0].cells[column].textContent.trim(),
      values: rows.map((row) => Number.parseFloat(row.cells[column].textContent)),
    }));
    bars(target, { labels, series, maximum, unit });
  }
}
