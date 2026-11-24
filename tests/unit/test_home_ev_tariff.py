# SPDX-License-Identifier: AGPL-3.0-or-later
"""§9 row 15 of docs/prds/tariff-coverage-classifier-presets.md at the home: simulate_home and `home run` charge an off_peak EV in its tariff's cheap minutes, and HomeConfig refuses one with no tariff."""

from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import CliRunner
from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.main import app
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.tariff import TariffConfig
from solar_challenge.weather import WeatherCache
from tests._ev_sessions import charging_sessions
from tests._off_peak_ev_on_each_tariff import FIRST_ARRIVAL, FIRST_SESSION_ON_EACH_TARIFF, JANUARY_DAYS, OFF_PEAK_EV
from tests._repository_paths import SCENARIOS_DIR
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
    """The (first minute, minute after the last) of the first unbroken run of minutes from FIRST_ARRIVAL whose demand exceeds the household's by more than half the 7 kW charger."""
    ev_kw = results.demand - generate_load_profile(home.load_config, results.window)
    return charging_sessions(ev_kw[FIRST_ARRIVAL:], above_kw=3.5)[0]


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


def test_home_run_on_economy_10_steps_demand_by_the_charger_at_00_00_and_05_00(
    tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """`home run` gives an off_peak EV its home tariff: scenarios/example-economy7.yaml on Economy 10, with an off_peak EV and a deterministic load.

    The first morning's session, of the stay from the evening before the run, ends at 05:00;
    Economy 7's 00:30-07:30 would put the steps at 00:30 and 05:30.
    """
    document = yaml.safe_load((SCENARIOS_DIR / "example-economy7.yaml").read_text())
    home = document["home"]
    home["ev"] = {
        "charger_type": "7kW",
        "arrival_hour": 18,
        "departure_hour": 7,
        "required_charge_kwh": 35,
        "smart_charging_mode": "off_peak",
    }
    home["tariff"] = {"type": "economy_10"}
    home["load"]["use_stochastic"] = False
    config_file = tmp_path / "example-economy10-off-peak-ev.yaml"
    config_file.write_text(yaml.safe_dump(document))
    weather_cache.put(synthetic_tmy(), "tmy", Location.bristol())
    output = tmp_path / "results.csv"

    result = CliRunner().invoke(
        app,
        ["home", "run", str(config_file), "--start", "2024-01-10", "--end", "2024-01-11", "--output", str(output)],
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    demand_steps = pd.read_csv(output, index_col=0, parse_dates=True)["demand_kw"].diff()
    charger_steps = demand_steps[demand_steps.abs() > 3.5]
    assert list(charger_steps.index) == [
        pd.Timestamp("2024-01-10 05:00", tz="Europe/London"),
        pd.Timestamp("2024-01-11 00:00", tz="Europe/London"),
        pd.Timestamp("2024-01-11 05:00", tz="Europe/London"),
    ]
    assert charger_steps.tolist() == pytest.approx([-7.0, 7.0, -7.0], abs=0.5)


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
