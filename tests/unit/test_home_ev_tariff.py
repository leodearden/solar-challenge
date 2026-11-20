# SPDX-License-Identifier: AGPL-3.0-or-later
"""§9 row 15 of docs/prds/tariff-coverage-classifier-presets.md through simulate_home: an off_peak EV home charges in its tariff's cheap minutes."""

import numpy as np
import pandas as pd
import pytest
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
