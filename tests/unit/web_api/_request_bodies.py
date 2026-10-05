# SPDX-License-Identifier: AGPL-3.0-or-later
"""Request bodies that more than one /api endpoint test module sends.

VALID_HOME_PAYLOAD is a home config /api/simulate/home accepts. MALFORMED_SEG_BODIES holds
seg values that every endpoint reading a seg block refuses with a 400 naming seg.
"""

import pytest


VALID_HOME_PAYLOAD: dict = {
    "pv_kw": 4.0,
    "battery_kwh": 5.0,
    "occupants": 3,
    "location": "bristol",
    "days": 7,
    "name": "Test Home",
}


MALFORMED_SEG_BODIES = [
    pytest.param({"rate_pence_per_kwh": float("nan")}, id="nan-rate"),
    pytest.param({"rate_pence_per_kwh": float("inf")}, id="infinite-rate"),
    pytest.param({"rate_pence_per_kwh": True}, id="boolean-rate"),
    pytest.param({"rate": 4.0}, id="unrecognised-key"),
    pytest.param({}, id="empty"),
    pytest.param({"preset": "Octopus", "rate_pence_per_kwh": 9}, id="preset-and-rate"),
    pytest.param({"preset": "custom", "rate_pence_per_kwh": 5.5}, id="custom-preset-and-rate"),
    pytest.param([1, 2], id="array"),
]
