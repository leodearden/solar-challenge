# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for build_dispatch_strategy, which builds the strategy each variant of DispatchStrategyConfig configures.

It refuses a grid_charging setting the strategy would ignore: under a variant that does not
charge from the grid, or with no tariff to find a cheap period in.
"""

from datetime import datetime
from typing import Any, Optional, get_args

import pytest

from solar_challenge.dispatch import (
    DispatchStrategyConfig,
    GridChargeConfig,
    PeakShavingStrategy,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategy,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
    build_dispatch_strategy,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.tariff import TariffConfig

_CASES = (
    (SelfConsumptionStrategyConfig(), SelfConsumptionStrategy),
    (TOUOptimizedStrategyConfig(peak_hours=((16, 19),)), TOUOptimizedStrategy),
    (PeakShavingStrategyConfig(import_limit_kw=2.0), PeakShavingStrategy),
)
"""Each variant's example, with the class of the strategy it configures."""

_GRID_CHARGING_CASES = _CASES[1:]
"""The cases whose variant charges from the grid, in a cheap period of the tariff."""

_GRID_CHARGING = GridChargeConfig(target_soc_fraction=0.9)


def test_the_cases_cover_the_union() -> None:
    assert {type(config) for config, _ in _CASES} == set(get_args(DispatchStrategyConfig))


@pytest.mark.parametrize("tariff", [TariffConfig.economy_7(), None], ids=["economy_7", "no-tariff"])
@pytest.mark.parametrize(
    ("config", "strategy_class"), _CASES, ids=[config.strategy_type for config, _ in _CASES]
)
def test_each_variant_builds_the_strategy_it_names(
    config: Any, strategy_class: type, tariff: Optional[TariffConfig]
) -> None:
    strategy = build_dispatch_strategy(config, grid_charging=None, tariff=tariff)

    assert isinstance(strategy, strategy_class)
    assert strategy.name == config.strategy_type


def test_the_tou_strategy_discharges_in_the_configs_peak_hours_only() -> None:
    strategy = build_dispatch_strategy(
        TOUOptimizedStrategyConfig(peak_hours=((16, 19),)), grid_charging=None, tariff=None
    )

    def discharge_kw(hour: int) -> float:
        return strategy.decide_action(
            timestamp=datetime(2024, 1, 15, hour, 0),
            generation_kw=0.0,
            demand_kw=1.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        ).discharge_kw

    assert discharge_kw(17) == 1.0
    assert discharge_kw(12) == 0.0


def test_the_peak_shaving_strategy_discharges_only_the_import_over_the_configs_limit() -> None:
    strategy = build_dispatch_strategy(
        PeakShavingStrategyConfig(import_limit_kw=2.0), grid_charging=None, tariff=None
    )

    decision = strategy.decide_action(
        timestamp=datetime(2024, 1, 15, 17, 0),
        generation_kw=0.0,
        demand_kw=3.0,
        battery_soc_kwh=2.5,
        battery_capacity_kwh=5.0,
    )

    assert decision.discharge_kw == 1.0


@pytest.mark.parametrize("tariff", [TariffConfig.economy_7(), None], ids=["economy_7", "no-tariff"])
def test_grid_charging_under_self_consumption_is_refused(tariff: Optional[TariffConfig]) -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(SelfConsumptionStrategyConfig(), grid_charging=_GRID_CHARGING, tariff=tariff)

    for named in ["grid_charging", "'self_consumption'", "does not charge from the grid"]:
        assert named in str(refused.value), (named, str(refused.value))


@pytest.mark.parametrize(
    "config", [config for config, _ in _GRID_CHARGING_CASES], ids=[config.strategy_type for config, _ in _GRID_CHARGING_CASES]
)
def test_grid_charging_without_a_tariff_is_refused(config: Any) -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(config, grid_charging=_GRID_CHARGING, tariff=None)

    for named in ["grid_charging", f"'{config.strategy_type}'", "tariff"]:
        assert named in str(refused.value), (named, str(refused.value))


@pytest.mark.parametrize(
    ("config", "strategy_class"), _GRID_CHARGING_CASES, ids=[config.strategy_type for config, _ in _GRID_CHARGING_CASES]
)
def test_a_variant_that_charges_from_the_grid_builds_with_grid_charging_on_a_tariff(
    config: Any, strategy_class: type
) -> None:
    strategy = build_dispatch_strategy(config, grid_charging=_GRID_CHARGING, tariff=TariffConfig.economy_7())

    assert isinstance(strategy, strategy_class)
