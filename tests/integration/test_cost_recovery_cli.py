# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Integration tests for CR5: --cost-recovery CLI flag and report block.

This file MIXES fast and slow tests and must NOT be added to
tests/unit/test_marker_registration.py's INTEGRATION_FILES allow-list.
The slow class carries @pytest.mark.slow directly; the fast classes run
in the offline verify loop.
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# §A — Helper factories (copied/adapted from test_cost_recovery_solve.py)
# ---------------------------------------------------------------------------


def _make_bill_breakdown(total_outlay: float = 367.5) -> "BillBreakdown":  # type: ignore[name-defined]
    """Build a minimal BillBreakdown for fixture use."""
    from solar_challenge.finance import BillBreakdown

    return BillBreakdown(
        standing_charge_gbp=100.0,
        import_cost_gbp=200.0,
        own_use_payment_gbp=50.0,
        vat_gbp=17.5,
        total_outlay_gbp=total_outlay,
        self_consumption_saving_gbp=30.0,
        baseline_bill_gbp=500.0,
        saving_vs_baseline_gbp=132.5,
        saving_pct=26.5,
        self_consumption_fraction=0.35,
    )


def _make_bill_distribution(
    min_gbp: float = 300.0,
    mean_gbp: float = 367.5,
    median_gbp: float = 367.5,
    max_gbp: float = 420.0,
) -> "BillDistribution":  # type: ignore[name-defined]
    """Build a minimal BillDistribution for fixture use."""
    from solar_challenge.finance import BillDistribution

    rep = _make_bill_breakdown(total_outlay=mean_gbp)
    return BillDistribution(
        representative=rep,
        per_home_net_bill_gbp=(min_gbp, mean_gbp, max_gbp),
        min_gbp=min_gbp,
        mean_gbp=mean_gbp,
        median_gbp=median_gbp,
        max_gbp=max_gbp,
    )


def _make_solution(
    own_use_rate: float = 15.0,
    net_surplus: float = 27.0,
    feasible: bool = True,
    binding: str = "floor",
    outlay: "BillDistribution | None" = None,  # type: ignore[name-defined]
) -> "CostRecoverySolution":  # type: ignore[name-defined]
    """Build a minimal CostRecoverySolution.

    When *outlay* is ``None`` (default) the distribution from
    :func:`_make_bill_distribution` is used.  Pass a custom distribution to
    test with values distinct from the main-bill fixture.
    """
    from solar_challenge.finance import CostRecoverySolution

    dist = outlay if outlay is not None else _make_bill_distribution()
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate,
        outlay=dist,
        representative_outlay_gbp=dist.representative.total_outlay_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus,
        saving_vs_baseline_gbp=dist.representative.saving_vs_baseline_gbp,
        saving_pct=dist.representative.saving_pct,
        feasible=feasible,
        binding=binding,
    )


# ---------------------------------------------------------------------------
# §B — RED tests for output.py cost-recovery block (step-1 / step-3)
# ---------------------------------------------------------------------------


class TestGenerateFinanceReportCostRecoveryBasic:
    """RED: generate_finance_report accepts cost_recovery kwarg and renders a block."""

    def test_cost_recovery_section_heading_present(self) -> None:
        """Report must contain a Cost-Recovery section heading when cost_recovery is provided."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        assert "cost-recovery" in report.lower(), (
            f"Expected 'Cost-Recovery' heading in report but got:\n{report}"
        )

    def test_cost_recovery_solved_rate_rendered(self) -> None:
        """Report must show the solved own-use rate."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=18.75, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        assert "18.75" in report, (
            f"Expected solved rate '18.75' in report but got:\n{report}"
        )

    def test_cost_recovery_net_surplus_rendered(self) -> None:
        """Report must show the CBS net surplus per home per year."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)
        cr_idx = report.find("## Cost-Recovery Analysis")
        assert cr_idx >= 0, "Cost-Recovery section not found"
        cr_section = report[cr_idx:]

        # Net surplus renders as £27.00 in the CR section (format: £{value:.2f})
        assert "£27.00" in cr_section, (
            f"Expected '£27.00' in CR section but got:\n{cr_section}"
        )

    def test_cost_recovery_feasible_indicator_present(self) -> None:
        """Report must contain a feasibility indicator."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        # Should contain some form of feasibility indicator
        assert "feasible" in report.lower() or "floor" in report.lower(), (
            f"Expected feasibility indicator in report but got:\n{report}"
        )

    def test_cost_recovery_none_produces_identical_report(self) -> None:
        """generate_finance_report(bill) without cost_recovery must match cost_recovery=None."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()

        report_default = generate_finance_report(bill)
        report_none = generate_finance_report(bill, cost_recovery=None)

        assert report_default == report_none, (
            "generate_finance_report() and generate_finance_report(cost_recovery=None) "
            "must produce identical output"
        )

    def test_cost_recovery_none_omits_section_heading(self) -> None:
        """generate_finance_report without cost_recovery must NOT contain a Cost-Recovery heading."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()

        report = generate_finance_report(bill)

        assert "cost-recovery" not in report.lower(), (
            f"'Cost-Recovery' heading should not appear without cost_recovery param:\n{report}"
        )


