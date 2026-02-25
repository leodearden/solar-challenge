#!/usr/bin/env python3
"""Test script to verify heat pump metrics in markdown report."""

import pandas as pd
import numpy as np
from solar_challenge.home import SimulationResults
from solar_challenge.output import generate_summary_report

# Create a simple test simulation with a full year of data
dates = pd.date_range("2023-01-01", "2023-12-31 23:59:00", freq="1min")
n_points = len(dates)

# Create synthetic data with seasonal variation
months = dates.month
winter_mask = np.isin(months, [12, 1, 2])
summer_mask = np.isin(months, [6, 7, 8])

# Heat pump load: high in winter, low in summer
heat_pump_load = np.zeros(n_points)
heat_pump_load[winter_mask] = np.random.uniform(2.5, 4.5, winter_mask.sum())  # 2.5-4.5 kW in winter
heat_pump_load[summer_mask] = np.random.uniform(0.5, 1.0, summer_mask.sum())  # 0.5-1.0 kW in summer
# Spring/fall moderate
spring_fall_mask = ~(winter_mask | summer_mask)
heat_pump_load[spring_fall_mask] = np.random.uniform(1.0, 2.0, spring_fall_mask.sum())

# Base load (other appliances)
base_load = np.random.uniform(0.3, 1.0, n_points)

# Total demand = heat pump + base load
demand = heat_pump_load + base_load

# Generation (solar) - high in summer, low in winter
generation = np.zeros(n_points)
hours = dates.hour
# Only generate during daylight hours (6am-6pm)
daylight_mask = (hours >= 6) & (hours <= 18)
generation[daylight_mask & winter_mask] = np.random.uniform(0.5, 2.0, (daylight_mask & winter_mask).sum())
generation[daylight_mask & summer_mask] = np.random.uniform(2.0, 5.0, (daylight_mask & summer_mask).sum())
generation[daylight_mask & spring_fall_mask] = np.random.uniform(1.0, 3.5, (daylight_mask & spring_fall_mask).sum())

# Simple self-consumption calculation
self_consumption = np.minimum(generation, demand)

# Battery (simple placeholders)
battery_charge = np.maximum(0, generation - demand) * 0.8
battery_discharge = np.maximum(0, demand - generation) * 0.5
battery_soc = np.cumsum(battery_charge - battery_discharge) * 0.01

# Grid flows
grid_import = np.maximum(0, demand - generation - battery_discharge)
grid_export = np.maximum(0, generation - demand - battery_charge)

# Cost placeholders
import_cost = grid_import * 0.25 / 60  # £0.25/kWh
export_revenue = grid_export * 0.05 / 60  # £0.05/kWh
tariff_rate = pd.Series(0.25, index=dates)

# Create SimulationResults
results = SimulationResults(
    generation=pd.Series(generation, index=dates),
    demand=pd.Series(demand, index=dates),
    self_consumption=pd.Series(self_consumption, index=dates),
    battery_charge=pd.Series(battery_charge, index=dates),
    battery_discharge=pd.Series(battery_discharge, index=dates),
    battery_soc=pd.Series(battery_soc, index=dates),
    grid_import=pd.Series(grid_import, index=dates),
    grid_export=pd.Series(grid_export, index=dates),
    import_cost=pd.Series(import_cost, index=dates),
    export_revenue=pd.Series(export_revenue, index=dates),
    tariff_rate=tariff_rate,
    strategy_name="self_consumption",
    heat_pump_load=pd.Series(heat_pump_load, index=dates),
)

# Generate report
report = generate_summary_report(results, home_name="Test Home with Heat Pump")

# Print report
print(report)
print("\n" + "=" * 80)
print("TEST VERIFICATION:")
print("=" * 80)

# Verify key sections are present
checks = [
    ("Heat Pump Impact section" in report or "## Heat Pump" in report, "✓ Heat pump section present"),
    ("Winter" in report and "Summer" in report, "✓ Seasonal comparison included"),
    ("Winter/Summer Ratio" in report, "✓ Ratio column present"),
    ("Key Insights" in report, "✓ Key insights section present"),
    ("Daily Average" in report, "✓ Daily averages shown"),
]

for check, message in checks:
    status = "✓" if check else "✗"
    print(f"{status} {message}")

all_passed = all(check for check, _ in checks)
print("\n" + ("=" * 80))
if all_passed:
    print("✓ ALL CHECKS PASSED")
else:
    print("✗ SOME CHECKS FAILED")
print("=" * 80)
