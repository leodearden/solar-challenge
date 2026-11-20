# SPDX-License-Identifier: AGPL-3.0-or-later
"""§9 row 15 of docs/prds/tariff-coverage-classifier-presets.md at the home: simulate_home charges an off_peak EV in its tariff's cheap minutes, and HomeConfig refuses one with no tariff."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.battery import BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from tests._off_peak_ev_on_each_tariff import FIRST_SESSION_ON_EACH_TARIFF, JANUARY_DAYS, OFF_PEAK_EV
from tests._synthetic_weather import synthetic_tmy, weather_for


def _off_peak_ev_home(tariff: TariffConfig) -> HomeConfig:
    """A home with 4 kW of PV, a deterministic 3400 kWh a year of load and the row's off_peak EV, on *tariff*."""
    return HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400, use_stochastic=False),
        ev_config=OFF_PEAK_EV,
        tariff_config=tariff,
    )


def _simulated(home: HomeConfig) -> SimulationResults:
    return simulate_home(home, *JANUARY_DAYS, weather=weather_for(home, synthetic_tmy()))


def _first_charging_session(home: HomeConfig, results: SimulationResults) -> tuple[pd.Timestamp, pd.Timestamp]:
    """The (first minute, minute after the last) of the first unbroken run of minutes whose demand exceeds the household's by more than half the 7 kW charger."""
    ev_kw = results.demand - generate_load_profile(home.load_config, results.window)
    charging = np.concatenate(([False], ev_kw.to_numpy() > 3.5, [False]))
    start, stop = np.flatnonzero(np.diff(charging))[:2]
    return ev_kw.index[start], ev_kw.index[0] + pd.Timedelta(minutes=int(stop))


@pytest.mark.parametrize(("tariff", "first_session"), FIRST_SESSION_ON_EACH_TARIFF)
def test_an_off_peak_ev_home_charges_in_its_tariffs_cheap_minutes(tariff, first_session):
    home = _off_peak_ev_home(tariff)

    assert _first_charging_session(home, _simulated(home)) == first_session


def test_on_economy_10_the_home_charges_its_ev_at_no_peak_rate_minute():
    economy_10 = TariffConfig.economy_10()
    home = _off_peak_ev_home(economy_10)
    results = _simulated(home)
    start, end = _first_charging_session(home, results)

    session_rates = results.tariff_rate[start : end - pd.Timedelta(minutes=1)]

    assert len(session_rates) == 300
    assert (session_rates != economy_10.peak_rate).all()


@pytest.mark.parametrize(
    "battery_config",
    [pytest.param(None, id="no-battery"), pytest.param(BatteryConfig.default_5kwh(), id="5-kwh-battery")],
)
def test_a_home_with_an_off_peak_ev_and_no_tariff_is_refused_when_built(battery_config):
    """The battery-less home pins the check ahead of HomeConfig's early return for a home with no battery."""
    with pytest.raises(ConfigurationError) as refused:
        HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(),
            battery_config=battery_config,
            ev_config=OFF_PEAK_EV,
        )

    assert "smart_charging_mode 'off_peak'" in str(refused.value)
    assert "cheap periods" in str(refused.value)
    assert "no tariff" in str(refused.value)


def test_a_home_with_an_off_peak_ev_builds_with_a_tariff():
    home = HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(),
        ev_config=OFF_PEAK_EV,
        tariff_config=TariffConfig.economy_7(),
    )

    assert home.tariff_config == TariffConfig.economy_7()


@pytest.mark.parametrize("mode", ["none", "solar"])
def test_a_home_whose_ev_reads_no_tariff_builds_without_one(mode):
    ev_config = EVConfig("7kW", 18, 7, 35.0, mode)

    home = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(), ev_config=ev_config)

    assert home.ev_config == ev_config