# ---------------------------------------------------------------------------
# §C — RED tests for full board-readable content (step-3)
# ---------------------------------------------------------------------------


class TestGenerateFinanceReportCostRecoveryFull:
    """RED: full board-readable content — distribution table, binding labels."""

    def test_outlay_distribution_renders(self) -> None:
        """Cost-recovery block must render the per-home total-outlay distribution at solved rate."""
        from solar_challenge.output import generate_finance_report

        # Use distinct cr_outlay values from the main-bill defaults (min=300, mean=367.5,
        # median=367.5, max=420) so each assertion is unambiguously pinned to the CR section.
        cr_outlay = _make_bill_distribution(
            min_gbp=289.0, mean_gbp=341.0, median_gbp=335.0, max_gbp=393.0
        )
        bill = _make_bill_distribution()  # defaults
        sol = _make_solution(
            own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor",
            outlay=cr_outlay,
        )

        report = generate_finance_report(bill, cost_recovery=sol)
        cr_idx = report.find("## Cost-Recovery Analysis")
        assert cr_idx >= 0, "Cost-Recovery section not found"
        cr_section = report[cr_idx:]

        # All four distribution stats must appear in the CR section with exact £-formatting
        assert "£289.00" in cr_section, f"min_gbp not in CR section:\n{cr_section}"
        assert "£341.00" in cr_section, f"mean_gbp not in CR section:\n{cr_section}"
        assert "£335.00" in cr_section, f"median_gbp not in CR section:\n{cr_section}"
        assert "£393.00" in cr_section, f"max_gbp not in CR section:\n{cr_section}"

    def test_representative_outlay_renders(self) -> None:
        """Cost-recovery block must render the representative_outlay_gbp."""
        from solar_challenge.output import generate_finance_report

        # Use a distinct mean_gbp (342.0) so the CR section's £342.00 cannot be
        # confused with the main-bill section's £367.50 (default mean).
        cr_outlay = _make_bill_distribution(mean_gbp=342.0)
        bill = _make_bill_distribution()  # defaults; mean_gbp=367.5
        sol = _make_solution(
            own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor",
            outlay=cr_outlay,
        )

        report = generate_finance_report(bill, cost_recovery=sol)
        cr_idx = report.find("## Cost-Recovery Analysis")
        assert cr_idx >= 0, "Cost-Recovery section not found"
        cr_section = report[cr_idx:]

        # representative_outlay_gbp = cr_outlay.representative.total_outlay_gbp = 342.0 → £342.00
        assert "£342.00" in cr_section, f"representative_outlay_gbp not in CR section:\n{cr_section}"

    def test_saving_vs_baseline_renders(self) -> None:
        """Cost-recovery block must render saving_vs_baseline_gbp."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")
        # _make_bill_breakdown default: saving_vs_baseline_gbp=132.5 → renders as £132.50

        report = generate_finance_report(bill, cost_recovery=sol)
        cr_idx = report.find("## Cost-Recovery Analysis")
        assert cr_idx >= 0, "Cost-Recovery section not found"
        cr_section = report[cr_idx:]

        # Scope to CR section; the main-bill section also contains £132.50 at the same format
        assert "£132.50" in cr_section, f"saving_vs_baseline_gbp not in CR section:\n{cr_section}"

    def test_saving_pct_renders(self) -> None:
        """Cost-recovery block must render saving_pct."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")
        # _make_bill_breakdown default: saving_pct=26.5 → renders as "26.5%" in CR section

        report = generate_finance_report(bill, cost_recovery=sol)
        cr_idx = report.find("## Cost-Recovery Analysis")
        assert cr_idx >= 0, "Cost-Recovery section not found"
        cr_section = report[cr_idx:]

        # Scope to CR section; the main-bill "Saving vs Baseline" row also contains "(26.5%)"
        assert "26.5" in cr_section, f"saving_pct not rendered in CR section:\n{cr_section}"

    def test_binding_floor_label_distinct(self) -> None:
        """binding='floor' must render a 'surplus meets floor' label."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        # Should show a human-readable label for 'floor' (surplus meets floor)
        assert "surplus meets floor" in report.lower(), (
            f"Expected 'surplus meets floor' label for binding='floor':\n{report}"
        )

    def test_binding_rate_clamped_zero_label_distinct(self) -> None:
        """binding='rate_clamped_zero' must render an over-feasible label."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=0.0, net_surplus=500.0, feasible=True, binding="rate_clamped_zero")

        report = generate_finance_report(bill, cost_recovery=sol)

        # Should show a human-readable label for 'rate_clamped_zero'
        assert "over-feasible" in report.lower() or "clamped" in report.lower(), (
            f"Expected 'over-feasible' or 'clamped' label for binding='rate_clamped_zero':\n{report}"
        )

    def test_binding_infeasible_above_retail_shows_warning(self) -> None:
        """binding='infeasible_above_retail' must render an explicit infeasible warning."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=30.0, net_surplus=-50.0, feasible=False, binding="infeasible_above_retail")

        report = generate_finance_report(bill, cost_recovery=sol)

        # Should contain an explicit infeasible warning
        report_lower = report.lower()
        assert "infeasible" in report_lower or "exceeds retail" in report_lower, (
            f"Expected infeasible warning for binding='infeasible_above_retail':\n{report}"
        )

    def test_three_binding_states_produce_distinct_labels(self) -> None:
        """The three binding states must each produce a distinct human-readable label."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()

        sol_floor = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")
        sol_clamped = _make_solution(own_use_rate=0.0, net_surplus=500.0, feasible=True, binding="rate_clamped_zero")
        sol_infeasible = _make_solution(own_use_rate=30.0, net_surplus=-50.0, feasible=False, binding="infeasible_above_retail")

        r_floor = generate_finance_report(bill, cost_recovery=sol_floor)
        r_clamped = generate_finance_report(bill, cost_recovery=sol_clamped)
        r_infeasible = generate_finance_report(bill, cost_recovery=sol_infeasible)

        # All three must differ (at minimum in the binding-label section)
        assert r_floor != r_clamped, "floor and rate_clamped_zero must produce different reports"
        assert r_floor != r_infeasible, "floor and infeasible_above_retail must produce different reports"
        assert r_clamped != r_infeasible, "rate_clamped_zero and infeasible_above_retail must produce different reports"


