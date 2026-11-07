# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finance bills a summary's totals over the window they cover (B6, D27 invariant 8).

householder_bill and bill_distribution bill over their summaries' own day count and
refuse any other, refuse a summary with no window and summaries over different
windows, and householder_bill refuses own-use outside 0 to the window's demand.
`finance run` bills the day count of the summaries its fleet simulator returns.

A bill is the window's year, by one rule with no threshold and no warning: the
window's totals × its annualisation_scale (year_days / days), and year_days of
standing charge.  A bill distribution and a projection name the window their
yearly figures were annualised from, and a projection refuses a fleet whose
homes cover different windows.
"""
from __future__ import annotations

import dataclasses
import math
import warnings
from collections.abc import Callable
from datetime import date

import pytest

from solar_challenge.finance import (
    BillBreakdown,
    BillDistribution,
    FinanceConfig,
    bill_distribution,
    householder_bill,
    project_multi_year,
    spreadsheet_revenue_curve,
)
from solar_challenge.home import SummaryStatistics, calculate_summary
from tests._cli_fleet_simulator import invoke_finance_run
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_scenario_and_finance,
    make_sim_results,
    make_window,
)
from tests._repository_paths import SCENARIOS_DIR

_IMPORT_RATE_GBP_PER_KWH = 0.30
_STANDING_PENCE_PER_DAY = 60.0
_OWN_USE_PENCE_PER_KWH = 15.0


def _summary(*, days: int, first_day: date = date(2021, 1, 1)) -> SummaryStatistics:
    """The summary of make_sim_results' home over *days* local dates from *first_day*.

    Its import is priced at 30 p/kWh, as a tariff would price it, so no bill
    falls back to the retail rate and warns.
    """
    summary = calculate_summary(make_sim_results(days=days, first_day=first_day))
    import_cost_gbp = summary.total_grid_import_kwh * _IMPORT_RATE_GBP_PER_KWH
    return dataclasses.replace(
        summary,
        total_import_cost_gbp=import_cost_gbp,
        net_cost_gbp=import_cost_gbp - summary.total_export_revenue_gbp,
    )


def _finance(*, self_consumption_override: float | None = None) -> FinanceConfig:
    """A FinanceConfig at 60 p/day standing and 15 p/kWh own-use, with *self_consumption_override*."""
    return FinanceConfig(
        standing_charge_pence_per_day=_STANDING_PENCE_PER_DAY,
        own_use_rate_pence_per_kwh=_OWN_USE_PENCE_PER_KWH,
        self_consumption_override=self_consumption_override,
    )


def _householder_bill(summary: SummaryStatistics, simulation_days: int) -> BillBreakdown:
    """householder_bill of *summary* over *simulation_days*, billing its self-consumption as own-use."""
    return householder_bill(summary, summary.total_self_consumption_kwh, _finance(), simulation_days)


class TestDayCountIsTheSummariesOwn:
    """INV-8: the day count a bill is computed over is its summaries' own."""

    def test_bill_distribution_refuses_a_day_count_other_than_its_summaries(self) -> None:
        summaries = [_summary(days=2, first_day=date(2024, 1, 1))] * 2

        with pytest.raises(ValueError, match=r"simulation_days=1 .*2 days, 2024-01-01 to 2024-01-02"):
            bill_distribution(summaries, _finance(), 1)

    def test_householder_bill_refuses_a_day_count_other_than_its_summarys(self) -> None:
        summary = _summary(days=2, first_day=date(2024, 1, 1))

        with pytest.raises(ValueError, match=r"simulation_days=1 .*2 days, 2024-01-01 to 2024-01-02"):
            _householder_bill(summary, 1)

    def test_the_summaries_own_day_count_bills(self) -> None:
        summary = _summary(days=2, first_day=date(2024, 1, 1))

        assert isinstance(_householder_bill(summary, 2), BillBreakdown)
        assert isinstance(bill_distribution([summary] * 2, _finance(), 2), BillDistribution)


