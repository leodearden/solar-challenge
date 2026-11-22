# SPDX-License-Identifier: AGPL-3.0-or-later
"""Finance bills a summary's totals over the window they cover (B6, D27 invariant 8).

householder_bill and bill_distribution take no day count: they bill over their
summaries' own window, which carries it, and bill_distribution refuses summaries
over different windows. householder_bill refuses an own-use outside 0 to the
window's demand with the ledger's invariants, naming it as passed. A summary always
carries its window: SummaryStatistics refuses one without (tests/unit/test_home.py).
`finance run` bills the day count of the summaries its fleet simulator returns.

A bill is the window's year, by one rule with no threshold and no warning: the
window's totals × its annualisation_scale (year_days / days), and year_days of
standing charge.  A bill distribution and a projection name the window their
yearly figures were annualised from, and a projection refuses a fleet whose
homes cover different windows.
"""
from __future__ import annotations

import math
import warnings
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from solar_challenge.finance import (
    BillBreakdown,
    FinanceConfig,
    basis_c_own_use_kwh,
    bill_distribution,
    householder_bill,
    project_multi_year,
    spreadsheet_revenue_curve,
)
from solar_challenge.fleet import FleetResults
from solar_challenge.home import RunPricing, SummaryStatistics, calculate_summary
from solar_challenge.scenario_writer import fleet_scenario, scenario_yaml
from tests._cli_fleet_simulator import invoke_finance_run
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_scenario_and_finance,
    make_sim_results,
    make_window,
)

_IMPORT_RATE_GBP_PER_KWH = 0.30
_STANDING_PENCE_PER_DAY = 60.0
_OWN_USE_PENCE_PER_KWH = 15.0


def _summary(*, days: int, first_day: date = date(2021, 1, 1)) -> SummaryStatistics:
    """The summary of make_sim_results' home over *days* local dates from *first_day*.

    Its import is priced by a 30 p/kWh tariff, so no bill falls back to the
    retail rate and warns.
    """
    return calculate_summary(
        make_sim_results(days=days, first_day=first_day, pricing=RunPricing(_IMPORT_RATE_GBP_PER_KWH, None))
    )


def _finance(*, self_consumption_override: float | None = None) -> FinanceConfig:
    """A FinanceConfig at 60 p/day standing and 15 p/kWh own-use, with *self_consumption_override*."""
    return FinanceConfig(
        standing_charge_pence_per_day=_STANDING_PENCE_PER_DAY,
        own_use_rate_pence_per_kwh=_OWN_USE_PENCE_PER_KWH,
        self_consumption_override=self_consumption_override,
    )


def _householder_bill(summary: SummaryStatistics) -> BillBreakdown:
    """householder_bill of *summary*, billing its self-consumption as own-use."""
    return householder_bill(summary, window_self_consumption_kwh=summary.total_self_consumption_kwh, finance=_finance())


def _representative_bill(summary: SummaryStatistics) -> BillBreakdown:
    """bill_distribution's representative bill of a fleet of *summary* alone, over its own window."""
    return bill_distribution([summary], _finance()).representative


_BILLERS = [
    pytest.param(_householder_bill, id="householder_bill"),
    pytest.param(_representative_bill, id="bill_distribution"),
]


class TestDayCountIsTheSummariesOwn:
    """INV-8: the day count a bill is computed over is its summaries' own, their window's: the bill functions take none."""

    @pytest.mark.parametrize("bill_of", _BILLERS)
    def test_the_summaries_own_day_count_bills(self, bill_of: Callable[[SummaryStatistics], BillBreakdown]) -> None:
        """A 2-day window in 2024 bills 2024's year_days of standing charge and its totals × that window's annualisation_scale, 366 / 2."""
        summary = _summary(days=2, first_day=date(2024, 1, 1))

        breakdown = bill_of(summary)

        assert breakdown.standing_charge_gbp == pytest.approx(summary.window.year_days * _STANDING_PENCE_PER_DAY / 100)
        assert breakdown.import_cost_gbp == pytest.approx(
            summary.total_import_cost_gbp * summary.window.annualisation_scale
        )


class TestWindowSelfConsumption:
    """householder_bill bills the home's own-use over its summary's window, window_self_consumption_kwh; the annual_self_consumption_kwh keyword is gone."""

    def test_householder_bill_of_a_summarys_basis_c_own_use_is_its_bill_in_a_distribution(self) -> None:
        """bill_distribution bills each summary's basis-C own-use, so householder_bill given that own-use bills the same."""
        summary = _summary(days=2, first_day=date(2024, 1, 1))

        breakdown = householder_bill(
            summary, window_self_consumption_kwh=basis_c_own_use_kwh(summary), finance=_finance()
        )

        assert breakdown == bill_distribution([summary], _finance()).representative

    def test_the_annual_self_consumption_kwh_keyword_is_refused(self) -> None:
        summary = _summary(days=2, first_day=date(2024, 1, 1))

        with pytest.raises(TypeError, match="unexpected keyword argument 'annual_self_consumption_kwh'"):
            householder_bill(summary, annual_self_consumption_kwh=summary.total_self_consumption_kwh, finance=_finance())