# ---------------------------------------------------------------------------
# §D — RED tests for CLI --cost-recovery flag existence (step-5)
# ---------------------------------------------------------------------------


class TestFinanceCLICostRecoveryHelp:
    """RED: `finance run --help` must list the --cost-recovery flag."""

    def test_help_exits_zero(self) -> None:
        """`finance run --help` must exit 0."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output

    def test_help_shows_cost_recovery_flag(self) -> None:
        """`finance run --help` must show --cost-recovery / --no-cost-recovery."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        output = result.output.lower()
        assert "cost-recovery" in output, (
            f"Expected '--cost-recovery' in finance run --help output:\n{result.output}"
        )

    def test_help_cost_recovery_mentions_solved_rate(self) -> None:
        """`finance run --help` cost-recovery flag must mention solved rate or cost-recovery."""
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        runner = CliRunner()
        result = runner.invoke(app, ["finance", "run", "--help"])
        assert result.exit_code == 0, result.output
        output = result.output.lower()
        # Flag help text should mention "cost-recovery" or "own-use" or "solve"
        assert any(kw in output for kw in ("cost-recovery", "own-use", "solve", "solved")), (
            f"Expected cost-recovery flag help text to mention solved rate:\n{result.output}"
        )


# ---------------------------------------------------------------------------
# §E — Helpers for fast patched CLI tests (adapted from test_cost_recovery_solve.py)
# ---------------------------------------------------------------------------


