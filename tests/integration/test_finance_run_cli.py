# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Offline tests of how `finance run` composes its one report from --assumptions, --project and --cost-recovery, with the fleet simulator injected through Click's context object."""
from __future__ import annotations

import warnings
from collections.abc import Mapping, Sequence
from pathlib import Path

import pandas as pd
import pytest
import yaml
from typer.testing import Result

from solar_challenge.config import load_scenario
from solar_challenge.finance import OwnUseBasis, with_own_use_basis
from solar_challenge.fleet import FleetConfig, FleetResults, FleetSimulate
from solar_challenge.home import simulate_home
from solar_challenge.projection import CostRecoveryRun, run_cost_recovery, scenario_fleet
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli, invoke_finance_run
from tests._finance_builders import make_fleet_results, make_fleet_results_of
from tests._markdown_tables import row_cells, table_rows
from tests._synthetic_weather import synthetic_june_weather, weather_for

_BILL_HEADING = "## Householder Bill"
_DISTRIBUTION_HEADING = "## Per-Home Bill Distribution (Total Annual Outlay, £)"
_PROJECT_HEADING = "## Project Economics"
_COST_RECOVERY_HEADING = "## Cost-Recovery Analysis"
_SOLVED_OUTLAY_HEADING = "## Per-Home Total Outlay at Solved Rate (£)"
_PROJECT_STATUS = "Computing project-level economics (DSCR/IRR/payback)…"
_COST_RECOVERY_STATUS = "Solving cost-recovery own-use rate…"


