"""Reproducible, public-data-first command line interface."""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

from .core import (OFGEM_Q4_2026, HeatPumpScenario, Tariff, aggregate_heatpump_days,
                   evaluate_heat_pump, gas_volume_to_kwh, price_meter_rows, summarize_meter)
from .forecast import fit_daily_model, predict_daily
from .pipeline import join_daily_meter_weather
from .signatures import identify_system_clues, interval_profile
from .economics import compare_tariffs, simulate_portfolio, investment_appraisal
from .flexibility import schedule_ev_charge
from .real_meter import import_lcl, measured_profile, expected_halfhourly_profile
from .heating_controls import House, Settings, simulate_heating, strategy_grid, align_meter_baseload
from .data import (fetch_open_meteo_daily, fetch_open_meteo_hourly,
                   fetch_heatpump_daily, fetch_octopus_unit_rates, read_csv,
                   write_csv, write_json)

# Official DESNZ NEED 2026 release, 2024 consumption year, England & Wales only.
NEED_EW_2024 = {
    'source_year': 2024, 'release_year': 2026, 'geography': 'England and Wales',
    'domestic_gas_kwh': {'mean': 11200, 'median': 10000, 'q1': 6500, 'q3': 14400,
                         'matched_properties_millions': 18.9},
    'domestic_electricity_kwh': {'mean': 3300, 'median': 2500, 'q1': 1600,
                                 'q3': 4100, 'matched_properties_millions': 23.5},
    'source_url': 'https://www.gov.uk/government/statistics/national-energy-efficiency-data-framework-need-report-summary-of-analysis-2026/national-energy-efficiency-data-framework-need-report-summary-of-analysis-2026-accessible-webpage',
    'caution': 'Different meter-matched sample sizes; medians cannot be added as a representative paired household.',
}


