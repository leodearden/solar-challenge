# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for CR5: --cost-recovery CLI flag and report block."""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from solar_challenge.cli.main import app
from solar_challenge.finance import BillDistribution
from solar_challenge.fleet import FleetResults
from solar_challenge.output import generate_finance_report
from tests._cli_fleet_simulator import invoke_finance_run
from tests._factories import (
    make_bill_breakdown,
    make_bill_distribution,
    make_bill_distribution_from_statistics,
    make_cost_recovery_solution,
)
from tests._finance_builders import make_fleet_results


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
    """The Value cell of the row labelled *label* in the table of *heading*'s own section.

    A section ends at the next heading, so the bill's own Min, Mean, Median and Max rows are never read as the cost-recovery block's.
    """
    assert f"{heading}\n" in report, f"No {heading!r} heading in the report:\n{report}"
    section = report.split(f"{heading}\n", 1)[1].split("\n#", 1)[0]
    rows = [
        [cell.strip() for cell in line.strip("|").split("|")]
        for line in section.splitlines()
        if line.startswith("|")
    ]
    matching_rows = [row for row in rows if row[0] == label]
    assert len(matching_rows) == 1, f"Expected one {label!r} row under {heading!r}:\n{section}"
    row = matching_rows[0]
    assert len(row) == 2, f"Expected the {label!r} row under {heading!r} to be a label and a value, got {row!r}:\n{section}"
    return row[1]


# ---------------------------------------------------------------------------
# §B — output.py cost-recovery block
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

        report = generate_finance_report(bill, cost_recovery=sol)

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

        report = generate_finance_report(bill, cost_recovery=sol)

        shown = _value_cell(report, "## Cost-Recovery Analysis", "Solved Own-Use Rate")
        assert shown == "18.75 p/kWh", f"solved rate not shown in its row:\n{report}"

    def test_cost_recovery_net_surplus_rendered(self) -> None:
        """Report must show the CBS net surplus per home per year."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(bill, cost_recovery=sol)

        shown = _value_cell(report, "## Cost-Recovery Analysis", "CBS Net Surplus / home / yr")
        assert shown == "£27.00", f"net surplus not shown in its row:\n{report}"

    def test_cost_recovery_feasible_indicator_present(self) -> None:
        """Report must contain a feasibility indicator."""
        bill = _make_bill_distribution()
        sol = make_cost_recovery_solution(
            own_use_rate_pence_per_kwh=15.0, net_surplus_per_home_per_year_gbp=27.0,
            feasible=True, binding="floor",
        )

        report = generate_finance_report(bill, cost_recovery=sol)

        # Should contain some form of feasibility indicator
        assert "feasible" in report.lower() or "floor" in report.lower(), (
            f"Expected feasibility indicator in report but got:\n{report}"
        )

    def test_cost_recovery_none_produces_identical_report(self) -> None:
        """generate_finance_report(bill) without cost_recovery must match cost_recovery=None."""
        bill = _make_bill_distribution()

        report_default = generate_finance_report(bill)
        report_none = generate_finance_report(bill, cost_recovery=None)

        assert report_default == report_none, (
            "generate_finance_report() and generate_finance_report(cost_recovery=None) "
            "must produce identical output"
        )

    def test_cost_recovery_none_omits_section_heading(self) -> None:
        """generate_finance_report without cost_recovery must NOT contain a Cost-Recovery heading."""
        bill = _make_bill_distribution()

        report = generate_finance_report(bill)

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
        return generate_finance_report(_make_bill_distribution(), cost_recovery=sol)

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

        report = generate_finance_report(bill, cost_recovery=sol)

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

        report = generate_finance_report(bill, cost_recovery=sol)

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

        report = generate_finance_report(bill, cost_recovery=sol)

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

        r_floor = generate_finance_report(bill, cost_recovery=sol_floor)
        r_clamped = generate_finance_report(bill, cost_recovery=sol_clamped)
        r_infeasible = generate_finance_report(bill, cost_recovery=sol_infeasible)

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
# §E — The fast CLI tests' scenario writer
# ---------------------------------------------------------------------------


def _write_interior_scenario(tmp_path: Path, n_homes: int = 5) -> Path:
    """Write a minimal interior-regime scenario YAML to tmp_path."""
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
            "battery": {"capacity_kwh": None},
            "load": {"annual_consumption_kwh": 3500},
        },
        "finance": {
            "standing_charge_pence_per_day": 28.0,
            # Interior-regime cost-recovery params: high capex, no grant, floor=100, retail=30p
            "pv_cost_per_kwp_gbp": 2000.0,
            "grant_gbp": 0.0,
            "own_use_rate_pence_per_kwh": 15.0,
            "retained_cash_floor_per_home_per_year_gbp": 100.0,
            "retail_baseline_rate_pence_per_kwh": 30.0,
            "asset_life_years": 25,
            "vat_rate": 0.05,
        },
    }
    path = tmp_path / "interior_scenario.yaml"
    path.write_text(yaml.dump(scenario))
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
