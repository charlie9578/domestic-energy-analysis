const MINUTE = 60_000;
export const HOUR = 60 * MINUTE;
export const DAY = 24 * HOUR;
export const dayStart = (stamp) => Math.floor(stamp / DAY) * DAY;
export const dateLabel = (stamp) => new Date(stamp).toISOString().slice(0, 10);

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const middle = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2;
};

function fields(line) {
  const items = line.match(/(?:^|,)(?:"(?:[^"]|"")*"|[^",]*)(?=,|$)/g) ?? [];
  if (items.join("") !== line) throw new Error("Malformed CSV row.");
  return items.map((item) => {
    const cell = item.replace(/^,/, "");
    return cell.startsWith('"') ? cell.slice(1, -1).replaceAll('""', '"') : cell.trim();
  });
}

export function parseSeries(text, kind, defaultMinutes) {
  const lines = text.replace(/^\uFEFF/, "").trim().split(/\r?\n/);
  const header = fields(lines.shift());
  const weather = kind === "weather";
  const temperature = weather || kind === "indoor";
  const heating = kind === "heating";
  const valueColumn = { weather: "temperature_c", indoor: "indoor_temperature_c",
    heating: "heating_fraction" }[kind] ?? "consumption_kwh";
  const keys = ["start_utc", valueColumn];
  if (new Set(header).size !== header.length || keys.some((key) => !header.includes(key))) {
    throw new Error(`Expected unique columns including ${keys.join(", ")}.`);
  }
  const index = Object.fromEntries(header.map((key, position) => [key, position]));
  const records = [];
  const seen = new Set();
  for (const [offset, line] of lines.entries()) {
    if (!line.trim()) continue;
    const columns = fields(line);
    const time = columns[index.start_utc];
    const value = columns[index[valueColumn]];
    const stamp = Date.parse(time);
    const minutes = weather ? 60 : Number(columns[index.duration_minutes] || defaultMinutes);
    const date = time?.slice(0, 10);
    const calendarStamp = Date.parse(date);
    const validDate = Number.isFinite(calendarStamp) && dateLabel(calendarStamp) === date;
    if (columns.length !== header.length || !validDate ||
        !/^\d{4}-\d\d-\d\dT(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)$/i.test(time) ||
        !Number.isFinite(stamp) || !Number.isInteger(minutes) || minutes < 1 || minutes > 1440 ||
        (weather && stamp % HOUR !== 0) || seen.has(stamp)) {
      throw new Error(`Row ${offset + 2}: invalid timestamp, duration, duplicate or column count.`);
    }
    seen.add(stamp);
    if (value === "") continue;
    const amount = Number(value);
    const [low, high] = temperature ? [-90, 65] : [0, heating ? 1 : Infinity];
    if (!Number.isFinite(amount) || amount < low || amount > high) {
      throw new Error(`Row ${offset + 2}: invalid ${valueColumn}.`);
    }
    const flag = columns[index.publisher_interpolated] ?? "";
    if (!["", "0", "1"].includes(flag)) throw new Error(`Row ${offset + 2}: interpolation flag must be 0 or 1.`);
    const end = stamp + minutes * MINUTE;
    const kw = temperature || heating ? null : amount / (minutes / 60);
    if (kw !== null && !Number.isFinite(kw)) throw new Error(`Row ${offset + 2}: invalid power.`);
    records.push({ start: stamp, end, amount, kw, flagged: flag === "1" });
  }
  records.sort((a, b) => a.start - b.start);
  if (!records.length) throw new Error("The file contains no usable values.");
  if (records.some((row, i) => i > 0 && row.start < records[i - 1].end)) {
    throw new Error("Intervals overlap. Check timestamps and the default duration.");
  }
  return records;
}

function runs(rows, predicate, accept) {
  let block = [];
  for (const row of rows) {
    const included = predicate(row);
    if (block.length && (!included || block.at(-1).end !== row.start)) {
      accept(block);
      block = [];
    }
    if (included) block.push(row);
  }
  if (block.length) accept(block);
}

function completeDays(rows) {
  const days = new Map();
  for (const row of rows) {
    if (row.flagged) continue;
    const day = dayStart(row.start);
    if (row.end > day + DAY) continue;
    const total = days.get(day) ?? { coverage: 0, energy: 0 };
    total.coverage += row.end - row.start;
    total.energy += row.amount;
    days.set(day, total);
  }
  return new Map([...days].filter(([, totals]) => totals.coverage === DAY)
    .map(([day, totals]) => [day, totals.energy]));
}

