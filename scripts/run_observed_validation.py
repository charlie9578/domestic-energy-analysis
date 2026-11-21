"""Run measured heat and smart-meter validation with separate counterfactuals."""
import argparse
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from domestic_energy.core import price_meter_rows, timestamp_utc
from domestic_energy.data import read_csv, write_csv, write_json
from domestic_energy.household_cohort import opsd_halfhours
from domestic_energy.economics import investment_appraisal
from domestic_energy.heating_controls import House, Settings, simulate_heating
from domestic_energy.pipeline import join_daily_meter_weather
from domestic_energy.real_meter import expected_halfhourly_profile
from domestic_energy.thermal_validation import UK, _fit, monitored_days, validate_signature

ROOT = Path(__file__).resolve().parents[1]
SYSTEMS = (3, 4, 8, 9, 11)
START = date(2023, 1, 1)
SPLIT = date(2024, 1, 1)
END = date(2025, 1, 1)


def sha256(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def daily_era5(path, zone):
    temperatures = {}
    seen = set()
    for row in read_csv(path):
        stamp = timestamp_utc(row["start_utc"])
        if stamp in seen or any((stamp.minute, stamp.second, stamp.microsecond)):
            raise ValueError("Expected unique aligned ERA5 hourly timestamps")
        seen.add(stamp)
        day = stamp.astimezone(zone).date()
        temperatures.setdefault(day, []).append(float(row["temperature_c"]))
    return [{"date": str(day), "temperature_c": mean(values)}
            for day, values in sorted(temperatures.items())
            if len(values) == civil_hours(day, zone)]


def civil_hours(day, zone):
    start = datetime.combine(day, time(), zone).astimezone(timezone.utc)
    end = datetime.combine(day + timedelta(days=1), time(), zone).astimezone(timezone.utc)
    return (end - start).total_seconds() / 3600


def daily_experiment(meter, weather, cutoff, zone):
    joined = join_daily_meter_weather(meter, weather, min_coverage=1, timezone_name=zone.key)
    train = [row for row in joined["daily_rows"] if row["date"] < cutoff]
    test = [row for row in joined["daily_rows"] if row["date"] >= cutoff]
    if len(train) < 14 or len(test) < 5:
        raise ValueError("Insufficient weather-matched complete meter days")

    def hours(day):
        return civil_hours(date.fromisoformat(day), zone)

    points = [(row["temperature_c"], row["consumption_kwh"] / hours(row["date"]))
              for row in train]
    intercept, slope = _fit(points)
    baseline = mean(power for _, power in points)
    mae = {}
    for name, predict in (("era5_temperature", lambda t: max(0, intercept + slope * t)),
                          ("mean_power", lambda t: baseline)):
        mae[name] = round(mean(
            abs(row["consumption_kwh"] - predict(row["temperature_c"]) * hours(row["date"]))
            for row in test), 4)

    return {
        "split_local_date": cutoff, "train_days": len(train), "test_days": len(test),
        "exclusion_counts": dict(Counter(row["reason"] for row in joined["excluded_dates"])),
        "measured_import_holdout_daily_mae_kwh": mae,
    }, {row["date"] for row in test}


def london_meter(weather_path):
    meter = read_csv(ROOT / "examples/real_lcl_mac000002_2012_part.csv")
    cutoff = expected_halfhourly_profile(meter)["holdout_daily"][0]["date"]
    result, heldout_dates = daily_experiment(meter, daily_era5(weather_path, UK), cutoff, UK)
    intervals = [row for row in meter
                 if timestamp_utc(row["start_utc"]).astimezone(UK).date().isoformat()
                 in heldout_dates]
    prices = {}
    for name, day_rate, night_rate in (("flat", 27, 27), ("night_discount", 35, 9)):
        rates = [{"start_utc": row["start_utc"], "unit_rate_p_per_kwh":
                  night_rate if timestamp_utc(row["start_utc"]).astimezone(UK).hour < 7
                  else day_rate} for row in intervals]
        prices[name] = price_meter_rows(intervals, rates, standing_p_per_day=55)
    return {**result, "hourly_era5_sha256": sha256(weather_path),
            "hypothetical_tariff_replay_on_unchanged_import": prices}


def konstanz_cohort(raw, derived):
    zone = ZoneInfo("Europe/Berlin")
    start = datetime(2016, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    end = datetime(2017, 1, 1, tzinfo=zone).astimezone(timezone.utc)
    homes = ("residential1", "residential2", "residential4", "residential5", "residential6")
    meter_path, weather_path = raw / "opsd_15min.csv", raw / "konstanz_era5.csv"
    weather = daily_era5(weather_path, zone)
    with meter_path.open(newline="", encoding="utf-8-sig") as file:
        cohort = opsd_halfhours(file, homes, start=start, end=end)
    expected = (end - start) // timedelta(minutes=30)
    results = {}
    for home in homes:
        rows = cohort.get(home, [])
        if len(rows) != expected:
            raise ValueError(f"{home}: expected {expected} half-hours, got {len(rows)}")
        measured = [row for row in rows if not row["publisher_interpolated"]]
        experiment, _ = daily_experiment(measured, weather, "2016-10-01", zone)
        write_csv(derived / f"opsd_2016_{home}.csv", rows, list(rows[0]))
        results[home] = {
            "half_hours": len(rows), "publisher_interpolated_half_hours": len(rows) - len(measured),
            "publisher_series_import_kwh": round(sum(row["consumption_kwh"] for row in rows), 3),
            "weather_validation_unflagged_only": experiment,
        }
    return {
        "timezone": zone.key,
        "first_start_utc": start.isoformat(), "end_exclusive_utc": end.isoformat(),
        "opsd_quarter_hour_csv_sha256": sha256(meter_path),
        "hourly_era5_sha256": sha256(weather_path), "households": results,
    }


def simulate_controls(days, validation, tariffs, agile_rates):
    # A half-hourly grid driven by each day's measured mean, with intraday variation omitted.
    window = [row for row in days if date(2024, 1, 8) <= row["date"] < date(2024, 1, 22)]
    if len(window) != 14:
        return {"status": "incomplete prespecified simulation weather window"}
    weather = []
    for row in window:
        start = datetime.combine(row["date"], time(), UK).astimezone(timezone.utc)
        for slot in range(int(row["hours"] * 2)):
            weather.append({"start_utc": (start + timedelta(minutes=30 * slot)).isoformat(),
                            "temperature_c": row["outdoor_c"]})
    signature = validation["signatures"]["indoor_outdoor"]
    low, high = signature["training_slope_week_bootstrap_95"]
    if low <= 0:
        return {"status": "training slope interval includes nonpositive values"}
    runs = []
    slopes = [low, signature["slope_w_per_k"], high]
    agile_name = "Published Octopus Agile AGILE-23-12-06 region G, energy only"
    tariff_cases = [*tariffs, {"name": agile_name, "flat_p_per_kwh": 27, "gas_p_per_kwh": 8}]
    for tariff in tariff_cases:
        reprice = tariff["name"] == agile_name
        for strategy, setback in (("constant", 20), ("setback", 17), ("setback", 18),
                                  ("setback", 19), ("preheat", 17)):
            candidates = []
            for slope in slopes:
                for capacity in (5, 10, 16):
                    result = simulate_heating(
                        weather, strategy=strategy, heat_source="heatpump", tariff=tariff,
                        house=House(heat_loss_w_per_k=slope, thermal_capacity_kwh_per_k=capacity,
                                    initial_indoor_c=20),
                        settings=Settings(setback_c=setback), record_intervals=reprice,
                    )
                    if reprice:
                        load = [{"start_utc": step["start_utc"], "duration_minutes": 30,
                                 "consumption_kwh": step["heating_electricity_kwh"]}
                                for step in result.pop("intervals")]
                        result["heating_only_cost_gbp"] = price_meter_rows(
                            load, agile_rates)["variable_cost_gbp"]
                    candidates.append(result)
            costs = [row["heating_only_cost_gbp"] for row in candidates]
            runs.append({"tariff": tariff["name"], "strategy": strategy,
                         "setback_c": setback if strategy == "setback" else None,
                         "simulated_heating_cost_range_gbp": [min(costs), max(costs)],
                         "comfort_feasible_cases": sum(row["comfort_feasible"] for row in candidates),
                         "cases": len(candidates)})
    winners = {}
    for tariff in tariff_cases:
        eligible = [row for row in runs if row["tariff"] == tariff["name"]
                    and row["comfort_feasible_cases"] == row["cases"]]
        winners[tariff["name"]] = min(
            eligible, key=lambda row: row["simulated_heating_cost_range_gbp"][1], default=None)
    return {"status": "simulated", "runs": runs, "lowest_worst_case_cost_by_tariff": winners}


def retrofit_screen(signature):
    # A 20% envelope improvement under assumed annual degree-days and SPF.
    low, high = signature["training_slope_week_bootstrap_95"]
    if low <= 0:
        return None
    cases = []
    for slope in (low, signature["slope_w_per_k"], high):
        for degree_days in (1800, 2400, 3000):
            for spf in (2.5, 3.5, 4.5):
                saved_heat = slope / 1000 * .20 * degree_days * 24
                annual = saved_heat / spf * .27
                cases.append(investment_appraisal(annual, capex_gbp=4000, lifetime_years=25))
    return {"cases": len(cases), "annual_net_saving_gbp_range": [
        min(c["year1_net_saving_gbp"] for c in cases), max(c["year1_net_saving_gbp"] for c in cases)],
        "npv_gbp_range": [min(c["npv_gbp"] for c in cases), max(c["npv_gbp"] for c in cases)],
        "positive_npv_cases": sum(c["npv_gbp"] > 0 for c in cases)}


def run(raw, derived):
    metadata_path = raw / "hpm_systems.json"
    metadata = {row["id"]: row for row in json.loads(metadata_path.read_text())}
    tariffs = json.loads((ROOT / "examples/hypothetical_heating_tariffs.json").read_text())
    agile_path = raw / "agile_jan2024.csv"
    agile_rates = read_csv(agile_path)
    report = {
        "measured_sources": {"heat_pump": "HeatpumpMonitor public daily CSV",
                             "equipment_labels": "HeatpumpMonitor public system metadata",
                             "london_meter": "UKPN Low Carbon London MAC000002 fixture"},
        "reanalysis_source": "Open-Meteo hourly ERA5, city-centre regional proxies",
        "hpm_metadata_sha256": sha256(metadata_path),
        "hpm_window_local": {"start_inclusive": str(START), "end_exclusive": str(END)},
        "uncertainty": {"method": "separate calendar-week percentile bootstraps",
                        "seed": 26, "replicates": 1000},
        "simulations": {"labels": "Counterfactual scenario costs and comfort",
                        "agile_unit_rates_sha256": sha256(agile_path),
                        "retrofit_assumptions": {"capex_gbp": 4000, "lifetime_years": 25,
                            "heat_loss_reduction": .20, "degree_days": [1800, 2400, 3000],
                            "spf": [2.5, 3.5, 4.5], "electricity_p": 27,
                            "real_discount_rate": .035},
                        "thermostat_assumptions": {"thermal_capacity_kwh_per_k": [5, 10, 16],
                            "initial_indoor_c": 20, "max_heat_kw": 9, "internal_gains_kw": .35,
                            "weather": "observed daily means repeated half-hourly, January 8–21 2024",
                            "cop_at_7c": 3.3, "cop_slope_per_outdoor_c": .055},
                        "systems": {}},
        "heat_pumps": {},
    }
    for system in SYSTEMS:
        path = raw / f"system_{system}.csv"
        days, excluded = monitored_days(read_csv(path), start=START, end=END)
        label = metadata[system]
        result = {"daily_csv_sha256": sha256(path), "days_excluded": excluded,
                  "reported_equipment_type": label["hp_type"], "reported_hybrid": label["hp_hybrid"],
                  "reported_space_heat_control_type": label["space_heat_control_type"]}
        report["heat_pumps"][system] = result
        try:
            validation = validate_signature(days, split=SPLIT)
        except ValueError as error:
            result["validation_excluded_reason"] = str(error)
            continue
        result["validation"] = validation
        thermostat = {"status": "air-source COP assumptions do not cover this equipment"}
        if label["hp_type"] == "Air Source" and not label["hp_hybrid"]:
            thermostat = simulate_controls(days, validation, tariffs, agile_rates)
        report["simulations"]["systems"][system] = {
            "thermostat": thermostat,
            "retrofit": retrofit_screen(validation["signatures"]["indoor_outdoor"]),
        }
    report["london"] = london_meter(raw / "london_era5.csv")
    report["konstanz_cohort"] = konstanz_cohort(raw, derived)
    return report


def export_cohort_archive(path, raw, derived, households):
    files = [derived / f"opsd_2016_{home}.csv" for home in households]
    files += [raw / "konstanz_era5.csv", ROOT / "research/OPSD_2016_ATTRIBUTION.txt"]
    path.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(path, "w") as archive:
        for file in files:
            archive.writestr(ZipInfo(file.name), file.read_bytes(), compress_type=ZIP_DEFLATED)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/observed_validation.json")
    parser.add_argument("--derived", type=Path, default=ROOT / "data/derived")
    parser.add_argument("--cohort-zip", type=Path, help="Package meter, ERA5 and attribution files")
    args = parser.parse_args()
    report = run(args.raw, args.derived)
    write_json(args.out, report)
    if args.cohort_zip:
        export_cohort_archive(args.cohort_zip, args.raw, args.derived,
                              report["konstanz_cohort"]["households"])


if __name__ == "__main__":
    main()
