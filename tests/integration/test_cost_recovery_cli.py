# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for CR5: --cost-recovery CLI flag and report block."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from solar_challenge.battery import Battery
from solar_challenge.board_report import generate_finance_report
from solar_challenge.cli.main import app
from solar_challenge.finance import BillDistribution
from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig
from solar_challenge.projection import fewest_simulated_ages
from tests._assumption_sections import make_assumption_section, sections_of
from tests._cli_fleet_simulator import RecordingSimulate, answering, invoke_cli, invoke_finance_run
from tests._factories import (
    make_bill_breakdown,
    make_bill_distribution,
    make_bill_distribution_from_statistics,
    make_cost_recovery_solution,
)
from tests._finance_builders import make_fleet_results
from tests._markdown_tables import row_cells
from tests._projection_fleet_names import PROJECTION_AGES_OVER_25_YEARS


# ---------------------------------------------------------------------------
# §A — Helpers
# ---------------------------------------------------------------------------


def _make_bill_distribution() -> BillDistribution:
    """The physics bill these tests pass to generate_finance_report."""
    return make_bill_distribution_from_statistics(
        representative_outlay_gbp=367.5,
        min_gbp=300.0,
        mean_gbp=367.5,
        median_gbp=367.5,
        max_gbp=420.0,
    )


def _value_cell(report: str, heading: str, label: str) -> str:
    """The one value cell of the row labelled *label* in the table under *heading*: a one-mode report's."""
    (cell,) = row_cells(report, heading, label)
    return cell


# ---------------------------------------------------------------------------
# §B — board_report.py cost-recovery block
# ---------------------------------------------------------------------------


class TestGenerateFinanceReportCostRecoveryBasic:
    """generate_finance_report accepts cost_recovery kwarg and renders a block."""

    def test_cost_recovery_section_heading_present(self) -> None:
        """Report must contain a Cost-Recovery section heading when cost_recovery is provided."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        assert "cost-recovery" in report.lower(), (
            f"Expected 'Cost-Recovery' heading in report but got:\n{report}"
        )

    def test_cost_recovery_solved_rate_rendered(self) -> None:
        """Report must show the solved own-use rate."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=18.75, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        shown = _value_cell(report, "## Cost-Recovery Analysis", "Solved Own-Use Rate")
        assert shown == "18.75 p/kWh", f"solved rate not shown in its row:\n{report}"

    def test_cost_recovery_net_surplus_rendered(self) -> None:
        """Report must show the CBS net surplus per home per year."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        shown = _value_cell(report, "## Cost-Recovery Analysis", "CBS Net Surplus / home / yr")
        assert shown == "£27.00", f"net surplus not shown in its row:\n{report}"

    def test_cost_recovery_feasible_indicator_present(self) -> None:
        """Report must contain a feasibility indicator."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        # Should contain some form of feasibility indicator
        assert "feasible" in report.lower() or "floor" in report.lower(), (
            f"Expected feasibility indicator in report but got:\n{report}"
        )

    def test_cost_recovery_none_produces_identical_report(self) -> None:
        """generate_finance_report(bill) without cost_recovery must match cost_recovery=None."""
        bill = _make_bill_distribution()

        report_default = generate_finance_report(sections_of(make_assumption_section(bill=bill)))
        report_none = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=None)))

        assert report_default == report_none, (
            "generate_finance_report() and generate_finance_report(cost_recovery=None) "
            "must produce identical output"
        )

    def test_cost_recovery_none_omits_section_heading(self) -> None:
        """generate_finance_report without cost_recovery must NOT contain a Cost-Recovery heading."""
        bill = _make_bill_distribution()

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill)))

        assert "cost-recovery" not in report.lower(), (
            f"'Cost-Recovery' heading should not appear without cost_recovery param:\n{report}"
        )


# ---------------------------------------------------------------------------
# §C — full board-readable content
# ---------------------------------------------------------------------------


