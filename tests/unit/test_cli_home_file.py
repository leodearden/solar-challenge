# SPDX-License-Identifier: AGPL-3.0-or-later
"""`home run` reads its file as config.load_scenario reads it and applies its options to the typed scenario."""

import dataclasses
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.config import load_home_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import LOCATION_PRESETS, parse_location
from solar_challenge.pv import PVConfig
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, covered_days
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._cli_stderr_text import stderr_text
from tests._repository_paths import SCENARIOS_DIR

_DAY = "2024-06-21"


@pytest.fixture(autouse=True)
def _in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Work in tmp_path, so each test writes its file under a short relative name that Rich prints unfolded."""
    monkeypatch.chdir(tmp_path)


def _written(document: dict[str, Any], name: str = "home.yaml") -> Path:
    """Write *document* as YAML to *name* in the working directory."""
    path = Path(name)
    path.write_text(yaml.safe_dump(document))
    return path


def _home_run(*arguments: str) -> tuple[Result, RecordingSimulate]:
    """`home run` with *arguments*, its simulation answered by a RecordingSimulate, which it returns beside the result."""
    recorder = RecordingSimulate()
    result = invoke_cli(["home", "run", *arguments], answering(recorder))
    return result, recorder


_DETERMINISTIC_LOAD = {"annual_consumption_kwh": 3400, "use_stochastic": False}


@pytest.mark.parametrize(
    ("document", "names"),
    [
        pytest.param({"pv": {"capacity_kw": 9}}, ("pv:", "home:"), id="flat-home"),
        pytest.param({"hom": {"pv": {"capacity_kw": 9}}}, ("'hom'",), id="misspelt-home-key"),
        pytest.param({"home": None}, ("home: must be a mapping",), id="null-home"),
        pytest.param({"home": {}, "seg": {"preset": "Nonexistent"}}, ("seg.preset:", "'Nonexistent'"), id="unknown-seg-preset"),
        pytest.param({"homes": [{}]}, ("fleet run",), id="one-home-list"),
        pytest.param({"homes": [{}, {}]}, ("fleet run", "2 homes"), id="two-home-list"),
        pytest.param(
            {
                "fleet_distribution": {
                    "n_homes": 2,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3500},
                }
            },
            ("fleet run",),
            id="fleet-distribution",
        ),
    ],
)
def test_a_file_home_run_cannot_simulate_is_refused_by_name_and_nothing_is_simulated(
    document: dict[str, Any], names: tuple[str, ...]
) -> None:
    result, recorder = _home_run(str(_written(document)), "--start", _DAY, "--end", _DAY)

    assert result.exit_code == 1
    stderr = stderr_text(result)
    assert stderr.startswith("Configuration error:"), stderr
    assert [name for name in names if name not in stderr] == [], stderr
    assert recorder.fleets == []


def _home_off_bristol_with_top_level_tariff_and_seg() -> Path:
    """Write home.yaml: 4 kW of PV and a deterministic 3400 kWh a year of load at 53.48, -2.24, on a top-level Economy 7 tariff and a 15p SEG rate."""
    return _written(
        {
            "location": {"latitude": 53.48, "longitude": -2.24, "timezone": "Europe/London"},
            "tariff": {"type": "economy_7"},
            "seg": {"rate_pence_per_kwh": 15.0},
            "home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD},
        }
    )


def _home_on_its_own_tariff_at_a_seg_preset() -> Path:
    """Write home.yaml: 4 kW of PV and a deterministic 3400 kWh a year of load on its own Economy 7 tariff, exporting at the Octopus SEG preset's rate."""
    return _written(
        {
            "seg": {"preset": "Octopus"},
            "home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD, "tariff": {"type": "economy_7"}},
        }
    )


def _committed_bristol_arbitrage() -> Path:
    """The committed scenarios/bristol-arbitrage.yaml."""
    return SCENARIOS_DIR / "bristol-arbitrage.yaml"


