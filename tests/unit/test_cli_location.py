# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home run --location` reads a location as location.parse_location reads it, and `config locations` lists location.LOCATION_PRESETS.

A run at a preset is shown to be at that preset by the weather cache seeded for it alone:
a run anywhere else reaches PVGIS, which fails a test run offline.
"""

from pathlib import Path

import pandas as pd
import pytest
from typer.testing import CliRunner, Result

from solar_challenge.cli.home import home_config_for_run
from solar_challenge.cli.main import app
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import LOCATION_PRESETS, parse_location
from solar_challenge.weather import WeatherCache
from tests._cli_table_text import table_text
from tests._seeded_tmy import ClearJuneDays

runner = CliRunner()

_DAY = "2024-06-21"
_JUNE_DAY = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1)


@pytest.fixture(autouse=True)
def _in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Work in tmp_path."""
    monkeypatch.chdir(tmp_path)


def _home_run_at(location: str) -> Result:
    """`home run` of the default home over _DAY, with no config file, at *location*."""
    return runner.invoke(
        app, ["home", "run", "--location", location, "--start", _DAY, "--end", _DAY], catch_exceptions=False
    )


@pytest.mark.parametrize("preset", list(LOCATION_PRESETS))
def test_home_run_runs_at_the_preset_its_location_option_names(preset: str, weather_cache: WeatherCache) -> None:
    weather_cache.put(_JUNE_DAY.hourly_weather(), "tmy", LOCATION_PRESETS[preset])

    result = _home_run_at(preset)

    assert result.exit_code == 0, result.output


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("london", id="preset"),
        pytest.param(" Edinburgh ", id="padded-title-case-preset"),
        pytest.param("51.48,-3.18,10", id="lat-lon-alt"),
    ],
)
def test_the_home_the_option_builds_is_at_the_location_parse_location_reads(text: str) -> None:
    """The location reaches the home whole, its name and altitude included."""
    assert home_config_for_run(None, location_str=text).location == parse_location(text)


@pytest.mark.parametrize(
    ("text", "named"),
    [
        pytest.param("londn", "'londn'", id="misspelt-preset"),
        pytest.param("51.5;-0.1", "'51.5;-0.1'", id="semicolon"),
        pytest.param("95,0", "latitude", id="latitude-out-of-range"),
        pytest.param("51.0,abc", "longitude", id="longitude-not-a-number"),
    ],
)
def test_a_location_the_grammar_refuses_is_a_configuration_error_and_nothing_is_simulated(
    text: str, named: str
) -> None:
    """`home run` prints parse_location's own refusal as its one line on stderr, so the "Simulating" status line printed before a run never appears."""
    with pytest.raises(ConfigurationError) as refusal:
        parse_location(text)

    result = _home_run_at(text)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert " ".join(result.stderr.split()) == f"Configuration error: {refusal.value}"
    assert named in str(refusal.value)


def test_the_location_options_help_names_each_preset() -> None:
    result = runner.invoke(app, ["home", "run", "--help"], catch_exceptions=False)

    assert result.exit_code == 0
    assert [preset for preset in LOCATION_PRESETS if preset not in table_text(result.stdout)] == []
