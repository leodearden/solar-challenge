# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the web reads a request body, refuses one it cannot read, and answers a refusal.

Every refusal a web reader raises is a ConfigurationError. refusal_text is the one judge
of a refusal at the web boundary: any other ValueError is answered as a refusal too, but
logged at ERROR as a probable defect first (docs/prds/web-request-boundary.md §3, its
reading of D2).

It imports no solar_challenge.web module, so a reader that needs only it loads none of
the web's Flask services (tests/unit/test_web_readers_below_services.py).
"""

import logging
from collections.abc import Collection, Mapping
from typing import Any

from flask import Response, jsonify, request
from werkzeug.exceptions import InternalServerError

from solar_challenge.errors import ConfigurationError
from solar_challenge.location import Location, parse_location
from solar_challenge.scenario_blocks import parse_location_block

logger = logging.getLogger(__name__)


def refusal_text(refusal: ValueError) -> str:
    """The text a web boundary answers *refusal* with: str(refusal).

    A ValueError that is not a ConfigurationError is no reader's refusal, so it is logged
    once at ERROR, with its traceback, as a probable defect.
    """
    if not isinstance(refusal, ConfigurationError):
        logger.error(
            "Refused a request with a %s, not a ConfigurationError: probable defect",
            type(refusal).__name__,
            exc_info=refusal,
        )
    return str(refusal)


def answer_refusal(refusal: ValueError) -> tuple[Response, int]:
    """Answer *refusal* HTTP 400 with {"error": refusal_text(refusal)}."""
    return jsonify({"error": refusal_text(refusal)}), 400


def answer_server_error(error: InternalServerError) -> tuple[Response, int]:
    """Answer a server error HTTP 500 with a JSON body; Flask.handle_exception has already logged the exception behind it."""
    return jsonify({"error": "Internal server error"}), 500


def require_json_object(value: object, what: str) -> dict[str, Any]:
    """Return *value*, which must be a JSON object: a dict, the type a JSON object parses to.

    Raises:
        ConfigurationError: For any other value, naming *what* and the type of *value*.
    """
    if not isinstance(value, dict):
        raise ConfigurationError(f"{what} must be a JSON object, got {type(value).__name__}")
    return value


def request_json_object() -> dict[str, Any]:
    """Return the current request's body, which must be a JSON object.

    Raises:
        ConfigurationError: From require_json_object, which refuses any other body
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
        ConfigurationError: Naming *what* and each unrecognised key, sorted, and listing the
            *recognised* keys, sorted.
    """
    unrecognised = sorted(body.keys() - recognised)
    if unrecognised:
        raise ConfigurationError(
            f"Unrecognised {what.lower()} keys: {', '.join(map(repr, unrecognised))}; "
            f"recognised keys: {', '.join(sorted(recognised))}"
        )


def present_fields(body: Mapping[str, Any]) -> dict[str, Any]:
    """The top-level fields form *body* sends: one sent as null, or as '' (a cleared input), is not sent, and a nested block's contents are that block's grammar's to read."""
    return {key: value for key, value in body.items() if value is not None and value != ""}


def require_encodable_text(text: str, what: str) -> str:
    """Return *text*, a request's *what*, which must encode as UTF-8, the encoding sqlite3 binds text in.

    A JSON string can escape a lone surrogate, which UTF-8 cannot encode.

    Raises:
        ConfigurationError: Naming *what* and *text*, for text holding a lone surrogate.
    """
    try:
        text.encode()
    except UnicodeEncodeError:
        raise ConfigurationError(f"{what} must be text that encodes as UTF-8, holding no lone surrogate; got {text!r}") from None
    return text


def refuse_unencodable_text(value: object, what: str) -> None:
    """Refuse *value*, a request's *what*, when it is text require_encodable_text refuses, and leave any other value to its reader.

    Raises:
        ConfigurationError: From require_encodable_text, naming *what* and *value*, for text holding
            a lone surrogate.
    """
    if isinstance(value, str):
        require_encodable_text(value, what)


#: The location a home or fleet form body that sends none runs at, as read_location reads it:
#: Bristol, the community energy project's site (location.LOCATION_PRESETS' bristol).
WEB_DEFAULT_LOCATION = "bristol"


def read_location(value: object) -> Location:
    """The Location a request's location *value* names: a string as location.parse_location reads it, a JSON object as scenario_blocks.parse_location_block reads a scenario's location: block.

    Raises:
        ConfigurationError: From parse_location or parse_location_block, for a value they
            refuse; for any other value, naming location and its type.
    """
    if isinstance(value, str):
        return parse_location(value)
    if isinstance(value, dict):
        return parse_location_block(value)
    raise ConfigurationError(f"location must be a string or a JSON object, got {type(value).__name__}")