@pytest.mark.parametrize(
    "home_file",
    [
        pytest.param(_home_off_bristol_with_top_level_tariff_and_seg, id="top-level-tariff-off-bristol"),
        pytest.param(_home_on_its_own_tariff_at_a_seg_preset, id="home-tariff-at-a-seg-preset"),
        pytest.param(_committed_bristol_arbitrage, id="bristol-arbitrage"),
    ],
)
def test_home_run_simulates_the_home_load_home_config_reads(home_file: Callable[[], Path]) -> None:
    path = home_file()

    result, recorder = _home_run(str(path), "--start", _DAY, "--end", _DAY)

    assert result.exit_code == 0, result.output
    assert recorder.homes == [load_home_config(path)]


def _with_pv_kw_9(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, pv_config=dataclasses.replace(home.pv_config, capacity_kw=9.0))


def _with_consumption_5000_kwh(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, load_config=dataclasses.replace(home.load_config, annual_consumption_kwh=5000.0))


def _in_edinburgh(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, location=LOCATION_PRESETS["edinburgh"])


def _at_55_95_minus_3_19(home: HomeConfig) -> HomeConfig:
    return dataclasses.replace(home, location=parse_location("55.95,-3.19"))


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        pytest.param(("--pv-kw", "9"), _with_pv_kw_9, id="pv-kw"),
        pytest.param(("--consumption-kwh", "5000"), _with_consumption_5000_kwh, id="consumption-kwh"),
        pytest.param(("--location", "edinburgh"), _in_edinburgh, id="location"),
        pytest.param(("--location", "55.95,-3.19"), _at_55_95_minus_3_19, id="location-coordinates"),
    ],
)
def test_each_option_replaces_only_its_own_setting_of_the_files_home(
    options: tuple[str, ...], expected: Callable[[HomeConfig], HomeConfig]
) -> None:
    path = _written(
        {
            "home": {
                "pv": {"capacity_kw": 4.0, "tilt": 20},
                "battery": {"capacity_kwh": 5.0},
                "load": _DETERMINISTIC_LOAD,
            }
        }
    )

    result, recorder = _home_run(str(path), "--start", _DAY, "--end", _DAY, *options)

    assert result.exit_code == 0, result.output
    assert recorder.homes == [expected(load_home_config(path))]


def _zero_pv_kw() -> None:
    dataclasses.replace(PVConfig(capacity_kw=4.0), capacity_kw=0.0)


def _zero_consumption_kwh() -> None:
    dataclasses.replace(LoadConfig(), annual_consumption_kwh=0.0)


@pytest.mark.parametrize(
    ("option", "construction"),
    [
        pytest.param("--pv-kw", _zero_pv_kw, id="pv-kw"),
        pytest.param("--consumption-kwh", _zero_consumption_kwh, id="consumption-kwh"),
    ],
)
def test_an_option_its_homes_config_refuses_is_refused_naming_the_option(
    option: str, construction: Callable[[], None]
) -> None:
    """The refusal is the config's own message under the option's name, since the user wrote no block for it."""
    with pytest.raises(ConfigurationError) as oracle:
        construction()

    result, recorder = _home_run("--start", _DAY, "--end", _DAY, option, "0")

    assert (result.exit_code, result.stdout) == (1, "")
    assert stderr_text(result) == f"Configuration error: {option}: {oracle.value}"
    assert recorder.fleets == []


def _london(day: object) -> pd.Timestamp:
    """The local midnight starting *day* in Europe/London."""
    return pd.Timestamp(day, tz="Europe/London")