class TestOneWindowPerDistribution:
    """A bill distribution is over one window: its summaries cover the same dates."""

    def test_summaries_over_different_dates_of_the_same_length_are_refused(self) -> None:
        january_2021 = _summary(days=3)
        january_2024 = _summary(days=3, first_day=date(2024, 1, 1))

        with pytest.raises(ValueError, match="position 2") as refusal:
            bill_distribution([january_2021, january_2021, january_2024], _finance(), 3)

        assert repr(january_2021.window) in str(refusal.value)
        assert repr(january_2024.window) in str(refusal.value)


class TestWindowlessSummaryRefused:
    """A summary with no window has no days to bill over: calculate_summary sets the window."""

    def test_householder_bill_refuses_a_summary_with_no_window(self) -> None:
        windowless = dataclasses.replace(_summary(days=365), window=None)

        with pytest.raises(ValueError, match=r"window.*calculate_summary"):
            _householder_bill(windowless, 365)

    def test_bill_distribution_refuses_a_summary_with_no_window(self) -> None:
        windowless = dataclasses.replace(_summary(days=365), window=None)

        with pytest.raises(ValueError, match=r"window.*calculate_summary"):
            bill_distribution([windowless], _finance(), 365)


class TestOwnUseWithinTheWindowsDemand:
    """householder_bill's own-use is the home's over the summary's window, so it lies from 0 to the window's demand (fk-286fe17c28c9)."""

    @pytest.mark.parametrize("self_consumption_override", [None, 0.3], ids=["physics", "override"])
    @pytest.mark.parametrize(
        "own_use_for_demand",
        [
            pytest.param(lambda demand_kwh: -0.1, id="below-zero"),
            pytest.param(lambda demand_kwh: demand_kwh + 0.1, id="above-the-demand"),
            pytest.param(lambda demand_kwh: math.nan, id="nan"),
        ],
    )
    def test_own_use_outside_the_windows_demand_is_refused(
        self, own_use_for_demand: Callable[[float], float], self_consumption_override: float | None
    ) -> None:
        summary = _summary(days=365)
        own_use_kwh = own_use_for_demand(summary.total_demand_kwh)

        with pytest.raises(ValueError, match="total_demand_kwh") as refusal:
            householder_bill(
                summary,
                own_use_kwh,
                _finance(self_consumption_override=self_consumption_override),
                summary.simulation_days,
            )

        assert repr(own_use_kwh) in str(refusal.value)

    def test_own_use_equal_to_the_windows_demand_bills(self) -> None:
        summary = _summary(days=365)

        breakdown = householder_bill(summary, summary.total_demand_kwh, _finance(), summary.simulation_days)

        assert breakdown.own_use_payment_gbp == pytest.approx(_OWN_USE_PENCE_PER_KWH * summary.total_demand_kwh / 100)


def _representative_bill(summary: SummaryStatistics) -> BillBreakdown:
    """bill_distribution's representative bill of a fleet of *summary* alone, over its own days."""
    return bill_distribution([summary], _finance(), summary.simulation_days).representative


_BILLERS = [
    pytest.param(lambda summary: _householder_bill(summary, summary.simulation_days), id="householder_bill"),
    pytest.param(_representative_bill, id="bill_distribution"),
]


