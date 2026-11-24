# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for the multi-year projection curve's value types and per-year interpolation.

YearPoint and MultiYearCurve are the curve's frozen dataclasses
(docs/prds/financial-layer-battery-fidelity.md §3.1).  project_multi_year's
curve follows PCHIP through the values at its sampled ages and never overshoots
them (§3.3 step 4, H4), and each year's revenue is the own-use rate times that
year's own-use plus PCHIP through the income at those ages; those tests run it
on an injected synthetic simulate.

All tests are offline/fast — no PVGIS/network is touched.
"""
from __future__ import annotations

import dataclasses
import math
from typing import TYPE_CHECKING

import numpy as np
import pytest
from scipy.interpolate import CubicSpline, PchipInterpolator

from solar_challenge.home import RunPricing
from solar_challenge.projection import MultiYearCurve, YearPoint, project_multi_year, scenario_fleet
from solar_challenge.pv import wired_dc_capacity_kw
from tests._finance_builders import make_fleet_results, make_scenario_and_finance, make_scenario_of, make_sized_home

if TYPE_CHECKING:
    import pandas as pd

    from solar_challenge.fleet import FleetConfig, FleetResults


class TestYearPoint:
    """YearPoint frozen dataclass construction and validation."""

    def _make_valid(self) -> YearPoint:
        return YearPoint(
            year=5,
            pv_soh=0.975,
            battery_soh=0.900,
            fleet_billed_own_use_kwh=10_000.0,
            fleet_export_kwh=3_000.0,
            fleet_import_kwh=5_000.0,
            fleet_revenue_gbp=1_200.0,
        )

    def test_construction_valid(self) -> None:
        """Valid YearPoint constructs without errors."""
        yp = self._make_valid()
        assert yp.year == 5
        assert yp.pv_soh == pytest.approx(0.975)
        assert yp.battery_soh == pytest.approx(0.900)
        assert yp.fleet_billed_own_use_kwh == pytest.approx(10_000.0)
        assert yp.fleet_export_kwh == pytest.approx(3_000.0)
        assert yp.fleet_import_kwh == pytest.approx(5_000.0)
        assert yp.fleet_revenue_gbp == pytest.approx(1_200.0)

    def test_frozen(self) -> None:
        """Assigning a field raises FrozenInstanceError."""
        yp = self._make_valid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            yp.year = 99  # type: ignore[misc]

    def test_pv_soh_out_of_range_low(self) -> None:
        """pv_soh < 0 raises ValueError."""
        with pytest.raises(ValueError, match="pv_soh"):
            YearPoint(
                year=0,
                pv_soh=-0.01,
                battery_soh=1.0,
                fleet_billed_own_use_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_pv_soh_out_of_range_high(self) -> None:
        """pv_soh > 1 raises ValueError."""
        with pytest.raises(ValueError, match="pv_soh"):
            YearPoint(
                year=0,
                pv_soh=1.01,
                battery_soh=1.0,
                fleet_billed_own_use_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    def test_battery_soh_out_of_range(self) -> None:
        """battery_soh outside [0,1] raises ValueError."""
        with pytest.raises(ValueError, match="battery_soh"):
            YearPoint(
                year=0,
                pv_soh=1.0,
                battery_soh=1.05,
                fleet_billed_own_use_kwh=0.0,
                fleet_export_kwh=0.0,
                fleet_import_kwh=0.0,
                fleet_revenue_gbp=0.0,
            )

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 2.5, True, -1])
    def test_a_year_that_is_negative_or_not_a_whole_number_is_refused_naming_it(
        self, value: float
    ) -> None:
        """A year that is negative, NaN, infinite, fractional or a bool is refused, naming year, that it must be a whole number >= 0, and the value."""
        with pytest.raises(ValueError) as exc_info:
            dataclasses.replace(self._make_valid(), year=value)

        assert str(exc_info.value) == f"year must be a whole number >= 0, got {value!r}"

    @pytest.mark.parametrize("value", [2.0, np.int64(2)], ids=["float", "numpy_int64"])
    def test_a_whole_number_year_is_held_as_the_int_it_equals(self, value: object) -> None:
        """A whole-number float or a numpy integer year is held as the plain int it equals, as year's annotation says."""
        year = dataclasses.replace(self._make_valid(), year=value).year

        assert year == 2
        assert type(year) is int

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -1.0])
    @pytest.mark.parametrize(
        "field", ["fleet_billed_own_use_kwh", "fleet_export_kwh", "fleet_import_kwh"]
    )
    def test_a_fleet_energy_that_is_negative_or_not_finite_is_refused_naming_it(
        self, field: str, value: float
    ) -> None:
        """A negative, NaN or infinite fleet energy is refused, naming the field, that it must be >= 0 and finite, and the value."""
        with pytest.raises(ValueError) as exc_info:
            dataclasses.replace(self._make_valid(), **{field: value})

        assert str(exc_info.value) == f"{field} must be >= 0 and finite, got {value!r}"

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_a_fleet_revenue_that_is_not_finite_is_refused_naming_it(self, value: float) -> None:
        """A NaN or infinite fleet revenue is refused, naming the field, that it must be finite, and the value."""
        with pytest.raises(ValueError) as exc_info:
            dataclasses.replace(self._make_valid(), fleet_revenue_gbp=value)

        assert str(exc_info.value) == f"fleet_revenue_gbp must be finite, got {value!r}"

    def test_a_negative_fleet_revenue_is_accepted(self) -> None:
        """A negative revenue is accepted: the cost-recovery solve rebuilds each year's revenue at trial own-use rates, which can fall below zero."""
        assert dataclasses.replace(self._make_valid(), fleet_revenue_gbp=-1_000.0).fleet_revenue_gbp == -1_000.0

    def test_boundary_soh_values_valid(self) -> None:
        """SOH == 0 or 1 is valid (exact boundary)."""
        # Should not raise
        yp0 = YearPoint(
            year=0,
            pv_soh=0.0,
            battery_soh=0.0,
            fleet_billed_own_use_kwh=0.0,
            fleet_export_kwh=0.0,
            fleet_import_kwh=0.0,
            fleet_revenue_gbp=0.0,
        )
        yp1 = YearPoint(
            year=0,
            pv_soh=1.0,
            battery_soh=1.0,
            fleet_billed_own_use_kwh=0.0,
            fleet_export_kwh=0.0,
            fleet_import_kwh=0.0,
            fleet_revenue_gbp=0.0,
        )
        assert yp0.pv_soh == 0.0
        assert yp1.pv_soh == 1.0


