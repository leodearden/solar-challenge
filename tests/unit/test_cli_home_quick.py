# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home quick` runs to completion from 1 June 2024 and simulates the default home."""

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.cli import home as home_cli
from solar_challenge.cli.main import app
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import synthetic_june_weather

runner = CliRunner()

_DAY = "2024-06-01"


@pytest.fixture(autouse=True)
def _bristol_june_tmy(weather_cache: WeatherCache) -> None:
    """Serve a clear _DAY, the day `home quick` starts on, as Bristol's TMY."""
    weather_cache.put(synthetic_june_weather(_DAY), "tmy", Location.bristol())


def test_home_quick_runs_to_completion_and_prints_the_summary() -> None:
    """`home quick 4 5 --days 1` exits 0 and prints the results table."""
    result = runner.invoke(app, ["home", "quick", "4", "5", "--days", "1"])

    assert result.exit_code == 0, result.output
    assert "Quick Simulation Results" in result.stdout


def test_home_quick_writes_the_csv_when_asked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`--output` saves the simulated minutes."""
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(app, ["home", "quick", "4", "--days", "1", "-o", "q.csv"])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "q.csv").stat().st_size > 0


def test_home_quick_simulates_the_default_home_from_1_june_2024(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no --consumption-kwh the load is LoadConfig()'s default, and the window starts 1 June 2024."""
    simulated = []
    real_simulate_home = home_cli.simulate_home

    def spy(home_config, start_date, end_date):  # type: ignore[no-untyped-def]
        simulated.append((home_config, start_date, end_date))
        return real_simulate_home(home_config, start_date, end_date)

    monkeypatch.setattr(home_cli, "simulate_home", spy)

    result = runner.invoke(app, ["home", "quick", "4", "--days", "1"])

    assert result.exit_code == 0, result.output
    [(home_config, start_date, _)] = simulated
    assert home_config.load_config.annual_consumption_kwh is None
    assert (
        home_config.load_config.get_annual_consumption()
        == LoadConfig().get_annual_consumption()
    )
    assert start_date.date() == pd.Timestamp(_DAY).date()
