# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.request_boundary, called directly: its request-body rules, a JSON object, only recognised keys, a top-level field sent as null or "" read as not sent, and text that encodes as UTF-8, its field readers, a JSON string, a JSON string or null, and a JSON boolean, its location reader, and its translator of a refusal into an answer."""

import logging
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask
from werkzeug.exceptions import InternalServerError

from solar_challenge.boolean_fields import as_boolean
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location, parse_location
from solar_challenge.scenario_blocks import parse_location_block
from solar_challenge.web.request_boundary import (
    answer_refusal,
    answer_server_error,
    present_fields,
    read_boolean,
    read_location,
    read_optional_string,
    read_string,
    refusal_text,
    refuse_unrecognised_keys,
    request_json_object,
    require_encodable_text,
    require_json_object,
)
from tests._error_records import error_records


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
        with pytest.raises(ConfigurationError) as exc_info:
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
            with pytest.raises(ConfigurationError, match="got NoneType"):
                request_json_object()


class TestRefuseUnrecognisedKeys:
    """refuse_unrecognised_keys passes a body of recognised keys and refuses one with any other key."""

    def test_a_body_of_recognised_keys_is_not_refused(self) -> None:
        """A subset of the recognised keys is enough; none is required."""
        refuse_unrecognised_keys({"pv_kw": 4.0}, frozenset({"pv_kw", "days"}), "Home config")

    def test_any_other_key_is_refused_naming_each_and_listing_the_recognised(self) -> None:
        """*what*, the label require_json_object takes, lower-cased; each unrecognised key as its repr, sorted; then the recognised keys, sorted."""
        with pytest.raises(ConfigurationError) as exc_info:
            refuse_unrecognised_keys(
                {"pv_kw": 4.0, "tarif": {}, "heat_pump": "ASHP"},
                frozenset({"pv_kw", "days"}),
                "Fleet form",
            )
        assert str(exc_info.value) == (
            "Unrecognised fleet form keys: 'heat_pump', 'tarif'; recognised keys: days, pv_kw"
        )


class TestPresentFields:
    """present_fields reads a form body's top-level field sent as null or "" (a cleared input) as not sent."""

    def test_a_field_sent_as_null_or_empty_text_is_dropped_and_every_other_is_kept(self) -> None:
        """Each field sent as None or "" is left out; each other field keeps the value it was sent with."""
        body = {"pv_kw": 4.0, "name": "", "tilt": None, "location": "bristol", "seed": None}
        assert present_fields(body) == {"pv_kw": 4.0, "location": "bristol"}

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(False, id="false"),
            pytest.param(0, id="zero"),
            pytest.param(0.0, id="zero-float"),
            pytest.param([], id="empty-array"),
            pytest.param({}, id="empty-object"),
        ],
    )
    def test_any_other_falsy_value_is_kept_as_sent(self, value: object) -> None:
        """Only null and "" read as not sent: any other falsy JSON value is a value the field's reader judges."""
        fields = present_fields({"battery_kwh": value})
        assert fields == {"battery_kwh": value}
        assert fields["battery_kwh"] is value

    def test_a_nested_blocks_contents_are_returned_untouched(self) -> None:
        """The rule is top level only: a block's own null or "" keys are its grammar's to read."""
        block = {"heat_pump_type": None, "name": ""}
        fields = present_fields({"heat_pump": block})
        assert fields == {"heat_pump": {"heat_pump_type": None, "name": ""}}
        assert fields["heat_pump"] is block

    def test_the_body_passed_in_is_not_mutated(self) -> None:
        """A new dict is returned; the body keeps every field it was sent with."""
        body = {"pv_kw": 4.0, "name": "", "tilt": None}
        present_fields(body)
        assert body == {"pv_kw": 4.0, "name": "", "tilt": None}


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
        with pytest.raises(ConfigurationError) as refusal:
            require_encodable_text(text, "points[1].run_id")
        assert str(refusal.value) == (
            f"points[1].run_id must be text that encodes as UTF-8, holding no lone surrogate; got {text!r}"
        )


