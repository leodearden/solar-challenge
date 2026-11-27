# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.stored_json: decoded_json, the value of a store's JSON text, and UndecodableJson, its refusal of text json.loads cannot decode; decoded_json_object, the JSON object a store's JSON text holds, and JsonObjectRefused, its refusal of text that holds none."""

import pytest

from solar_challenge.web.stored_json import JsonObjectRefused, UndecodableJson, decoded_json, decoded_json_object
from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE

_AN_OBJECT_AS_TEXT_AND_BYTES = [
    pytest.param('{"pv_kw": 4.0, "homes": [1, null]}', id="text"),
    pytest.param(b'{"pv_kw": 4.0, "homes": [1, null]}', id="bytes"),
]


@pytest.mark.parametrize("text", _AN_OBJECT_AS_TEXT_AND_BYTES)
def test_json_text_decodes_to_the_value_it_holds(text: str | bytes) -> None:
    assert decoded_json(text) == {"pv_kw": 4.0, "homes": [1, None]}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("{not json", id="malformed"),
        pytest.param("", id="empty"),
        pytest.param(b"\xff", id="bytes-not-utf-8"),
    ],
)
def test_text_that_is_not_json_is_refused_as_not_json_caused_by_the_value_error_of_json_loads(
    text: str | bytes,
) -> None:
    with pytest.raises(UndecodableJson) as refused:
        decoded_json(text)

    assert refused.value.reason == "is not JSON"
    assert isinstance(refused.value.refusal, ValueError)
    assert refused.value.__cause__ is refused.value.refusal


def test_text_nested_too_deeply_to_decode_is_refused_as_such_caused_by_the_recursion() -> None:
    with pytest.raises(UndecodableJson) as refused:
        decoded_json(JSON_NESTED_TOO_DEEPLY_TO_DECODE)

    assert refused.value.reason == "is nested too deeply to decode as JSON"
    assert isinstance(refused.value.refusal, RecursionError)
    assert refused.value.__cause__ is refused.value.refusal


@pytest.mark.parametrize("text", _AN_OBJECT_AS_TEXT_AND_BYTES)
def test_json_text_holding_an_object_decodes_to_that_object(text: str | bytes) -> None:
    assert decoded_json_object(text) == {"pv_kw": 4.0, "homes": [1, None]}


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("[1]", id="array"),
        pytest.param("42", id="number"),
        pytest.param("null", id="json-null"),
    ],
)
def test_json_that_is_not_an_object_is_refused_as_not_a_json_object_with_no_refusal_of_json_loads(
    text: str,
) -> None:
    with pytest.raises(JsonObjectRefused) as refused:
        decoded_json_object(text)

    assert refused.value.reason == "is not a JSON object"
    assert refused.value.refusal is None
    assert refused.value.__cause__ is None
    assert not isinstance(refused.value, ValueError)


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("{not json", id="not-json"),
        pytest.param(JSON_NESTED_TOO_DEEPLY_TO_DECODE, id="nested-too-deeply"),
    ],
)
def test_text_decoded_json_refuses_is_refused_with_its_reason_caused_by_the_same_refusal_of_json_loads(
    text: str,
) -> None:
    with pytest.raises(UndecodableJson) as undecodable:
        decoded_json(text)
    with pytest.raises(JsonObjectRefused) as refused:
        decoded_json_object(text)

    assert refused.value.reason == undecodable.value.reason
    assert type(refused.value.refusal) is type(undecodable.value.refusal)
    assert refused.value.__cause__ is refused.value.refusal
