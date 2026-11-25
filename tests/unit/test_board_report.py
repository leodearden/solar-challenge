# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.board_report, the finance and config-ranking board reports."""

from dataclasses import fields, replace
from datetime import date

import pytest
from solar_challenge.board_report import AssumptionSection, generate_config_ranking_report, generate_finance_report
from solar_challenge.finance import BillDistribution, CostRecoverySolution, OwnUseBasis
from solar_challenge.optimize import RankedSweep
from solar_challenge.timebase import SimulationWindow
from tests._assumption_sections import make_assumption_section, sections_of
from tests._factories import (
    make_bill_distribution,
    make_config_result,
    make_cost_recovery_solution,
    make_ranked_sweep,
)
from tests._finance_builders import make_window
from tests._grid_charge_forecast_notices import PV_BLIND_AND_TRAILING_NOTICE, TRAILING_NOTICE


def _annualised_from(window: SimulationWindow) -> BillDistribution:
    """make_bill_distribution's distribution, its yearly figures annualised from *window*."""
    return replace(make_bill_distribution(), annualised_from=window)


def _one_config_sweep(window: SimulationWindow) -> RankedSweep:
    """A sweep of one feasible config, whose outlay's yearly figures are annualised from *window*."""
    cr = make_config_result(outlay=_annualised_from(window))
    return make_ranked_sweep((cr,))


def _sections(bill: BillDistribution, *, side_by_side: bool = False) -> dict[OwnUseBasis, AssumptionSection]:
    """A finance report's input billing *bill* under physics, and under the spreadsheet too when *side_by_side*."""
    bases = (OwnUseBasis.SIMULATED, OwnUseBasis.OVERRIDE) if side_by_side else (OwnUseBasis.SIMULATED,)
    return sections_of(*(make_assumption_section(basis, bill=bill) for basis in bases))


def _sized_by(*forecasts: str) -> BillDistribution:
    """make_bill_distribution's distribution, its homes' grid charge sized by *forecasts*."""
    return replace(make_bill_distribution(), grid_charge_forecasts=forecasts)


class TestGridChargeForecastNotice:
    """A board report of homes whose grid charge a forecast sized says, under its first heading, which forecast and what it is."""

    @pytest.mark.parametrize("side_by_side", [False, True], ids=["physics-only", "side-by-side"])
    def test_a_finance_report_names_each_forecast_under_its_title(self, side_by_side: bool) -> None:
        dist = _sized_by("pv_blind", "trailing_14_days")

        report = generate_finance_report(_sections(dist, side_by_side=side_by_side), scenario_name="Bristol")

        assert report.startswith("# Finance Report: Bristol\n\n" + PV_BLIND_AND_TRAILING_NOTICE + "## Householder Bill")

    def test_a_finance_report_gives_the_forecast_notice_after_the_extrapolation_notice(self) -> None:
        dist = replace(_sized_by("trailing_14_days"), annualised_from=make_window(days=2, first_day=date(2024, 3, 31)))

        report = generate_finance_report(_sections(dist), scenario_name="Bristol")

        assert report.startswith(
            "# Finance Report: Bristol\n\n"
            "*Yearly figures are extrapolated ×183.000 from a 2-day window (2024-03-31 to 2024-04-01), "
            "not whole calendar years.*\n\n" + TRAILING_NOTICE + "## Householder Bill"
        )

    def test_a_finance_report_whose_homes_did_not_grid_charge_has_no_notice(self) -> None:
        report = generate_finance_report(_sections(_sized_by()), scenario_name="Bristol")

        assert report == generate_finance_report(_sections(make_bill_distribution()), scenario_name="Bristol")
        assert "sized by" not in report

    def test_a_ranking_report_names_its_outlays_forecasts_under_its_first_heading(self) -> None:
        sweep = make_ranked_sweep((make_config_result(outlay=_sized_by("pv_blind", "trailing_14_days")),))

        assert generate_config_ranking_report(sweep).startswith(
            "## Cost-Recovery Rank\n\n" + PV_BLIND_AND_TRAILING_NOTICE + "| Config"
        )

    def test_a_ranking_report_whose_homes_did_not_grid_charge_has_no_notice(self) -> None:
        sweep = make_ranked_sweep((make_config_result(outlay=_sized_by()),))

        assert generate_config_ranking_report(sweep).startswith("## Cost-Recovery Rank\n\n| Config")


