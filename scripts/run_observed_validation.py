"""Run measured heat and smart-meter validation with separate counterfactuals."""
import argparse
import csv
import gzip
import hashlib
import json
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean

from domestic_energy.core import price_meter_rows, timestamp_utc
from domestic_energy.data import read_csv, write_json
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


def london_meter(station_path):
    meter = read_csv(ROOT / "examples/real_lcl_mac000002_2012_part.csv")
    with gzip.open(station_path, "rt", newline="") as source:
        weather = [{"date": row[0], "temperature_c": row[1]} for row in csv.reader(source)
                   if "2012-10-12" <= row[0] <= "2012-11-24" and row[1]]
    joined = join_daily_meter_weather(meter, weather, min_coverage=1)
    # Use the same calendar cutoff as the existing half-hourly experiment.
    profile = expected_halfhourly_profile(meter)
    cutoff = profile["holdout_daily"][0]["date"]
    train = [row for row in joined["daily_rows"] if row["date"] < cutoff]
    test = [row for row in joined["daily_rows"] if row["date"] >= cutoff]
    if len(train) < 14 or len(test) < 5:
        raise ValueError("Insufficient weather-matched London days")
    # DST-normalize daily energy in the fit, then restore the physical holdout length.
    def hours(day):
        local_day = date.fromisoformat(day)
        start = datetime.combine(local_day, time(), UK).astimezone(timezone.utc)
        end = datetime.combine(local_day + timedelta(days=1), time(), UK).astimezone(timezone.utc)
        return (end - start).total_seconds() / 3600

    points = [(row["temperature_c"], row["consumption_kwh"] / hours(row["date"]))
              for row in train]
    intercept, slope = _fit(points)
    baseline = mean(power for _, power in points)
    mae = {}
    for name, predict in (("station_weather", lambda t: max(0, intercept + slope * t)),
                          ("mean_power", lambda t: baseline)):
        mae[name] = round(mean(
            abs(row["consumption_kwh"] - predict(row["temperature_c"]) * hours(row["date"]))
            for row in test), 4)

    heldout_dates = {row["date"] for row in test}
    intervals = [row for row in meter
                 if timestamp_utc(row["start_utc"]).astimezone(UK).date().isoformat()
                 in heldout_dates]
    prices = {}
    for name, day_rate, night_rate in (("flat", 27, 27), ("night_discount", 35, 9)):
        rates = [{"start_utc": row["start_utc"], "unit_rate_p_per_kwh":
                  night_rate if timestamp_utc(row["start_utc"]).astimezone(UK).hour < 7
                  else day_rate} for row in intervals]
        prices[name] = price_meter_rows(intervals, rates, standing_p_per_day=55)
    return {
        "station_sha256": sha256(station_path),
        "split_local_date": cutoff, "train_days": len(train), "test_days": len(test),
        "exclusion_counts": dict(Counter(row["reason"] for row in joined["excluded_dates"])),
        "measured_import_holdout_daily_mae_kwh": mae,
        "hypothetical_tariff_replay_on_unchanged_import": prices,
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


def run(raw):
    metadata_path = raw / "hpm_systems.json"
    metadata = {row["id"]: row for row in json.loads(metadata_path.read_text())}
    tariffs = json.loads((ROOT / "examples/hypothetical_heating_tariffs.json").read_text())
    agile_path = raw / "agile_jan2024.csv"
    agile_rates = read_csv(agile_path)
    report = {
        "measured_sources": {"heat_pump": "HeatpumpMonitor public daily CSV",
                             "equipment_labels": "HeatpumpMonitor public system metadata",
                             "london_weather": "Meteostat daily station 03772 (Heathrow)",
                             "london_meter": "UKPN Low Carbon London MAC000002 fixture"},
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
    report["london"] = london_meter(raw / "heathrow.csv.gz")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw", type=Path, default=ROOT / "data/raw")
    parser.add_argument("--out", type=Path, default=ROOT / "reports/observed_validation.json")
    args = parser.parse_args()
    write_json(args.out, run(args.raw))


if __name__ == "__main__":
    main()
