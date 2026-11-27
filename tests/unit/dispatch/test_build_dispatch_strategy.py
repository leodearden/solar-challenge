# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for build_dispatch_strategy, which builds the strategy each variant of DispatchStrategyConfig configures.

It refuses a grid_charging setting the strategy would ignore: under a variant that does not
charge from the grid, or with no tariff to find a cheap period in. A battery's event windows
wrap the strategy it builds, through with_event_discharge.
"""

from collections.abc import Iterable
from datetime import date, datetime
from typing import NamedTuple, Optional, get_args
from zoneinfo import ZoneInfo

import pytest

from solar_challenge.dispatch import (
    DispatchDecision,
    DispatchStrategy,
    DispatchStrategyConfig,
    EventDischargeStrategy,
    EventDischargeWindow,
    GridChargeConfig,
    PeakShavingStrategy,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategy,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
    build_dispatch_strategy,
    with_event_discharge,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.tariff import TariffConfig


class _Case(NamedTuple):
    """A variant of DispatchStrategyConfig: its example, the class of the strategy it configures, and whether that strategy charges from the grid in a cheap period of the tariff."""

    config: DispatchStrategyConfig
    strategy_class: type[DispatchStrategy]
    charges_from_the_grid: bool


_CASES = (
    _Case(SelfConsumptionStrategyConfig(), SelfConsumptionStrategy, charges_from_the_grid=False),
    _Case(TOUOptimizedStrategyConfig(peak_hours=((16, 19),)), TOUOptimizedStrategy, charges_from_the_grid=True),
    _Case(PeakShavingStrategyConfig(import_limit_kw=2.0), PeakShavingStrategy, charges_from_the_grid=True),
)
"""One case for each variant of DispatchStrategyConfig."""

_GRID_CHARGING_CASES = tuple(case for case in _CASES if case.charges_from_the_grid)
"""The cases whose variant charges from the grid, in a cheap period of the tariff."""

_NON_GRID_CHARGING_CASES = tuple(case for case in _CASES if not case.charges_from_the_grid)
"""The cases whose variant does not charge from the grid."""

_GRID_CHARGING = GridChargeConfig(target_soc_fraction=0.9)


def _ids(cases: Iterable[_Case]) -> list[str]:
    return [case.config.strategy_type for case in cases]


def test_the_cases_cover_the_union() -> None:
    assert {type(case.config) for case in _CASES} == set(get_args(DispatchStrategyConfig))


@pytest.mark.parametrize("tariff", [TariffConfig.economy_7(), None], ids=["economy_7", "no-tariff"])
@pytest.mark.parametrize("case", _CASES, ids=_ids(_CASES))
def test_each_variant_builds_the_strategy_it_names(case: _Case, tariff: Optional[TariffConfig]) -> None:
    strategy = build_dispatch_strategy(case.config, grid_charging=None, tariff=tariff)

    assert isinstance(strategy, case.strategy_class)
    assert strategy.name == case.config.strategy_type
    assert strategy.charges_from_the_grid == case.charges_from_the_grid


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
            timestep_minutes=1.0,
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
        timestep_minutes=1.0,
    )

    assert decision.discharge_kw == 1.0


@pytest.mark.parametrize("tariff", [TariffConfig.economy_7(), None], ids=["economy_7", "no-tariff"])
@pytest.mark.parametrize("case", _NON_GRID_CHARGING_CASES, ids=_ids(_NON_GRID_CHARGING_CASES))
def test_grid_charging_under_a_variant_that_does_not_charge_from_the_grid_is_refused(
    case: _Case, tariff: Optional[TariffConfig]
) -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(case.config, grid_charging=_GRID_CHARGING, tariff=tariff)

    for named in ["grid_charging", f"'{case.config.strategy_type}'", "does not charge from the grid"]:
        assert named in str(refused.value), (named, str(refused.value))


@pytest.mark.parametrize("case", _NON_GRID_CHARGING_CASES, ids=_ids(_NON_GRID_CHARGING_CASES))
def test_the_refusal_under_a_variant_that_does_not_charge_from_the_grid_names_each_variant_that_does(
    case: _Case,
) -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(case.config, grid_charging=_GRID_CHARGING, tariff=TariffConfig.economy_7())

    remedies = str(refused.value).partition("remove grid_charging, or use ")[2]
    expected = sorted(each.config.strategy_type for each in _GRID_CHARGING_CASES)
    assert sorted(remedies.split(" or ")) == expected, str(refused.value)


@pytest.mark.parametrize("case", _GRID_CHARGING_CASES, ids=_ids(_GRID_CHARGING_CASES))
def test_grid_charging_without_a_tariff_is_refused(case: _Case) -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(case.config, grid_charging=_GRID_CHARGING, tariff=None)

    for named in ["grid_charging", f"'{case.config.strategy_type}'", "tariff"]:
        assert named in str(refused.value), (named, str(refused.value))


@pytest.mark.parametrize("case", _GRID_CHARGING_CASES, ids=_ids(_GRID_CHARGING_CASES))
def test_a_variant_that_charges_from_the_grid_builds_with_grid_charging_on_a_tariff(case: _Case) -> None:
    strategy = build_dispatch_strategy(case.config, grid_charging=_GRID_CHARGING, tariff=TariffConfig.economy_7())

    assert isinstance(strategy, case.strategy_class)


_LONDON = ZoneInfo("Europe/London")

_EVENT = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17,))
"""An event on 2024-01-15 from 17:00 to 18:00."""


def _decide_on_a_one_kw_shortfall(strategy: DispatchStrategy, timestamp: datetime) -> DispatchDecision:
    return strategy.decide_action(
        timestamp=timestamp,
        generation_kw=0.0,
        demand_kw=1.0,
        battery_soc_kwh=2.5,
        battery_capacity_kwh=5.0,
        timestep_minutes=1.0,
    )


@pytest.mark.parametrize("case", _CASES, ids=_ids(_CASES))
def test_with_no_event_windows_the_built_strategy_is_the_unwrapped_one(case: _Case) -> None:
    tariff = TariffConfig.economy_7()

    strategy = build_dispatch_strategy(case.config, grid_charging=None, tariff=tariff, event_discharge=())

    assert type(strategy) is case.strategy_class
    assert strategy.name == build_dispatch_strategy(case.config, grid_charging=None, tariff=tariff).name


@pytest.mark.parametrize("case", _CASES, ids=_ids(_CASES))
def test_event_windows_wrap_the_built_strategy_at_the_batterys_discharge_limit(case: _Case) -> None:
    tariff = TariffConfig.economy_7()
    unwrapped = build_dispatch_strategy(case.config, grid_charging=None, tariff=tariff)

    strategy = build_dispatch_strategy(
        case.config, grid_charging=None, tariff=tariff, event_discharge=(_EVENT,), max_discharge_kw=2.5
    )

    assert isinstance(strategy, EventDischargeStrategy)
    assert strategy.name == f"event_discharge({case.config.strategy_type})"
    in_the_event = _decide_on_a_one_kw_shortfall(strategy, datetime(2024, 1, 15, 17, 30, tzinfo=_LONDON))
    assert in_the_event.export_kw == 1.5
    noon = datetime(2024, 1, 15, 12, 0, tzinfo=_LONDON)
    assert _decide_on_a_one_kw_shortfall(strategy, noon) == _decide_on_a_one_kw_shortfall(unwrapped, noon)


@pytest.mark.parametrize("case", _NON_GRID_CHARGING_CASES, ids=_ids(_NON_GRID_CHARGING_CASES))
def test_a_wrapped_build_refuses_grid_charging_naming_its_base(case: _Case) -> None:
    with pytest.raises(
        ConfigurationError, match=f"dispatch strategy '{case.config.strategy_type}' does not charge from the grid"
    ):
        build_dispatch_strategy(
            case.config,
            grid_charging=_GRID_CHARGING,
            tariff=TariffConfig.economy_7(),
            event_discharge=(_EVENT,),
            max_discharge_kw=2.5,
        )


def test_event_windows_without_a_discharge_limit_are_refused_naming_both() -> None:
    with pytest.raises(ConfigurationError) as refused:
        build_dispatch_strategy(
            SelfConsumptionStrategyConfig(), grid_charging=None, tariff=None, event_discharge=(_EVENT,)
        )

    for named in ["event_discharge", "max_discharge_kw"]:
        assert named in str(refused.value), (named, str(refused.value))


def test_with_no_event_windows_with_event_discharge_returns_the_strategy_itself() -> None:
    strategy = SelfConsumptionStrategy()

    assert with_event_discharge(strategy, (), max_discharge_kw=2.5) is strategy


def test_with_event_windows_with_event_discharge_wraps_the_strategy() -> None:
    strategy = TOUOptimizedStrategy([(16, 20)])

    wrapped = with_event_discharge(strategy, (_EVENT,), max_discharge_kw=2.5)

    assert isinstance(wrapped, EventDischargeStrategy)
    assert wrapped.name == "event_discharge(tou_optimized)"
