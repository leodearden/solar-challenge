# SPDX-License-Identifier: AGPL-3.0-or-later
"""Invariant 11's window half: the CLI's window defaults are timebase's.

Every --start and --end option of the CLI defaults to the ISO string of timebase.DEFAULT_FIRST_DAY or
DEFAULT_LAST_DAY, or to None, as optimize configs' options do: an option left unset reads the scenario's period, or
that default window when the scenario sets no period. config template home and config template scenario write that
window as their period. No module of src/solar_challenge outside timebase.py holds a string that is exactly an ISO
date, so no window default is restated as a literal (docs/prds/dashboard-limits-and-distribution-table.md §4.2).
"""

import ast
import re
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import NoReturn

import pandas as pd
import pytest
import typer.core
import typer.main
import yaml
from typer.testing import CliRunner

import solar_challenge.cli
from solar_challenge.timebase import DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY
from tests._cli_fleet_simulator import ReachedTheSweep, answering, invoke_cli

_WINDOW_OPTION_DEFAULTS = {
    "--start": DEFAULT_FIRST_DAY.isoformat(),
    "--end": DEFAULT_LAST_DAY.isoformat(),
}
"""Each window option's name, and the ISO string it defaults to unless it defaults to None."""

_COMMANDS_WITH_A_WINDOW = frozenset({"home run", "fleet run", "fleet sweep", "finance run", "optimize configs"})
"""The commands that take --start and --end, each named by its path from the CLI's root."""

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def _window_options() -> Iterator[tuple[str, str, object]]:
    """(command path, option name, default) for each --start or --end option of the CLI's commands, as ('home run', '--start', '2024-01-01')."""
    root = typer.main.get_command(solar_challenge.cli.app)
    assert isinstance(root, typer.core.TyperGroup), f"The CLI's root is a group of commands, not {root!r}"
    return _window_options_under(root, ())


def _window_options_under(group: typer.core.TyperGroup, path: tuple[str, ...]) -> Iterator[tuple[str, str, object]]:
    """_window_options' triples for the commands under group, whose own path from the CLI's root is path."""
    for name, command in group.commands.items():
        command_path = (*path, name)
        if isinstance(command, typer.core.TyperGroup):
            yield from _window_options_under(command, command_path)
            continue
        for parameter in command.params:
            for option in sorted(_WINDOW_OPTION_DEFAULTS.keys() & set(parameter.opts)):
                yield " ".join(command_path), option, parameter.default


def _iso_date_literals(package_dir: Path, *, skipping: Path) -> list[tuple[str, int, str]]:
    """(path relative to package_dir, line, value) of each string constant that is exactly an ISO date, as "2024-06-01", in the Python files under package_dir other than skipping, in path and line order.

    A date inside a longer string, as in "--start 2024-01-01 --end 2024-01-07", is not one.
    """
    return sorted(
        (module.relative_to(package_dir).as_posix(), node.lineno, node.value)
        for module in sorted(package_dir.rglob("*.py"))
        if module != skipping
        for node in ast.walk(ast.parse(module.read_text(encoding="utf-8"), filename=str(module)))
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and _ISO_DATE.fullmatch(node.value)
    )


def test_every_start_and_end_option_defaults_to_the_default_window_or_to_none() -> None:
    """None is optimize configs' default for both options, which then read the scenario's period, or the default window when the scenario sets none (tests/unit/test_window_defaults.py::test_optimize_configs_given_no_window_simulates_the_default_window)."""
    options = list(_window_options())

    misdefaulted = [
        f"{command} {option} defaults to {default!r}"
        for command, option, default in options
        if default not in (_WINDOW_OPTION_DEFAULTS[option], None)
    ]
    assert misdefaulted == [], (
        f"Each --start defaults to {_WINDOW_OPTION_DEFAULTS['--start']!r} or None, and each --end to "
        f"{_WINDOW_OPTION_DEFAULTS['--end']!r} or None, timebase's default window: {'; '.join(misdefaulted)}"
    )
    assert _COMMANDS_WITH_A_WINDOW <= {command for command, _, _ in options}, options


def test_optimize_configs_given_no_window_simulates_the_default_window(tmp_path: Path) -> None:
    """Given neither --start nor --end, over a scenario that sets no period, the sweep simulates timebase's default window."""
    scenario_file = tmp_path / "scenario.yaml"
    scenario_file.write_text(
        yaml.safe_dump(
            {
                "name": "No period",
                "location": {"latitude": 51.45, "longitude": -2.58, "timezone": "Europe/London"},
                "fleet_distribution": {
                    "n_homes": 1,
                    "seed": 42,
                    "pv": {"capacity_kw": 4.0},
                    "load": {"annual_consumption_kwh": 3500},
                },
                "finance": {"standing_charge_pence_per_day": 28.0},
            }
        ),
        encoding="utf-8",
    )
    asked_windows: list[tuple[date, date]] = []

    def simulate(fleet: object, start: pd.Timestamp, end: pd.Timestamp) -> NoReturn:
        asked_windows.append((start.date(), end.date()))
        raise ReachedTheSweep

    result = invoke_cli(["optimize", "configs", str(scenario_file)], answering(simulate))

    assert isinstance(result.exception, ReachedTheSweep), result.output
    assert asked_windows == [(DEFAULT_FIRST_DAY, DEFAULT_LAST_DAY)]


@pytest.mark.parametrize("template_type", ["home", "scenario"])
def test_config_template_writes_the_default_window_as_its_period(tmp_path: Path, template_type: str) -> None:
    """The template's period is the default window's two days, each written as a quoted ISO string, which YAML reads as text."""
    template_file = tmp_path / f"{template_type}.yaml"

    written = CliRunner().invoke(
        solar_challenge.cli.app,
        ["config", "template", template_type, "-o", str(template_file)],
        catch_exceptions=False,
    )

    assert written.exit_code == 0, written.output
    assert yaml.safe_load(template_file.read_text(encoding="utf-8"))["period"] == {
        "start_date": DEFAULT_FIRST_DAY.isoformat(),
        "end_date": DEFAULT_LAST_DAY.isoformat(),
    }


def test_the_date_literal_scan_names_a_module_holding_an_iso_date_string(tmp_path: Path) -> None:
    """The scan names the seeded module's ISO date and its line, and passes over a date inside a longer string and over the one module it skips."""
    (tmp_path / "seeded.py").write_text(
        'START = "2024-03-01"\nHELP = "e.g. --start 2024-03-01 --end 2024-03-07"\n', encoding="utf-8"
    )
    (tmp_path / "timebase.py").write_text('FIRST = "2024-01-01"\n', encoding="utf-8")

    assert _iso_date_literals(tmp_path, skipping=tmp_path / "timebase.py") == [("seeded.py", 1, "2024-03-01")]


def test_no_module_outside_timebase_holds_an_iso_date_string(project_root: Path) -> None:
    """A window default is read from timebase, the one module that holds the window's days."""
    package_dir = project_root / "src" / "solar_challenge"

    literals = _iso_date_literals(package_dir, skipping=package_dir / "timebase.py")

    assert literals == [], (
        "Modules of src/solar_challenge that restate a date as an ISO string, in place of reading it from "
        "timebase: " + "; ".join(f"{path}:{line}: {value!r}" for path, line, value in literals)
    )
