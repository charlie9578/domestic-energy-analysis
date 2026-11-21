"""Public API adapters and CSV helpers; no user credentials or private datasets needed."""
from __future__ import annotations

import csv
import io
import json
import time
from datetime import timedelta
from pathlib import Path
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from .core import timestamp_utc

APP_AGENT = 'domestic-energy-analysis-research/0.1 (public data; GitHub charlie9578/domestic-energy-analysis)'
APPROVED_HOSTS = {'heatpumpmonitor.org', 'api.octopus.energy', 'archive-api.open-meteo.com'}


def get_text(url: str, *, delay: float = 0, attempts: int = 3, timeout: int = 30) -> str:
    """Bounded retry for approved HTTPS APIs; do not follow redirects to other hosts."""
    from urllib.error import HTTPError, URLError
    host = urlparse(url).hostname
    if urlparse(url).scheme != 'https' or host not in APPROVED_HOSTS:
        raise ValueError(f'Unapproved public data URL: {url}')
    if delay:
        time.sleep(delay)
    last = None
    for attempt in range(attempts):
        try:
            with urlopen(Request(url, headers={'User-Agent': APP_AGENT, 'Accept': 'application/json, text/csv'}),
                         timeout=timeout) as response:
                if urlparse(response.url).hostname not in APPROVED_HOSTS:
                    raise ValueError('Unexpected redirect host')
                return response.read(25_000_000).decode('utf-8-sig')
        except (HTTPError, URLError, TimeoutError) as exc:
            last = exc
            if isinstance(exc, HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise
            if attempt < attempts - 1:
                time.sleep(2 ** attempt)
    raise RuntimeError(f'Public API unavailable: {last}')


def read_csv(path: str | Path) -> list[dict]:
    with open(path, newline='', encoding='utf-8-sig') as handle:
        return list(csv.DictReader(handle))


def write_csv(path: str | Path, rows: list[dict], fieldnames: list[str]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open('w', newline='', encoding='utf-8') as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def write_json(path: str | Path, data: dict) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, sort_keys=True) + '\n', encoding='utf-8')


def fetch_heatpump_daily(system_id: int, *, delay: float = 0.3) -> list[dict]:
    if not 1 <= system_id <= 1_000_000:
        raise ValueError('Invalid public system ID')
    csv_url = f'https://heatpumpmonitor.org/system/stats/daily?id={system_id}'
    return list(csv.DictReader(io.StringIO(get_text(csv_url, delay=delay))))


def fetch_octopus_unit_rates(product: str, tariff: str, start: str, end: str,
                             *, max_pages: int = 30) -> list[dict]:
    """Expand public rate validity periods into exact UTC 30-minute slots.

    API response `value_inc_vat` is in p/kWh; can be negative. Never guess a rate.
    """
    from urllib.parse import quote
    start_dt, end_dt = timestamp_utc(start), timestamp_utc(end)
    if end_dt <= start_dt or (end_dt - start_dt).days > 100:
        raise ValueError('Request must be >0 and <=100 days; chunk longer analyses')
    if start_dt.minute not in (0, 30) or end_dt.minute not in (0, 30) or start_dt.second or end_dt.second:
        raise ValueError('Use exact 30-minute UTC boundaries')
    for val in (product, tariff):
        if not val or not all(c.isalnum() or c in '-_' for c in val):
            raise ValueError('Invalid product or tariff code')
    base = ('https://api.octopus.energy/v1/products/' + quote(product) +
            '/electricity-tariffs/' + quote(tariff) + '/standard-unit-rates/')
    url = base + '?' + urlencode({'period_from': start_dt.isoformat(),
                                  'period_to': end_dt.isoformat(), 'page_size': 250})
    raw_rates = []
    for _ in range(max_pages):
        response = json.loads(get_text(url))
        raw_rates.extend(response.get('results') or [])
        url = response.get('next')
        if not url:
            break
        if not url.startswith(base):
            raise ValueError('Unexpected pagination URL')
    else:
        raise RuntimeError('Exceeded page limit: shorten the requested window')
    result = {}
    for item in raw_rates:
        valid_from = timestamp_utc(item['valid_from'])
        valid_to = timestamp_utc(item['valid_to']) if item['valid_to'] else end_dt
        start_slot, end_slot = max(start_dt, valid_from), min(end_dt, valid_to)
        if start_slot.minute not in (0, 30) or end_slot.minute not in (0, 30):
            raise ValueError('Tariff boundary not on a 30-minute slot')
        cursor = start_slot
        while cursor < end_slot:
            key = cursor.isoformat()
            value = float(item['value_inc_vat'])
            if key in result and result[key] != value:
                raise ValueError(f'Conflicting tariff rates for {key}')
            result[key] = value
            cursor += timedelta(minutes=30)
    slots = []
    cursor = start_dt
    while cursor < end_dt:
        key = cursor.isoformat()
        if key not in result:
            raise ValueError(f'Missing public unit rate at {key}')
        slots.append({'start_utc': key, 'unit_rate_p_per_kwh': result[key]})
        cursor += timedelta(minutes=30)
    return slots


