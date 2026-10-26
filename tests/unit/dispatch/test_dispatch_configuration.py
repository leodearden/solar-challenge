# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the dispatch-configuration types: GridChargeConfig and the strategy configs.

Each strategy config is a frozen variant of the tagged union DispatchStrategyConfig. Its tag
is its strategy_type field, which no constructor takes, and STRATEGY_CONFIG_BY_TYPE maps each
tag to its variant. A variant refuses what its strategy's constructor refuses, with the same
ConfigurationError: one validator per rule, at both entry points.
"""

import dataclasses
import typing
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import (
    STRATEGY_CONFIG_BY_TYPE,
    DispatchStrategyConfig,
    GridChargeConfig,
    PeakShavingStrategy,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategy,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from tests._unusable_numbers import UNUSABLE_NUMBERS

_EXAMPLES = (
    SelfConsumptionStrategyConfig(),
    TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
    PeakShavingStrategyConfig(import_limit_kw=3.0),
)
"""One example of each variant of DispatchStrategyConfig."""


def _tag(example: Any) -> str:
    """The test id of an example: its tag."""
    return str(example.strategy_type)


def _init_fields(example: Any) -> dict[str, Any]:
    """The fields of a variant its constructor takes, by name."""
    return {each.name: getattr(example, each.name) for each in dataclasses.fields(example) if each.init}


def _refusal(build: Callable[[], object]) -> tuple[type[BaseException], str]:
    """The type and message of the exception *build* raises."""
    with pytest.raises(Exception) as raised:
        build()
    return type(raised.value), str(raised.value)


class TestTheUnion:
    """DispatchStrategyConfig is the union of the variants, and STRATEGY_CONFIG_BY_TYPE its tag table."""

    def test_the_examples_cover_the_union(self) -> None:
        assert {type(example) for example in _EXAMPLES} == set(typing.get_args(DispatchStrategyConfig))

    def test_each_variant_is_tagged_with_its_strategy_type(self) -> None:
        assert [example.strategy_type for example in _EXAMPLES] == [
            "self_consumption",
            "tou_optimized",
            "peak_shaving",
        ]

    def test_the_tag_table_maps_each_tag_to_its_variant(self) -> None:
        assert dict(STRATEGY_CONFIG_BY_TYPE) == {example.strategy_type: type(example) for example in _EXAMPLES}

    def test_the_tag_table_is_read_only(self) -> None:
        with pytest.raises(TypeError):
            STRATEGY_CONFIG_BY_TYPE["turbo"] = SelfConsumptionStrategyConfig  # type: ignore[index]


class TestTheVariants:
    """Each variant is a frozen value: its tag is no constructor argument, and its field tree is its block."""

    @pytest.mark.parametrize("example", _EXAMPLES, ids=_tag)
    def test_no_variant_takes_its_tag_as_a_constructor_argument(self, example: Any) -> None:
        with pytest.raises(TypeError, match="strategy_type"):
            type(example)(**_init_fields(example), strategy_type=example.strategy_type)

    @pytest.mark.parametrize(
        ("example", "field_tree"),
        [
            pytest.param(
                SelfConsumptionStrategyConfig(), {"strategy_type": "self_consumption"}, id="self_consumption"
            ),
            pytest.param(
                TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
                {"peak_hours": ((16, 19),), "strategy_type": "tou_optimized"},
                id="tou_optimized",
            ),
            pytest.param(
                PeakShavingStrategyConfig(import_limit_kw=3.0),
                {"import_limit_kw": 3.0, "strategy_type": "peak_shaving"},
                id="peak_shaving",
            ),
        ],
    )
    def test_a_variants_field_tree_is_its_tag_and_its_own_fields(
        self, example: Any, field_tree: dict[str, Any]
    ) -> None:
        assert dataclasses.asdict(example) == field_tree

    @pytest.mark.parametrize("example", _EXAMPLES, ids=_tag)
    def test_a_variant_refuses_a_field_assignment(self, example: Any) -> None:
        for each in dataclasses.fields(example):
            with pytest.raises(dataclasses.FrozenInstanceError):
                setattr(example, each.name, getattr(example, each.name))

    @pytest.mark.parametrize("example", _EXAMPLES, ids=_tag)
    def test_equal_variants_hash_equal(self, example: Any) -> None:
        twin = dataclasses.replace(example)

        assert twin == example
        assert twin is not example
        assert hash(twin) == hash(example)

    @pytest.mark.parametrize("example", _EXAMPLES, ids=_tag)
    def test_a_battery_config_carrying_a_variant_is_hashable(self, example: Any) -> None:
        battery = BatteryConfig(5.0, dispatch_strategy=example, grid_charging=GridChargeConfig(0.8))

        assert hash(battery) == hash(dataclasses.replace(battery))


class TestGridChargeConfig:
    """GridChargeConfig's target_soc_fraction is in (0, 1], 0.9 by default."""

    def test_the_default_target_is_0_9(self) -> None:
        assert GridChargeConfig().target_soc_fraction == 0.9

    @pytest.mark.parametrize("target", [0.8, 1.0, 0.01])
    def test_a_target_in_0_to_1_is_kept(self, target: float) -> None:
        assert GridChargeConfig(target_soc_fraction=target).target_soc_fraction == target

    @pytest.mark.parametrize(
        "value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word"), pytest.param(None, id="null")]
    )
    def test_a_target_that_is_not_a_finite_number_is_refused_naming_it(self, value: object) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            GridChargeConfig(target_soc_fraction=value)

        assert str(refusal.value) == f"target_soc_fraction must be a finite number, got {value!r}"

    @pytest.mark.parametrize("target", [0.0, -0.1, 1.5])
    def test_a_target_outside_0_to_1_is_refused_naming_its_bounds(self, target: float) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            GridChargeConfig(target_soc_fraction=target)

        assert str(refusal.value) == f"target_soc_fraction must be greater than 0 and at most 1, got {target!r}"

    @pytest.mark.parametrize(
        ("value", "held"),
        [
            pytest.param(1, 1.0, id="whole-number"),
            pytest.param("0.5", 0.5, id="quoted"),
            pytest.param(np.float64(0.8), 0.8, id="numpy"),
        ],
    )
    def test_it_holds_the_target_as_the_float_it_reads(self, value: object, held: float) -> None:
        target = GridChargeConfig(target_soc_fraction=value).target_soc_fraction

        assert target == held
        assert type(target) is float

    def test_it_refuses_a_field_assignment(self) -> None:
        with pytest.raises(dataclasses.FrozenInstanceError):
            GridChargeConfig().target_soc_fraction = 0.5  # type: ignore[misc]