class TestOneWindowPerDistribution:
    """A bill distribution is over one window: its summaries cover the same dates."""

    def test_summaries_over_different_dates_of_the_same_length_are_refused(self) -> None:
        january_2021 = _summary(days=3)
        january_2024 = _summary(days=3, first_day=date(2024, 1, 1))

        with pytest.raises(ValueError, match="position 2") as refusal:
            bill_distribution([january_2021, january_2021, january_2024], _finance())

        assert repr(january_2021.window) in str(refusal.value)
        assert repr(january_2024.window) in str(refusal.value)


class TestOwnUseWithinTheWindowsDemand:
    """householder_bill's own-use is the home's over the summary's window, so it lies from 0 to the window's demand (fk-286fe17c28c9).

    householder_bill refuses one outside, on either basis and before it scales
    it, naming the ledger's invariant it breaks: L1, finite and >= 0, or L2, at
    most the demand.
    """

    @pytest.mark.parametrize("days", [365, 30], ids=["whole-year", "30-day"])
    @pytest.mark.parametrize("self_consumption_override", [None, 0.3], ids=["physics", "override"])
    @pytest.mark.parametrize(
        ("own_use_for_demand", "invariant"),
        [
            pytest.param(lambda demand_kwh: -0.1, "L1", id="below-zero"),
            pytest.param(lambda demand_kwh: demand_kwh + 0.1, "L2", id="above-the-demand"),
            pytest.param(lambda demand_kwh: math.nan, "L1", id="nan"),
        ],
    )
    def test_own_use_outside_the_windows_demand_is_refused_naming_it_as_passed(
        self,
        own_use_for_demand: Callable[[float], float],
        invariant: str,
        self_consumption_override: float | None,
        days: int,
    ) -> None:
        """A 30-day window's scale is 365/30, and the refusal still names the caller's figure, not the year's."""
        summary = _summary(days=days)
        own_use_kwh = own_use_for_demand(summary.total_demand_kwh)

        with pytest.raises(ValueError, match=f"HomeLedger {invariant}:") as refusal:
            householder_bill(summary, own_use_kwh, _finance(self_consumption_override=self_consumption_override))

        assert f"window_self_consumption_kwh={own_use_kwh!r}" in str(refusal.value)

    def test_own_use_above_a_short_windows_demand_is_refused_naming_the_windows_demand(self) -> None:
        summary = _summary(days=30)

        with pytest.raises(ValueError, match="HomeLedger L2:") as refusal:
            householder_bill(summary, summary.total_demand_kwh + 0.1, _finance())

        assert f"total_demand_kwh={summary.total_demand_kwh!r}" in str(refusal.value)

    def test_own_use_equal_to_the_windows_demand_bills(self) -> None:
        summary = _summary(days=365)

        breakdown = householder_bill(summary, summary.total_demand_kwh, _finance())

        assert breakdown.own_use_payment_gbp == pytest.approx(_OWN_USE_PENCE_PER_KWH * summary.total_demand_kwh / 100)


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
            _householder_bill(summary)
            bill_distribution([summary], _finance())


class TestYearlyFiguresNameTheirWindow:
    """A bill distribution and a projection carry the window their yearly figures were annualised from."""

    def test_a_bill_distribution_names_its_summaries_window(self) -> None:
        distribution = bill_distribution([_summary(days=30)] * 2, _finance())

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


def _write_scenario(directory: Path, fleet_results: FleetResults) -> Path:
    """Write a scenario of *fleet_results*' homes, billed at _STANDING_PENCE_PER_DAY of standing charge, to *directory*, and return its path."""
    document = {
        **fleet_scenario(fleet_results.home_configs, name="Finance window"),
        "finance": {"standing_charge_pence_per_day": _STANDING_PENCE_PER_DAY},
    }
    path = directory / "scenario.yaml"
    path.write_text(scenario_yaml(document), encoding="utf-8")
    return path


def test_finance_run_bills_the_days_of_the_summaries_its_simulator_returns(tmp_path: Path) -> None:
    """`finance run`'s default dates count 2024's 366 days; the fleet's summaries cover 2021's 365, which it bills at the scenario's _STANDING_PENCE_PER_DAY."""
    fleet_results = make_fleet_results(n_homes=2)
    assert calculate_summary(fleet_results.per_home_results[0]).window == make_window(days=365)

    result = invoke_finance_run([str(_write_scenario(tmp_path, fleet_results))], fleet_results)

    assert result.exit_code == 0, result.output
    assert f"| Standing Charge | £{365 * _STANDING_PENCE_PER_DAY / 100:.2f} |" in result.stdout
