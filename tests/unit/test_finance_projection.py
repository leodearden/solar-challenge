# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's curve shape, fleet energy aggregation,
and its refusal of a simulated age whose aggregates are not all finite.

The projection runs on an injected synthetic simulate, with no PVGIS or network.
"""
from __future__ import annotations

import dataclasses
import math

import pandas as pd
import pytest

from solar_challenge.finance import MultiYearCurve, project_multi_year
from solar_challenge.fleet import FleetConfig, FleetResults
from solar_challenge.home import calculate_summary
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
    make_scenario_and_finance,
    make_sim_results,
)


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_billed_own_use_at_sampled_age(self) -> None:
        """fleet_billed_own_use_kwh at a sampled age is the fleet's basis-C own-use, the sum of demand - import."""
        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

        summaries = [calculate_summary(r) for r in fr.per_home_results]
        expected_own_use = sum(s.total_demand_kwh - s.total_grid_import_kwh for s in summaries)

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)

        # At age 0 (a seed point), the value should match the injected summary
        assert curve.points[0].fleet_billed_own_use_kwh == pytest.approx(
            expected_own_use, rel=1e-4
        )

    def test_fleet_export_at_sampled_age(self) -> None:
        """fleet_export_kwh at a sampled age equals sum of per-home totals."""
        n_homes = 2
        exp_per_home = 500.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, export_kwh=exp_per_home)

        expected_export = sum(
            calculate_summary(r).total_grid_export_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_export_kwh == pytest.approx(expected_export, rel=1e-4)

    def test_fleet_import_at_sampled_age(self) -> None:
        """fleet_import_kwh at a sampled age equals sum of per-home totals."""
        n_homes = 2
        imp_per_home = 200.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, import_kwh=imp_per_home)

        expected_import = sum(
            calculate_summary(r).total_grid_import_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert curve.points[0].fleet_import_kwh == pytest.approx(expected_import, rel=1e-4)


class TestProjectMultiYearRefusesNonFiniteAggregates:
    """A simulated age whose fleet aggregates are not all finite is refused,
    naming the age and each such aggregate with its value.
    """

    @pytest.mark.parametrize("asset_life_years", [1, 25])
    @pytest.mark.parametrize(
        ("totals", "refused"),
        [
            pytest.param({"self_kwh": math.inf}, "fleet_sc=inf, fleet_revenue=inf", id="infinite-self-consumption"),
            pytest.param({"export_kwh": math.inf}, "fleet_exp=inf", id="infinite-export"),
            pytest.param(
                {"import_kwh": math.inf},
                "fleet_sc=nan, fleet_imp=inf, fleet_revenue=nan",
                id="infinite-import-makes-own-use-nan",
            ),
        ],
    )
    def test_a_non_finite_aggregate_at_a_seed_age_is_refused_naming_the_age_and_each_aggregate(
        self, asset_life_years: int, totals: dict[str, float], refused: str
    ) -> None:
        """A fleet whose totals are infinite at every age is refused at age 0, the first seed.

        With demand and import both infinite, basis-C own-use (demand − import)
        is inf − inf = NaN, so the NaN arises in the projection's own arithmetic.
        An infinite export leaves revenue finite: the scenario sets no SEG rate
        and the fleet's export revenue is £0, so its SEG income is £0.
        """
        scenario, finance = make_scenario_and_finance(asset_life_years=asset_life_years)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(
                scenario, finance, simulate=lambda fc, s, e: make_fleet_results(homes=fc.homes, **totals)
            )

        assert str(exc_info.value) == (
            f"every aggregate of the fleet simulated at age 0 must be finite: got {refused}"
        )

    def test_a_non_finite_aggregate_at_a_bisection_trial_age_is_refused_naming_that_age(self) -> None:
        """A fleet that is finite at the seeds 0, 12 and 24 is refused at age 6, the adaptive loop's first trial.

        A NaN trial's deviation is never above the error target, and max() drops
        it from the error estimate, so unrefused it would vanish from the bisection
        and the projection would return a curve built from the finite seeds.
        """
        scenario, finance = make_scenario_and_finance(asset_life_years=25)

        def simulate(fleet_config: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
            age = fleet_config.homes[0].pv_config.system_age_years
            return make_fleet_results(homes=fleet_config.homes, import_kwh=math.inf if age == 6.0 else 12.0)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(scenario, finance, simulate=simulate)

        assert str(exc_info.value) == (
            "every aggregate of the fleet simulated at age 6 must be finite: "
            "got fleet_sc=nan, fleet_imp=inf, fleet_revenue=nan"
        )

    @pytest.mark.parametrize("asset_life_years", [1, 25])
    def test_a_non_finite_battery_discharge_is_refused_naming_its_home(self, asset_life_years: int) -> None:
        """A home whose battery discharge is infinite is refused at age 0, by its place in the fleet.

        Only the discharge series changes, so demand, own-use and revenue stay
        finite and no UserWarning fires.
        """
        scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=asset_life_years)
        finite = make_sim_results()
        infinite_discharge = dataclasses.replace(finite, battery_discharge=finite.battery_discharge + math.inf)

        with pytest.raises(ValueError) as exc_info:
            project_multi_year(
                scenario,
                finance,
                simulate=lambda fc, s, e: make_fleet_results_of([finite, infinite_discharge], homes=fc.homes),
            )

        assert str(exc_info.value) == (
            "every aggregate of the fleet simulated at age 0 must be finite: got per_home_discharge[1]=inf"
        )
