"""Domestic energy research toolkit. No network action on import."""
from .core import (OFGEM_Q4_2026, HeatPumpScenario, Tariff, aggregate_heatpump_days,
                   evaluate_heat_pump, gas_volume_to_kwh, price_meter_rows, summarize_meter)

__version__ = '0.1.0'
