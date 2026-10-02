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


class RequestBodyNotAJsonObject(ValueError):
    """The request body is not a JSON object; the message names the type the body parsed to."""


def request_json_object() -> dict[str, Any]:
    """Return the current request's body, which must be a JSON object.

    Raises:
        RequestBodyNotAJsonObject: For any other body. An absent, non-JSON or
            unparseable body, or JSON null, reads as NoneType.
    """
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise RequestBodyNotAJsonObject(f"Request body must be a JSON object, got {type(body).__name__}")
    return body


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


# Built-in configuration presets for home simulations.
BUILTIN_PRESETS: list[dict[str, Any]] = [
    {"name": "Small Urban", "pv_kw": 3.0, "battery_kwh": 0, "consumption_kwh": 2900},
    {"name": "Medium Suburban", "pv_kw": 4.0, "battery_kwh": 5.0, "consumption_kwh": 3500},
    {"name": "Large with Battery", "pv_kw": 6.0, "battery_kwh": 10.0, "consumption_kwh": 4500},
]
