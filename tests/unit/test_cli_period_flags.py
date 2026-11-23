# SPDX-License-Identifier: AGPL-3.0-or-later
"""finance run and optimize configs read --start and --end as config.period_window reads a scenario file's period, refusing a pair that gives no window before they simulate any fleet."""

from pathlib import Path
from typing import NoReturn

import pytest
import yaml

from tests._cli_fleet_simulator import answering, invoke_cli

_COMMANDS_READING_A_PERIOD = [
    pytest.param(("finance", "run"), id="finance-run"),
    pytest.param(("optimize", "configs"), id="optimize-configs"),
]


def _write_scenario(tmp_path: Path) -> Path:
    """A one-home scenario with a finance: block and no period, which both commands read."""
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
            }
        ),
        encoding="utf-8",
    )
    return scenario_file


def _simulate_must_not_run(fleet: object, start: object, end: object) -> NoReturn:
    pytest.fail("the command simulated a fleet before refusing its period")


def _whitespace_normalised(output: str) -> str:
    """*output* with every run of whitespace one space, so Rich's line wrapping cannot split a message."""
    return " ".join(output.split())


@pytest.mark.parametrize("command", _COMMANDS_READING_A_PERIOD)
@pytest.mark.parametrize(
    ("flags", "refusal"),
    [
        pytest.param(
            ["--start", "2024", "--end", "2024-01-07"],
            "Configuration error: period.start_date: '2024' is not a day",
            id="P10-a-start-that-is-not-a-day",
        ),
        pytest.param(
            ["--start", "2024-08-31", "--end", "2024-06-01"],
            "Configuration error: period.start_date: 2024-08-31 to period.end_date 2024-06-01 gives no window",
            id="a-last-day-before-the-first",
        ),
    ],
)
def test_a_period_flag_pair_that_gives_no_window_is_refused_before_any_simulation(
    tmp_path: Path, command: tuple[str, str], flags: list[str], refusal: str
) -> None:
    result = invoke_cli([*command, str(_write_scenario(tmp_path)), *flags], answering(_simulate_must_not_run))

    assert result.exit_code == 1, result.output
    assert refusal in _whitespace_normalised(result.output), result.output
