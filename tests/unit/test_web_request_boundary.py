# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.request_boundary, called directly: its request-body rules, a JSON object, only recognised keys and text that encodes as UTF-8, and its location reader."""

from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask

from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location, parse_location
from solar_challenge.scenario_blocks import parse_location_block
from solar_challenge.web.request_boundary import (
    NotAJsonObject,
    read_location,
    refuse_unencodable_text,
    refuse_unrecognised_keys,
    request_json_object,
    require_encodable_text,
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


class TestRefuseUnencodableText:
    """refuse_unencodable_text refuses text require_encodable_text refuses and leaves any other value to its reader."""

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(None, id="null"),
            pytest.param(5, id="integer"),
            pytest.param(True, id="boolean"),
            pytest.param([chr(0xD800)], id="array-holding-a-lone-surrogate"),
            pytest.param({"name": chr(0xD800)}, id="object-holding-a-lone-surrogate"),
        ],
    )
    def test_a_value_that_is_not_text_is_left_to_its_reader(self, value: object) -> None:
        refuse_unencodable_text(value, "name")

    def test_text_that_encodes_is_not_refused(self) -> None:
        refuse_unencodable_text("Café ☀ 😀", "name")

    def test_text_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        text = chr(0xD800)
        with pytest.raises(ValueError) as expected:
            require_encodable_text(text, "name")
        with pytest.raises(ValueError) as refusal:
            refuse_unencodable_text(text, "name")
        assert str(refusal.value) == str(expected.value)


class TestReadLocation:
    """read_location reads a string as location.parse_location reads it and a JSON object as scenario_blocks.parse_location_block reads a location: block, carrying each grammar's refusal as raised; any other JSON value is refused naming its type."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("London ", id="preset"),
            pytest.param("51.5,-0.1", id="lat-lon"),
            pytest.param("51.5,-0.1,11", id="lat-lon-alt"),
        ],
    )
    def test_a_string_is_the_location_parse_location_reads(self, text: str) -> None:
        """A string of each form the location grammar accepts is the whole Location parse_location reads from it."""
        assert read_location(text) == parse_location(text)

    @pytest.mark.parametrize(
        "block",
        [
            pytest.param({"latitude": 51.5, "longitude": -0.1}, id="coordinates"),
            pytest.param({}, id="empty"),
        ],
    )
    def test_a_json_object_is_the_location_parse_location_block_reads(
        self, block: dict[str, Any]
    ) -> None:
        """A JSON object is the whole Location parse_location_block reads from it as a location: block."""
        assert read_location(block) == parse_location_block(block)

    @pytest.mark.parametrize(
        ("value", "grammar", "named"),
        [
            pytest.param("londn", parse_location, "'londn'", id="unknown-place"),
            pytest.param("95,0", parse_location, "latitude", id="latitude-above-90"),
            pytest.param(
                {"latitude": 50}, parse_location_block, "location.longitude", id="object-without-longitude"
            ),
        ],
    )
    def test_a_value_its_grammar_refuses_is_refused_with_that_grammars_refusal(
        self, value: object, grammar: Callable[[Any], Location], named: str
    ) -> None:
        """A value the grammar for its type refuses is refused with that grammar's own ConfigurationError, carried verbatim."""
        with pytest.raises(ConfigurationError) as expected:
            grammar(value)
        with pytest.raises(ConfigurationError) as refusal:
            read_location(value)

        assert str(refusal.value) == str(expected.value)
        assert named in str(refusal.value)

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [
            pytest.param(None, "NoneType", id="null"),
            pytest.param(5, "int", id="integer"),
            pytest.param(51.5, "float", id="float"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param([51.5, -0.1], "list", id="array"),
        ],
    )
    def test_any_other_json_value_is_refused_naming_location_and_its_type(
        self, value: object, type_name: str
    ) -> None:
        """A JSON value that is neither a string nor an object is refused naming location and its JSON type."""
        with pytest.raises(ConfigurationError) as refusal:
            read_location(value)

        assert str(refusal.value).startswith("location")
        assert str(refusal.value).endswith(f"got {type_name}")