def fetch_open_meteo_daily(latitude: float, longitude: float, start_date: str, end_date: str,
                          *, timezone_name: str = 'Europe/London') -> list[dict]:
    """Historical reanalysis local-day weather, used for weather-aware models.

    Open-Meteo API conditions and model/licence must be checked for intended use.
    Location is sent to the public service. Max 366 days per call (chunk longer).
    """
    from datetime import date
    from zoneinfo import ZoneInfo
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('Invalid coordinates')
    ZoneInfo(timezone_name)
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if end < start or (end - start).days > 365:
        raise ValueError('Request 1 to 366 days at a time')
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urlencode({
        'latitude': latitude, 'longitude': longitude,
        'start_date': str(start), 'end_date': str(end),
        'daily': 'temperature_2m_mean,temperature_2m_min,temperature_2m_max,precipitation_sum',
        'timezone': timezone_name, 'models': 'era5',
    })
    raw = json.loads(get_text(url))
    daily = raw.get('daily') or {}
    dates = daily.get('time') or []
    temp = daily.get('temperature_2m_mean') or []
    temp_min = daily.get('temperature_2m_min') or []
    temp_max = daily.get('temperature_2m_max') or []
    precipitation = daily.get('precipitation_sum') or []
    if not (len(dates) == len(temp) == len(temp_min) == len(temp_max) == len(precipitation) == (end-start).days+1):
        raise ValueError('Weather response missing days/variables: do not fill with zero')
    rows = []
    for d, avg, low, high, rain in zip(dates, temp, temp_min, temp_max, precipitation):
        if any(x is None for x in (avg, low, high, rain)):
            raise ValueError(f'Missing Open-Meteo weather value for {d}')
        rows.append({'date': d, 'temperature_c': float(avg),
                     'temperature_min_c': float(low), 'temperature_max_c': float(high),
                     'precipitation_mm': float(rain)})
    return rows


def fetch_open_meteo_hourly(latitude: float, longitude: float, start_date: str,
                           end_date: str) -> list[dict]:
    """ERA5 UTC hours with instantaneous temperature/wind and forward interval values."""
    from datetime import date, datetime, time
    from math import isfinite

    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
        raise ValueError('Invalid coordinates')
    start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
    if end < start or (end - start).days > 31:
        raise ValueError('Request 1 to 32 calendar days of hourly data')

    # Open-Meteo reports precipitation and shortwave for the preceding hour.
    # Fetch the following midnight so the last requested hour has its end value.
    variables = {
        'temperature_2m': ('temperature_c', '°C', 0),
        'shortwave_radiation': ('shortwave_w_m2', 'W/m²', 1),
        'precipitation': ('precipitation_mm', 'mm', 1),
        'wind_speed_10m': ('wind_speed_m_s', 'm/s', 0),
    }
    url = 'https://archive-api.open-meteo.com/v1/archive?' + urlencode({
        'latitude': latitude, 'longitude': longitude,
        'start_date': str(start), 'end_date': str(end + timedelta(days=1)),
        'hourly': ','.join(variables), 'wind_speed_unit': 'ms',
        'timezone': 'UTC', 'models': 'era5',
    })
    payload = json.loads(get_text(url))
    data = payload.get('hourly') or {}
    units = payload.get('hourly_units') or {}
    count = ((end - start).days + 1) * 24
    midnight = datetime.combine(start, time())
    expected = [(midnight + timedelta(hours=i)).isoformat(timespec='minutes')
                for i in range(count + 24)]
    if data.get('time') != expected:
        raise ValueError('Hourly weather timestamps are incomplete, duplicated or out of order')
    for variable, (_, unit, _) in variables.items():
        series = data.get(variable)
        if units.get(variable) != unit or not isinstance(series, list) or len(series) != len(expected):
            raise ValueError(f'Malformed hourly weather variable or units: {variable}')

    rows = []
    for index, stamp in enumerate(expected[:count]):
        row = {'start_utc': stamp + '+00:00'}
        for variable, (column, _, offset) in variables.items():
            value = data[variable][index + offset]
            if (type(value) not in (int, float) or not isfinite(value)
                    or (variable != 'temperature_2m' and value < 0)):
                raise ValueError(f'Missing or invalid hourly weather value: {variable} for {stamp} UTC')
            row[column] = float(value)
        rows.append(row)
    return rows
