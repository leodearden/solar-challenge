# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home quick` runs to completion from 1 June 2024 and simulates the default home."""

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import synthetic_june_weather

runner = CliRunner()

_DAY = "2024-06-01"


@pytest.fixture(autouse=True)
def _bristol_june_tmy(weather_cache: WeatherCache) -> None:
    """Serve a clear _DAY, the day `home quick` starts on, as Bristol's TMY."""
    weather_cache.put(synthetic_june_weather(_DAY), "tmy", Location.bristol())


def _saved_minutes(tmp_path: Path, *options: str) -> pd.DataFrame:
    """The minutes `home quick 4 --days 1 *options` saves, read back from a CSV under tmp_path."""
    csv_path = tmp_path / "quick.csv"

    result = runner.invoke(
        app, ["home", "quick", "4", "--days", "1", *options, "-o", str(csv_path)]
    )

    assert result.exit_code == 0, result.output
    return pd.read_csv(csv_path, index_col=0, parse_dates=True)


def test_home_quick_runs_to_completion_and_prints_the_summary() -> None:
    """`home quick 4 5 --days 1` exits 0 and prints the results table."""
    result = runner.invoke(app, ["home", "quick", "4", "5", "--days", "1"])

    assert result.exit_code == 0, result.output
    assert "Quick Simulation Results" in result.stdout


def test_home_quick_saves_the_minutes_from_midnight_on_1_june_2024(tmp_path: Path) -> None:
    """`--output` saves the simulated minutes, the first at midnight on 1 June 2024."""
    saved = _saved_minutes(tmp_path)

    assert saved.index[0] == pd.Timestamp(_DAY, tz=Location.bristol().timezone)


@pytest.mark.parametrize(
    ("consumption_options", "expected_load"),
    [
        pytest.param([], LoadConfig(), id="default-is-the-ofgem-tdcv"),
        pytest.param(
            ["-c", "4200"],
            LoadConfig(annual_consumption_kwh=4200.0),
            id="c-sets-the-annual-consumption",
        ),
    ],
)
def test_home_quick_demand_is_the_days_share_of_the_annual_consumption(
    consumption_options: list[str], expected_load: LoadConfig, tmp_path: Path
) -> None:
    """The saved day's demand sums to the expected load's day, which the annual consumption fixes whatever the random profile."""
    saved = _saved_minutes(tmp_path, *consumption_options)

    day = pd.Timestamp(_DAY)
    expected_demand = generate_load_profile(expected_load, day, day)
    assert saved["demand_kw"].sum() == pytest.approx(expected_demand.sum())