def _home_without_a_period() -> Path:
    """Write home.yaml: 4 kW of PV and a deterministic 3400 kWh a year of load, with no period:."""
    return _written({"home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD}})


@pytest.mark.parametrize(
    ("home_file", "flags", "first", "last"),
    [
        pytest.param(_committed_bristol_arbitrage, (), "2024-01-15", "2024-01-15", id="the-files-period"),
        pytest.param(
            _committed_bristol_arbitrage, ("--start", "2024-01-10"), "2024-01-10", "2024-01-15", id="start-flag"
        ),
        pytest.param(_committed_bristol_arbitrage, ("--end", "2024-01-20"), "2024-01-15", "2024-01-20", id="end-flag"),
        pytest.param(
            _committed_bristol_arbitrage,
            ("--start", "2024-01-10", "--end", "2024-01-20"),
            "2024-01-10",
            "2024-01-20",
            id="both-flags",
        ),
        pytest.param(_home_without_a_period, (), DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, id="no-period"),
        pytest.param(None, ("--end", "2024-01-31"), DEFAULT_FIRST_DAY, "2024-01-31", id="no-file-end-flag"),
    ],
)
def test_home_run_simulates_the_files_period_each_flag_replacing_only_its_own_day(
    home_file: Callable[[], Path] | None, flags: tuple[str, ...], first: object, last: object
) -> None:
    files = () if home_file is None else (str(home_file()),)

    result, recorder = _home_run(*files, *flags)

    assert result.exit_code == 0, result.output
    assert recorder.bounds == [(_london(first), _london(last))]


def test_home_run_names_the_window_it_simulates() -> None:
    result, _ = _home_run(str(_committed_bristol_arbitrage()), "--start", "2024-01-10")

    assert result.exit_code == 0, result.output
    assert "Simulating 6 days from 2024-01-10 to 2024-01-15" in stderr_text(result)


def test_location_moves_the_files_period_onto_its_clock() -> None:
    """A file at a location on another clock simulates its period's days at the --location's local midnights."""
    path = _written(
        {
            "location": {"latitude": 48.85, "longitude": 2.35, "timezone": "Europe/Paris"},
            "period": {"start_date": "2024-01-10", "end_date": "2024-01-12"},
            "home": {"pv": {"capacity_kw": 4.0}, "load": _DETERMINISTIC_LOAD},
        }
    )

    result, recorder = _home_run(str(path), "--location", "bristol")

    assert result.exit_code == 0, result.output
    assert [home.location for home in recorder.homes] == [LOCATION_PRESETS["bristol"]]
    assert recorder.bounds == [(_london("2024-01-10"), _london("2024-01-12"))]


@pytest.mark.parametrize(
    ("home_file", "flags", "named", "first", "last"),
    [
        pytest.param(
            _committed_bristol_arbitrage,
            ("--start", "2024-01-20"),
            "--start 2024-01-20",
            date(2024, 1, 20),
            date(2024, 1, 15),
            id="start-flag-after-the-files-end",
        ),
        pytest.param(
            None,
            ("--end", "2024-01-10", "--start", "2024-01-20"),
            "--start 2024-01-20 --end 2024-01-10",
            date(2024, 1, 20),
            date(2024, 1, 10),
            id="end-flag-before-start-flag",
        ),
    ],
)
def test_flag_days_that_leave_no_window_are_refused_naming_the_flags_and_nothing_is_simulated(
    home_file: Callable[[], Path] | None, flags: tuple[str, ...], named: str, first: date, last: date
) -> None:
    """The refusal is the window's own reason under the flags given, since the user wrote no period: for them."""
    with pytest.raises(ValueError) as reason:
        covered_days(first, last)
    files = () if home_file is None else (str(home_file()),)

    result, recorder = _home_run(*files, *flags)

    assert (result.exit_code, result.stdout) == (1, "")
    assert stderr_text(result) == f"Configuration error: {named}: {reason.value}"
    assert recorder.fleets == []


def test_a_flag_that_is_not_a_date_is_a_usage_error() -> None:
    result, recorder = _home_run("--start", "2024-13-01")

    assert result.exit_code == 2
    assert recorder.fleets == []
