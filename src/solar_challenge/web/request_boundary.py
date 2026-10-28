# SPDX-License-Identifier: AGPL-3.0-or-later
"""How the web reads a request body and refuses one it cannot read.

It imports no solar_challenge.web module, so a reader that needs only it loads none of
the web's Flask services (tests/unit/test_web_readers_below_services.py).
"""

from collections.abc import Collection, Mapping
from typing import Any

from flask import request

from solar_challenge.location import Location


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


LOCATION_PRESETS: dict[str, Location] = {
    "bristol": Location(latitude=51.45, longitude=-2.58, altitude=11.0, name="Bristol, UK"),
    "london": Location(latitude=51.51, longitude=-0.13, altitude=11.0, name="London, UK"),
    "edinburgh": Location(latitude=55.95, longitude=-3.19, altitude=47.0, name="Edinburgh, UK"),
    "manchester": Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester, UK"),
}


def resolve_location(location: object) -> Location:
    """The Location *location* names: a LOCATION_PRESETS key, in any case and with surrounding whitespace, or 'lat,lon' coordinates.

    Raises:
        ValueError: For any other value, a non-string included, naming location,
            the value and the accepted forms; or, from Location, for
            coordinates outside its range.
    """
    if isinstance(location, str):
        key = location.strip().lower()
        if key in LOCATION_PRESETS:
            return LOCATION_PRESETS[key]
        coordinates = _lat_lon(location)
        if coordinates is not None:
            latitude, longitude = coordinates
            return Location(latitude=latitude, longitude=longitude)
    raise ValueError(
        "location must be 'lat,lon' coordinates or one of "
        f"{', '.join(map(repr, LOCATION_PRESETS))}, got {location!r}"
    )


def _lat_lon(text: str) -> tuple[float, float] | None:
    """The latitude and longitude of 'lat,lon' *text*, two numbers float() reads either side of one comma; None for any other text."""
    try:
        latitude, longitude = map(float, text.split(","))
    except ValueError:
        return None
    return latitude, longitude
