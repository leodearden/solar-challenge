# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 10: a battery's grid_charging is honoured, or refused as its HomeConfig is built or as simulate_home is given a strategy that would ignore it; it is never run and ignored.

The home is f44's probe: 4 kW of PV, a deterministic 3400 kWh a year and a 5 kWh battery that
grid-charges to 0.9, simulated on 2024-06-15 in synthetic June weather. The probe found three
settings that ran storing 0 kWh from the grid, with no warning. A tariff with no cheap period,
such as a flat rate, is a fourth: a strategy that grid-charges never finds a minute to charge in
(docs/prds/tariff-coverage-classifier-presets.md §5.4, §9 row 9).

No HomeConfig or BatteryConfig is built at import: each test builds its own, so a config
refused by mistake fails its own cases and not the module's collection.
"""

import dataclasses
import datetime
import warnings
from collections.abc import Callable
from zoneinfo import ZoneInfo

import pandas as pd
import pytest
from solar_challenge.battery import Battery, BatteryConfig
from solar_challenge.dispatch import (
    ChargeWindow,
    DispatchStrategy,
    DispatchStrategyConfig,
    GridChargeConfig,
    PeakShavingStrategy,
    PeakShavingStrategyConfig,
    ScheduledChargeStrategy,
    SelfConsumptionStrategy,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.flow import simulate_timestep
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from solar_challenge.weather import PrefetchedWeather
from tests._synthetic_weather import synthetic_june_weather, weather_for

_DAY = pd.Timestamp("2024-06-15")

_E7 = TariffConfig.economy_7()

_FLAT = TariffConfig.flat_rate(0.25)

_LONDON = ZoneInfo("Europe/London")


def _battery(strategy: DispatchStrategyConfig | None = None) -> BatteryConfig:
    """A 5 kWh battery that grid-charges to 0.9, dispatched by *strategy*, or naming no strategy, so by self-consumption, when None."""
    battery = BatteryConfig(capacity_kwh=5.0, grid_charging=GridChargeConfig(0.9))
    return battery if strategy is None else dataclasses.replace(battery, dispatch_strategy=strategy)


def _home(battery: BatteryConfig | None, *, tariff: TariffConfig | None = None) -> HomeConfig:
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
        battery_config=battery,
        tariff_config=tariff,
    )


def _simulate_the_day(home: HomeConfig, *, strategy: DispatchStrategy | None = None) -> SimulationResults:
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        return simulate_home(
            home, _DAY, _DAY, weather=weather_for(home, synthetic_june_weather(_DAY)), strategy=strategy
        )


_PEAK_SHAVING = PeakShavingStrategyConfig(import_limit_kw=3.0)

# Each home whose dispatch grid-charges, by its id, with the strategy its results name.
_HONOURED: dict[str, tuple[Callable[[], HomeConfig], str]] = {
    "battery-peak_shaving-on-e7": (lambda: _home(_battery(_PEAK_SHAVING), tariff=_E7), "peak_shaving"),
    "battery-tou_optimized-on-the-tariff-clock-on-e7": (
        lambda: _home(_battery(TOUOptimizedStrategyConfig()), tariff=_E7),
        "tou_optimized",
    ),
}


# Each refused row builds its battery's strategy, None for a battery naming none, which dispatches self-consumption, when the test runs.
@pytest.mark.parametrize(
    ("build_battery_strategy", "tariff", "named"),
    [
        pytest.param(lambda: None, None, ["grid_charging", "self_consumption"], id="default-dispatch"),
        pytest.param(
            SelfConsumptionStrategyConfig,
            None,
            ["grid_charging", "self_consumption"],
            id="battery-self_consumption",
        ),
        pytest.param(
            SelfConsumptionStrategyConfig,
            _E7,
            ["grid_charging", "self_consumption"],
            id="battery-self_consumption-on-e7",
        ),
        pytest.param(
            TOUOptimizedStrategyConfig,
            None,
            ["'tou_optimized'", "no tariff"],
            id="battery-tou_optimized-on-the-tariff-clock-without-a-tariff",
        ),
        pytest.param(
            lambda: _PEAK_SHAVING,
            None,
            ["grid_charging", "peak_shaving", "tariff"],
            id="battery-peak_shaving-without-a-tariff",
        ),
        pytest.param(
            TOUOptimizedStrategyConfig,
            _FLAT,
            ["grid_charging", "'tou_optimized'", _FLAT.name, "no cheap period"],
            id="battery-tou_optimized-on-a-flat-tariff",
        ),
        pytest.param(
            lambda: _PEAK_SHAVING,
            _FLAT,
            ["grid_charging", "'peak_shaving'", _FLAT.name, "no cheap period"],
            id="battery-peak_shaving-on-a-flat-tariff",
        ),
    ],
)
def test_a_home_whose_dispatch_would_ignore_its_grid_charging_is_refused_when_built(
    build_battery_strategy: Callable[[], DispatchStrategyConfig | None],
    tariff: TariffConfig | None,
    named: list[str],
) -> None:
    battery = _battery(build_battery_strategy())

    with pytest.raises(ConfigurationError) as refused:
        _home(battery, tariff=tariff)

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


@pytest.mark.parametrize(
    ("strategy", "named"),
    [
        pytest.param(SelfConsumptionStrategy(), "'self_consumption'", id="self_consumption"),
        pytest.param(
            ScheduledChargeStrategy(SelfConsumptionStrategy(), (), _LONDON),
            "'scheduled_charge(self_consumption)'",
            id="no-window-over-self_consumption",
        ),
    ],
)
def test_a_strategy_given_to_simulate_home_that_would_ignore_the_grid_charging_is_refused_before_the_run_asks_for_weather(
    strategy: DispatchStrategy, named: str
) -> None:
    """The weather answers for no location, so a run that asked for it would raise LookupError instead."""
    home = _home(_battery(TOUOptimizedStrategyConfig()), tariff=_E7)

    with pytest.raises(ConfigurationError) as refused:
        simulate_home(home, _DAY, _DAY, weather=PrefetchedWeather({}), strategy=strategy)

    for name in ["grid_charging", named, "does not charge from the grid"]:
        assert name in str(refused.value), (name, str(refused.value))


@pytest.mark.parametrize(
    ("strategy", "strategy_name"),
    [
        pytest.param(TOUOptimizedStrategy([(16, 19)]), "tou_optimized", id="tou_optimized"),
        pytest.param(PeakShavingStrategy(3.0), "peak_shaving", id="peak_shaving"),
        pytest.param(
            ScheduledChargeStrategy(
                SelfConsumptionStrategy(),
                (ChargeWindow("daily", datetime.time(0, 30), datetime.timedelta(hours=7), 0.9, False),),
                _LONDON,
            ),
            "scheduled_charge(self_consumption)",
            id="a-window-over-self_consumption",
        ),
    ],
)
def test_a_strategy_given_to_simulate_home_that_charges_from_the_grid_grid_charges(
    strategy: DispatchStrategy, strategy_name: str
) -> None:
    home = _home(_battery(TOUOptimizedStrategyConfig()), tariff=_E7)

    results = _simulate_the_day(home, strategy=strategy)

    assert results.strategy_name == strategy_name
    assert calculate_summary(results).total_grid_charge_kwh > 0


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