export function detectPatterns({ gas = [], electricity = [], weather = [], indoor = [], heating = [], exploratory = true }) {
  const temperatures = new Map(weather.filter((row) => !row.flagged)
    .map((row) => [row.start, row.amount]));
  const cold = (row) => {
    for (let hour = Math.floor(row.start / HOUR) * HOUR; hour < row.end; hour += HOUR) {
      const temperature = temperatures.get(hour);
      if (temperature === undefined || temperature > 15) return false;
    }
    return true;
  };
  const events = [];
  const add = (type, block, evidence) => events.push({
    type, start: block[0].start, end: block.at(-1).end, evidence,
  });
  const span = (rows) => rows.at(-1).end - rows[0].start;

  // A supplied activation log takes precedence wherever it covers the full interval.
  const heatingCoverage = heating.filter((row) => !row.flagged);
  function logged(row) {
    let low = 0;
    let high = heatingCoverage.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if (heatingCoverage[middle].end <= row.start) low = middle + 1;
      else high = middle;
    }
    let covered = row.start;
    for (let i = low; i < heatingCoverage.length && covered < row.end; i++) {
      if (heatingCoverage[i].start > covered) return false;
      covered = heatingCoverage[i].end;
    }
    return covered >= row.end;
  }
  const roomByTime = new Map(indoor.filter((row) => !row.flagged).map((row) => [row.start, row.amount]));
  runs(heating, (row) => !row.flagged && row.amount > 0, (block) => {
    const start = block[0].start, end = block.at(-1).end;
    const duty = block.reduce((sum, row) => sum + row.amount * (row.end - row.start), 0);
    const before = roomByTime.get(start);
    const after = roomByTime.get(end);
    const room = before !== undefined && after !== undefined
      ? ` Indoor readings at the window boundaries were ${before.toFixed(1)}°C and ${after.toFixed(1)}°C.` : "";
    add("Recorded heating activation", block,
      `Positive heating signal in each interval, equivalent to ${Math.round(duty / MINUTE)} active minutes in total. Exact switch times may be unavailable.${room}`);
  });
  if (!exploratory) return { events, baselineDays: null };
  runs(gas, (row) => !row.flagged && row.kw >= 2 && !logged(row) && cold(row), (block) => {
    if (block.length >= 2 && span(block) >= 90 * MINUTE) {
      add("Space-heating candidate", block, "Gas averaged at least 2 kW for 90+ minutes with matching outdoor temperatures at or below 15°C.");
    }
  });
  runs(gas, (row) => !row.flagged && row.kw >= 2 && !logged(row), (block) => {
    if (!temperatures.size && block.length >= 2 && span(block) >= 90 * MINUTE) {
      add("Sustained gas use", block, "Gas averaged at least 2 kW for 90+ minutes. Add matched outdoor temperature to check for a space-heating pattern.");
    } else if (span(block) <= 45 * MINUTE) {
      add("Short gas burst", block, "Could be hot water (including a shower), cooking or boiler cycling. The meter cannot distinguish them.");
    }
  });
  runs(electricity, (row) => !row.flagged && row.kw >= 2.5, (block) => {
    const typical = median(block.map((row) => row.kw));
    if (block.length >= 2 && span(block) >= HOUR &&
        block.every((row) => Math.abs(row.kw - typical) <= typical * 0.2)) {
      add("EV-like electrical load", block, "A sustained, fairly level load of 2.5 kW or more. Storage heaters, batteries and other equipment can look similar.");
    } else if (span(block) <= 45 * MINUTE) {
      add("Short electrical burst", block, "A brief load of 2.5 kW or more. Cooking, electric hot water or another appliance are possible.");
    }
  });

  const electricDays = completeDays(electricity);
  const gasDays = completeDays(gas);
  const matched = electricity.length && gas.length;
  const primary = electricity.length ? electricDays : gasDays;
  const eligible = [...primary].filter(([day]) => !matched || gasDays.has(day));
  const dailyBaseline = median(eligible.map(([, kwh]) => kwh));
  const gasBaseline = matched ? median(eligible.map(([day]) => gasDays.get(day))) : 0;
  if (eligible.length >= 14 && dailyBaseline > 0) {
    const daily = eligible.map(([start, kwh]) => ({ start, end: start + DAY, kwh }));
    runs(daily, (row) => row.kwh < dailyBaseline * 0.55 &&
      (!gasBaseline || gasDays.get(row.start) < gasBaseline * 0.65), (block) => {
      if (block.length >= 3) {
        add("Sustained low use", block, "Three or more complete days below 55% of usual daily use. Where typical gas use is positive, both fuels must be low. An absence or a change in routine could explain it.");
      }
    });
    for (const row of daily.filter((day) => day.kwh > dailyBaseline * 1.8)) {
      add("Unusually high daily use", [row], "Daily use exceeded 180% of the median across eligible days.");
    }
  }
  const weatherDays = new Map();
  for (const [day] of electricDays) {
    const hours = Array.from({ length: 24 }, (_, i) => temperatures.get(day + i * HOUR));
    if (hours.every((value) => value !== undefined)) {
      weatherDays.set(day, hours.reduce((sum, value) => sum + value, 0) / 24);
    }
  }
  const mild = [...weatherDays].filter(([, temperature]) => temperature >= 15)
    .map(([day]) => electricDays.get(day));
  if (mild.length >= 7) {
    const reference = median(mild);
    for (const [day, temperature] of weatherDays) {
      const energy = electricDays.get(day);
      if (!logged({ start: day, end: day + DAY }) && temperature <= 10 && energy > reference * 1.5 && energy - reference >= 2) {
        add("Cold-weather electrical demand", [{ start: day, end: day + DAY }],
          "On a day averaging 10°C or colder, electricity exceeded the median of at least seven 15°C+ days by 50% and at least 2 kWh. Electric heating is one possible cause.");
      }
    }
  }
  return { events: events.sort((a, b) => a.start - b.start), baselineDays: eligible.length };
}

