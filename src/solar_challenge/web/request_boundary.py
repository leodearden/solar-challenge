# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the web reads a request body and refuses one it cannot read.

It imports no solar_challenge.web module, so a reader that needs only it loads none of
the web's Flask services (tests/unit/test_web_readers_below_services.py).
"""

from collections.abc import Collection, Mapping
from typing import Any

from flask import request

from solar_challenge.config import parse_location_block
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location, parse_location


class NotAJsonObject(ValueError):
    """A JSON value the web reads as an object is not one; the message names the value and the type received."""


def require_json_object(value: object, what: str) -> dict[str, Any]:
    """Return *value*, which must be a JSON object: a dict, the type a JSON object parses to.

    Raises:
        NotAJsonObject: For any other value, naming *what* and the type of *value*.
    """
    if not isinstance(value, dict):
        raise NotAJsonObject(f"{what} must be a JSON object, got {type(value).__name__}")
    return value


def request_json_object() -> dict[str, Any]:
    """Return the current request's body, which must be a JSON object.

    Raises:
        NotAJsonObject: From require_json_object, which refuses any other body
            as the "Request body". An absent, non-JSON or unparseable body, or
            JSON null, reads as NoneType; so does a body nested so deeply that
            parsing it exhausts the recursion limit, which get_json(silent=True)
            does not swallow.
    """
    try:
        body = request.get_json(silent=True)
    except RecursionError:
        body = None
    return require_json_object(body, "Request body")


def refuse_unrecognised_keys(body: Mapping[str, Any], recognised: Collection[str], what: str) -> None:
    """Refuse *body*, a request's *what*, when it has a top-level key outside *recognised*.

    *what* is the label require_json_object takes for the same body; the refusal names it
    lower-cased.

    Raises:
        ValueError: Naming *what* and each unrecognised key, sorted, and listing the
            *recognised* keys, sorted.
    """
    unrecognised = sorted(body.keys() - recognised)
    if unrecognised:
        raise ValueError(
            f"Unrecognised {what.lower()} keys: {', '.join(map(repr, unrecognised))}; "
            f"recognised keys: {', '.join(sorted(recognised))}"
        )


def require_encodable_text(text: str, what: str) -> str:
    """Return *text*, a request's *what*, which must encode as UTF-8, the encoding sqlite3 binds text in.

    A JSON string can escape a lone surrogate, which UTF-8 cannot encode.

    Raises:
        ValueError: Naming *what* and *text*, for text holding a lone surrogate.
    """
    try:
        text.encode()
    except UnicodeEncodeError:
        raise ValueError(f"{what} must be text that encodes as UTF-8, holding no lone surrogate; got {text!r}") from None
    return text


def refuse_unencodable_text(value: object, what: str) -> None:
    """Refuse *value*, a request's *what*, when it is text require_encodable_text refuses, and leave any other value to its reader.

    Raises:
        ValueError: From require_encodable_text, naming *what* and *value*, for text holding
            a lone surrogate.
    """
    if isinstance(value, str):
        require_encodable_text(value, what)


def read_location(value: object) -> Location:
    """The Location a request's location *value* names: a string as location.parse_location reads it, a JSON object as config.parse_location_block reads a scenario's location: block.

    Raises:
        ConfigurationError: From parse_location or parse_location_block, for a value they
            refuse; for any other value, naming location and its type.
    """
    if isinstance(value, str):
        return parse_location(value)
    if isinstance(value, dict):
        return parse_location_block(value)
    raise ConfigurationError(f"location must be a string or a JSON object, got {type(value).__name__}")
