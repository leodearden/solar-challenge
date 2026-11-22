# SPDX-License-Identifier: AGPL-3.0-or-later
"""SweepSpec, the one sweep value generator, and its SweepMode, how a sweep spaces its points from min to max."""

import math
import sys
from typing import Any

import pytest
import yaml

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    SweepMode,
    SweepSpec,
    detect_sweep_spec,
    parse_fleet_distribution_config,
)
from tests._names_as_a_word import names_as_a_word
from tests._repository_paths import SCENARIOS_DIR

_MULTIPLIER_PATH = "fleet_distribution.battery.capacity_kwh.multiplier"

#: Values no mode names: a word that is no mode, a member's name rather than its value, null, and a number.
_NOT_A_MODE = [
    pytest.param("log", id="a-word-that-is-no-mode"),
    pytest.param("GEOMETRIC", id="a-members-name"),
    pytest.param(None, id="null"),
    pytest.param(1, id="a-number"),
]

#: Finite ends whose points are not all finite: an infinite ratio, an infinite step, and a power past the largest float.
_ENDS_WITH_POINTS_NOT_ALL_FINITE = [
    pytest.param(1e-300, 1e300, 3, "geometric", id="geometric-whose-ratio-overflows"),
    pytest.param(-1e308, 1e308, 3, "linear", id="linear-whose-step-overflows"),
    pytest.param(1.0, sys.float_info.max, 5, "geometric", id="geometric-whose-power-overflows"),
]


def _words_not_named(message: str, *words: object) -> list[object]:
    """The *words* that *message* does not name as words of their own, as names_as_a_word reads them."""
    return [word for word in words if not names_as_a_word(message, word)]


def _swept_fleet(**multiplier: object) -> dict[str, Any]:
    """A two-home fleet_distribution: block whose battery capacity is its PV capacity times a sweep giving *multiplier*'s keys."""
    return {
        "n_homes": 2,
        "pv": {"capacity_kw": 4.0},
        "battery": {
            "capacity_kwh": {
                "type": "proportional_to",
                "source": "pv.capacity_kw",
                "multiplier": {"type": "sweep", **multiplier},
            }
        },
    }


class TestTheMode:
    """A spec's mode is a SweepMode: geometric unless it names another, and a value naming none is refused."""

    def test_a_spec_that_names_no_mode_is_geometric(self) -> None:
        assert SweepSpec(1, 4, 3).mode is SweepMode.GEOMETRIC

    def test_a_spec_given_a_modes_string_holds_the_mode_it_names(self) -> None:
        assert SweepSpec(1, 4, 3, "linear").mode is SweepMode.LINEAR
        assert SweepSpec(1, 4, 3, "linear") == SweepSpec(1, 4, 3, SweepMode.LINEAR)

    @pytest.mark.parametrize("bad", _NOT_A_MODE)
    def test_a_spec_given_a_value_naming_no_mode_is_refused_naming_the_value_and_both_modes(self, bad: object) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            SweepSpec(1, 4, 3, mode=bad)

        assert _words_not_named(str(refusal.value), "mode", repr(bad), "linear", "geometric") == []

    def test_parse_returns_the_mode_a_string_or_a_member_names(self) -> None:
        assert SweepMode.parse("geometric") is SweepMode.GEOMETRIC
        assert SweepMode.parse(SweepMode.LINEAR) is SweepMode.LINEAR

    def test_parse_refuses_a_value_naming_no_mode_as_a_spec_given_it_is_refused(self) -> None:
        with pytest.raises(ConfigurationError) as parse_refusal:
            SweepMode.parse("log")
        with pytest.raises(ConfigurationError) as construction_refusal:
            SweepSpec(1, 4, 3, mode="log")

        assert str(parse_refusal.value) == str(construction_refusal.value)


