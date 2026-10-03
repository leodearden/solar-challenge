# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.shared's JSON-object rule, called directly."""

import pytest

pytest.importorskip("flask")

from solar_challenge.web.shared import NotAJsonObject, require_json_object


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