class TestMultiYearCurve:
    """MultiYearCurve frozen dataclass construction and validation."""

    def _make_point(self, year: int, val: float = 1.0) -> YearPoint:
        return YearPoint(
            year=year,
            pv_soh=max(0.0, 1.0 - year * 0.005),
            battery_soh=max(0.0, 1.0 - year * 0.01),
            fleet_billed_own_use_kwh=val,
            fleet_export_kwh=val * 0.3,
            fleet_import_kwh=val * 0.5,
            fleet_revenue_gbp=val * 0.1,
        )

    def _make_valid(self) -> MultiYearCurve:
        points = tuple(self._make_point(y) for y in range(25))
        return MultiYearCurve(
            points=points,
            sampled_ages=(0, 12, 24),
            interp_error_estimate=0.5,
            annualised_from=None,
            fleet_pv_dc_kw=8.0,
        )

    def test_construction_valid(self) -> None:
        """Valid MultiYearCurve constructs and exposes all §3.1 fields."""
        mc = self._make_valid()
        assert len(mc.points) == 25
        assert mc.sampled_ages == (0, 12, 24)
        assert mc.interp_error_estimate == pytest.approx(0.5)
        assert mc.fleet_pv_dc_kw == 8.0

    def test_points_is_tuple(self) -> None:
        """points is a tuple (immutable)."""
        mc = self._make_valid()
        assert isinstance(mc.points, tuple)

    def test_sampled_ages_is_tuple(self) -> None:
        """sampled_ages is a tuple (immutable)."""
        mc = self._make_valid()
        assert isinstance(mc.sampled_ages, tuple)

    def test_frozen(self) -> None:
        """Assigning a field raises FrozenInstanceError."""
        mc = self._make_valid()
        with pytest.raises(dataclasses.FrozenInstanceError):
            mc.interp_error_estimate = 99.0  # type: ignore[misc]

    def test_empty_points_raises(self) -> None:
        """Empty points tuple raises ValueError."""
        with pytest.raises(ValueError, match="points"):
            MultiYearCurve(
                points=(),
                sampled_ages=(0,),
                interp_error_estimate=0.0,
                annualised_from=None,
                fleet_pv_dc_kw=8.0,
            )

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, -0.1])
    def test_an_interp_error_estimate_that_is_negative_or_not_finite_is_refused_naming_it(
        self, value: float
    ) -> None:
        """A negative, NaN or infinite interp_error_estimate is refused, naming the field, that it must be >= 0 and finite, and the value."""
        with pytest.raises(ValueError) as exc_info:
            dataclasses.replace(self._make_valid(), interp_error_estimate=value)

        assert str(exc_info.value) == f"interp_error_estimate must be >= 0 and finite, got {value!r}"

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 0.0, -1.0])
    def test_a_fleet_pv_dc_kw_that_is_not_above_zero_or_not_finite_is_refused_naming_it(
        self, value: float
    ) -> None:
        """A zero, negative, NaN or infinite fleet_pv_dc_kw is refused, naming the field, that it must be > 0 and finite, and the value."""
        with pytest.raises(ValueError) as exc_info:
            dataclasses.replace(self._make_valid(), fleet_pv_dc_kw=value)

        assert str(exc_info.value) == f"fleet_pv_dc_kw must be > 0 and finite, got {value!r}"

    def test_empty_sampled_ages_raises(self) -> None:
        """Empty sampled_ages raises ValueError."""
        points = tuple(self._make_point(y) for y in range(25))
        with pytest.raises(ValueError, match="sampled_ages"):
            MultiYearCurve(
                points=points,
                sampled_ages=(),
                interp_error_estimate=0.0,
                annualised_from=None,
                fleet_pv_dc_kw=8.0,
            )



