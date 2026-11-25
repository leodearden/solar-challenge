# SPDX-License-Identifier: AGPL-3.0-or-later
"""finance run and optimize configs simulate their file's period: as load_scenario reads it, and --start and --end each replace only their own day through cli.utils' option pair.

A flag that is not a YYYY-MM-DD date is a usage error, and flag days or a
period: block that give no window are refused before any simulation.
"""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.timebase import covered_days
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._cli_stderr_text import stderr_text

# Each command that simulates its file's period, with the options it needs to run beside the file.
_COMMANDS_READING_A_PERIOD = [
    pytest.param(("finance", "run"), (), id="finance-run"),
    pytest.param(
        ("optimize", "configs"),
        ("--pv", "4", "--battery", "0", "--inverter", "5", "--sensitivity", ""),
        id="optimize-configs",
    ),
]

_JUNE_TO_AUGUST = {"start_date": "2024-06-01", "end_date": "2024-08-31"}


def _write_scenario(tmp_path: Path, **blocks: object) -> Path:
    """A one-home scenario with a finance: block, which both commands read, and the top-level *blocks* given."""
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(
        yaml.safe_dump(
            {
                "name": "Period flags",
                "location": {"latitude": 51.45, "longitude": -2.58, "timezone": "Europe/London"},
                "fleet_distribution": {
                    "n_homes": 1,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3500},
                },
                "finance": {"standing_charge_pence_per_day": 28.0},
                **blocks,
            }
        ),
        encoding="utf-8",
    )
    return scenario_file


def _invoke(
    command: tuple[str, ...], scenario_file: Path, command_options: tuple[str, ...], flags: tuple[str, ...]
) -> tuple[Result, RecordingSimulate]:
    """*command* on *scenario_file* with *command_options* then *flags*, its simulations answered by a RecordingSimulate, which it returns beside the result."""
    recorder = RecordingSimulate()
    result = invoke_cli([*command, str(scenario_file), *command_options, *flags], answering(recorder))
    return result, recorder


def _london(day: str) -> pd.Timestamp:
    """The local midnight starting *day* in Europe/London."""
    return pd.Timestamp(day, tz="Europe/London")


@pytest.mark.parametrize(("command", "command_options"), _COMMANDS_READING_A_PERIOD)
@pytest.mark.parametrize(
    ("flags", "first", "last"),
    [
        pytest.param((), "2024-06-01", "2024-08-31", id="the-files-period"),
        pytest.param(("--end", "2024-06-07"), "2024-06-01", "2024-06-07", id="end-flag"),
        pytest.param(("--start", "2024-07-01"), "2024-07-01", "2024-08-31", id="start-flag"),
    ],
)
def test_each_command_simulates_its_files_period_and_a_flag_replaces_only_its_own_day(
    tmp_path: Path,
    command: tuple[str, ...],
    command_options: tuple[str, ...],
    flags: tuple[str, ...],
    first: str,
    last: str,
) -> None:
    scenario_file = _write_scenario(tmp_path, period=_JUNE_TO_AUGUST)

    result, recorder = _invoke(command, scenario_file, command_options, flags)

    assert result.exit_code == 0, result.output
    assert set(recorder.bounds) == {(_london(first), _london(last))}


@pytest.mark.parametrize(("command", "command_options"), _COMMANDS_READING_A_PERIOD)
def test_a_flag_that_is_not_a_date_is_a_usage_error_before_any_simulation(
    tmp_path: Path, command: tuple[str, ...], command_options: tuple[str, ...]
) -> None:
    result, recorder = _invoke(command, _write_scenario(tmp_path), command_options, ("--start", "2024"))

    assert result.exit_code == 2, result.output
    assert recorder.fleets == []


@pytest.mark.parametrize(("command", "command_options"), _COMMANDS_READING_A_PERIOD)
@pytest.mark.parametrize(
    ("blocks", "flags", "named", "first", "last"),
    [
        pytest.param(
            {},
            ("--start", "2024-08-31", "--end", "2024-06-01"),
            "--start 2024-08-31 --end 2024-06-01",
            date(2024, 8, 31),
            date(2024, 6, 1),
            id="end-flag-before-start-flag",
        ),
        pytest.param(
            {"period": _JUNE_TO_AUGUST},
            ("--start", "2024-09-01"),
            "--start 2024-09-01",
            date(2024, 9, 1),
            date(2024, 8, 31),
            id="start-flag-after-the-files-end",
        ),
    ],
)
def test_flag_days_that_leave_no_window_are_refused_naming_the_flags_before_any_simulation(
    tmp_path: Path,
    command: tuple[str, ...],
    command_options: tuple[str, ...],
    blocks: dict[str, object],
    flags: tuple[str, ...],
    named: str,
    first: date,
    last: date,
) -> None:
    """The refusal is the window's own reason under the flags given."""
    with pytest.raises(ValueError) as reason:
        covered_days(first, last)

    result, recorder = _invoke(command, _write_scenario(tmp_path, **blocks), command_options, flags)

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert stderr_text(result) == f"Configuration error: {named}: {reason.value}"
    assert recorder.fleets == []


@pytest.mark.parametrize(("command", "command_options"), _COMMANDS_READING_A_PERIOD)
@pytest.mark.parametrize(
    ("period", "refusal"),
    [
        pytest.param(
            {"start": "2024-06-01", "end": "2024-06-07"},
            "Configuration error: period: unrecognised keys",
            id="start-and-end-keys",
        ),
        pytest.param("2024", "Configuration error: period: must be a mapping, got str", id="a-string"),
    ],
)
def test_a_period_block_the_reader_refuses_is_refused_naming_period_before_any_simulation(
    tmp_path: Path, command: tuple[str, ...], command_options: tuple[str, ...], period: object, refusal: str
) -> None:
    result, recorder = _invoke(command, _write_scenario(tmp_path, period=period), command_options, ())

    assert result.exit_code == 1, result.output
    assert refusal in stderr_text(result), result.output
    assert recorder.fleets == []