@pytest.fixture(scope="module")
def fleet_results() -> FleetResults:
    """Two homes, each self-consuming 2,000 kWh, exporting 800 kWh and importing 1,200 kWh over a year."""
    return make_fleet_results(n_homes=2, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


_INTERIOR_FINANCE: Mapping[str, float] = {
    "standing_charge_pence_per_day": 28.0,
    "pv_cost_per_kwp_gbp": 2000.0,
    "grant_gbp": 0.0,
    "own_use_rate_pence_per_kwh": 15.0,
    "retained_cash_floor_per_home_per_year_gbp": 100.0,
    "retail_baseline_rate_pence_per_kwh": 30.0,
}
"""A finance block whose cost-recovery solve binds at its retained-cash floor under either own-use basis, for fleet_results' fleet."""


def _write_scenario(
    directory: Path,
    *,
    self_consumption_override: float | None = None,
    seg_rate: float | None = None,
    tariff: dict[str, object] | None = None,
    name: str | None = "Finance Run CLI Test",
    n_homes: int = 2,
    finance: Mapping[str, float] | None = None,
) -> Path:
    """Write a scenario of *n_homes* battery-less homes to *directory*, and return its path.

    Its finance block is a 28 p/day standing charge with *finance*'s keys
    merged over it, and carries *self_consumption_override*; the scenario has
    a top-level SEG rate of *seg_rate*, its top-level tariff: block, which every
    home it generates is priced at, is *tariff*, and its name is *name*, each
    only when given.
    """
    finance_block: dict[str, float] = {"standing_charge_pence_per_day": 28.0, **(finance or {})}
    if self_consumption_override is not None:
        finance_block["self_consumption_override"] = self_consumption_override
    scenario: dict[str, object] = {
        "location": {"latitude": 51.45, "longitude": -2.58, "timezone": "Europe/London"},
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 1,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": finance_block,
    }
    if seg_rate is not None:
        scenario["seg"] = {"rate_pence_per_kwh": seg_rate}
    if tariff is not None:
        scenario["tariff"] = tariff
    if name is not None:
        scenario["name"] = name
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "scenario.yaml"
    path.write_text(yaml.safe_dump(scenario))
    return path


def _total_outlay_cells(report: str) -> list[str]:
    """The cells of the report's Total Outlay row after its label: one per bill the report renders."""
    return row_cells(report, _BILL_HEADING, "**Total Outlay**")


def _bill_cells(scenario: Path, assumptions: str, fleet_results: FleetResults) -> list[str]:
    """The Total Outlay cells of the report that `finance run --assumptions <assumptions>` prints for *scenario*."""
    result = invoke_finance_run(["--assumptions", assumptions, str(scenario)], fleet_results)
    assert result.exit_code == 0, result.output
    return _total_outlay_cells(result.stdout)


def _in_order_of_appearance(text: str, fragments: Sequence[str]) -> list[str]:
    """The *fragments* that occur in *text*, in the order of their first occurrence."""
    return sorted((fragment for fragment in fragments if fragment in text), key=text.index)


def _section(report: str, heading: str) -> str:
    """The lines of *report* from its *heading* line up to the next ## heading."""
    lines = report.splitlines()
    assert heading in lines, report
    first = lines.index(heading)
    next_heading = next(
        (number for number in range(first + 1, len(lines)) if lines[number].startswith("## ")),
        len(lines),
    )
    return "\n".join(lines[first:next_heading])


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


def _own_use_payment_cell(report: str) -> str:
    """The one cell of the report's Own-Use Payment row after its label: a single bill's own-use payment."""
    (cell,) = row_cells(report, _BILL_HEADING, "Own-Use Payment")
    return cell


def test_the_spreadsheet_bill_is_headed_by_its_override_and_names_no_physics(tmp_path: Path) -> None:
    """One home generating 4,000 kWh and demanding 3,400, of which it imports 2,200, owes £420.00 of own-use at 70% of its generation and £180.00 at its simulated 1,200 kWh, each at 15 p/kWh."""
    scenario = _write_scenario(tmp_path, n_homes=1, finance={"standing_charge_pence_per_day": 60.0})
    one_home = make_fleet_results(n_homes=1, self_kwh=1200.0, export_kwh=2800.0, import_kwh=2200.0)

    spreadsheet = invoke_finance_run(["--assumptions", "spreadsheet", str(scenario)], one_home)
    physics = invoke_finance_run(["--assumptions", "physics", str(scenario)], one_home)

    assert spreadsheet.exit_code == 0, spreadsheet.output
    assert physics.exit_code == 0, physics.output
    assert "| Line Item | Spreadsheet (70% self-consumption) |" in spreadsheet.stdout.splitlines()
    assert _own_use_payment_cell(spreadsheet.stdout) == "£420.00"
    assert "Physics" not in spreadsheet.stdout
    assert _own_use_payment_cell(physics.stdout) == "£180.00"


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


def test_project_economics_are_the_same_with_and_without_cost_recovery(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """For a scenario that sets a SEG rate, --project's Project Economics block is the same whether or not --cost-recovery is also passed.

    The fleet earns no export revenue, so SEG income could reach the block only
    through the scenario's rate itself.
    """
    scenario = _write_scenario(tmp_path, seg_rate=5.5)

    project_only = invoke_finance_run(["--project", str(scenario)], fleet_results)
    with_cost_recovery = invoke_finance_run(
        ["--project", "--cost-recovery", str(scenario)], fleet_results
    )

    assert project_only.exit_code == 0, project_only.output
    assert with_cost_recovery.exit_code == 0, with_cost_recovery.output
    assert _section(project_only.stdout, _PROJECT_HEADING) == _section(
        with_cost_recovery.stdout, _PROJECT_HEADING
    )


def test_without_economics_flags_the_fleet_is_simulated_once(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """finance run simulates its fleet once, for its bill, when neither --project nor --cost-recovery asks for more."""
    simulator = _RecordingSimulator(fleet_results)

    result = invoke_cli(["finance", "run", str(_write_scenario(tmp_path))], answering(simulator))

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
        answering(simulator),
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


def test_every_simulation_of_project_and_cost_recovery_pays_the_scenarios_seg_rate(tmp_path: Path) -> None:
    """The bill run and every projection age the economics and the cost-recovery solve ask for simulate homes paid the scenario's SEG rate."""
    recorder = RecordingSimulate()
    scenario = _write_scenario(tmp_path, seg_rate=5.5)

    result = invoke_cli(
        ["finance", "run", "--project", "--cost-recovery", "--start", "2024-06-01", "--end", "2024-06-07", str(scenario)],
        answering(recorder),
    )

    assert result.exit_code == 0, result.output
    assert len(recorder.fleets) > 1
    assert [home.seg_tariff.rate_pence_per_kwh if home.seg_tariff is not None else None for home in recorder.homes] == [
        5.5
    ] * len(recorder.homes)


@pytest.mark.parametrize("name", ["Finance Run CLI Test", None])
def test_the_report_is_titled_with_the_files_name_else_its_path(tmp_path: Path, name: str | None) -> None:
    scenario = _write_scenario(tmp_path, name=name)

    result = invoke_cli(
        ["finance", "run", "--start", "2024-06-01", "--end", "2024-06-07", str(scenario)],
        answering(RecordingSimulate()),
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines()[0] == f"# Finance Report: {name if name is not None else scenario}"


_MIDSUMMER = "2024-06-21"


def _simulated_on_a_clear_midsummer_day(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
    """Each home of *fleet_config* simulated by simulate_home from *start* to *end* on a clear 21 June's weather."""
    weather = synthetic_june_weather(_MIDSUMMER)
    return make_fleet_results_of(
        [simulate_home(home, start, end, weather=weather_for(home, weather)) for home in fleet_config.homes],
        homes=fleet_config.homes,
    )


def _import_cost_cell(report: str) -> str:
    """The one cell of the report's Import Cost row after its label: a single bill's import cost."""
    (cell,) = row_cells(report, _BILL_HEADING, "Import Cost")
    return cell


def _finance_run_on_midsummer(scenario: Path) -> tuple[Result, list[str]]:
    """`finance run` of *scenario* over 21 June, its homes simulated by simulate_home, and the message of every warning it raised."""
    with warnings.catch_warnings(record=True) as raised:
        warnings.simplefilter("always")
        result = invoke_cli(
            ["finance", "run", str(scenario), "--start", _MIDSUMMER, "--end", _MIDSUMMER],
            answering(_simulated_on_a_clear_midsummer_day),
        )
    return result, [str(warning.message) for warning in raised]


def test_a_scenarios_zero_tariff_bills_its_homes_no_import_and_warns_of_no_missing_tariff(tmp_path: Path) -> None:
    """The scenario's £0 flat tariff prices every home's simulated run, so `finance run` bills their import at £0 rather than at retail."""
    scenario = _write_scenario(tmp_path, seg_rate=4.1, tariff={"type": "flat_rate", "rate_per_kwh": 0.0})

    result, raised = _finance_run_on_midsummer(scenario)

    assert result.exit_code == 0, result.output
    assert _import_cost_cell(result.stdout) == "£0.00"
    assert not [message for message in raised if "no tariff configured" in message]
    assert "no tariff configured" not in result.output


def test_a_scenario_without_a_tariff_bills_its_homes_import_at_retail_and_warns(tmp_path: Path) -> None:
    scenario = _write_scenario(tmp_path, seg_rate=4.1)

    result, raised = _finance_run_on_midsummer(scenario)

    assert result.exit_code == 0, result.output
    assert _import_cost_cell(result.stdout) != "£0.00"
    assert [message for message in raised if "no tariff configured" in message]


def _cost_recovery_run(scenario_path: Path, basis: OwnUseBasis, simulate: FleetSimulate) -> CostRecoveryRun:
    """The cost-recovery run of the scenario at *scenario_path* under its finance put on *basis*, every age simulated by *simulate*, its warnings ignored."""
    scenario = load_scenario(scenario_path)
    assert scenario.finance is not None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return run_cost_recovery(
            scenario_fleet(scenario), with_own_use_basis(scenario.finance, basis), simulate=simulate
        )


def _figures(run: CostRecoveryRun) -> dict[tuple[str, str], str]:
    """*run*'s figures the report renders, keyed by (heading, row label), formatted as the report formats them."""
    return {
        (_COST_RECOVERY_HEADING, "Solved Own-Use Rate"): f"{run.solution.own_use_rate_pence_per_kwh:.2f} p/kWh",
        (_COST_RECOVERY_HEADING, "CBS Net Surplus / home / yr"): f"£{run.solution.net_surplus_per_home_per_year_gbp:.2f}",
        (_PROJECT_HEADING, "Mean Fleet Surplus / yr"): f"£{run.economics.mean_fleet_surplus_per_year_gbp:,.0f}",
        (_PROJECT_HEADING, "Min DSCR (loan years)"): f"{run.economics.min_dscr:.2f}×",
    }


def test_spreadsheet_economics_and_solve_are_the_overrides(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """--assumptions spreadsheet reports the projection, economics and solve of the scenario's finance at the 70% override, not the physics ones."""
    path = _write_scenario(tmp_path, finance=_INTERIOR_FINANCE)

    def fake(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
        return fleet_results

    spreadsheet = _cost_recovery_run(path, OwnUseBasis.OVERRIDE, fake)
    physics = _cost_recovery_run(path, OwnUseBasis.SIMULATED, fake)
    assert (spreadsheet.solution.binding, physics.solution.binding) == ("floor", "floor")
    expected, physics_figures = _figures(spreadsheet), _figures(physics)
    assert (
        expected[(_COST_RECOVERY_HEADING, "Solved Own-Use Rate")]
        != physics_figures[(_COST_RECOVERY_HEADING, "Solved Own-Use Rate")]
    )

    result = invoke_finance_run(
        ["--assumptions", "spreadsheet", "--project", "--cost-recovery", str(path)], fleet_results
    )

    assert result.exit_code == 0, result.output
    rendered = {(heading, label): row_cells(result.stdout, heading, label) for heading, label in expected}
    assert rendered == {key: [figure] for key, figure in expected.items()}
    assert rendered != {key: [figure] for key, figure in physics_figures.items()}


def test_physics_on_a_yaml_override_is_the_physics_run(
    tmp_path: Path, fleet_results: FleetResults
) -> None:
    """--assumptions physics reports the same bill, economics and solve for a scenario whose finance block sets a 0.70 override as for the same scenario without one."""
    plain = _write_scenario(tmp_path / "plain", finance=_INTERIOR_FINANCE)
    overridden = _write_scenario(
        tmp_path / "overridden", finance={**_INTERIOR_FINANCE, "self_consumption_override": 0.70}
    )
    arguments = ["--assumptions", "physics", "--project", "--cost-recovery"]

    plain_run = invoke_finance_run([*arguments, str(plain)], fleet_results)
    overridden_run = invoke_finance_run([*arguments, str(overridden)], fleet_results)

    assert plain_run.exit_code == 0, plain_run.output
    assert overridden_run.exit_code == 0, overridden_run.output
    assert overridden_run.stdout == plain_run.stdout


def _fleets_simulated(scenario: Path, assumptions: str) -> tuple[int, str]:
    """How many fleets `finance run --assumptions <assumptions> --project --cost-recovery` asks a fresh RecordingSimulate for over 1-7 June 2024, and the report it prints."""
    recorder = RecordingSimulate()
    result = invoke_cli(
        [
            "finance", "run", "--assumptions", assumptions, "--project", "--cost-recovery",
            "--start", "2024-06-01", "--end", "2024-06-07", str(scenario),
        ],
        answering(recorder),
    )
    assert result.exit_code == 0, result.output
    return len(recorder.fleets), result.stdout


def test_both_modes_render_every_table_in_two_columns_and_project_once_per_mode(tmp_path: Path) -> None:
    """--assumptions both projects the fleet once per mode, the age-0 fleet answered by the one bill run, and renders every table physics then spreadsheet."""
    scenario = _write_scenario(tmp_path)

    count_physics, _ = _fleets_simulated(scenario, "physics")
    count_both, report = _fleets_simulated(scenario, "both")

    assert count_physics > 1
    assert count_both - 1 == 2 * (count_physics - 1)
    for heading in (
        _BILL_HEADING,
        _DISTRIBUTION_HEADING,
        _PROJECT_HEADING,
        _COST_RECOVERY_HEADING,
        _SOLVED_OUTLAY_HEADING,
    ):
        assert table_rows(report, heading)[0][1:] == ["Physics", "Spreadsheet (70% self-consumption)"], heading
