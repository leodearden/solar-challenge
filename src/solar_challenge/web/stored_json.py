# SPDX-License-Identifier: AGPL-3.0-or-later
"""decoded_json, the value of the JSON text a store holds, and decoded_json_object, the JSON object that text holds, each with one refusal.

json.loads refuses text that is not JSON with a ValueError, and text nested deeper than it can
decode with a RecursionError, raised before it can tell whether the text is JSON. decoded_json
refuses both as an UndecodableJson whose reason says which. decoded_json_object refuses that
text, with the same reason and refusal, and JSON that is not an object, with the reason "is not
a JSON object", as a JsonObjectRefused. So each store that reads JSON text catches one type, the
refusal of the function it reads through.
"""

import json
from typing import Any


class UndecodableJson(Exception):
    """JSON text json.loads cannot decode: the reason, "is not JSON" or "is nested too deeply to decode as JSON", and json.loads's refusal, which is also its cause.

    It is not a ValueError: a store's own text that cannot be decoded is a server fault, never a
    request's bad value.
    """

    def __init__(self, reason: str, refusal: ValueError | RecursionError) -> None:
        super().__init__(reason)
        self.reason = reason
        self.refusal = refusal


class JsonObjectRefused(Exception):
    """JSON text that holds no JSON object: the reason, decoded_json's or "is not a JSON object", and json.loads's refusal, which is also its cause, or None when the text is JSON but not an object.

    It is not a ValueError, for the reason UndecodableJson is not.
    """

    def __init__(self, reason: str, refusal: ValueError | RecursionError | None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.refusal = refusal


def decoded_json(text: str | bytes) -> Any:
    """The value the JSON text *text* holds.

    Raises:
        UndecodableJson: json.loads refuses *text*; it carries that refusal, which is also its cause.
    """
    try:
        return json.loads(text)
    except ValueError as refusal:
        raise UndecodableJson("is not JSON", refusal) from refusal
    except RecursionError as refusal:
        raise UndecodableJson("is nested too deeply to decode as JSON", refusal) from refusal


def decoded_json_object(text: str | bytes) -> dict[str, Any]:
    """The JSON object the JSON text *text* holds.

    Raises:
        JsonObjectRefused: decoded_json refuses *text*, with its reason and json.loads's refusal,
            which is also the cause; or *text* is JSON but not an object, "null" included, with
            the reason "is not a JSON object" and no refusal.
    """
    try:
        value = decoded_json(text)
    except UndecodableJson as undecodable:
        raise JsonObjectRefused(undecodable.reason, undecodable.refusal) from undecodable.refusal
    if not isinstance(value, dict):
        raise JsonObjectRefused("is not a JSON object", None)
    return value