class TestOneAnnualisationRule:
    """A bill is the window's year: its totals × annualisation_scale (year_days / days) and year_days of standing charge, with no threshold."""

    @pytest.mark.parametrize("bill_of", _BILLERS)
    def test_a_window_across_two_years_bills_a_mean_years_share_of_its_totals(
        self, bill_of: Callable[[SummaryStatistics], BillBreakdown]
    ) -> None:
        """2024-01-01 to 2025-02-03 crosses a new year, so its 400 days scale to a mean year's 365.25."""
        summary = _summary(days=400, first_day=date(2024, 1, 1))
        scale = 365.25 / 400

        breakdown = bill_of(summary)

        assert breakdown.own_use_payment_gbp == pytest.approx(
            _OWN_USE_PENCE_PER_KWH * summary.total_self_consumption_kwh * scale / 100
        )
        assert breakdown.import_cost_gbp == pytest.approx(summary.total_import_cost_gbp * scale)
        assert breakdown.standing_charge_gbp == pytest.approx(365.25 * _STANDING_PENCE_PER_DAY / 100)

    @pytest.mark.parametrize("bill_of", _BILLERS)
    def test_a_leap_calendar_year_bills_366_days_of_standing_charge_and_its_own_totals(
        self, bill_of: Callable[[SummaryStatistics], BillBreakdown]
    ) -> None:
        summary = _summary(days=366, first_day=date(2024, 1, 1))

        breakdown = bill_of(summary)

        assert breakdown.standing_charge_gbp == pytest.approx(366 * _STANDING_PENCE_PER_DAY / 100)
        assert breakdown.own_use_payment_gbp == pytest.approx(
            _OWN_USE_PENCE_PER_KWH * summary.total_self_consumption_kwh / 100
        )

    @pytest.mark.parametrize("bill_of", _BILLERS)
    def test_a_360_day_window_is_scaled_to_its_year(self, bill_of: Callable[[SummaryStatistics], BillBreakdown]) -> None:
        """No threshold leaves a window of 360 days or more unscaled."""
        summary = _summary(days=360)

        breakdown = bill_of(summary)

        assert breakdown.own_use_payment_gbp == pytest.approx(
            _OWN_USE_PENCE_PER_KWH * summary.total_self_consumption_kwh * (365 / 360) / 100
        )

    def test_a_30_day_window_bills_without_a_warning(self) -> None:
        summary = _summary(days=30)

        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            _householder_bill(summary, 30)
            bill_distribution([summary], _finance(), 30)


class TestYearlyFiguresNameTheirWindow:
    """A bill distribution and a projection carry the window their yearly figures were annualised from."""

    def test_a_bill_distribution_names_its_summaries_window(self) -> None:
        distribution = bill_distribution([_summary(days=30)] * 2, _finance(), 30)

        assert distribution.annualised_from == make_window(days=30)

    def test_a_projection_names_its_fleets_window(self) -> None:
        scenario, finance = make_scenario_and_finance()
        fleet = make_fleet_results(days=3)

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)

        assert curve.annualised_from == make_window(days=3)

    def test_a_projection_refuses_a_fleet_whose_homes_cover_different_windows(self) -> None:
        scenario, finance = make_scenario_and_finance(n_homes=2)
        january_2021 = make_sim_results(days=3)
        january_2024 = make_sim_results(days=3, first_day=date(2024, 1, 1))
        fleet = make_fleet_results_of([january_2021, january_2024])

        with pytest.raises(ValueError, match="position 1") as refusal:
            project_multi_year(scenario, finance, simulate=lambda fc, s, e: fleet)

        assert repr(january_2021.window) in str(refusal.value)
        assert repr(january_2024.window) in str(refusal.value)

    def test_a_spreadsheet_curve_is_annualised_from_no_window(self) -> None:
        """Its yearly figures are the spreadsheet's yearly assumptions, not a simulated window's totals."""
        curve = spreadsheet_revenue_curve(
            n_homes=2,
            pv_kwp=4.0,
            kwh_per_kwp=950.0,
            self_consumption_fraction=0.7,
            own_use_rate_pence_per_kwh=15.0,
            export_rate_pence_per_kwh=4.1,
            asset_life_years=5,
        )

        assert curve.annualised_from is None


def test_finance_run_bills_the_days_of_the_summaries_its_simulator_returns() -> None:
    """`finance run`'s default dates count 2024's 366 days; the fleet's summaries cover 2021's 365, which it bills."""
    fleet_results = make_fleet_results(n_homes=2)
    assert calculate_summary(fleet_results.per_home_results[0]).window == make_window(days=365)

    result = invoke_finance_run([str(SCENARIOS_DIR / "bristol-phase1.yaml")], fleet_results)

    assert result.exit_code == 0, result.output
    assert "| Standing Charge | £219.00 |" in result.stdout
