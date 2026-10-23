# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for config.substitute_config_variables: the ${NAME} and ${NAME:default} placeholders it replaces and those it refuses."""

import copy
from typing import Any

import pytest

from solar_challenge.config import substitute_config_variables
from solar_challenge.errors import ConfigurationError


def _battery_ratio_fleet(multiplier: object) -> dict[str, Any]:
    """Return a fleet file of two homes with 4 kW of PV, each with a battery of *multiplier* kWh per kW of PV."""
    return {
        "fleet_distribution": {
            "n_homes": 2,
            "seed": 1,
            "pv": {"capacity_kw": 4.0},
            "battery": {
                "capacity_kwh": {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": multiplier}
            },
        }
    }


class TestPlaceholdersThatAreWholeValues:
    """A placeholder that is the whole of a string value is replaced by its supplied value, else by its default, and every other value is kept."""

    def test_a_supplied_variable_replaces_its_placeholder(self) -> None:
        assert substitute_config_variables(
            _battery_ratio_fleet("${BATTERY_RATIO:1.0}"), {"BATTERY_RATIO": 0.5}
        ) == _battery_ratio_fleet(0.5)

    def test_a_placeholder_whose_variable_is_not_supplied_takes_its_default(self) -> None:
        assert substitute_config_variables({"a": "${A}", "b": "${B:2.5}"}, {"A": 1.0}) == {"a": 1.0, "b": 2.5}

    def test_a_placeholder_in_a_list_is_replaced(self) -> None:
        document = {"homes": [{"pv": {"capacity_kw": "${X}"}}, {"pv": {"capacity_kw": 3.0}}]}

        assert substitute_config_variables(document, {"X": 5.0}) == {
            "homes": [{"pv": {"capacity_kw": 5.0}}, {"pv": {"capacity_kw": 3.0}}]
        }

    def test_a_value_holding_no_placeholder_is_kept(self) -> None:
        """A $ and braces that form no placeholder are text like any other, not a malformed placeholder."""
        document = {
            "name": "Bristol",
            "note": "costs $5 {approx}",
            "n": 2,
            "f": 1.5,
            "flag": True,
            "none": None,
            "items": ["x", 1],
        }

        assert substitute_config_variables(document, {}) == document

    def test_the_document_read_is_left_unchanged(self) -> None:
        document = {"homes": [{"pv": {"capacity_kw": "${X}"}}]}
        unchanged = copy.deepcopy(document)

        substitute_config_variables(document, {"X": 5.0})

        assert document == unchanged


class TestASuppliedVariableNoPlaceholderNamesIsRefused:
    """A supplied variable that no placeholder names is refused, naming it and the document's placeholders at their key paths."""

    def test_a_misspelt_variable_is_refused_naming_it_and_the_documents_placeholders(self) -> None:
        """Unrefused, every value supplied for the misspelt name would leave the multiplier at its default."""
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables(_battery_ratio_fleet("${BATTERY_RATIO:1.0}"), {"BATTERY_RATI0": 0.5})

        assert str(refusal.value) == (
            "Variables with no placeholder in the document: 'BATTERY_RATI0'; "
            "its placeholders: 'BATTERY_RATIO' at fleet_distribution.battery.capacity_kwh.multiplier"
        )

    def test_a_misspelt_variable_for_a_placeholder_with_no_default_is_refused_naming_both(self) -> None:
        """The misspelt variable is refused before the placeholder it leaves without a value."""
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables({"a": "${X}"}, {"Y": 1.0})

        assert str(refusal.value) == "Variables with no placeholder in the document: 'Y'; its placeholders: 'X' at a"

    def test_a_variable_is_refused_when_the_document_holds_no_placeholders(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables({"n_homes": 2}, {"X": 1.0})

        assert str(refusal.value) == "Variables with no placeholder in the document: 'X'; it holds no placeholders"

    def test_every_unmatched_variable_is_named_in_sorted_order(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables({"a": "${A}", "b": "${B:2}"}, {"A": 1.0, "Z": 3.0, "Y": 4.0})

        assert str(refusal.value) == (
            "Variables with no placeholder in the document: 'Y', 'Z'; its placeholders: 'A' at a, 'B' at b"
        )


class TestAPlaceholderWithNoValueIsRefused:
    """A placeholder whose variable is neither supplied nor defaulted is refused, naming the variable and its key path."""

    def test_a_placeholder_neither_supplied_nor_defaulted_is_refused_naming_its_key_path(self) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables({"homes": [{"pv": {"capacity_kw": "${X}"}}]})

        assert str(refusal.value) == "homes[0].pv.capacity_kw: variable 'X' is not supplied and has no default"


class TestAMalformedPlaceholderIsRefused:
    """A malformed placeholder is refused as soon as its string is read, naming the variable and its key path."""

    @pytest.mark.parametrize(
        ("document", "variables", "message"),
        [
            pytest.param(
                {"name": "fleet-${BATTERY_RATIO}"},
                {"BATTERY_RATIO": 2.0},
                "name: variable 'BATTERY_RATIO' is inside the longer string 'fleet-${BATTERY_RATIO}'; "
                "a placeholder must be the whole value",
                id="suffix-with-the-variable-supplied",
            ),
            pytest.param(
                {"homes": [{"name": "home-${N:1}"}]},
                {},
                "homes[0].name: variable 'N' is inside the longer string 'home-${N:1}'; "
                "a placeholder must be the whole value",
                id="in-a-list-with-nothing-supplied",
            ),
            pytest.param(
                {"a": "${A}${B}"},
                {"A": 1.0, "B": 2.0},
                "a: variable 'A' is inside the longer string '${A}${B}'; a placeholder must be the whole value",
                id="two-placeholders",
            ),
        ],
    )
    def test_a_placeholder_inside_a_longer_string_is_refused_naming_the_variable_and_its_key_path(
        self, document: dict[str, Any], variables: dict[str, float], message: str
    ) -> None:
        """The refusal names the embedded placeholder, not the supplied variable it leaves with no placeholder."""
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables(document, variables)

        assert str(refusal.value) == message

    @pytest.mark.parametrize(
        ("document", "variables", "message"),
        [
            pytest.param(
                {"homes": [{"pv": {"capacity_kw": "${X:abc}"}}]},
                {},
                "homes[0].pv.capacity_kw: the default of variable 'X' must be a finite number, got 'abc'",
                id="word",
            ),
            pytest.param(
                {"homes": [{}, {"pv": {"capacity_kw": "${X:}"}}]},
                {},
                "homes[1].pv.capacity_kw: the default of variable 'X' must be a finite number, got ''",
                id="empty",
            ),
            pytest.param(
                {"pv": {"tilt": "${X:nan}"}},
                {},
                "pv.tilt: the default of variable 'X' must be a finite number, got 'nan'",
                id="nan",
            ),
            pytest.param(
                {"pv": {"tilt": "${X:inf}"}},
                {},
                "pv.tilt: the default of variable 'X' must be a finite number, got 'inf'",
                id="infinite",
            ),
            pytest.param(
                {"pv": {"capacity_kw": "${X:abc}"}},
                {"X": 1.0},
                "pv.capacity_kw: the default of variable 'X' must be a finite number, got 'abc'",
                id="supplied-variable",
            ),
        ],
    )
    def test_a_default_that_is_not_a_finite_number_is_refused_naming_the_variable_and_its_key_path(
        self, document: dict[str, Any], variables: dict[str, float], message: str
    ) -> None:
        """The default is read with the document, so it is refused even where a supplied value would replace it."""
        with pytest.raises(ConfigurationError) as refusal:
            substitute_config_variables(document, variables)

        assert str(refusal.value) == message
