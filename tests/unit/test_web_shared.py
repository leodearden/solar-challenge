# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.shared's JSON-object rule and location resolver, called directly."""

import pytest

pytest.importorskip("flask")

from solar_challenge.location import Location
from solar_challenge.web.shared import (
    LOCATION_PRESETS,
    NotAJsonObject,
    require_json_object,
    resolve_location,
)


def _accepted_forms_refusal(value: object) -> str:
    """The refusal resolve_location gives *value*, naming it and the forms it accepts."""
    return (
        "location must be 'lat,lon' coordinates or one of "
        f"{', '.join(map(repr, LOCATION_PRESETS))}, got {value!r}"
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


class TestResolveLocation:
    """resolve_location returns the location a preset name or 'lat,lon' coordinates name, and refuses every other value naming it."""

    @pytest.mark.parametrize(
        ("spelling", "key"),
        [
            pytest.param(spelling, key, id=f"{key}-{form}")
            for key in LOCATION_PRESETS
            for form, spelling in (
                ("as-keyed", key),
                ("upper-case", key.upper()),
                ("title-case-padded", f"  {key.title()} "),
            )
        ],
    )
    def test_a_preset_name_resolves_to_that_preset_in_any_case_and_with_surrounding_whitespace(
        self, spelling: str, key: str
    ) -> None:
        """A LOCATION_PRESETS key resolves to its preset, whatever its case and the whitespace around it."""
        assert resolve_location(spelling) == LOCATION_PRESETS[key]

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("51.5,-0.1", id="bare"),
            pytest.param(" 51.5 , -0.1 ", id="padded"),
        ],
    )
    def test_lat_lon_coordinates_resolve_to_a_location_at_them(self, text: str) -> None:
        """'lat,lon' coordinates, with or without whitespace around each number, resolve to a Location at them."""
        assert resolve_location(text) == Location(latitude=51.5, longitude=-0.1)

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("Paris", id="unknown-place"),
            pytest.param("lodnon", id="typo"),
            pytest.param("51.5;-0.1", id="wrong-separator"),
            pytest.param("51.5,-0.1,11", id="lat-lon-altitude"),
            pytest.param("51.5", id="one-number"),
            pytest.param("north,west", id="two-words"),
            pytest.param("", id="empty"),
        ],
    )
    def test_a_string_of_any_other_form_is_refused_naming_it_and_the_accepted_forms(
        self, text: str
    ) -> None:
        """A string that is neither a preset name nor 'lat,lon' coordinates is refused naming it as sent and the accepted forms, never read as Bristol."""
        with pytest.raises(ValueError) as refusal:
            resolve_location(text)
        assert str(refusal.value) == _accepted_forms_refusal(text)

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(None, id="null"),
            pytest.param(5, id="integer"),
            pytest.param(51.5, id="float"),
            pytest.param(True, id="boolean"),
            pytest.param([51.5, -0.1], id="array"),
            pytest.param({"latitude": 51.5}, id="object"),
        ],
    )
    def test_a_value_that_is_not_a_string_is_refused_naming_it_and_the_accepted_forms(
        self, value: object
    ) -> None:
        """A value that is not a string gets the same refusal, naming the value by its repr: None, not 'None'."""
        with pytest.raises(ValueError) as refusal:
            resolve_location(value)
        assert str(refusal.value) == _accepted_forms_refusal(value)

    @pytest.mark.parametrize(
        ("text", "latitude", "longitude"),
        [
            pytest.param("95,0", 95.0, 0.0, id="latitude-above-90"),
            pytest.param("0,181", 0.0, 181.0, id="longitude-above-180"),
            pytest.param("nan,0", float("nan"), 0.0, id="nan-latitude"),
        ],
    )
    def test_coordinates_location_refuses_are_refused_with_its_own_message(
        self, text: str, latitude: float, longitude: float
    ) -> None:
        """'lat,lon' coordinates that Location refuses are refused with Location's own message, not the accepted-forms one, since they are of an accepted form."""
        with pytest.raises(ValueError) as location_refusal:
            Location(latitude=latitude, longitude=longitude)
        with pytest.raises(ValueError) as refusal:
            resolve_location(text)
        assert str(refusal.value) == str(location_refusal.value)