class TestOneValidatorPerRule:
    """A variant and its strategy's constructor refuse the same values with the same ConfigurationError."""

    @pytest.mark.parametrize(
        "peak_hours",
        [
            pytest.param([], id="no-window"),
            pytest.param([(25, 28)], id="after-midnight"),
            pytest.param([(-1, 5)], id="negative-start"),
            pytest.param([(20, 17)], id="start-after-end"),
            pytest.param([(17, 17)], id="start-at-end"),
            pytest.param([(16, 25)], id="end-after-midnight"),
        ],
    )
    def test_invalid_peak_hours_are_refused_alike(self, peak_hours: list[tuple[int, int]]) -> None:
        refusal = _refusal(lambda: TOUOptimizedStrategyConfig(peak_hours=tuple(peak_hours)))

        assert refusal == _refusal(lambda: TOUOptimizedStrategy(peak_hours=list(peak_hours)))
        refusal_type, message = refusal
        assert refusal_type is ConfigurationError
        assert "peak_hours" in message
        for start, end in peak_hours:
            assert f"({start}, {end})" in message

    @pytest.mark.parametrize("peak_hours", [[(0, 24)], [(7, 9), (17, 20)], [(23, 24)]])
    def test_valid_peak_hours_build_both(self, peak_hours: list[tuple[int, int]]) -> None:
        assert TOUOptimizedStrategyConfig(peak_hours=tuple(peak_hours)).peak_hours == tuple(peak_hours)
        assert TOUOptimizedStrategy(peak_hours=list(peak_hours)).name == "tou_optimized"

    @pytest.mark.parametrize("import_limit_kw", [0.0, -5.0])
    def test_a_limit_that_is_not_positive_is_refused_alike(self, import_limit_kw: float) -> None:
        refusal = _refusal(lambda: PeakShavingStrategyConfig(import_limit_kw=import_limit_kw))

        assert refusal == _refusal(lambda: PeakShavingStrategy(import_limit_kw=import_limit_kw))
        assert refusal == (ConfigurationError, f"import_limit_kw must be greater than 0, got {import_limit_kw!r}")

    @pytest.mark.parametrize(
        "value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word"), pytest.param(None, id="null")]
    )
    def test_a_limit_that_is_not_a_finite_number_is_refused_alike(self, value: object) -> None:
        assert (
            _refusal(lambda: PeakShavingStrategyConfig(import_limit_kw=value))
            == _refusal(lambda: PeakShavingStrategy(import_limit_kw=value))
            == (ConfigurationError, f"import_limit_kw must be a finite number, got {value!r}")
        )

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(2, id="whole-number"),
            pytest.param("2.0", id="quoted"),
            pytest.param(np.float64(2.0), id="numpy"),
        ],
    )
    def test_both_hold_the_limit_as_the_float_they_read(self, value: object) -> None:
        """Of a 3 kW shortfall, the strategy sheds the 1 kW over its 2 kW limit."""
        held = PeakShavingStrategyConfig(import_limit_kw=value).import_limit_kw
        decision = PeakShavingStrategy(import_limit_kw=value).decide_action(
            timestamp=datetime(2024, 1, 15, 17, 0),
            generation_kw=0.0,
            demand_kw=3.0,
            battery_soc_kwh=2.5,
            battery_capacity_kwh=5.0,
        )

        assert held == 2.0
        assert type(held) is float
        assert decision.discharge_kw == 1.0

    def test_a_positive_limit_builds_both(self) -> None:
        assert PeakShavingStrategyConfig(import_limit_kw=0.1).import_limit_kw == 0.1
        assert PeakShavingStrategy(import_limit_kw=0.1).name == "peak_shaving"