def _make_pv_config(system_age_years: float = 0.0) -> "PVConfig":  # type: ignore[name-defined]
    from solar_challenge.pv import PVConfig
    return PVConfig(
        capacity_kw=4.0,
        azimuth=180.0,
        tilt=35.0,
        system_age_years=system_age_years,
        degradation_rate_per_year=0.005,
    )


def _make_load_config() -> "LoadConfig":  # type: ignore[name-defined]
    from solar_challenge.load import LoadConfig
    return LoadConfig(annual_consumption_kwh=3500.0)


def _make_home_config() -> "HomeConfig":  # type: ignore[name-defined]
    from solar_challenge.home import HomeConfig
    from solar_challenge.location import Location
    return HomeConfig(
        pv_config=_make_pv_config(),
        load_config=_make_load_config(),
        location=Location.bristol(),
    )


def _make_sim_results(
    self_kwh: float = 2000.0,
    export_kwh: float = 800.0,
    import_kwh: float = 1200.0,
    n_minutes: int = 525600,
) -> "SimulationResults":  # type: ignore[name-defined]
    import pandas as pd
    from solar_challenge.home import SimulationResults

    idx = pd.date_range("2020-01-01", periods=n_minutes, freq="1min", tz="Europe/London")
    sc_kw = self_kwh / (n_minutes / 60.0)
    exp_kw = export_kwh / (n_minutes / 60.0)
    imp_kw = import_kwh / (n_minutes / 60.0)
    gen_kw = sc_kw + exp_kw
    demand_kw = sc_kw + imp_kw
    zeros = pd.Series(0.0, index=idx)
    return SimulationResults(
        generation=pd.Series(gen_kw, index=idx),
        demand=pd.Series(demand_kw, index=idx),
        self_consumption=pd.Series(sc_kw, index=idx),
        battery_charge=zeros.copy(),
        battery_discharge=zeros.copy(),
        battery_soc=zeros.copy(),
        grid_import=pd.Series(imp_kw, index=idx),
        grid_export=pd.Series(exp_kw, index=idx),
        import_cost=zeros.copy(),
        export_revenue=zeros.copy(),
        tariff_rate=zeros.copy(),
        grid_charge_cost=None,
    )


def _make_fleet_results_interior(n_homes: int = 5) -> "FleetResults":  # type: ignore[name-defined]
    """Build a FleetResults that yields binding='floor', feasible=True when solved.

    Uses the interior-regime shape from test_cost_recovery_solve.py:
    high capex (£2000/kWp), no grant, floor=100, retail=30p, sc=2000 kWh/home/yr.

    Uses a full-year unscaled Series (525600 minutes = 365 days, identical to the
    proven CR4 fixture in _setup_interior).  With a full-year Series AND the CLI's
    default full-year window (days=366 ≥ the 360 annualisation threshold) NEITHER
    the bill-block path NOR solve_cost_recovery_rate's internal sim annualises —
    both see a true 365-day Series so all paths are mutually consistent and the
    solve yields binding='floor', feasible=True, net_surplus == floor (£100/home/yr),
    solved rate ≈ 18.96 p/kWh.
    """
    from solar_challenge.fleet import FleetResults

    homes = [_make_home_config() for _ in range(n_homes)]
    per_home = [
        _make_sim_results(
            self_kwh=2000.0,
            export_kwh=800.0,
            import_kwh=1200.0,
            n_minutes=525600,  # 365 * 24 * 60 — full year, no annualisation needed
        )
        for _ in range(n_homes)
    ]
    return FleetResults(per_home_results=per_home, home_configs=homes)


def _write_interior_scenario(tmp_path: "Path", n_homes: int = 5) -> "Path":  # type: ignore[name-defined]
    """Write a minimal interior-regime scenario YAML to tmp_path."""
    import yaml
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
# §F — Module-scoped fixture + RED end-to-end CLI tests (step-7)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def interior_fleet_results() -> "FleetResults":  # type: ignore[name-defined]
    """Module-scoped fixture: build interior-regime FleetResults once per module.

    Building once avoids reconstructing ~9 MB of per-minute Series four times
    across the E2E test class.
    """
    return _make_fleet_results_interior()


