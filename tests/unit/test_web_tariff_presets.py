# SPDX-License-Identifier: AGPL-3.0-or-later
"""Both simulate pages start each economy tariff type at tariff.PRESET_RATES' rates.

Each page hands its Alpine component the table, one rate pair per economy type, in the
x-data that mounts it, so the forms state no economy rate of their own and a run the home
form sends at its starting Economy 7 rates is charged the library's preset rates.
"""

import json
from typing import Any

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.home import simulate_home
from solar_challenge.tariff import PRESET_RATES
from solar_challenge.web.simulation_params import parse_home_config
from tests._home_payload import VALID_HOME_PAYLOAD
from tests._html_page import element_attributes
from tests._synthetic_weather import sunless_weather, weather_for

_EXPECTED = {
    tariff_type: {"off_peak_rate": rates.off_peak_rate, "peak_rate": rates.peak_rate}
    for tariff_type, rates in PRESET_RATES.items()
}
_DAY = "2024-01-10"


def _component_argument(page: str, component: str) -> Any:
    """The JSON argument *page* hands its Alpine *component* in the x-data of the one div that mounts it."""
    scopes = [attributes.get("x-data") or "" for attributes in element_attributes(page, "div")]
    (x_data,) = [scope for scope in scopes if scope.startswith(f"{component}(")]
    try:
        return json.loads(x_data.removeprefix(f"{component}(").removesuffix(")"))
    except json.JSONDecodeError as exc:
        pytest.fail(f"x-data={x_data!r} does not pass {component} a JSON argument: {exc}")


def test_the_home_page_hands_its_form_each_economy_types_preset_rates(client: FlaskClient) -> None:
    page = client.get("/simulate/home").get_data(as_text=True)

    assert _component_argument(page, "homeSimulator") == _EXPECTED


def test_the_fleet_page_hands_its_form_each_economy_types_preset_rates(client: FlaskClient) -> None:
    page = client.get("/simulate/fleet").get_data(as_text=True)

    assert _component_argument(page, "fleetSimulator") == _EXPECTED


def test_the_home_forms_default_economy_7_payload_runs_at_the_preset_rates(client: FlaskClient) -> None:
    """The body the home form sends on Economy 7 before any rate is typed, run over one sunless day."""
    page = client.get("/simulate/home").get_data(as_text=True)
    pair = _component_argument(page, "homeSimulator")["economy_7"]
    body = {
        **{key: value for key, value in VALID_HOME_PAYLOAD.items() if key != "days"},
        "start": _DAY,
        "end": _DAY,
        "tariff": {"type": "economy_7", "peak_rate": pair["peak_rate"], "off_peak_rate": pair["off_peak_rate"]},
    }
    home, start, end, _ = parse_home_config(body)

    with pytest.warns(UserWarning, match="seg_tariff"):
        results = simulate_home(home, start, end, weather=weather_for(home, sunless_weather(_DAY, temp_air=5.0)))

    assert results.tariff_rate[pd.Timestamp(f"{_DAY} 03:00", tz="Europe/London")] == (
        PRESET_RATES["economy_7"].off_peak_rate
    )
    assert results.tariff_rate[pd.Timestamp(f"{_DAY} 18:00", tz="Europe/London")] == (
        PRESET_RATES["economy_7"].peak_rate
    )
