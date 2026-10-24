# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home quick` runs to completion from 1 June 2024 and simulates the default home, reading its weather from the test's own cache, or, run as its own process, from the directory CACHE_DIR_VARIABLE names; its help names that home's consumption."""

import os
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.load import LoadConfig, generate_load_profile
from solar_challenge.location import Location
from solar_challenge.weather import CACHE_DIR_VARIABLE, DEFAULT_CACHE_DIR, WeatherCache
from tests._network_guard import refusing_network
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-01"

_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1)
bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()

pytestmark = pytest.mark.usefixtures("bristol_june_tmy")


def _saved_minutes(tmp_path: Path, *options: str) -> pd.DataFrame:
    """The minutes `home quick 4 --days 1 *options` saves, read back from a CSV under tmp_path."""
    csv_path = tmp_path / "quick.csv"

    result = runner.invoke(
        app, ["home", "quick", "4", "--days", "1", *options, "-o", str(csv_path)]
    )

    assert result.exit_code == 0, result.output
    return pd.read_csv(csv_path, index_col=0, parse_dates=True)


def _total_generation_kwh(stdout: str) -> float:
    """The Total Generation figure of the summary table `home quick` prints, in kWh."""
    match = re.search(r"Total Generation\W+(\d+(?:\.\d+)?) kWh", stdout)
    assert match is not None, stdout
    return float(match.group(1))


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
        pytest.param([], LoadConfig(), id="no-c-takes-load-configs-default"),
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


def test_home_quick_run_as_its_own_process_reads_the_weather_cache_the_variable_names(tmp_path: Path) -> None:
    """`home quick 4 --days 1`, run as a child in an empty working directory, simulates offline from the cache the variable names.

    The child runs solar_challenge.cli.app, the object the solar-challenge console script runs. Its
    environment names a cache of this test's making in the variable, in place of the test's own
    weather_cache. It leaves no cache in its working directory.
    """
    cache_dir = tmp_path / "weather"
    _JUNE_DAYS.seed_as_bristol_tmy(WeatherCache(cache_dir=cache_dir))
    working_dir = tmp_path / "working"
    working_dir.mkdir()

    with refusing_network() as refused:
        result = subprocess.run(
            [sys.executable, "-c", "from solar_challenge.cli import app; app()", "home", "quick", "4", "--days", "1"],
            cwd=working_dir,
            env={**os.environ, CACHE_DIR_VARIABLE: str(cache_dir)},
            capture_output=True,
            text=True,
            timeout=120,
        )

    assert refused == []
    assert result.returncode == 0, result.stderr
    assert _total_generation_kwh(result.stdout) > 0
    assert not (working_dir / DEFAULT_CACHE_DIR).exists()


def test_home_quick_help_names_the_consumption_it_defaults_to() -> None:
    """`home quick --help` gives --consumption-kwh's default as a figure: the annual consumption a LoadConfig with no total simulates."""
    result = runner.invoke(app, ["home", "quick", "--help"])

    assert result.exit_code == 0, result.output
    assert f"{LoadConfig().get_annual_consumption():,.0f}" in result.stdout
