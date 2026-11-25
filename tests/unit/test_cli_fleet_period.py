# SPDX-License-Identifier: AGPL-3.0-or-later
"""`fleet run` and `fleet sweep` simulate the period: of their file, each of --start and --end replacing only its own day, and timebase's default window where the file sets no period."""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY, covered_days
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli
from tests._cli_stderr_text import stderr_text
from tests._fleet_sweep_paths import PARAM_SWEEP, YAML_SWEEP, SweepPath, two_home_fleet_distribution


@pytest.fixture(autouse=True)
def _in_tmp_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Work in tmp_path, so each test writes its file under a short relative name that Rich prints unfolded."""
    monkeypatch.chdir(tmp_path)


_FILE_PERIOD = {"start_date": "2024-06-01", "end_date": "2024-06-07"}


@dataclass(frozen=True)
class _Command:
    """A fleet command on fleet.yaml: the battery capacity_kwh its file holds, the command's name and options, and how many fleets it simulates."""

    capacity_kwh: object
    name: str
    options: tuple[str, ...]
    fleets: int


def _sweep_command(path: SweepPath) -> _Command:
    """`fleet sweep` along *path*, one fleet for each of its values."""
    return _Command(path.capacity_kwh, "sweep", path.options, len(path.values))


_FLEET_RUN = _Command(5.0, "run", (), 1)

_COMMANDS = [
    pytest.param(_FLEET_RUN, id="fleet-run"),
    pytest.param(_sweep_command(YAML_SWEEP), id="fleet-sweep-yaml"),
    pytest.param(_sweep_command(PARAM_SWEEP), id="fleet-sweep-param"),
]


def _write_fleet_file(capacity_kwh: object, period: Optional[dict[str, str]]) -> None:
    """Write fleet.yaml: two homes of 4 kW of PV, a deterministic 3400 kWh a year of load and a battery of *capacity_kwh*, with *period* as its period: when given."""
    document: dict[str, object] = {
        "fleet_distribution": two_home_fleet_distribution(battery={"capacity_kwh": capacity_kwh})
    }
    if period is not None:
        document["period"] = period
    Path("fleet.yaml").write_text(yaml.safe_dump(document))


def _london(day: object) -> pd.Timestamp:
    """The local midnight starting *day* in Europe/London."""
    return pd.Timestamp(day, tz="Europe/London")


def _fleet(command: _Command, *flags: str) -> tuple[Result, RecordingSimulate]:
    """The fleet *command* on fleet.yaml with *flags*, its simulations answered by a RecordingSimulate, which it returns beside the result."""
    recorder = RecordingSimulate()
    result = invoke_cli(["fleet", command.name, "fleet.yaml", *command.options, *flags], answering(recorder))
    return result, recorder

_WINDOWS = [
    pytest.param(_FILE_PERIOD, (), "2024-06-01", "2024-06-07", id="the-files-period"),
    pytest.param(_FILE_PERIOD, ("--end", "2024-06-03"), "2024-06-01", "2024-06-03", id="end-flag"),
    pytest.param(_FILE_PERIOD, ("--start", "2024-06-05"), "2024-06-05", "2024-06-07", id="start-flag"),
    pytest.param(
        _FILE_PERIOD, ("--start", "2024-06-02", "--end", "2024-06-04"), "2024-06-02", "2024-06-04", id="both-flags"
    ),
    pytest.param(None, ("--end", "2024-01-07"), DEFAULT_FIRST_DAY, "2024-01-07", id="default-first-day"),
    pytest.param(None, ("--start", "2024-12-25"), "2024-12-25", DEFAULT_LAST_DAY, id="default-last-day"),
]


@pytest.mark.parametrize("command", _COMMANDS)
@pytest.mark.parametrize(("period", "flags", "first", "last"), _WINDOWS)
def test_each_command_simulates_the_files_period_each_flag_replacing_only_its_own_day(
    command: _Command,
    period: Optional[dict[str, str]],
    flags: tuple[str, ...],
    first: object,
    last: object,
) -> None:
    _write_fleet_file(command.capacity_kwh, period)

    result, recorder = _fleet(command, *flags)

    assert result.exit_code == 0, result.output
    assert recorder.bounds == [(_london(first), _london(last))] * command.fleets


def test_fleet_run_counts_the_days_of_the_files_period() -> None:
    _write_fleet_file(_FLEET_RUN.capacity_kwh, _FILE_PERIOD)

    result, _ = _fleet(_FLEET_RUN)

    assert result.exit_code == 0, result.output
    assert "Simulating fleet of 2 homes for 7 days" in stderr_text(result)


@pytest.mark.parametrize("command", _COMMANDS)
def test_flags_that_leave_no_window_are_refused_naming_them_and_nothing_is_simulated(command: _Command) -> None:
    """The refusal is the window's own reason under the flag given, since the user wrote no such period: themselves."""
    with pytest.raises(ValueError) as reason:
        covered_days(date(2024, 6, 8), date(2024, 6, 7))
    _write_fleet_file(command.capacity_kwh, _FILE_PERIOD)

    result, recorder = _fleet(command, "--start", "2024-06-08")

    assert (result.exit_code, result.stdout) == (1, "")
    assert stderr_text(result) == f"Configuration error: --start 2024-06-08: {reason.value}"
    assert recorder.fleets == []


@pytest.mark.parametrize("command", _COMMANDS)
def test_a_flag_that_is_not_a_date_is_a_usage_error_naming_the_flag(command: _Command) -> None:
    _write_fleet_file(command.capacity_kwh, _FILE_PERIOD)

    result, recorder = _fleet(command, "--start", "2024-13-01")

    assert result.exit_code == 2
    assert "Invalid value for '--start'" in stderr_text(result)
    assert recorder.fleets == []

