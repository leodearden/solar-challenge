# SPDX-License-Identifier: AGPL-3.0-or-later
"""Runs of the bristol-arbitrage home without grid charging, over a sunless winter day or two clear June days, and the run in which its battery exports from 17:00 to 19:00.

The exporting run's base strategy holds the battery's charge for a 16:00 to 20:00 peak, so the battery has charge
to export from 17:00 even on the sunless day, which self-consumption would have drained by then. Every run checks
its balance every minute.

Usage::

    from tests._exporting_runs import RUN_DAYS, exporting_run, run_over

    exporting = exporting_run("2024-01-15-sunless")
    self_consuming = run_over("2024-01-15-sunless", SelfConsumptionStrategy())
"""

import dataclasses
from typing import Optional

import pandas as pd

from solar_challenge.dispatch import DispatchStrategy, GridChargeConfig, TOUOptimizedStrategy
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from tests._bristol_arbitrage_home import bristol_arbitrage_home
from tests._exporting_strategy import ExportingStrategy
from tests._synthetic_weather import sunless_weather, synthetic_june_weather, weather_for

#: The hours, on the run's own clock, in which the exporting run's battery exports.
EXPORT_HOURS = range(17, 19)

#: Each day's weather, first day and last day, by the day's id.
RUN_DAYS: dict[str, tuple[pd.DataFrame, str, str]] = {
    "2024-01-15-sunless": (sunless_weather("2024-01-15", temp_air=5.0), "2024-01-15", "2024-01-15"),
    "2024-06-20_to_21-clear": (synthetic_june_weather("2024-06-20", (1.0, 1.0)), "2024-06-20", "2024-06-21"),
}

_BASE_HOLDING_FOR_THE_PEAK = TOUOptimizedStrategy([(16, 20)])


def home_of_the_runs(grid_charging: Optional[GridChargeConfig] = None) -> HomeConfig:
    """The bristol-arbitrage home, its battery's grid_charging replaced by *grid_charging*, so by default charging from PV alone."""
    home = bristol_arbitrage_home()
    assert home.battery_config is not None
    return dataclasses.replace(
        home, battery_config=dataclasses.replace(home.battery_config, grid_charging=grid_charging)
    )


def run_over(
    day_id: str, strategy: DispatchStrategy, grid_charging: Optional[GridChargeConfig] = None
) -> SimulationResults:
    """home_of_the_runs(grid_charging) over RUN_DAYS[day_id] under *strategy*, its balance checked every minute."""
    home = home_of_the_runs(grid_charging)
    weather, start, end = RUN_DAYS[day_id]
    return simulate_home(
        home,
        pd.Timestamp(start),
        pd.Timestamp(end),
        validate_balance=True,
        weather=weather_for(home, weather),
        strategy=strategy,
    )


def exporting_run(day_id: str) -> SimulationResults:
    """home_of_the_runs() over RUN_DAYS[day_id], exporting all it may in EXPORT_HOURS and holding its charge for the peak otherwise."""
    battery = home_of_the_runs().battery_config
    assert battery is not None
    return run_over(day_id, ExportingStrategy(_BASE_HOLDING_FOR_THE_PEAK, EXPORT_HOURS, battery))
