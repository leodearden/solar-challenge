# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home's simulation results at one row a minute, with sinusoidal generation and a flat demand,
for tests that need a run whose flows vary through each day rather than totals they choose.

Generation is a sine over each day, clipped at zero, and demand is flat. PV meets demand first
and exports the rest, and the grid meets the shortfall, so the home both imports and exports.
Nothing flows through a battery, there is no heat pump and nothing is priced. A test that
chooses a run's totals builds it with tests._finance_builders.make_sim_results instead.

Usage::

    from tests._sinusoidal_sim_results import make_sinusoidal_sim_results

    results = make_sinusoidal_sim_results(days=2)
    figure = power_flow_timeline(results)
"""

import numpy as np
import pandas as pd

from solar_challenge.home import SimulationResults


def make_sinusoidal_sim_results(days: int = 3) -> SimulationResults:
    """*days* days from midnight on 1 June 2024 at one row a minute: generation a daily sine
    clipped at zero, demand flat and met by PV first; no battery, heat pump or prices."""
    freq = "min"
    index = pd.date_range("2024-06-01", periods=days * 1440, freq=freq, tz="Europe/London")

    hours = np.arange(len(index)) / 60.0
    generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
    demand = np.full(len(index), 0.5)
    self_consumption = np.minimum(generation, demand)
    grid_import = np.maximum(0, demand - generation)
    grid_export = np.maximum(0, generation - demand)
    battery_charge = np.zeros(len(index))
    battery_discharge = np.zeros(len(index))
    battery_soc = np.zeros(len(index))

    def _series(values: np.ndarray, name: str) -> pd.Series:
        return pd.Series(values, index=index, name=name)

    return SimulationResults(
        generation=_series(generation, "generation_kw"),
        demand=_series(demand, "demand_kw"),
        self_consumption=_series(self_consumption, "self_consumption_kw"),
        battery_charge=_series(battery_charge, "battery_charge_kw"),
        battery_discharge=_series(battery_discharge, "battery_discharge_kw"),
        battery_soc=_series(battery_soc, "battery_soc_kwh"),
        grid_import=_series(grid_import, "grid_import_kw"),
        grid_export=_series(grid_export, "grid_export_kw"),
        import_cost=_series(np.zeros(len(index)), "import_cost_gbp"),
        export_revenue=_series(np.zeros(len(index)), "export_revenue_gbp"),
        tariff_rate=_series(np.zeros(len(index)), "tariff_rate_per_kwh"),
        strategy_name="self_consumption",
    )
