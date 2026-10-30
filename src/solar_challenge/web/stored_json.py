# SPDX-License-Identifier: AGPL-3.0-or-later
"""decoded_json: the value of the JSON text a store holds, with one refusal, UndecodableJson, for text json.loads cannot decode.

json.loads refuses text that is not JSON with a ValueError, and text nested deeper than it can
decode with a RecursionError, raised before it can tell whether the text is JSON. decoded_json
refuses both as an UndecodableJson whose reason says which, so the run store and the presets
table each catch one type.
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
