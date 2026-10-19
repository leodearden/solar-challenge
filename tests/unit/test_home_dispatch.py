# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for which dispatch simulate_home runs a home under, as named by its results' strategy_name, and the cadence each dispatch path steps the engine at.

A home whose dispatch_strategy is tou_optimized runs the tariff-rate TOU path when it has a tariff
and its battery, if any, names no strategy of its own. Otherwise it runs its battery's strategy,
self-consumption by default.
"""

import dataclasses

import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.config import DispatchStrategyConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import SimulationWindow
from tests._synthetic_weather import synthetic_june_weather

_TOU_HOME = HomeConfig(
    pv_config=PVConfig(capacity_kw=4.0),
    load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
    battery_config=BatteryConfig(capacity_kwh=5.0),
    tariff_config=TariffConfig.economy_7(),
    seg_tariff=SEG_PRESETS["Octopus"],
    dispatch_strategy="tou_optimized",
)


def _simulate_june_21(home: HomeConfig) -> SimulationResults:
    day = pd.Timestamp("2024-06-21")
    return simulate_home(home, day, day, weather_data=synthetic_june_weather(day))


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
def test_results_name_the_dispatch_selected_for_the_home(home, strategy_name):
    """Each home's results name the dispatch selected for it: the tariff-rate TOU path, or its battery's strategy."""
    assert _simulate_june_21(home).strategy_name == strategy_name


def test_tou_optimized_saves_the_battery_for_the_dear_rate_and_self_consumption_does_not():
    """On Economy 7 the run named tou_optimized holds its battery through the cheap night rate and spends it at the dear rate.

    The run named self_consumption spends it whenever demand exceeds generation, at the cheap rate too.
    """
    tou = _simulate_june_21(_TOU_HOME)
    self_consumption = _simulate_june_21(dataclasses.replace(_TOU_HOME, dispatch_strategy="greedy"))

    cheap = tou.tariff_rate < tou.tariff_rate.max()
    assert (tou.strategy_name, self_consumption.strategy_name) == ("tou_optimized", "self_consumption")
    assert (tou.battery_discharge[cheap] == 0.0).all()
    assert (tou.battery_discharge[~cheap] > 0.0).any()
    assert (self_consumption.battery_discharge[cheap] > 0.0).any()


@pytest.mark.parametrize(
    ("home", "strategy_name"),
    [
        pytest.param(_TOU_HOME, "tou_optimized", id="tariff-tou-path"),
        pytest.param(dataclasses.replace(_TOU_HOME, dispatch_strategy="greedy"), "self_consumption", id="strategy-path"),
    ],
)
def test_each_dispatch_path_steps_the_engine_at_the_runs_cadence(home, strategy_name):
    """Each row's demand comes back at the kW its load profile asked for only while the engine integrates each row over the step of the run's window and the results turn each row's kWh back into kW over the same step.

    So it fails if either engine call is handed step_hours where step_minutes belongs, or if the
    conversion multiplies by step_hours.
    """
    day = pd.Timestamp("2024-06-21")

    results = _simulate_june_21(home)

    load_profile = generate_load_profile(
        home.load_config, day, day, timezone=home.location.timezone, ev_config=home.ev_config
    )
    assert results.strategy_name == strategy_name
    assert (results.battery_charge > 0).any()
    assert (results.battery_discharge > 0).any()
    assert results.window == SimulationWindow.of_index(load_profile.index)
    pd.testing.assert_series_equal(results.demand, load_profile, check_names=False, rtol=1e-12, atol=0.0)
