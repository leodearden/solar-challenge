# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Offline tests of how `finance run` composes its one report from --assumptions, --project and --cost-recovery, with the fleet simulator injected through Click's context object."""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
import yaml

from solar_challenge.fleet import FleetConfig, FleetResults
from tests._cli_fleet_simulator import invoke_cli, invoke_finance_run
from tests._finance_builders import make_fleet_results, make_fleet_results_of

_PROJECT_HEADING = "## Project Economics"
_COST_RECOVERY_HEADING = "## Cost-Recovery Analysis"
_PROJECT_STATUS = "Computing project-level economics (DSCR/IRR/payback)…"
_COST_RECOVERY_STATUS = "Solving cost-recovery own-use rate…"


@pytest.fixture(scope="module")
def fleet_results() -> FleetResults:
    """Two homes, each self-consuming 2,000 kWh, exporting 800 kWh and importing 1,200 kWh over a year."""
    return make_fleet_results(n_homes=2, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


def _write_scenario(
    directory: Path,
    *,
    self_consumption_override: float | None = None,
    seg_rate: float | None = None,
) -> Path:
    """Write a scenario of two battery-less homes to *directory*, and return its path.

    Its finance block carries *self_consumption_override* and the scenario has a
    top-level SEG rate of *seg_rate*, each only when given.
    """
    finance: dict[str, float] = {"standing_charge_pence_per_day": 28.0}
    if self_consumption_override is not None:
        finance["self_consumption_override"] = self_consumption_override
    scenario: dict[str, object] = {
        "name": "Finance Run CLI Test",
        "location": {"latitude": 51.45, "longitude": -2.58, "timezone": "Europe/London"},
        "fleet_distribution": {
            "n_homes": 2,
            "seed": 1,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": finance,
    }
    if seg_rate is not None:
        scenario["seg"] = {"rate_pence_per_kwh": seg_rate}
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "scenario.yaml"
    path.write_text(yaml.safe_dump(scenario))
    return path


def _total_outlay_cells(report: str) -> list[str]:
    """The cells of the report's Total Outlay row after its label: one per bill the report renders."""
    rows = [line for line in report.splitlines() if line.startswith("| **Total Outlay** |")]
    assert len(rows) == 1, report
    return [cell.strip() for cell in rows[0].strip("|").split("|")][1:]


def _bill_cells(scenario: Path, assumptions: str, fleet_results: FleetResults) -> list[str]:
    """The Total Outlay cells of the report that `finance run --assumptions <assumptions>` prints for *scenario*."""
    result = invoke_finance_run(["--assumptions", assumptions, str(scenario)], fleet_results)
    assert result.exit_code == 0, result.output
    return _total_outlay_cells(result.stdout)


def _in_order_of_appearance(text: str, fragments: Sequence[str]) -> list[str]:
    """The *fragments* that occur in *text*, in the order of their first occurrence."""
    return sorted((fragment for fragment in fragments if fragment in text), key=text.index)


class _RecordingSimulator:
    """A fleet simulator that records each simulation it is asked for, and answers with its results for the homes asked about."""

    def __init__(self, results: FleetResults) -> None:
        self._results = results
        self.requests: list[tuple[FleetConfig, pd.Timestamp, pd.Timestamp]] = []

    def __call__(
        self, fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp
    ) -> FleetResults:
        self.requests.append((fleet_config, start, end))
        return make_fleet_results_of(self._results.per_home_results, homes=fleet_config.homes)


def test_each_assumptions_mode_renders_its_own_bill_column(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """--assumptions physics and spreadsheet each render one bill, and both renders the two side by side."""
    scenario = _write_scenario(tmp_path)

    physics = _bill_cells(scenario, "physics", fleet_results)
    spreadsheet = _bill_cells(scenario, "spreadsheet", fleet_results)
    both = _bill_cells(scenario, "both", fleet_results)

    assert both == physics + spreadsheet
    assert physics != spreadsheet


def test_the_spreadsheet_column_bills_the_scenarios_override_and_the_physics_column_ignores_it(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """--assumptions both bills its spreadsheet column at the scenario's self_consumption_override, and its physics column at the simulated own-use whatever the override."""
    without_override = _write_scenario(tmp_path / "without_override")
    with_override = _write_scenario(tmp_path / "with_override", self_consumption_override=0.5)

    physics_without, spreadsheet_without = _bill_cells(without_override, "both", fleet_results)
    physics_with, spreadsheet_with = _bill_cells(with_override, "both", fleet_results)

    assert physics_with == physics_without
    assert spreadsheet_with != spreadsheet_without


@pytest.mark.parametrize(
    ("flags", "headings", "status_lines"),
    [
        pytest.param((), [], [], id="neither"),
        pytest.param(("--project",), [_PROJECT_HEADING], [_PROJECT_STATUS], id="project"),
        pytest.param(
            ("--cost-recovery",),
            [_COST_RECOVERY_HEADING],
            [_COST_RECOVERY_STATUS],
            id="cost-recovery",
        ),
        pytest.param(
            ("--project", "--cost-recovery"),
            [_PROJECT_HEADING, _COST_RECOVERY_HEADING],
            [_PROJECT_STATUS, _COST_RECOVERY_STATUS],
            id="both",
        ),
    ],
)
def test_each_economics_flag_adds_its_block_and_status_line(
    tmp_path: Path,
    fleet_results: FleetResults,
    flags: tuple[str, ...],
    headings: list[str],
    status_lines: list[str],
) -> None:
    """--project and --cost-recovery each announce themselves on stderr and append their own block to the report, the project block first when both are passed."""
    result = invoke_finance_run([*flags, str(_write_scenario(tmp_path))], fleet_results)

    assert result.exit_code == 0, result.output
    assert _in_order_of_appearance(
        result.stdout, [_PROJECT_HEADING, _COST_RECOVERY_HEADING]
    ) == headings
    assert _in_order_of_appearance(
        " ".join(result.stderr.split()), [_PROJECT_STATUS, _COST_RECOVERY_STATUS]
    ) == status_lines


def test_without_economics_flags_the_fleet_is_simulated_once(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """finance run simulates its fleet once, for its bill, when neither --project nor --cost-recovery asks for more."""
    simulator = _RecordingSimulator(fleet_results)

    result = invoke_cli(["finance", "run", str(_write_scenario(tmp_path))], simulator)

    assert result.exit_code == 0, result.output
    assert len(simulator.requests) == 1


def test_the_simulator_receives_the_fleet_paid_the_scenarios_seg_rate_over_the_window(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """finance run simulates the scenario's homes, each paid the scenario's SEG rate, over the --start to --end window in the scenario's timezone."""
    simulator = _RecordingSimulator(fleet_results)
    scenario = _write_scenario(tmp_path, seg_rate=5.5)

    result = invoke_cli(
        ["finance", "run", str(scenario), "--start", "2024-06-01", "--end", "2024-06-07"],
        simulator,
    )

    assert result.exit_code == 0, result.output
    fleet_config, start, end = simulator.requests[0]
    assert [
        home.seg_tariff.rate_pence_per_kwh if home.seg_tariff is not None else None
        for home in fleet_config.homes
    ] == [5.5, 5.5]
    assert start == pd.Timestamp("2024-06-01", tz="Europe/London")
    assert end == pd.Timestamp("2024-06-07", tz="Europe/London")
    assert "Simulating fleet of 2 homes for 7 days…" in " ".join(result.stderr.split())