class TestReadString:
    """read_string returns a JSON string that encodes as UTF-8 and refuses any other JSON value naming the field and its type."""

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("run-2kw", id="ascii"),
            pytest.param("", id="empty"),
            pytest.param("Café ☀ 😀", id="non-ascii-and-astral"),
        ],
    )
    def test_a_string_is_returned_as_given(self, text: str) -> None:
        assert read_string(text, "name") is text

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [
            pytest.param(None, "NoneType", id="null"),
            pytest.param(5, "int", id="integer"),
            pytest.param(4.5, "float", id="float"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param([], "list", id="empty-array"),
            pytest.param(["a"], "list", id="array"),
            pytest.param({"x": 1}, "dict", id="object"),
        ],
    )
    def test_any_other_json_value_is_refused_naming_the_field_and_its_type(
        self, value: object, type_name: str
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_string(value, "name")
        assert str(refusal.value) == f"name must be a JSON string, got {type_name}"

    def test_text_holding_a_lone_surrogate_is_refused_as_require_encodable_text_refuses_it(self) -> None:
        text = chr(0xD800)
        with pytest.raises(ConfigurationError) as expected:
            require_encodable_text(text, "name")
        with pytest.raises(ConfigurationError) as refusal:
            read_string(text, "name")
        assert str(refusal.value) == str(expected.value)


class TestReadOptionalString:
    """read_optional_string reads null as no value and any other JSON value as read_string reads it."""

    def test_null_is_none(self) -> None:
        assert read_optional_string(None, "notes") is None

    def test_a_string_is_returned_as_given(self) -> None:
        text = "Checked"
        assert read_optional_string(text, "notes") is text

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(5, id="integer"),
            pytest.param(["a"], id="array"),
        ],
    )
    def test_any_other_json_value_is_refused_as_read_string_refuses_it(self, value: object) -> None:
        with pytest.raises(ConfigurationError) as expected:
            read_string(value, "notes")
        with pytest.raises(ConfigurationError) as refusal:
            read_optional_string(value, "notes")
        assert str(refusal.value) == str(expected.value)


class TestReadBoolean:
    """read_boolean returns a JSON boolean and refuses any other JSON value as boolean_fields.as_boolean refuses it."""

    @pytest.mark.parametrize("value", [True, False])
    def test_a_boolean_is_returned_as_itself(self, value: bool) -> None:
        assert read_boolean(value, "stochastic") is value

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param("false", id="string-false"),
            pytest.param("true", id="string-true"),
            pytest.param(0, id="zero"),
            pytest.param(1, id="one"),
            pytest.param(None, id="null"),
            pytest.param([], id="empty-array"),
            pytest.param({}, id="empty-object"),
        ],
    )
    def test_any_other_json_value_is_refused_as_as_boolean_refuses_it(self, value: object) -> None:
        with pytest.raises(ConfigurationError) as expected:
            as_boolean(value, "stochastic")
        with pytest.raises(ConfigurationError) as refusal:
            read_boolean(value, "stochastic")
        assert str(refusal.value) == str(expected.value)
        assert str(refusal.value).startswith("stochastic")


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
                {"latitude": 50}, parse_location_block, "location: requires 'longitude'", id="object-without-longitude"
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


class _ProbeRefusal(ValueError):
    """A ValueError that is not a ConfigurationError, as a reader's bug might raise."""


_BOUNDARY_LOGGER = "solar_challenge.web.request_boundary"


class TestRefusalText:
    """refusal_text is the refusal's text, and logs a ValueError that is not a ConfigurationError as a probable defect."""

    def test_a_configuration_error_is_its_text_and_logs_nothing(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger=_BOUNDARY_LOGGER):
            text = refusal_text(ConfigurationError("x"))

        assert text == "x"
        assert error_records(caplog, _BOUNDARY_LOGGER) == []

    def test_any_other_value_error_is_its_text_logged_once_as_a_probable_defect(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        refusal = ValueError("probe")
        with caplog.at_level(logging.ERROR, logger=_BOUNDARY_LOGGER):
            text = refusal_text(refusal)

        assert text == "probe"
        [record] = error_records(caplog, _BOUNDARY_LOGGER)
        message = record.getMessage()
        assert "ValueError" in message
        assert "not a ConfigurationError" in message
        assert "probable defect" in message
        assert record.exc_info is not None
        assert record.exc_info[1] is refusal

    def test_a_value_error_subclass_is_named_by_its_own_type(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.ERROR, logger=_BOUNDARY_LOGGER):
            text = refusal_text(_ProbeRefusal("probe"))

        assert text == "probe"
        [record] = error_records(caplog, _BOUNDARY_LOGGER)
        assert "_ProbeRefusal" in record.getMessage()


class TestAnswers:
    """answer_refusal answers a refusal 400 with its text; answer_server_error answers 500 with a JSON body."""

    def test_a_refusal_is_answered_400_with_its_text(self) -> None:
        with Flask(__name__).test_request_context():
            response, status = answer_refusal(ConfigurationError("x"))

            assert status == 400
            assert response.get_json() == {"error": "x"}

    def test_a_server_error_is_answered_500_with_a_json_body(self) -> None:
        with Flask(__name__).test_request_context():
            response, status = answer_server_error(InternalServerError())

            assert status == 500
            assert response.mimetype == "application/json"
            assert response.get_json() == {"error": "Internal server error"}
