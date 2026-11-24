# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the demand simulate_home dispatches a home against, and the rows it runs on.

The heat pump's share of that demand is tested in tests/unit/test_home_heat_pump.py.
"""

import datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from numpy.lib.stride_tricks import sliding_window_view
from solar_challenge.ev import EVConfig, generate_ev_charging_profile
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from solar_challenge.weather import WeatherCache
from tests._home_run_demand import home_run_demand_kw
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


def _at(text: str) -> pd.Timestamp:
    """The time *text* on London's clock."""
    return pd.Timestamp(text, tz="Europe/London")


def test_demand_is_the_households_load_plus_its_evs_charging_on_its_locations_clock():
    """A Paris home with an EV demands its household's load plus its EV's charging, on Paris minutes, not London's."""
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3000.0, seed=42),
        ev_config=EVConfig(charger_type="7kW", arrival_hour=18),
        location=Location(latitude=48.85, longitude=2.35, timezone="Europe/Paris", name="Paris"),
    )
    day = pd.Timestamp("2024-06-21")
    paris_window = SimulationWindow(day.date(), day.date(), ONE_MINUTE, "Europe/Paris")

    results = simulate_home(home, day, day, weather=weather_for(home, synthetic_june_weather(day)))

    household_kw = generate_load_profile(home.load_config, paris_window)
    ev_kw = generate_ev_charging_profile(home.ev_config, paris_window)
    assert (ev_kw > 0).any()
    pd.testing.assert_series_equal(results.demand, household_kw + ev_kw, check_names=False, rtol=1e-12, atol=0.0)


def test_a_solar_ev_charges_in_the_run_of_its_stay_with_the_most_of_the_homes_generation():
    """B5: a three-hour charge in the 08:00-16:59 stay takes the earliest 180-row run of the most generation, not 10:00-12:59."""
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
        ev_config=EVConfig("7kW", 8, 17, 21.0, "solar"),
    )
    day = pd.Timestamp("2024-06-21")

    results = simulate_home(home, day, day, weather=weather_for(home, synthetic_june_weather(day)))

    ev_kw = results.demand - generate_load_profile(home.load_config, results.window)
    stay_generation = results.generation[_at("2024-06-21 08:00") : _at("2024-06-21 16:59")]
    start = int(np.argmax(sliding_window_view(stay_generation.to_numpy(), 180).sum(axis=1)))
    most_generation = stay_generation.index[start : start + 180]
    assert list(ev_kw.index[ev_kw.to_numpy() > 3.5]) == list(most_generation)
    assert most_generation[0] != _at("2024-06-21 10:00")


def _home_run_ev_kw(
    tmp_path: Path, weather_cache: WeatherCache, ev_block: dict[str, Any], *, start: str, end: str
) -> pd.Series:
    """The kW by which *ev_block* raises `home run`'s demand_kw on each row."""
    with_the_ev = home_run_demand_kw(tmp_path, weather_cache, ev_block=ev_block, start=start, end=end)
    without_an_ev = home_run_demand_kw(tmp_path, weather_cache, ev_block=None, start=start, end=end)
    return with_the_ev - without_an_ev


def test_home_run_charges_a_none_ev_from_18_00_on_each_wall_clock_day_across_the_spring_change(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    ev_block = {
        "charger_type": "7kW",
        "arrival_hour": 18,
        "departure_hour": 7,
        "required_charge_kwh": 35,
        "smart_charging_mode": "none",
    }

    ev_kw = _home_run_ev_kw(tmp_path, weather_cache, ev_block, start="2024-03-29", end="2024-04-02")

    charging = ev_kw[ev_kw.abs() > 1e-9]
    evenings = [
        pd.date_range(f"{date} 18:00", f"{date} 22:59", freq="1min", tz="Europe/London")
        for date in ("2024-03-29", "2024-03-30", "2024-03-31", "2024-04-01", "2024-04-02")
    ]
    assert list(charging.index) == [minute for evening in evenings for minute in evening]
    assert charging.to_numpy() == pytest.approx(np.full(len(charging), 7.0), abs=1e-9)


def test_home_run_charges_an_off_peak_ev_on_its_first_morning_from_the_evening_before(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """On Economy 7, the one morning of 21 June charges the stay from 20 June's 18:00: 00:30-05:29, 35 kWh."""
    ev_block = {
        "charger_type": "7kW",
        "arrival_hour": 18,
        "departure_hour": 8,
        "required_charge_kwh": 35,
        "smart_charging_mode": "off_peak",
    }

    ev_kw = _home_run_ev_kw(tmp_path, weather_cache, ev_block, start="2024-06-21", end="2024-06-21")

    charging = ev_kw[ev_kw.abs() > 1e-9]
    assert list(charging.index) == list(
        pd.date_range("2024-06-21 00:30", "2024-06-21 05:29", freq="1min", tz="Europe/London")
    )
    assert charging.to_numpy() == pytest.approx(np.full(len(charging), 7.0), abs=1e-9)
    assert charging.sum() / 60 == pytest.approx(35.0, abs=1e-9)


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