class TestFinanceCLICostRecoveryE2EFast:
    """Fast patched end-to-end tests for --cost-recovery flag wiring."""

    def test_cost_recovery_flag_renders_block(
        self, tmp_path: "Path", interior_fleet_results: "FleetResults"  # type: ignore[name-defined]
    ) -> None:
        """--cost-recovery must render the cost-recovery block in the output."""
        from unittest.mock import patch
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario_file = _write_interior_scenario(tmp_path)
        fr = interior_fleet_results

        with (
            patch("solar_challenge.cli.finance.simulate_fleet", return_value=fr),
            patch("solar_challenge.fleet.simulate_fleet", return_value=fr),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["finance", "run", "--cost-recovery", str(scenario_file)])

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        output = result.output.lower()
        assert "cost-recovery" in output, (
            f"Expected cost-recovery block in output:\n{result.output}"
        )

    def test_cost_recovery_flag_shows_solved_rate(
        self, tmp_path: "Path", interior_fleet_results: "FleetResults"  # type: ignore[name-defined]
    ) -> None:
        """--cost-recovery output must contain the solved own-use rate."""
        from unittest.mock import patch
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario_file = _write_interior_scenario(tmp_path)
        fr = interior_fleet_results

        with (
            patch("solar_challenge.cli.finance.simulate_fleet", return_value=fr),
            patch("solar_challenge.fleet.simulate_fleet", return_value=fr),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["finance", "run", "--cost-recovery", str(scenario_file)])

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        # The solved rate should appear as "X.XX p/kWh" (case-insensitive)
        assert "p/kwh" in result.output.lower(), (
            f"Expected 'p/kWh' in cost-recovery output:\n{result.output}"
        )

    def test_cost_recovery_flag_shows_feasible(
        self, tmp_path: "Path", interior_fleet_results: "FleetResults"  # type: ignore[name-defined]
    ) -> None:
        """--cost-recovery output must contain feasibility indicator for interior regime."""
        from unittest.mock import patch
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario_file = _write_interior_scenario(tmp_path)
        fr = interior_fleet_results

        with (
            patch("solar_challenge.cli.finance.simulate_fleet", return_value=fr),
            patch("solar_challenge.fleet.simulate_fleet", return_value=fr),
        ):
            runner = CliRunner()
            result = runner.invoke(app, ["finance", "run", "--cost-recovery", str(scenario_file)])

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        output = result.output.lower()
        # Interior regime → binding='floor' → "surplus meets floor" (strict pin; see step-9 design decision)
        assert "surplus meets floor" in output, (
            f"Expected 'surplus meets floor' in output (interior regime must bind at floor):\n{result.output}"
        )

    def test_no_cost_recovery_omits_block(
        self, tmp_path: "Path", interior_fleet_results: "FleetResults"  # type: ignore[name-defined]
    ) -> None:
        """--no-cost-recovery (default) must NOT render the cost-recovery block."""
        from unittest.mock import patch
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario_file = _write_interior_scenario(tmp_path)
        fr = interior_fleet_results

        with (
            patch("solar_challenge.cli.finance.simulate_fleet", return_value=fr),
            patch("solar_challenge.fleet.simulate_fleet", return_value=fr),
        ):
            runner = CliRunner()
            # Invoke WITHOUT --cost-recovery (default is --no-cost-recovery)
            result = runner.invoke(app, ["finance", "run", str(scenario_file)])

        assert result.exit_code == 0, f"Exit {result.exit_code}. Output:\n{result.output}"
        assert "cost-recovery analysis" not in result.output.lower(), (
            f"'Cost-Recovery Analysis' should NOT appear without --cost-recovery:\n{result.output}"
        )


@pytest.mark.slow
class TestFinanceCLICostRecoverySlowE2E:
    """Slow real-PVGIS end-to-end test (H8 board signal)."""

    def test_cost_recovery_bristol_short_window(self) -> None:
        """E2E: `finance run --cost-recovery scenarios/bristol-phase1.yaml` exits 0 with CR block."""
        from pathlib import Path
        from typer.testing import CliRunner
        from solar_challenge.cli.main import app

        scenario = Path("scenarios/bristol-phase1.yaml")
        if not scenario.exists():
            pytest.skip("bristol-phase1.yaml not found")

        runner = CliRunner()
        result = runner.invoke(
            app,
            [
                "finance",
                "run",
                str(scenario),
                "--cost-recovery",
                "--start", "2024-01-01",
                "--end", "2024-01-03",
            ],
        )
        assert result.exit_code == 0, (
            f"Exit {result.exit_code}. Output:\n{result.output}"
        )
        output = result.output.lower()
        assert "cost-recovery" in output, (
            f"Expected cost-recovery block headings in output:\n{result.output}"
        )
