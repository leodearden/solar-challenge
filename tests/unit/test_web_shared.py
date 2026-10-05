# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.shared's request-body rules, called directly: a JSON object, and only recognised keys."""

import pytest

pytest.importorskip("flask")

from solar_challenge.web.shared import (
    NotAJsonObject,
    refuse_unrecognised_keys,
    require_json_object,
)


class TestRequireJsonObject:
    """require_json_object passes a JSON object through and refuses every other JSON value."""

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param({}, id="empty"),
            pytest.param({"pv_kw": 4.0}, id="non-empty"),
        ],
    )
    def test_a_json_object_is_returned_as_given(self, value: dict) -> None:
        """A JSON object is returned as the same object, not a copy."""
        assert require_json_object(value, "Home config") is value

    @pytest.mark.parametrize(
        ("what", "value", "type_name"),
        [
            pytest.param("Request body", [1], "list", id="request-body-array"),
            pytest.param("Request body", None, "NoneType", id="request-body-null"),
            pytest.param("Home config", "x", "str", id="home-config-string"),
            pytest.param("Home config", "", "str", id="home-config-empty-string"),
            pytest.param("base_config", 5, "int", id="base-config-integer"),
            pytest.param("base_config", 4.5, "float", id="base-config-float"),
            pytest.param("Builder form", True, "bool", id="builder-form-boolean"),
            pytest.param("Builder form", [], "list", id="builder-form-empty-array"),
        ],
    )
    def test_any_other_value_is_refused_naming_what_and_its_type(
        self, what: str, value: object, type_name: str
    ) -> None:
        """Any other value, falsy ones included, is refused naming *what* verbatim and the type received."""
        with pytest.raises(NotAJsonObject) as exc_info:
            require_json_object(value, what)
        assert str(exc_info.value) == f"{what} must be a JSON object, got {type_name}"

    def test_the_refusal_is_a_value_error(self) -> None:
        """Every web caller answers a ValueError, with HTTP 400 or an assistant tool_result error."""
        with pytest.raises(ValueError):
            require_json_object("x", "Home config")


class TestRefuseUnrecognisedKeys:
    """refuse_unrecognised_keys passes a body of recognised keys and refuses one with any other key."""

    def test_a_body_of_recognised_keys_is_not_refused(self) -> None:
        """A subset of the recognised keys is enough; none is required."""
        refuse_unrecognised_keys({"pv_kw": 4.0}, frozenset({"pv_kw", "days"}), "Home config")

    def test_any_other_key_is_refused_naming_each_and_listing_the_recognised(self) -> None:
        """*what*, the label require_json_object takes, lower-cased; each unrecognised key as its repr, sorted; then the recognised keys, sorted."""
        with pytest.raises(ValueError) as exc_info:
            refuse_unrecognised_keys(
                {"pv_kw": 4.0, "tarif": {}, "heat_pump": "ASHP"},
                frozenset({"pv_kw", "days"}),
                "Fleet form",
            )
        assert str(exc_info.value) == (
            "Unrecognised fleet form keys: 'heat_pump', 'tarif'; recognised keys: days, pv_kw"
        )