class TestTheYamlReader:
    """A ``type: sweep`` multiplier is built as a SweepSpec from the keys it gives, so a sweep naming no mode takes the field's default."""

    def test_a_sweep_naming_no_mode_is_geometric(self) -> None:
        sweep = detect_sweep_spec(parse_fleet_distribution_config(_swept_fleet(min=0.5, max=2.0, steps=3)))

        assert sweep == SweepSpec(min=0.5, max=2.0, steps=3)
        assert sweep is not None and sweep.mode is SweepMode.GEOMETRIC

    def test_a_sweep_naming_linear_is_linear(self) -> None:
        sweep = detect_sweep_spec(
            parse_fleet_distribution_config(_swept_fleet(min=0.5, max=2.0, steps=3, mode="linear"))
        )

        assert sweep is not None and sweep.mode is SweepMode.LINEAR

    def test_a_sweep_naming_no_mode_it_knows_is_refused_naming_the_multiplier_and_the_value(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config(_swept_fleet(min=0.5, max=2.0, steps=3, mode="log"))

        assert _words_not_named(str(refusal.value), _MULTIPLIER_PATH, "mode", "'log'") == []


class TestThePoints:
    """A spec's points run from min to max in steps points, as a tuple: a list is never equal to the tuple literal each is compared with."""

    def test_a_geometric_sweeps_points_grow_by_a_constant_ratio(self) -> None:
        assert SweepSpec(1, 4, 3).get_values() == (1.0, 2.0, 4.0)

    def test_a_linear_sweeps_points_grow_by_a_constant_step(self) -> None:
        assert SweepSpec(1, 4, 3, "linear").get_values() == (1.0, 2.5, 4.0)


class TestFinitePoints:
    """A spec is refused unless every one of its points is finite, naming both its ends, so no sweep reaches a home as an infinite or undefined value."""

    @pytest.mark.parametrize(("low", "high", "steps", "mode"), _ENDS_WITH_POINTS_NOT_ALL_FINITE)
    def test_a_spec_whose_points_are_not_all_finite_is_refused_naming_its_ends(
        self, low: float, high: float, steps: int, mode: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            SweepSpec(low, high, steps, mode)

        assert _words_not_named(str(refusal.value), "min", "max", low, high) == []

    def test_a_spec_ending_at_the_largest_float_builds_when_its_points_are_finite(self) -> None:
        assert math.isfinite(SweepSpec(1.0, sys.float_info.max, 3).get_values()[-1])

    def test_a_yaml_sweep_whose_points_are_not_all_finite_is_refused_naming_the_multiplier_and_its_ends(self) -> None:
        """The shipped proportional battery sweep, its geometric multiplier from 1e-300 to 1e300 in 3 steps."""
        document = yaml.safe_load((SCENARIOS_DIR / "bristol-phase1-proportional-battery-sweep.yaml").read_text())
        document["fleet_distribution"]["battery"]["capacity_kwh"]["multiplier"].update(min=1.0e-300, max=1.0e300, steps=3)

        with pytest.raises(ConfigurationError) as refusal:
            parse_fleet_distribution_config(document["fleet_distribution"])

        assert _words_not_named(str(refusal.value), _MULTIPLIER_PATH, "min", "max") == []


class TestTheKeptChecks:
    """A geometric sweep starts above zero, and every sweep ends above where it starts."""

    def test_a_geometric_sweep_from_zero_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="geometric mode requires min > 0"):
            SweepSpec(0, 4, 3)

    @pytest.mark.parametrize(
        ("low", "high"),
        [pytest.param(4, 4, id="max-at-min"), pytest.param(4, 1, id="max-below-min")],
    )
    def test_a_sweep_whose_max_is_not_above_its_min_is_refused(self, low: float, high: float) -> None:
        with pytest.raises(ConfigurationError, match="max must be greater than min"):
            SweepSpec(low, high, 3, "linear")

    def test_a_linear_sweep_from_zero_builds(self) -> None:
        assert SweepSpec(0, 4, 3, "linear").min == 0.0
