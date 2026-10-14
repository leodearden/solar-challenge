# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the demand simulate_home dispatches a home against.

The heat pump's share of that demand is tested in test_home_heat_pump.py.
"""

import pandas as pd
from solar_challenge.ev import EVConfig
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from tests._synthetic_weather import synthetic_june_weather


def test_demand_is_the_homes_load_profile_on_its_locations_clock_ev_charging_included():
    """A Paris home with an EV demands its load profile, EV charging included, on Paris minutes, not London's."""
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        ev_config=EVConfig(charger_type="7kW", arrival_hour=18),
        location=Location(latitude=48.85, longitude=2.35, timezone="Europe/Paris", name="Paris"),
    )
    day = pd.Timestamp("2024-06-21")

    results = simulate_home(home, day, day, weather_data=synthetic_june_weather(day))

    load_profile = generate_load_profile(home.load_config, day, day, timezone="Europe/Paris", ev_config=home.ev_config)
    household_load = generate_load_profile(home.load_config, day, day, timezone="Europe/Paris")
    assert (load_profile > household_load).any()
    pd.testing.assert_series_equal(results.demand, load_profile, check_names=False, rtol=1e-12, atol=0.0)
