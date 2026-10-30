# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home request body that solar_challenge.web.simulation_params.parse_home_config reads and POST /api/simulate/home accepts.

parse_home_config's own tests and the /api endpoint tests share it.

Usage::

    from tests._home_payload import VALID_HOME_PAYLOAD

    parse_home_config({**VALID_HOME_PAYLOAD, "pv_kw": 3.0})
"""

VALID_HOME_PAYLOAD: dict[str, object] = {
    "pv_kw": 4.0,
    "battery_kwh": 5.0,
    "occupants": 3,
    "location": "bristol",
    "days": 7,
    "name": "Test Home",
}
