# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 10: a battery's grid_charging is honoured or refused as its HomeConfig is built, never run and ignored.

The home is f44's probe: 4 kW of PV, a deterministic 3400 kWh a year and a 5 kWh battery that
grid-charges to 0.9, simulated on 2024-06-15 in synthetic June weather. The probe found three
settings that ran storing 0 kWh from the grid, with no warning.

No HomeConfig or BatteryConfig is built at import: each test builds its own, so a config
refused by mistake fails its own cases and not the module's collection.
"""

import dataclasses
import datetime
import warnings
from collections.abc import Callable

import pandas as pd
import pytest
from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    DispatchStrategyConfig,
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.flow import simulate_timestep
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from tests._synthetic_weather import synthetic_june_weather, weather_for

_DAY = pd.Timestamp("2024-06-15")

_E7 = TariffConfig.economy_7()


def _battery(strategy: DispatchStrategyConfig | None = None) -> BatteryConfig:
    """A 5 kWh battery that grid-charges to 0.9, dispatched by *strategy*, or by its home's when None."""
    return BatteryConfig(capacity_kwh=5.0, dispatch_strategy=strategy, grid_charging=GridChargeConfig(0.9))


def _home(
    battery: BatteryConfig | None,
    *,
    tariff: TariffConfig | None = None,
    dispatch_strategy: str = "greedy",
) -> HomeConfig:
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
        battery_config=battery,
        tariff_config=tariff,
        dispatch_strategy=dispatch_strategy,
    )


def _simulate_the_day(home: HomeConfig) -> SimulationResults:
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        return simulate_home(home, _DAY, _DAY, weather=weather_for(home, synthetic_june_weather(_DAY)))


_PEAK_SHAVING = PeakShavingStrategyConfig(import_limit_kw=3.0)

# Each home whose dispatch grid-charges, by its id, with the strategy its results name.
_HONOURED: dict[str, tuple[Callable[[], HomeConfig], str]] = {
    "home-tou_optimized-on-e7": (
        lambda: _home(_battery(), tariff=_E7, dispatch_strategy="tou_optimized"),
        "tou_optimized",
    ),
    "battery-peak_shaving-on-e7": (lambda: _home(_battery(_PEAK_SHAVING), tariff=_E7), "peak_shaving"),
    "both-levels-the-battery-s-strategy-wins": (
        lambda: _home(_battery(_PEAK_SHAVING), tariff=_E7, dispatch_strategy="tou_optimized"),
        "peak_shaving",
    ),
}


@pytest.mark.parametrize(
    ("battery_strategy", "tariff", "dispatch_strategy", "named"),
    [
        pytest.param(None, None, "greedy", ["grid_charging", "self_consumption"], id="default-dispatch"),
        pytest.param(
            SelfConsumptionStrategyConfig(),
            None,
            "greedy",
            ["grid_charging", "self_consumption"],
            id="battery-self_consumption",
        ),
        pytest.param(
            SelfConsumptionStrategyConfig(),
            _E7,
            "greedy",
            ["grid_charging", "self_consumption"],
            id="battery-self_consumption-on-e7",
        ),
        pytest.param(
            None,
            None,
            "tou_optimized",
            ["dispatch_strategy 'tou_optimized'", "tariff"],
            id="home-tou_optimized-without-a-tariff",
        ),
        pytest.param(
            _PEAK_SHAVING,
            None,
            "greedy",
            ["grid_charging", "peak_shaving", "tariff"],
            id="battery-peak_shaving-without-a-tariff",
        ),
    ],
)
def test_a_home_whose_dispatch_would_ignore_its_grid_charging_is_refused_when_built(
    battery_strategy: DispatchStrategyConfig | None,
    tariff: TariffConfig | None,
    dispatch_strategy: str,
    named: list[str],
) -> None:
    battery = _battery(battery_strategy)

    with pytest.raises(ConfigurationError) as refused:
        _home(battery, tariff=tariff, dispatch_strategy=dispatch_strategy)

    for name in named:
        assert name in str(refused.value), (name, str(refused.value))


@pytest.mark.parametrize(("build_home", "strategy_name"), list(_HONOURED.values()), ids=list(_HONOURED))
def test_a_home_whose_dispatch_honours_its_grid_charging_charges_from_the_grid(
    build_home: Callable[[], HomeConfig], strategy_name: str
) -> None:
    results = _simulate_the_day(build_home())

    assert results.strategy_name == strategy_name
    assert calculate_summary(results).total_grid_charge_kwh > 0


@pytest.mark.parametrize("build_home", [build for build, _ in _HONOURED.values()], ids=list(_HONOURED))
def test_an_honoured_home_without_its_tariff_is_refused(build_home: Callable[[], HomeConfig]) -> None:
    home = build_home()

    with pytest.raises(ConfigurationError, match="tariff"):
        dataclasses.replace(home, tariff_config=None)


def test_a_battery_naming_no_strategy_grid_charges_under_a_tou_strategy_driven_through_simulate_timestep() -> None:
    """The shape a caller of the engine drives: a TOUOptimizedStrategy, on Economy 7, at 02:00 in its cheap night."""
    flows = simulate_timestep(
        generation_kw=0.0,
        demand_kw=0.5,
        battery=Battery(_battery()),
        timestep_minutes=1.0,
        timestamp=datetime.datetime(2024, 6, 15, 2, 0),
        strategy=TOUOptimizedStrategy([(16, 19)]),
        tariff=_E7,
    )

    assert flows.grid_charge > 0


def test_a_home_without_a_battery_may_ask_for_tou_optimized_without_a_tariff() -> None:
    home = _home(None, dispatch_strategy="tou_optimized")

    assert (home.battery_config, home.tariff_config, home.dispatch_strategy) == (None, None, "tou_optimized")
