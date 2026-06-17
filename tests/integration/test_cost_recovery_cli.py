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
) -> "CostRecoverySolution":  # type: ignore[name-defined]
    """Build a minimal CostRecoverySolution."""
    from solar_challenge.finance import CostRecoverySolution

    outlay = _make_bill_distribution()
    return CostRecoverySolution(
        own_use_rate_pence_per_kwh=own_use_rate,
        outlay=outlay,
        representative_outlay_gbp=outlay.representative.total_outlay_gbp,
        net_surplus_per_home_per_year_gbp=net_surplus,
        saving_vs_baseline_gbp=outlay.representative.saving_vs_baseline_gbp,
        saving_pct=outlay.representative.saving_pct,
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

        # Net surplus of 27.0 should appear in the report
        assert "27" in report, (
            f"Expected net surplus '27' in report but got:\n{report}"
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
        """Cost-recovery block must render the householder total-outlay distribution."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution(min_gbp=310.0, mean_gbp=367.5, median_gbp=360.0, max_gbp=430.0)
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        # All four distribution stats should appear in the cost-recovery block
        assert "310" in report, f"min_gbp=310 not in report:\n{report}"
        assert "367" in report, f"mean_gbp=367.5 not in report:\n{report}"
        assert "360" in report, f"median_gbp=360 not in report:\n{report}"
        assert "430" in report, f"max_gbp=430 not in report:\n{report}"

    def test_representative_outlay_renders(self) -> None:
        """Cost-recovery block must render the representative_outlay_gbp."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")

        report = generate_finance_report(bill, cost_recovery=sol)

        # representative_outlay_gbp comes from outlay.representative.total_outlay_gbp = mean_gbp = 367.5
        assert "367" in report, f"representative_outlay_gbp not in report:\n{report}"

    def test_saving_vs_baseline_renders(self) -> None:
        """Cost-recovery block must render saving_vs_baseline_gbp."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")
        # The _make_solution helper sets saving_vs_baseline_gbp=132.5

        report = generate_finance_report(bill, cost_recovery=sol)

        assert "132" in report, f"saving_vs_baseline not rendered:\n{report}"

    def test_saving_pct_renders(self) -> None:
        """Cost-recovery block must render saving_pct."""
        from solar_challenge.output import generate_finance_report

        bill = _make_bill_distribution()
        sol = _make_solution(own_use_rate=15.0, net_surplus=27.0, feasible=True, binding="floor")
        # _make_solution sets saving_pct=26.5

        report = generate_finance_report(bill, cost_recovery=sol)

        assert "26.5" in report or "26" in report, f"saving_pct not rendered:\n{report}"

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