class TestGenerateFinanceReportCostRecoveryFull:
    """Full board-readable content — distribution table, binding labels."""

    def _report_with_distinct_outlay_figures(self) -> str:
        """The finance report of a solution whose outlay's representative, min, mean, median and max are five different figures, none of them one of the bill's.

        Nor is its representative's saving vs baseline the bill's representative's.
        So a cost-recovery row that shows the wrong figure fails the test that reads it.
        """
        cr_outlay = make_bill_distribution(
            representative=make_bill_breakdown(
                total_outlay_gbp=337.0, saving_vs_baseline_gbp=163.0, saving_pct=32.6,
            ),
            min_gbp=289.0,
            mean_gbp=341.0,
            median_gbp=335.0,
            max_gbp=393.0,
        )
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
            outlay=cr_outlay,
        )
        return generate_finance_report(
            sections_of(make_assumption_section(bill=_make_bill_distribution(), cost_recovery=sol)),
        )

    def test_outlay_distribution_renders(self) -> None:
        """Cost-recovery block must render the per-home total-outlay distribution at solved rate."""
        report = self._report_with_distinct_outlay_figures()

        expected = {"Min": "£289.00", "Mean": "£341.00", "Median": "£335.00", "Max": "£393.00"}
        shown = {
            label: _value_cell(report, "## Per-Home Total Outlay at Solved Rate (£)", label)
            for label in expected
        }
        assert shown == expected, f"outlay statistics not shown in their rows:\n{report}"

    def test_representative_outlay_renders(self) -> None:
        """Cost-recovery block must render the representative_outlay_gbp."""
        report = self._report_with_distinct_outlay_figures()

        shown = _value_cell(report, "## Cost-Recovery Analysis", "Representative Householder Outlay")
        assert shown == "£337.00", f"representative outlay not shown in its row:\n{report}"

    def test_saving_vs_baseline_renders(self) -> None:
        """Cost-recovery block must render saving_vs_baseline_gbp."""
        report = self._report_with_distinct_outlay_figures()

        shown = _value_cell(report, "## Cost-Recovery Analysis", "Saving vs Baseline")
        assert shown == "£163.00 (32.6%)", f"saving vs baseline not shown in its row:\n{report}"

    def test_saving_pct_renders(self) -> None:
        """Cost-recovery block must render saving_pct."""
        report = self._report_with_distinct_outlay_figures()

        shown = _value_cell(report, "## Cost-Recovery Analysis", "Saving vs Baseline")
        assert shown == "£163.00 (32.6%)", f"saving vs baseline not shown in its row:\n{report}"

    def test_binding_floor_label_distinct(self) -> None:
        """binding='floor' must render a 'surplus meets floor' label."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        # Should show a human-readable label for 'floor' (surplus meets floor)
        assert "surplus meets floor" in report.lower(), (
            f"Expected 'surplus meets floor' label for binding='floor':\n{report}"
        )

    def test_binding_rate_clamped_zero_label_distinct(self) -> None:
        """binding='rate_clamped_zero' must render an over-feasible label."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=0.0, net_surplus_per_home_per_year_gbp=500.0,
            feasible=True, binding="rate_clamped_zero",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        # Should show a human-readable label for 'rate_clamped_zero'
        assert "over-feasible" in report.lower() or "clamped" in report.lower(), (
            f"Expected 'over-feasible' or 'clamped' label for binding='rate_clamped_zero':\n{report}"
        )

    def test_binding_infeasible_above_retail_shows_warning(self) -> None:
        """binding='infeasible_above_retail' must render an explicit infeasible warning."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=30.0, net_surplus_per_home_per_year_gbp=-50.0,
            feasible=False, binding="infeasible_above_retail",
        )

        report = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol)))

        # Should contain an explicit infeasible warning
        report_lower = report.lower()
        assert "infeasible" in report_lower or "exceeds retail" in report_lower, (
            f"Expected infeasible warning for binding='infeasible_above_retail':\n{report}"
        )

    def test_three_binding_states_produce_distinct_labels(self) -> None:
        """The three binding states must each produce a distinct human-readable label."""
        bill = _make_bill_distribution()

        sol_floor = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )
        sol_clamped = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=0.0, net_surplus_per_home_per_year_gbp=500.0,
            feasible=True, binding="rate_clamped_zero",
        )
        sol_infeasible = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=30.0, net_surplus_per_home_per_year_gbp=-50.0,
            feasible=False, binding="infeasible_above_retail",
        )

        r_floor = generate_finance_report(sections_of(make_assumption_section(bill=bill, cost_recovery=sol_floor)))
        r_clamped = generate_finance_report(
            sections_of(make_assumption_section(bill=bill, cost_recovery=sol_clamped)),
        )
        r_infeasible = generate_finance_report(
            sections_of(make_assumption_section(bill=bill, cost_recovery=sol_infeasible)),
        )

        # All three must differ (at minimum in the binding-label section)
        assert r_floor != r_clamped, "floor and rate_clamped_zero must produce different reports"
        assert r_floor != r_infeasible, "floor and infeasible_above_retail must produce different reports"
        assert r_clamped != r_infeasible, "rate_clamped_zero and infeasible_above_retail must produce different reports"


# ---------------------------------------------------------------------------
# §D — CLI --cost-recovery flag existence
# ---------------------------------------------------------------------------


class TestFinanceCLICostRecoveryHelp:
    """`finance run --help` lists the --cost-recovery flag."""

    def test_help_exits_zero(self) -> None:
        """`finance run --help` must exit 0."""
        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output

    def test_help_shows_cost_recovery_flag(self) -> None:
        """`finance run --help` must show --cost-recovery / --no-cost-recovery."""
        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        output = result.output.lower()
        assert "cost-recovery" in output, (
            f"Expected '--cost-recovery' in finance run --help output:\n{result.output}"
        )

    def test_help_cost_recovery_mentions_solved_rate(self) -> None:
        """`finance run --help` cost-recovery flag must mention solved rate or cost-recovery."""
        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        output = result.output.lower()
        # Flag help text should mention "cost-recovery" or "own-use" or "solve"
        assert any(kw in output for kw in ("cost-recovery", "own-use", "solve", "solved")), (
            f"Expected cost-recovery flag help text to mention solved rate:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §E — The fast CLI tests' scenario writers
# ---------------------------------------------------------------------------

_INTERIOR_FINANCE: dict[str, float | int] = {
    "standing_charge_pence_per_day": 28.0,
    # Interior-regime cost-recovery params: high capex, no grant, floor=100, retail=30p
    "pv_cost_per_kwp_gbp": 2000.0,
    "grant_gbp": 0.0,
    "own_use_rate_pence_per_kwh": 15.0,
    "retained_cash_floor_per_home_per_year_gbp": 100.0,
    "retail_baseline_rate_pence_per_kwh": 30.0,
    "asset_life_years": 25,
    "vat_rate": 0.05,
}
"""The interior-regime finance block every scenario writer here writes: the --cost-recovery solve binds at the floor."""


def _write_interior_scenario(tmp_path: Path, n_homes: int = 5, *, battery_kwh: float | None = None) -> Path:
    """Write a minimal scenario YAML under the interior-regime finance block to tmp_path.

    Its n_homes seeded homes each have a fixed battery_kwh battery with no soh set, and no battery by default.
    """
    scenario = {
        "name": "CR5 CLI Test",
        "location": {
            "latitude": 51.45,
            "longitude": -2.58,
            "timezone": "Europe/London",
        },
        "fleet_distribution": {
            "n_homes": n_homes,
            "seed": 42,
            "pv": {"capacity_kw": 4.0, "azimuth": 180, "tilt": 35},
            "battery": {"capacity_kwh": battery_kwh},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": _INTERIOR_FINANCE,
    }
    path = tmp_path / "interior_scenario.yaml"
    path.write_text(yaml.dump(scenario))
    return path


def _write_unaged_battery_scenario(tmp_path: Path) -> Path:
    """Write _write_interior_scenario's scenario of two homes, each with a 5 kWh battery: its age-0 fleet differs from its configured homes only in each battery's soh."""
    return _write_interior_scenario(tmp_path, n_homes=2, battery_kwh=5.0)


def _write_aged_pv_scenario(tmp_path: Path) -> Path:
    """Write a homes-list scenario of two homes under _INTERIOR_FINANCE, each with 6-year-old 4 kW PV and a 5 kWh battery.

    Its age-0 fleet resets the PV's age, so it differs from the bill run's homes
    and no projection age is answered by the bill run.
    """
    home = {
        "pv": {"capacity_kw": 4.0, "system_age_years": 6.0},
        "battery": {"capacity_kwh": 5.0},
        "load": {"annual_consumption_kwh": 3400, "use_stochastic": False},
    }
    path = tmp_path / "aged_pv_scenario.yaml"
    path.write_text(yaml.safe_dump({"name": "Aged PV", "homes": [home, home], "finance": _INTERIOR_FINANCE}))
    return path


# ---------------------------------------------------------------------------
# §F — Module-scoped fixture + end-to-end CLI tests
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def interior_fleet_results() -> FleetResults:
    """Five default homes, each self-consuming 2,000 kWh, exporting 800 and importing 1,200 a year.

    Under _write_interior_scenario's finance (£2,000/kWp, no grant, a £100 floor,
    30p retail) the --cost-recovery solve binds at the floor and is feasible.
    The results span 365 days, at least the 360-day threshold, so neither the
    bill block nor the solve annualises them.
    """
    return make_fleet_results(n_homes=5, self_kwh=2000.0, export_kwh=800.0, import_kwh=1200.0)


class TestFinanceCLICostRecoveryE2EFast:
    """Fast end-to-end tests for --cost-recovery flag wiring."""

    def test_cost_recovery_flag_renders_block(
        self, tmp_path: Path, interior_fleet_results: FleetResults
    ) -> None:
        """--cost-recovery must render the cost-recovery block in the output."""
        scenario_file = _write_interior_scenario(tmp_path)

        result = invoke_finance_run(["--cost-recovery", str(scenario_file)], interior_fleet_results)

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        output = result.output.lower()
        assert "cost-recovery" in output, (
            f"Expected cost-recovery block in output:\n{result.output}"
        )

    def test_cost_recovery_flag_shows_solved_rate(
        self, tmp_path: Path, interior_fleet_results: FleetResults
    ) -> None:
        """--cost-recovery output must contain the solved own-use rate."""
        scenario_file = _write_interior_scenario(tmp_path)

        result = invoke_finance_run(["--cost-recovery", str(scenario_file)], interior_fleet_results)

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        # The solved rate should appear as "X.XX p/kWh" (case-insensitive)
        assert "p/kwh" in result.output.lower(), (
            f"Expected 'p/kWh' in cost-recovery output:\n{result.output}"
        )

    def test_cost_recovery_flag_shows_feasible(
        self, tmp_path: Path, interior_fleet_results: FleetResults
    ) -> None:
        """--cost-recovery output must contain feasibility indicator for interior regime."""
        scenario_file = _write_interior_scenario(tmp_path)

        result = invoke_finance_run(["--cost-recovery", str(scenario_file)], interior_fleet_results)

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        output = result.output.lower()
        # Interior regime → binding='floor' → "surplus meets floor"
        assert "surplus meets floor" in output, (
            f"Expected 'surplus meets floor' in output (interior regime must bind at floor):\n{result.output}"
        )

    def test_no_cost_recovery_omits_block(
        self, tmp_path: Path, interior_fleet_results: FleetResults
    ) -> None:
        """--no-cost-recovery (default) must NOT render the cost-recovery block."""
        scenario_file = _write_interior_scenario(tmp_path)

        # Invoke WITHOUT --cost-recovery (default is --no-cost-recovery)
        result = invoke_finance_run([str(scenario_file)], interior_fleet_results)

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        assert "cost-recovery analysis" not in result.output.lower(), (
            f"'Cost-Recovery Analysis' should NOT appear without --cost-recovery:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §G — The age-0 fleet simulated once per finance run (B16, L10)
# ---------------------------------------------------------------------------


def _at_starting_soh(homes: Sequence[HomeConfig]) -> list[HomeConfig]:
    """*homes* with each battery's soh set to the soh a Battery built from it holds, the battery-less homes as they are."""
    return [
        home
        if home.battery_config is None
        else replace(home, battery_config=replace(home.battery_config, soh=Battery(home.battery_config).soh))
        for home in homes
    ]


