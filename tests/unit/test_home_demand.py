# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the demand simulate_home dispatches a home against, and the rows it runs on.

The heat pump's share of that demand is tested in tests/unit/test_home_heat_pump.py.
"""

import datetime

import pandas as pd
import pytest
from solar_challenge.ev import EVConfig
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._synthetic_weather import synthetic_june_weather, synthetic_tmy, weather_for

_BRISTOL_ELEXON_HOME = HomeConfig(
    pv_config=PVConfig(capacity_kw=4.0),
    load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
)


def _london_window(first: str, last: str) -> SimulationWindow:
    """The window from the ISO date first to the ISO date last, both counted, at one minute on London's clock."""
    return SimulationWindow(
        datetime.date.fromisoformat(first), datetime.date.fromisoformat(last), ONE_MINUTE, "Europe/London"
    )


def test_demand_is_the_homes_load_profile_on_its_locations_clock_ev_charging_included():
    """A Paris home with an EV demands its load profile, EV charging included, on Paris minutes, not London's."""
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        ev_config=EVConfig(charger_type="7kW", arrival_hour=18),
        location=Location(latitude=48.85, longitude=2.35, timezone="Europe/Paris", name="Paris"),
    )
    day = pd.Timestamp("2024-06-21")
    paris_window = SimulationWindow(day.date(), day.date(), ONE_MINUTE, "Europe/Paris")

    results = simulate_home(home, day, day, weather=weather_for(home, synthetic_june_weather(day)))

    load_profile = generate_load_profile(home.load_config, paris_window, ev_config=home.ev_config)
    household_load = generate_load_profile(home.load_config, paris_window)
    assert (load_profile > household_load).any()
    pd.testing.assert_series_equal(results.demand, load_profile, check_names=False, rtol=1e-12, atol=0.0)


@pytest.mark.parametrize(
    ("start_date", "end_date", "window"),
    [
        pytest.param(
            pd.Timestamp("2024-03-30"),
            pd.Timestamp("2024-03-31"),
            _london_window("2024-03-30", "2024-03-31"),
            id="naive-dates-ending-on-the-spring-change",
        ),
        pytest.param(
            pd.Timestamp("2024-10-26", tz="Europe/London"),
            pd.Timestamp("2024-10-27", tz="Europe/London"),
            _london_window("2024-10-26", "2024-10-27"),
            id="london-dates-ending-on-the-autumn-change",
        ),
        pytest.param(
            pd.Timestamp("2024-06-20 23:30", tz="UTC"),
            pd.Timestamp("2024-06-21 22:30", tz="UTC"),
            _london_window("2024-06-21", "2024-06-21"),
            id="utc-instants-on-one-london-date",
        ),
    ],
)
def test_a_runs_rows_are_its_windows_rows(
    start_date: pd.Timestamp, end_date: pd.Timestamp, window: SimulationWindow
) -> None:
    """A run's window is its first and last dates on its location's clock, a naive date read as already on it, and the run is on that window's rows, from its first day's midnight to the midnight after its last."""
    results = simulate_home(
        _BRISTOL_ELEXON_HOME,
        start_date,
        end_date,
        weather=weather_for(_BRISTOL_ELEXON_HOME, synthetic_tmy()),
    )

    assert results.window == window
    assert results.demand.index.equals(window.rows())
    assert results.generation.index.equals(window.rows())


def test_a_homes_demand_on_a_day_is_the_same_whatever_run_holds_it() -> None:
    """4 April 2024 follows the spring clock change in a run from 25 March and not in one from 3 April, and both give it one demand, first peaking at 17:30 BST."""
    weather = weather_for(_BRISTOL_ELEXON_HOME, synthetic_tmy())
    end_date = pd.Timestamp("2024-04-05")

    from_march = simulate_home(_BRISTOL_ELEXON_HOME, pd.Timestamp("2024-03-25"), end_date, weather=weather)
    from_april = simulate_home(_BRISTOL_ELEXON_HOME, pd.Timestamp("2024-04-03"), end_date, weather=weather)

    april_4th = from_march.demand.loc["2024-04-04"]
    assert april_4th.equals(from_april.demand.loc["2024-04-04"])
    assert april_4th.idxmax() == pd.Timestamp("2024-04-04 17:30", tz="Europe/London")
