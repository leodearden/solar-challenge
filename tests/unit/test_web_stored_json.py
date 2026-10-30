# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.stored_json: decoded_json, the value of a store's JSON text, and UndecodableJson, its refusal of text json.loads cannot decode."""

import pytest

from solar_challenge.web.stored_json import UndecodableJson, decoded_json
from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE


@pytest.mark.parametrize(
    "text",
    [
        pytest.param('{"pv_kw": 4.0, "homes": [1, null]}', id="text"),
        pytest.param(b'{"pv_kw": 4.0, "homes": [1, null]}', id="bytes"),
    ],
)
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