def _simulate_each_home_given(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
    """make_fleet_results of the homes the projection asks for."""
    return make_fleet_results(homes=fleet_config.homes)


class TestTheCurveCarriesThePvDcItsGenerationCameFrom:
    """project_multi_year's curve carries the PV DC its homes wire, the basis project_economics prices."""

    def test_the_curves_fleet_pv_dc_kw_is_the_dc_its_homes_wire(self) -> None:
        scenario = make_scenario_of([make_sized_home(pv_kwp=3.0), make_sized_home(pv_kwp=5.0)])
        _, finance = make_scenario_and_finance(asset_life_years=5)
        wired = sum(wired_dc_capacity_kw(home.pv_config) for home in scenario_fleet(scenario).homes)
        assert wired != pytest.approx(8.0), (
            "the homes must wire a DC other than their 8 kWp nameplate, "
            "or this test cannot tell the two bases apart"
        )

        curve = project_multi_year(
            scenario, finance, error_target_pct=math.inf, simulate=_simulate_each_home_given
        )

        assert curve.fleet_pv_dc_kw == pytest.approx(wired)


_PLATEAU_KWH = 10_000.0
_PLATEAU_END_AGE = 12
_DECLINE_KWH_PER_YEAR = 400.0


def _self_consumption_kwh_at(age: float) -> float:
    """Flat at 10,000 kWh to age 12, then falling 400 kWh a year."""
    return _PLATEAU_KWH - _DECLINE_KWH_PER_YEAR * max(0.0, age - _PLATEAU_END_AGE)


def _simulate_plateau_then_decline(
    fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp
) -> FleetResults:
    """The fleet's results: every home's self-consumption is _self_consumption_kwh_at the fleet's PV age."""
    age = fleet_config.homes[0].pv_config.system_age_years
    return make_fleet_results(homes=fleet_config.homes, self_kwh=_self_consumption_kwh_at(age))


def _project_without_refinement(asset_life_years: int) -> MultiYearCurve:
    """One home projected over *asset_life_years*; an infinite error target samples only the seed ages."""
    scenario, finance = make_scenario_and_finance(asset_life_years=asset_life_years)
    return project_multi_year(
        scenario,
        finance,
        error_target_pct=math.inf,
        simulate=_simulate_plateau_then_decline,
    )


class TestPerYearInterpolation:
    """project_multi_year fills the years between its sampled ages by PCHIP through their values
    (docs/prds/financial-layer-battery-fidelity.md §3.3 step 4, H4).
    """

    def test_years_between_sampled_ages_follow_pchip_through_their_values(self) -> None:
        """Every year, the sampled ages included, equals scipy's PchipInterpolator through the sampled values."""
        curve = _project_without_refinement(25)
        ages = list(curve.sampled_ages)
        sampled_kwh = [_self_consumption_kwh_at(age) for age in ages]
        years = np.arange(25)
        expected = PchipInterpolator(ages, sampled_kwh)(years)

        assert np.max(np.abs(expected - np.interp(years, ages, sampled_kwh))) > 100.0, (
            "the fixture must make PCHIP differ from straight lines between the sampled ages, "
            "or this test cannot tell interpolants apart"
        )
        assert [point.fleet_billed_own_use_kwh for point in curve.points] == pytest.approx(
            expected.tolist(), rel=1e-9
        )

    def test_declining_sampled_values_give_a_non_increasing_curve_within_their_range(self) -> None:
        """A declining set of sampled values gives a curve that never rises and never leaves their range."""
        curve = _project_without_refinement(25)
        ages = list(curve.sampled_ages)
        sampled_kwh = [_self_consumption_kwh_at(age) for age in ages]

        assert np.max(CubicSpline(ages, sampled_kwh)(np.arange(25))) > max(sampled_kwh) + 100.0, (
            "a free cubic must overshoot these sampled values, or this test cannot tell "
            "a shape-preserving interpolant from one that is not"
        )
        per_year_kwh = [point.fleet_billed_own_use_kwh for point in curve.points]
        tolerance_kwh = 1e-6
        rising_years = [
            year
            for year in range(1, len(per_year_kwh))
            if per_year_kwh[year] > per_year_kwh[year - 1] + tolerance_kwh
        ]
        assert rising_years == []
        assert min(per_year_kwh) >= min(sampled_kwh) - tolerance_kwh
        assert max(per_year_kwh) <= max(sampled_kwh) + tolerance_kwh

    def test_a_one_year_life_projects_only_the_age_zero_simulation(self) -> None:
        """A one-year life samples only age 0, and its one year is that simulation's value."""
        curve = _project_without_refinement(1)

        assert curve.sampled_ages == (0,)
        assert [point.fleet_billed_own_use_kwh for point in curve.points] == pytest.approx(
            [_self_consumption_kwh_at(0)]
        )


_SEG_PENCE_PER_KWH = 5.0
_OWN_USE_RATE_PENCE_PER_KWH = 15.0


def _export_kwh_at(age: float) -> float:
    """Rising 500 kWh a year from 4,000 kWh, so the SEG income rises while the own-use plateaus then falls."""
    return 4_000.0 + 500.0 * age


def _income_gbp_at(age: float) -> float:
    """The SEG income of _export_kwh_at at _SEG_PENCE_PER_KWH."""
    return _export_kwh_at(age) * _SEG_PENCE_PER_KWH / 100.0


def _simulate_own_use_plateau_and_rising_income(
    fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp
) -> FleetResults:
    """The fleet's results: _self_consumption_kwh_at and _export_kwh_at the fleet's PV age, its export at a fixed SEG rate."""
    age = fleet_config.homes[0].pv_config.system_age_years
    return make_fleet_results(
        homes=fleet_config.homes,
        self_kwh=_self_consumption_kwh_at(age),
        export_kwh=_export_kwh_at(age),
        pricing=RunPricing(0.30, _SEG_PENCE_PER_KWH),
    )


_LATE_EXPORT_KWH_PER_YEAR = 1_000.0


def _late_export_kwh_at(age: float) -> float:
    """0 kWh to age 12, then rising 1,000 kWh a year, so the SEG income is £0 at ages 0 and 12 and £600 at age 24."""
    return _LATE_EXPORT_KWH_PER_YEAR * max(0.0, age - _PLATEAU_END_AGE)


def _simulate_own_use_plateau_and_export_only_after_age_12(
    fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp
) -> FleetResults:
    """The fleet's results: _self_consumption_kwh_at and _late_export_kwh_at the fleet's PV age, its export at a fixed SEG rate."""
    age = fleet_config.homes[0].pv_config.system_age_years
    return make_fleet_results(
        homes=fleet_config.homes,
        self_kwh=_self_consumption_kwh_at(age),
        export_kwh=_late_export_kwh_at(age),
        pricing=RunPricing(0.30, _SEG_PENCE_PER_KWH),
    )


class TestPerYearRevenue:
    """Each year's revenue is the own-use rate times that year's billed own-use, plus PCHIP through the income nodes.

    Revenue itself is not interpolated, so it is affine in the own-use rate in
    every year (docs/cost-recovery-finance-model.md §4, C6).
    """

    def _project_seeds_only(self) -> MultiYearCurve:
        scenario, finance = make_scenario_and_finance(asset_life_years=25)
        return project_multi_year(
            scenario,
            dataclasses.replace(finance, own_use_rate_pence_per_kwh=_OWN_USE_RATE_PENCE_PER_KWH),
            error_target_pct=math.inf,
            simulate=_simulate_own_use_plateau_and_rising_income,
        )

    def test_each_years_revenue_is_the_rate_times_its_own_use_plus_pchip_through_the_income_nodes(self) -> None:
        curve = self._project_seeds_only()
        ages = list(curve.sampled_ages)
        years = np.arange(25)
        income = PchipInterpolator(ages, [_income_gbp_at(age) for age in ages])(years)
        own_use = np.array([point.fleet_billed_own_use_kwh for point in curve.points])
        expected = _OWN_USE_RATE_PENCE_PER_KWH * own_use / 100.0 + income

        revenue_nodes = [
            _OWN_USE_RATE_PENCE_PER_KWH * _self_consumption_kwh_at(age) / 100.0 + _income_gbp_at(age) for age in ages
        ]
        assert np.max(np.abs(PchipInterpolator(ages, revenue_nodes)(years) - expected)) > 1.0, (
            "the fixture's own-use and income nodes must not be proportional, or PCHIP through the revenue "
            "nodes cannot be told apart from the rate times the own-use plus PCHIP through the income nodes"
        )
        assert [point.fleet_revenue_gbp for point in curve.points] == pytest.approx(expected.tolist(), rel=1e-9)

    def test_no_years_revenue_is_below_zero_where_a_free_cubic_through_the_income_nodes_is(self) -> None:
        """At a 0 p own-use rate, income nodes of £0 at ages 0 and 12 give no year a revenue below £0."""
        scenario, finance = make_scenario_and_finance(asset_life_years=25)
        curve = project_multi_year(
            scenario,
            dataclasses.replace(finance, own_use_rate_pence_per_kwh=0.0),
            error_target_pct=math.inf,
            simulate=_simulate_own_use_plateau_and_export_only_after_age_12,
        )
        ages = list(curve.sampled_ages)
        income_nodes = [_late_export_kwh_at(age) * _SEG_PENCE_PER_KWH / 100.0 for age in ages]

        assert np.min(CubicSpline(ages, income_nodes)(np.arange(_PLATEAU_END_AGE))) < -1.0, (
            "a free cubic through the income nodes must go below £0 between ages 0 and 12, or this test "
            "cannot tell a shape-preserving interpolant of the income from one that is not"
        )
        assert min(point.fleet_revenue_gbp for point in curve.points) >= 0.0
