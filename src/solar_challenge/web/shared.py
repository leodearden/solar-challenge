# SPDX-License-Identifier: AGPL-3.0-or-later
"""Shared helpers for the Solar Challenge web application."""

from __future__ import annotations

from typing import Any

from flask import current_app, request

from solar_challenge.location import Location
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RunStorage


def get_storage() -> RunStorage:
    """Return the RunStorage singleton from current Flask app extensions."""
    return current_app.extensions["storage"]  # type: ignore[no-any-return]


def get_job_manager() -> JobManager:
    """Return the JobManager singleton from current Flask app extensions."""
    return current_app.extensions["job_manager"]  # type: ignore[no-any-return]


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
            JSON null, reads as NoneType.
    """
    return require_json_object(request.get_json(silent=True), "Request body")


LOCATION_PRESETS: dict[str, Location] = {
    "bristol": Location(latitude=51.45, longitude=-2.58, altitude=11.0, name="Bristol, UK"),
    "london": Location(latitude=51.51, longitude=-0.13, altitude=11.0, name="London, UK"),
    "edinburgh": Location(latitude=55.95, longitude=-3.19, altitude=47.0, name="Edinburgh, UK"),
    "manchester": Location(latitude=53.48, longitude=-2.24, altitude=38.0, name="Manchester, UK"),
}


def resolve_location(preset_str: str) -> Location:
    """Map a location string to a Location instance.

    Accepts preset names (bristol, london, edinburgh, manchester) or
    a 'lat,lon' string.  Falls back to Bristol on parse errors.
    """
    key = preset_str.strip().lower()
    if key in LOCATION_PRESETS:
        return LOCATION_PRESETS[key]
    try:
        lat, lon = map(float, key.split(","))
        return Location(latitude=lat, longitude=lon)
    except ValueError:
        return Location.bristol()