class TestFinanceRunSimulatesTheAge0FleetOnce:
    """`finance run --project --cost-recovery` on an unaged scenario asks its simulator once for the fleet whose homes are, at their starting soh, its bill run's."""

    def test_project_and_cost_recovery_ask_the_simulator_for_the_age_0_fleet_once(self, tmp_path: Path) -> None:
        scenario = _write_unaged_battery_scenario(tmp_path)
        recorder = RecordingSimulate()

        result = invoke_cli(
            [
                "finance", "run", "--project", "--cost-recovery",
                "--start", "2024-06-01", "--end", "2024-06-07", str(scenario),
            ],
            answering(recorder),
        )

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        assert all(home.battery_config is not None for home in recorder.fleets[0].homes), (
            "premise: every home of the bill run has a battery, whose soh each age of the projection sets"
        )
        bill_run = _at_starting_soh(recorder.fleets[0].homes)
        age_0 = [fleet for fleet in recorder.fleets if _at_starting_soh(fleet.homes) == bill_run]
        assert len(age_0) == 1, (
            f"the simulator was asked for the age-0 fleet {len(age_0)} times, as {[fleet.name for fleet in age_0]}, "
            f"among the fleets {[fleet.name for fleet in recorder.fleets]}"
        )
        assert len(recorder.fleets) > 1, "the projection's other ages reach the simulator"
        assert "## Project Economics" in result.stdout, result.output
        assert "## Cost-Recovery Analysis" in result.stdout, result.output