class TestExtrapolationNotice:
    """A board report whose bills are annualised from a window other than whole calendar years says so under its first heading."""

    @pytest.mark.parametrize("side_by_side", [False, True], ids=["physics-only", "side-by-side"])
    def test_a_finance_report_from_a_window_that_is_not_whole_calendar_years_says_so_under_its_title(
        self, side_by_side: bool
    ) -> None:
        dist = _annualised_from(make_window(days=2, first_day=date(2024, 3, 31)))

        report = generate_finance_report(_sections(dist, side_by_side=side_by_side), scenario_name="Bristol")

        assert report.startswith(
            "# Finance Report: Bristol\n\n"
            "*Yearly figures are extrapolated ×183.000 from a 2-day window (2024-03-31 to 2024-04-01), "
            "not whole calendar years.*\n\n"
            "## Householder Bill"
        )

    @pytest.mark.parametrize(
        "window",
        [
            pytest.param(make_window(days=365, first_day=date(2023, 1, 1)), id="calendar-year-2023"),
            pytest.param(make_window(days=731, first_day=date(2023, 1, 1)), id="two-calendar-years"),
        ],
    )
    def test_a_finance_report_from_whole_calendar_years_has_no_notice(self, window: SimulationWindow) -> None:
        report = generate_finance_report(_sections(_annualised_from(window)), scenario_name="Bristol")

        assert report == generate_finance_report(_sections(make_bill_distribution()), scenario_name="Bristol")
        assert "extrapolated" not in report

    def test_a_ranking_report_from_a_30_day_window_says_so_under_its_first_heading(self) -> None:
        sweep = _one_config_sweep(make_window(days=30, first_day=date(2024, 6, 1)))

        assert generate_config_ranking_report(sweep).startswith(
            "## Cost-Recovery Rank\n\n"
            "*Yearly figures are extrapolated ×12.200 from a 30-day window (2024-06-01 to 2024-06-30), "
            "not whole calendar years.*\n\n"
            "| Config"
        )

    def test_a_ranking_report_from_a_whole_calendar_year_has_no_notice(self) -> None:
        report = generate_config_ranking_report(_one_config_sweep(make_window(days=365, first_day=date(2023, 1, 1))))

        assert "extrapolated" not in report
        assert report.startswith("## Cost-Recovery Rank\n\n| Config")


class _UncheckedSolution(CostRecoverySolution):
    """A solution that slipped past CostRecoverySolution's own binding check, which the board reports refuse again where they read it.

    CostRecoverySolution(binding="other") already raises at construction, so this double is the only way a report can be handed one.
    """

    def __post_init__(self) -> None:
        pass


def _solution_with_binding_other() -> CostRecoverySolution:
    """make_cost_recovery_solution's feasible solution, its binding "other", which is in no label table."""
    base = make_cost_recovery_solution()
    return _UncheckedSolution(
        **{**{f.name: getattr(base, f.name) for f in fields(base)}, "binding": "other", "feasible": True}
    )


class TestABindingOutsideTheLabelTableIsRefused:
    """Both board reports refuse, naming it, a cost-recovery binding their label table does not hold, rather than rendering it as some other binding or as raw text."""

    def test_a_finance_report_refuses_a_binding_outside_the_label_table_by_name(self) -> None:
        solution = _solution_with_binding_other()

        with pytest.raises(ValueError, match="'other'"):
            generate_finance_report(sections_of(make_assumption_section(cost_recovery=solution)))

    def test_a_ranking_report_refuses_a_binding_outside_the_label_table_by_name(self) -> None:
        cr = replace(make_config_result(), solution=_solution_with_binding_other(), binding="other")

        with pytest.raises(ValueError, match="'other'"):
            generate_config_ranking_report(make_ranked_sweep((cr,)))
