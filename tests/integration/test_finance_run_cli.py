# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Offline tests of how `finance run` composes its one report from --assumptions, --project and --cost-recovery, with the fleet simulator injected through Click's context object."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from solar_challenge.fleet import FleetResults
from tests._cli_fleet_simulator import invoke_finance_run
from tests._finance_builders import make_fleet_results


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