_PROJECT_AND_COST_RECOVERY_OVER_A_WEEK = ["finance", "run", "--project", "--cost-recovery", "--start", "2024-06-01", "--end", "2024-06-07"]
"""`finance run` with both economics blocks over the first week of June 2024, its scenario file to follow."""


class TestFinanceRunMakesOneProjection:
    """`finance run --project --cost-recovery` asks its simulator for its bill run and one projection's ages, no more."""

    def test_an_aged_fleet_is_simulated_for_its_bill_and_one_projection(self, tmp_path: Path) -> None:
        recorder = RecordingSimulate()

        result = invoke_cli([*_PROJECT_AND_COST_RECOVERY_OVER_A_WEEK, str(_write_aged_pv_scenario(tmp_path))], answering(recorder))

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        assert tuple(fleet.name for fleet in recorder.fleets[1:]) == PROJECTION_AGES_OVER_25_YEARS
        assert len(recorder.fleets) == 1 + fewest_simulated_ages(25)
        assert "## Project Economics" in result.stdout, result.output
        assert "## Cost-Recovery Analysis" in result.stdout, result.output

    def test_an_unaged_fleets_age_0_projection_age_is_answered_by_its_bill_run(self, tmp_path: Path) -> None:
        """The bill run, then the projection's four later ages."""
        recorder = RecordingSimulate()

        result = invoke_cli(
            [*_PROJECT_AND_COST_RECOVERY_OVER_A_WEEK, str(_write_unaged_battery_scenario(tmp_path))], answering(recorder)
        )

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        assert len(recorder.fleets) == fewest_simulated_ages(25), [fleet.name for fleet in recorder.fleets]
