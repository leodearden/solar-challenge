# SPDX-License-Identifier: AGPL-3.0-or-later
"""scenario_blocks' refusal toolkit: every refusal the grammar writes reads '<block label>: <problem>'."""

import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import (
    block_label,
    constructed,
    refusal,
    refuse_missing_keys,
    refuse_unrecognised_keys,
    require_list,
    require_mapping,
)


class TestRefusal:
    """refusal builds, and does not raise, the ConfigurationError of the block at a path."""

    def test_it_returns_the_refusal_naming_the_block(self) -> None:
        built = refusal("home.pv", "x")

        assert isinstance(built, ConfigurationError)
        assert str(built) == "home.pv: x"

    def test_the_top_level_is_named_as_such(self) -> None:
        assert str(refusal("", "x")) == f"{block_label('')}: x" == "the top level: x"


class TestRequireMapping:
    """require_mapping returns a mapping it is given and refuses anything else, naming its type."""

    def test_it_returns_the_mapping(self) -> None:
        block = {"rate_per_kwh": 0.25}

        assert require_mapping("home.tariff", block) is block

    @pytest.mark.parametrize(
        ("data", "type_name"),
        [
            pytest.param("flat", "str", id="str"),
            pytest.param([1], "list", id="list"),
            pytest.param(5, "int", id="int"),
            pytest.param(None, "NoneType", id="null"),
        ],
    )
    def test_a_value_that_is_no_mapping_is_refused_naming_its_type(self, data: object, type_name: str) -> None:
        with pytest.raises(ConfigurationError) as refused:
            require_mapping("home.tariff", data)

        assert str(refused.value) == f"home.tariff: must be a mapping, got {type_name}"

    def test_a_top_level_that_is_no_mapping_is_refused_as_the_top_level(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            require_mapping("", ["a", "b"])

        assert str(refused.value) == "the top level: must be a mapping, got list"


class TestRequireList:
    """require_list returns a list it is given and refuses anything else, naming its type."""

    def test_it_returns_the_list(self) -> None:
        homes = [{}, {}]

        assert require_list("homes", homes) is homes

    @pytest.mark.parametrize(
        ("data", "type_name"),
        [
            pytest.param(5, "int", id="int"),
            pytest.param({"a": 1}, "dict", id="dict"),
            pytest.param("a", "str", id="str"),
            pytest.param(None, "NoneType", id="null"),
        ],
    )
    def test_a_value_that_is_no_list_is_refused_naming_its_type(self, data: object, type_name: str) -> None:
        with pytest.raises(ConfigurationError) as refused:
            require_list("homes", data)

        assert str(refused.value) == f"homes: must be a list, got {type_name}"


class TestRefuseUnrecognisedKeys:
    """refuse_unrecognised_keys returns a mapping of recognised keys and refuses one holding any other."""

    def test_it_returns_a_mapping_of_recognised_keys(self) -> None:
        block = {"x": 1}

        assert refuse_unrecognised_keys("home.pv", block, {"x", "y"}) is block

    def test_unrecognised_keys_are_refused_sorted_beside_the_recognised_ones(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            refuse_unrecognised_keys("home.pv", {"b": 1, "x": 2, "a": 3}, {"y", "x"})

        assert str(refused.value) == "home.pv: unrecognised keys 'a', 'b'; recognised keys: x, y"

    def test_a_value_that_is_no_mapping_is_refused_as_require_mapping_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            refuse_unrecognised_keys("home.pv", 4.0, {"x"})

        assert str(refused.value) == "home.pv: must be a mapping, got float"


class TestRefuseMissingKeys:
    """refuse_missing_keys refuses a block that leaves out keys it needs, naming each in the order given."""

    def test_no_missing_key_is_no_refusal(self) -> None:
        assert refuse_missing_keys("home.tariff", []) is None

    def test_the_missing_keys_are_named_in_the_order_given(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            refuse_missing_keys("home.tariff.periods[0]", ["end_time", "rate_per_kwh"])

        assert str(refused.value) == "home.tariff.periods[0]: requires 'end_time', 'rate_per_kwh'"


def test_a_construction_refusal_keeps_the_types_refusal_as_its_cause() -> None:
    """constructed's '<label>: <message>' refusal is raised from the type's own refusal."""
    with pytest.raises(ConfigurationError) as refused:
        constructed("home.pv", PVConfig, capacity_kw=4.0, azimuth=400)

    assert isinstance(refused.value.__cause__, ConfigurationError)
    assert str(refused.value) == f"home.pv: {refused.value.__cause__}"