def _print_or_save(result: dict, output: str | None) -> None:
    if output:
        write_json(output, result)
        print(f'Wrote {output}')
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='domestic-energy',
        description='Research toolkit for GB domestic gas, electricity, heat pumps, smart meters and pricing')
    sub = p.add_subparsers(dest='command', required=True)
    b = sub.add_parser('benchmark', help='Published England/Wales 2024 NEED statistics')
    b.add_argument('--out')
    s = sub.add_parser('scenario', help='Compare gas boiler to heat pump, same useful heat')
    s.add_argument('--gas-kwh', type=float, default=10000)
    s.add_argument('--heating-fraction', type=float, default=0.85)
    s.add_argument('--boiler-efficiency', type=float, default=0.85)
    s.add_argument('--spf', type=float, default=3.0)
    s.add_argument('--other-electricity-kwh', type=float, default=2500)
    s.add_argument('--electricity-p', type=float, default=OFGEM_Q4_2026.electricity_p_per_kwh)
    s.add_argument('--gas-p', type=float, default=OFGEM_Q4_2026.gas_p_per_kwh)
    s.add_argument('--electricity-standing-p', type=float, default=OFGEM_Q4_2026.electricity_standing_p_per_day)
    s.add_argument('--gas-standing-p', type=float, default=OFGEM_Q4_2026.gas_standing_p_per_day)
    s.add_argument('--days', type=int, default=365)
    s.add_argument('--disconnect-gas', action='store_true')
    s.add_argument('--capex', type=float, default=0)
    s.add_argument('--out')
    g = sub.add_parser('gas-convert', help='Convert meter volume to gas kWh using bill calorific value')
    g.add_argument('volume', type=float)
    g.add_argument('--unit', choices=['m3', 'ft3', 'hundred_ft3'], default='m3')
    g.add_argument('--calorific-mj', type=float, default=39.5)
    g.add_argument('--out')
    m = sub.add_parser('meter', help='Analyze UTC timestamped interval consumption')
    m.add_argument('--csv', required=True)
    m.add_argument('--rates', help='CSV mapping UTC interval start to p/kWh')
    m.add_argument('--standing-p', type=float, default=0)
    m.add_argument('--timezone', default='Europe/London')
    m.add_argument('--out')
    hp = sub.add_parser('heatpump', help='Analyze HeatpumpMonitor.org daily CSV')
    hp.add_argument('--csv', required=True)
    hp.add_argument('--min-quality', type=float, default=95)
    hp.add_argument('--min-hours', type=float, default=23)
    hp.add_argument('--out')
    fp = sub.add_parser('fetch-heatpumps', help='Fetch selected published system daily observations')
    fp.add_argument('--ids', required=True, help='Comma-separated IDs from heatpumpmonitor.org')
    fp.add_argument('--out-dir', default='data/raw/heatpumps')
    fp.add_argument('--min-quality', type=float, default=95)
    fr = sub.add_parser('fetch-rates', help='Fetch historical public Octopus tariff rates, no API key')
    fr.add_argument('--product', required=True, help='Tariff product code')
    fr.add_argument('--tariff', required=True, help='Regional electricity tariff code')
    fr.add_argument('--start', required=True, help='Inclusive offset-aware UTC datetime')
    fr.add_argument('--end', required=True, help='Exclusive offset-aware UTC datetime')
    fr.add_argument('--out', required=True)
    d = sub.add_parser('demo', help='Analyze *synthetic* sample and generate results locally')
    d.add_argument('--out-dir', default='reports/demo')
    w = sub.add_parser('fetch-weather', help='Fetch location/time-specific public Open-Meteo ERA5 data')
    w.add_argument('--lat', type=float, required=True)
    w.add_argument('--lon', type=float, required=True)
    w.add_argument('--start', required=True, help='YYYY-MM-DD')
    w.add_argument('--end', required=True, help='YYYY-MM-DD inclusive')
    w.add_argument('--hourly', action='store_true', help='UTC-hourly temperature/shortwave instead of local-day data')
    w.add_argument('--timezone', default='Europe/London')
    w.add_argument('--out', required=True)
    prep = sub.add_parser('prepare-daily', help='Join interval meter, local weather and declared occupancy')
    prep.add_argument('--meter', required=True)
    prep.add_argument('--weather', required=True)
    prep.add_argument('--occupancy')
    prep.add_argument('--timezone', default='Europe/London')
    prep.add_argument('--out', required=True, help='Daily model-ready CSV')
    prep.add_argument('--qa', help='JSON QA with skipped/incomplete days')
    fm = sub.add_parser('forecast', help='Train/validate daily weather/occupancy usage model')
    fm.add_argument('--csv', required=True, help='Daily date,temperature_c,consumption_kwh[,away,work_from_home]')
    fm.add_argument('--future-csv', help='Optional daily future weather plus known away/WFH flags')
    fm.add_argument('--fuel', choices=['gas','electricity','delivered_heat'], default='gas')
    fm.add_argument('--boiler-efficiency', type=float)
    fm.add_argument('--floor-area', type=float)
    fm.add_argument('--out')
    de = sub.add_parser('detect', help='Conservative meter signature hypotheses')
    de.add_argument('--electricity', required=True)
    de.add_argument('--gas')
    de.add_argument('--export')
    de.add_argument('--weather', help='Daily weather in local dates')
    de.add_argument('--timezone', default='Europe/London')
    de.add_argument('--out')
    cp = sub.add_parser('compare-tariffs', help='Replay tariff JSON against opt-in interval CSV')
    cp.add_argument('--csv', required=True, help='SYNTHETIC or consented private interval profile, local-only')
    cp.add_argument('--tariffs', required=True, help='JSON array of tariff definitions')
    cp.add_argument('--pv-scale', type=float, default=0)
    cp.add_argument('--battery-kwh', type=float, default=0)
    cp.add_argument('--battery-power', type=float, default=3)
    cp.add_argument('--direct-electric-from-gas', action='store_true')
    cp.add_argument('--storage-heater-kwh-th', type=float, default=0)
    cp.add_argument('--storage-heater-power', type=float, default=7)
    cp.add_argument('--insulation-reduction', type=float, default=0)
    cp.add_argument('--hp-spf', type=float)
    cp.add_argument('--disconnect-gas', action='store_true')
    cp.add_argument('--remaining-gas-electric-factor', type=float,
                    help='Electric kWh per kWh residual non-space-heating gas to electrify')
    cp.add_argument('--timezone', default='Europe/London')
    cp.add_argument('--out')
    pg = sub.add_parser('portfolio-grid', help='Batch tariff × retrofit scenario grid from JSON')
    pg.add_argument('--csv', required=True)
    pg.add_argument('--tariffs', required=True)
    pg.add_argument('--scenarios', required=True, help='JSON list of {name, parameters...} scenarios')
    pg.add_argument('--out')
    lc = sub.add_parser('import-lcl', help='Convert real UKPN Low Carbon London raw CSV/ZIP to UTC intervals')
    lc.add_argument('--input', required=True, action='append', help='LCL CSV, .csv.gz, or ZIP; repeat for blocks')
    lc.add_argument('--household', required=True, help='Explicit one household, e.g. MAC000002')
    lc.add_argument('--timestamp-mode', choices=['utc_end', 'utc_start'], required=True,
                    help='Source convention: raw UTC/GMT timestamp labels end/start of interval')
    lc.add_argument('--out', required=True, help='Canonical per-household interval CSV')
    lc.add_argument('--qa', help='Optional QA JSON with gap and duplicate counts')
    real = sub.add_parser('measured-profile', help='Report actual electricity profile, no appliance labels')
    real.add_argument('--csv', required=True)
    real.add_argument('--expectations', action='store_true', help='Add time-ordered half-hourly heldout forecast')
    real.add_argument('--out')
    hc = sub.add_parser('heating-study', help='Compare physical thermostat/heat-source scenarios and tariffs')
    hc.add_argument('--weather', required=True, help='UTC hourly or half-hourly weather from fetch-weather --hourly')
    hc.add_argument('--tariffs', required=True, help='Hypothetical tariff JSON list; no claims about current offers')
    hc.add_argument('--house-json', help='Optional House parameter JSON')
    hc.add_argument('--settings-json', help='Optional thermostat Settings parameter JSON')
    hc.add_argument('--away-days', default='', help='Explicit known away dates, comma-separated YYYY-MM-DD')
    hc.add_argument('--wfh-days', default='', help='Explicit known WFH dates, comma-separated YYYY-MM-DD')
    hc.add_argument('--storage-backup-kw', type=float, default=0.)
    hc.add_argument('--baseload-csv', help='Optional verified non-space-heating electricity profile; exact UTC join')
    hc.add_argument('--confirm-nonheating-baseload', action='store_true',
                    help='Required to prevent counting heating electricity twice')
    hc.add_argument('--out')
    trace = sub.add_parser('heating-trace', help='Inspect every interval of one thermostat strategy')
    trace.add_argument('--weather', required=True)
    trace.add_argument('--tariff', required=True, help='Single JSON tariff object')
    trace.add_argument('--source', choices=['gas','heatpump','resistive','storage'], required=True)
    trace.add_argument('--strategy', choices=['constant','setback','timed','wfh_aware','preheat',
                                              'storage_constant','storage_setback','storage_timed'], required=True)
    trace.add_argument('--house-json')
    trace.add_argument('--settings-json')
    trace.add_argument('--away-days', default='')
    trace.add_argument('--wfh-days', default='')
    trace.add_argument('--out')
    ev = sub.add_parser('ev-plan', help='Best-rate EV charge plan from provided half-hour rate CSV')
    ev.add_argument('--rates', required=True)
    ev.add_argument('--arrival', required=True)
    ev.add_argument('--departure', required=True)
    ev.add_argument('--battery-energy-kwh', type=float, required=True)
    ev.add_argument('--charger-kw', type=float, default=7)
    ev.add_argument('--efficiency', type=float, default=.9)
    ev.add_argument('--out')
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == 'benchmark':
            _print_or_save(NEED_EW_2024, args.out)
        elif args.command == 'scenario':
            s = HeatPumpScenario(gas_kwh=args.gas_kwh, gas_heating_fraction=args.heating_fraction,
                boiler_efficiency=args.boiler_efficiency, heat_pump_spf=args.spf,
                other_electricity_kwh=args.other_electricity_kwh, days=args.days,
                disconnect_gas=args.disconnect_gas, retrofit_capex_gbp=args.capex)
            t = Tariff(args.electricity_p, args.gas_p, args.electricity_standing_p, args.gas_standing_p)
            _print_or_save(evaluate_heat_pump(s, t), args.out)
        elif args.command == 'gas-convert':
            _print_or_save({'volume': args.volume, 'unit': args.unit,
                'calorific_mj_per_m3': args.calorific_mj,
                'gas_kwh': gas_volume_to_kwh(args.volume, unit=args.unit,
                                             calorific_mj_per_m3=args.calorific_mj)}, args.out)
        elif args.command == 'meter':
            rows = read_csv(args.csv)
            result = (price_meter_rows(rows, read_csv(args.rates),
                        standing_p_per_day=args.standing_p, timezone_name=args.timezone)
                      if args.rates else summarize_meter(rows, timezone_name=args.timezone))
            _print_or_save(result, args.out)
        elif args.command == 'heatpump':
            _print_or_save(aggregate_heatpump_days(read_csv(args.csv),
                      min_quality=args.min_quality, min_data_hours=args.min_hours), args.out)
        elif args.command == 'fetch-heatpumps':
            ids = [int(v.strip()) for v in args.ids.split(',')]
            if not ids or len(ids) != len(set(ids)) or len(ids) > 25:
                raise ValueError('Provide 1 to 25 distinct system IDs; avoid hammering the public server')
            dest = Path(args.out_dir)
            all_results = {}
            for system_id in ids:
                rows = fetch_heatpump_daily(system_id)
                if rows:
                    write_csv(dest / f'system_{system_id}_daily.csv', rows, list(rows[0]))
                stats = aggregate_heatpump_days(rows, min_quality=args.min_quality)
                write_json(dest / f'system_{system_id}_summary.json', stats)
                all_results[str(system_id)] = stats
                print(f'System {system_id}: {stats["accepted_days"]} accepted days')
            write_json(dest / 'summary.json', all_results)
        elif args.command == 'fetch-rates':
            rates = fetch_octopus_unit_rates(args.product, args.tariff, args.start, args.end)
            write_csv(args.out, rates, ['start_utc', 'unit_rate_p_per_kwh'])
            print(f'Wrote {len(rates)} rate intervals to {args.out}')
        elif args.command == 'fetch-weather':
            if args.hourly:
                weather = fetch_open_meteo_hourly(args.lat, args.lon, args.start, args.end)
                columns = ['start_utc','temperature_c','shortwave_w_m2']
            else:
                weather = fetch_open_meteo_daily(args.lat, args.lon, args.start, args.end,
                                                  timezone_name=args.timezone)
                columns = ['date','temperature_c','temperature_min_c','temperature_max_c','precipitation_mm']
            write_csv(args.out, weather, columns)
            print(f'Wrote {len(weather)} weather records to {args.out}')
        elif args.command == 'prepare-daily':
            result = join_daily_meter_weather(read_csv(args.meter), read_csv(args.weather),
                occupancy_rows=read_csv(args.occupancy) if args.occupancy else None,
                timezone_name=args.timezone)
            cols = ['date', 'temperature_c', 'consumption_kwh', 'coverage_fraction', 'away', 'work_from_home']
            write_csv(args.out, result['daily_rows'], cols)
            if args.qa:
                write_json(args.qa, {k: v for k,v in result.items() if k != 'daily_rows'})
            print(f'Wrote {result["accepted_days"]} days and excluded {result["excluded_days"]} partial/missing days')
        elif args.command == 'forecast':
            model = fit_daily_model(read_csv(args.csv), fuel=args.fuel,
                boiler_efficiency=args.boiler_efficiency, floor_area_m2=args.floor_area)
            result = {'fitted_model': model}
            if args.future_csv:
                result['forecast'] = predict_daily(model, read_csv(args.future_csv))
            _print_or_save(result, args.out)
        elif args.command == 'detect':
            e = read_csv(args.electricity)
            result = identify_system_clues(e, gas_rows=read_csv(args.gas) if args.gas else None,
                export_rows=read_csv(args.export) if args.export else None,
                weather_daily=read_csv(args.weather) if args.weather else None,
                timezone_name=args.timezone)
            result['profile'] = interval_profile(e, timezone_name=args.timezone)
            _print_or_save(result, args.out)
        elif args.command == 'compare-tariffs':
            tariffs = json.loads(Path(args.tariffs).read_text(encoding='utf-8'))
            result = compare_tariffs(read_csv(args.csv), tariffs,
                pv_scale=args.pv_scale, battery_kwh=args.battery_kwh,
                direct_electric_from_gas=args.direct_electric_from_gas,
                storage_heater_kwh_th=args.storage_heater_kwh_th,
                storage_heater_power_kw=args.storage_heater_power,
                battery_power_kw=args.battery_power,
                insulation_heat_reduction=args.insulation_reduction,
                heat_pump_spf=args.hp_spf, disconnect_gas=args.disconnect_gas,
                remaining_gas_to_electric_kwh_per_kwh=args.remaining_gas_electric_factor,
                timezone_name=args.timezone)
            _print_or_save(result, args.out)
        elif args.command == 'portfolio-grid':
            rows = read_csv(args.csv)
            tariffs = json.loads(Path(args.tariffs).read_text(encoding='utf-8'))
            scenarios = json.loads(Path(args.scenarios).read_text(encoding='utf-8'))
            if not isinstance(scenarios, list) or not scenarios or len(scenarios) > 100:
                raise ValueError('1..100 scenarios required')
            output = []
            for scenario in scenarios:
                params = {key: value for key, value in scenario.items() if key != 'name'}
                for tariff in tariffs:
                    result = simulate_portfolio(rows, tariff, **params)
                    output.append({'scenario': scenario['name'], 'tariff': tariff['name'],
                        'cost_gbp': result['with_battery']['total_bill_gbp'],
                        'electricity_import_kwh': result['with_battery']['grid_import_kwh'],
                        'pv_export_kwh': result['with_battery']['grid_export_kwh'],
                        'coverage_fraction': result['coverage_fraction'],
                        'achieved_hp_spf': result['resulting_heat_pump_spf']})
            output.sort(key=lambda x: (x['cost_gbp'], x['scenario']))
            _print_or_save({'results': output,
                'warning': 'Scenario costs cannot be compared as annual bills unless coverage is representative and complete. Capex is excluded; run investment appraisal.'}, args.out)
        elif args.command == 'import-lcl':
            parsed = import_lcl(args.input, args.household, timestamp_mode=args.timestamp_mode)
            write_csv(args.out, parsed['rows'], ['start_utc','consumption_kwh','duration_minutes'])
            if args.qa:
                write_json(args.qa, parsed['qa'])
            print(f"Imported {parsed['qa']['selected_intervals']} measured intervals; "
                  f"coverage={parsed['qa']['coverage_fraction']}, kWh={parsed['qa']['observed_total_kwh']}")
        elif args.command == 'measured-profile':
            rows = read_csv(args.csv)
            result = measured_profile(rows)
            if args.expectations:
                result['expected_usage_validation'] = expected_halfhourly_profile(rows)
            _print_or_save(result, args.out)
        elif args.command in ('heating-study', 'heating-trace'):
            from datetime import date
            def known_dates(value):
                return {date.fromisoformat(x.strip()) for x in value.split(',') if x.strip()}
            weather = read_csv(args.weather)
            house = House(**json.loads(Path(args.house_json).read_text(encoding='utf-8'))) if args.house_json else House()
            settings = Settings(**json.loads(Path(args.settings_json).read_text(encoding='utf-8'))) if args.settings_json else Settings()
            away, wfh = known_dates(args.away_days), known_dates(args.wfh_days)
            if args.command == 'heating-study':
                baseload = None
                if args.baseload_csv:
                    if not args.confirm_nonheating_baseload:
                        raise ValueError('Confirm meter CSV excludes space heating before using as baseload')
                    baseload = align_meter_baseload(weather, read_csv(args.baseload_csv))
                result = strategy_grid(weather,
                    json.loads(Path(args.tariffs).read_text(encoding='utf-8')),
                    house=house, settings=settings, away_dates=away, wfh_dates=wfh,
                    baseload_kwh=baseload, storage_backup_heat_kw=args.storage_backup_kw)
            else:
                result = simulate_heating(weather, heat_source=args.source,
                    strategy=args.strategy,
                    tariff=json.loads(Path(args.tariff).read_text(encoding='utf-8')),
                    house=house, settings=settings, away_dates=away, wfh_dates=wfh,
                    record_intervals=True)
            _print_or_save(result, args.out)
        elif args.command == 'ev-plan':
            result = schedule_ev_charge(read_csv(args.rates), arrival_utc=args.arrival,
                departure_utc=args.departure, battery_energy_needed_kwh=args.battery_energy_kwh,
                charger_kw=args.charger_kw, charging_efficiency=args.efficiency)
            _print_or_save(result, args.out)
        elif args.command == 'demo':
            root = Path(__file__).resolve().parent.parent
            sample = root / 'examples'
            out = Path(args.out_dir)
            out.mkdir(parents=True, exist_ok=True)
            meter = read_csv(sample / 'synthetic_smart_meter.csv')
            rates = read_csv(sample / 'synthetic_tou_rates.csv')
            results = {
                'data_note': 'Consumption and time-of-use rates are SYNTHETIC examples, not observations or live offers.',
                'meter_flat_26_32p': price_meter_rows(meter, [
                    {'start_utc': r['start_utc'], 'unit_rate_p_per_kwh': 26.32} for r in meter],
                    standing_p_per_day=54.83),
                'meter_synthetic_tou': price_meter_rows(meter, rates, standing_p_per_day=54.83),
                'heatpump_sample': aggregate_heatpump_days(read_csv(sample / 'synthetic_heatpump_daily.csv')),
                'scenario': evaluate_heat_pump(HeatPumpScenario()),
                'benchmark': NEED_EW_2024,
            }
            write_json(out / 'results.json', results)
            sensitivity = []
            for elec_p in [16, 20, 24, 26.32, 30, 35]:
                for spf in [2, 2.5, 3, 3.5, 4, 4.5]:
                    result = evaluate_heat_pump(replace(HeatPumpScenario(), heat_pump_spf=spf),
                        replace(OFGEM_Q4_2026, electricity_p_per_kwh=elec_p))
                    sensitivity.append({'electricity_p_per_kwh': elec_p, 'spf': spf,
                        'annual_saving_gbp': result['annual_saving_gbp']})
            write_csv(out / 'sensitivity.csv', sensitivity,
                      ['electricity_p_per_kwh', 'spf', 'annual_saving_gbp'])
            print(f'Generated synthetic demo and sensitivity in {out}')
        else:
            raise ValueError('Unknown command')
        return 0
    except (ValueError, OSError, KeyError, RuntimeError, json.JSONDecodeError) as exc:
        print(f'error: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