export function demoSeries() {
  const start = Date.UTC(2025, 0, 1);
  const data = { gas: [], electricity: [], weather: [], indoor: [] };
  for (let day = 0; day < 28; day++) {
    for (let slot = 0; slot < 48; slot++) {
      const stamp = start + day * DAY + slot * HOUR / 2;
      const away = day >= 5 && day <= 8;
      const gas = away ? 0 : slot >= 12 && slot <= 16 ? 2 : slot === 37 ? 1.2 : 0;
      const electricity = away ? 0.08 : day % 4 === 0 && slot < 6 ? 3.4 :
        slot === 36 ? 1.5 : (slot >= 32 && slot <= 42 ? 0.35 : 0.18);
      for (const [fuel, amount] of Object.entries({ gas, electricity })) {
        data[fuel].push({ start: stamp, end: stamp + HOUR / 2, amount, kw: amount * 2, flagged: false });
      }
      if (slot % 2 === 0) {
        data.weather.push({ start: stamp, end: stamp + HOUR,
          amount: 5 + 3 * Math.sin(slot / 48 * Math.PI * 2 - 2), flagged: false });
        data.indoor.push({ start: stamp, end: stamp + HOUR,
          amount: (away ? 16.5 : 19) + Math.sin(slot / 48 * Math.PI * 2 - 2), flagged: false });
      }
    }
  }
  return data;
}

export function clockProfile(data, zone) {
  const clock = new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", hourCycle: "h23" });
  const bins = Array.from({ length: 24 }, (_, hour) => ({ hour, amounts: {}, counts: {} }));
  for (const [channel, key, scale] of [
    ["indoor", "indoor_c", 1], ["weather", "outdoor_c", 1], ["heating", "heating_percent", 100],
  ]) {
    for (const row of data[channel] ?? []) {
      if (row.flagged || row.end - row.start > HOUR) continue;
      const bin = bins[Number(clock.format(row.start))];
      const minutes = (row.end - row.start) / MINUTE;
      bin.amounts[key] = (bin.amounts[key] ?? 0) + row.amount * minutes * scale;
      bin.counts[key] = (bin.counts[key] ?? 0) + minutes;
    }
  }
  return bins.map(({ hour, amounts, counts }) => ({
    hour, indoor_hours: (counts.indoor_c ?? 0) / 60,
    ...Object.fromEntries(Object.entries(amounts).map(([key, value]) => [key, value / counts[key]])),
  }));
}

export function scheduledTarget(hour, { dayStart, nightStart, dayTarget, nightTarget }) {
  const daytime = dayStart < nightStart ? hour >= dayStart && hour < nightStart
    : hour >= dayStart || hour < nightStart;
  return daytime ? dayTarget : nightTarget;
}
