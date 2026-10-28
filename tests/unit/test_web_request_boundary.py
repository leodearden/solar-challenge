# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.request_boundary, called directly: its request-body rules, a JSON object, only recognised keys and text that encodes as UTF-8, and its location resolver."""

import pytest

pytest.importorskip("flask")

from flask import Flask

from solar_challenge.location import Location
from solar_challenge.web.request_boundary import (
    LOCATION_PRESETS,
    NotAJsonObject,
    refuse_unrecognised_keys,
    request_json_object,
    require_encodable_text,
    require_json_object,
    resolve_location,
)


def _assert_names_location_the_accepted_forms_and_the_value(
    refusal: ValueError, value: object
) -> None:
    """Assert that *refusal* names the location field and the forms resolve_location accepts, 'lat,lon' coordinates and every LOCATION_PRESETS key, and ends naming *value* by its repr, as sent."""
    message = str(refusal)
    assert message.startswith("location")
    assert "lat,lon" in message
    for key in LOCATION_PRESETS:
        assert repr(key) in message
    assert message.endswith(repr(value))


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


class TestRequestJsonObject:
    def test_a_body_nested_past_the_recursion_limit_reads_as_unparseable(self) -> None:
        """get_json(silent=True) swallows only ValueError, so the RecursionError of parsing is read as NoneType."""
        with Flask(__name__).test_request_context(
            data="[" * 100000, content_type="application/json", method="POST"
        ):
            with pytest.raises(NotAJsonObject, match="got NoneType"):
                request_json_object()


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


class TestRequireEncodableText:
    """require_encodable_text passes text that encodes as UTF-8 and refuses text holding a lone surrogate."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("run-2kw", id="ascii"),
            pytest.param("", id="empty"),
            pytest.param("Café ☀ 😀", id="non-ascii-and-astral"),
        ],
    )
    def test_text_that_encodes_is_returned_as_given(self, text: str) -> None:
        assert require_encodable_text(text, "points[0].run_id") is text

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("\ud800", id="a-lone-high-surrogate"),
            pytest.param("run-\udc00", id="a-lone-low-surrogate-after-text"),
        ],
    )
    def test_text_holding_a_lone_surrogate_is_refused_naming_what_and_the_text(self, text: str) -> None:
        with pytest.raises(ValueError) as refusal:
            require_encodable_text(text, "points[1].run_id")
        assert str(refusal.value) == (
            f"points[1].run_id must be text that encodes as UTF-8, holding no lone surrogate; got {text!r}"
        )


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
        _assert_names_location_the_accepted_forms_and_the_value(refusal.value, text)

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
        _assert_names_location_the_accepted_forms_and_the_value(refusal.value, value)

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
