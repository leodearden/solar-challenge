# SPDX-License-Identifier: AGPL-3.0-or-later
"""Both simulate pages start each economy tariff type at tariff.PRESET_RATES' rates.

The home page hands its Alpine component the table, one rate pair per economy type, and
the fleet page hands its component its tariff table, FLEET_FORM_TARIFFS, whose economy
choices start at those rates, each in the x-data that mounts it. So the forms state no
economy rate of their own, and an Economy 7 home body at the pair the home page hands its
form is charged the library's preset rates.
"""

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.home import simulate_home
from solar_challenge.tariff import PRESET_RATES
from solar_challenge.web.simulation_params import parse_home_config
from tests._alpine_component_arguments import component_arguments
from tests._home_payload import VALID_HOME_PAYLOAD
from tests._synthetic_weather import sunless_weather, weather_for

_EXPECTED = {
    tariff_type: {"off_peak_rate": rates.off_peak_rate, "peak_rate": rates.peak_rate}
    for tariff_type, rates in PRESET_RATES.items()
}
_DAY = "2024-01-10"


def test_the_home_page_hands_its_form_each_economy_types_preset_rates(client: FlaskClient) -> None:
    page = client.get("/simulate/home").get_data(as_text=True)

    assert component_arguments(page, "homeSimulator") == [_EXPECTED]


def test_the_fleet_page_hands_its_form_each_economy_types_preset_rates(client: FlaskClient) -> None:
    page = client.get("/simulate/fleet").get_data(as_text=True)
    tariff_choices = component_arguments(page, "fleetSimulator")[0]

    assert {
        choice["type"]: {setting["key"]: setting["start"] for setting in choice["settings"]}
        for choice in tariff_choices
        if choice["type"] in PRESET_RATES
    } == _EXPECTED


def test_an_economy_7_body_at_the_pair_the_home_page_hands_its_form_is_charged_the_preset_rates(
    client: FlaskClient,
) -> None:
    """parse_home_config reads the body as an Economy 7 run charged PRESET_RATES' off-peak rate at 03:00 and its peak rate at 18:00 of one sunless day.

    The body is built here from the page's pair. The body the form's own buildPayload sends is
    tests/e2e/test_home_form_interactions.py::test_each_economy_type_shows_and_keeps_its_own_rates's to check.
    """
    page = client.get("/simulate/home").get_data(as_text=True)
    (tariff_rates,) = component_arguments(page, "homeSimulator")
    pair = tariff_rates["economy_7"]
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
