# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for which dispatch simulate_home runs a home under, as named by its results' strategy_name.

A home whose dispatch_strategy is tou_optimized runs the tariff-rate TOU path when it has a tariff
and its battery, if any, names no strategy of its own. Otherwise it runs its battery's strategy,
self-consumption by default.
"""

import dataclasses

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig
from tests._synthetic_weather import synthetic_june_weather

_TOU_HOME = HomeConfig(
    pv_config=PVConfig(capacity_kw=4.0),
    load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
    battery_config=BatteryConfig(capacity_kwh=5.0),
    tariff_config=TariffConfig.economy_7(),
    seg_tariff=SEG_PRESETS["Octopus"],
    dispatch_strategy="tou_optimized",
)


@pytest.mark.parametrize(
    ("home", "strategy_name"),
    [
        pytest.param(_TOU_HOME, "tou_optimized", id="tou_optimized-with-a-tariff"),
        pytest.param(
            dataclasses.replace(_TOU_HOME, battery_config=None),
            "tou_optimized",
            id="tou_optimized-with-a-tariff-and-no-battery",
        ),
        pytest.param(
            dataclasses.replace(_TOU_HOME, tariff_config=None),
            "self_consumption",
            id="tou_optimized-without-a-tariff",
        ),
        pytest.param(
            dataclasses.replace(_TOU_HOME, dispatch_strategy="greedy"),
            "self_consumption",
            id="greedy-with-a-tariff",
        ),
        pytest.param(
            dataclasses.replace(
                _TOU_HOME,
                battery_config=BatteryConfig(
                    capacity_kwh=5.0,
                    dispatch_strategy=DispatchStrategyConfig(strategy_type="peak_shaving", import_limit_kw=0.1),
                ),
            ),
            "peak_shaving",
            id="tou_optimized-whose-battery-names-peak_shaving",
        ),
        pytest.param(
            dataclasses.replace(
                _TOU_HOME,
                dispatch_strategy="greedy",
                battery_config=BatteryConfig(
                    capacity_kwh=5.0,
                    dispatch_strategy=DispatchStrategyConfig(strategy_type="tou_optimized", peak_hours=[(16, 20)]),
                ),
            ),
            "tou_optimized",
            id="greedy-whose-battery-names-tou_optimized",
        ),
    ],
)
def test_results_name_the_dispatch_the_home_ran(home, strategy_name):
    """Each home's results name the dispatch it ran: the tariff-rate TOU path, or its battery's strategy."""
    day = pd.Timestamp("2024-06-21")

    results = simulate_home(home, day, day, weather_data=synthetic_june_weather("2024-06-21"))

    assert results.strategy_name == strategy_name
