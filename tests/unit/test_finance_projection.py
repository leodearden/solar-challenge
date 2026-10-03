# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for project_multi_year's curve shape and fleet energy aggregation.

The projection runs on an injected synthetic simulate, with no PVGIS or network.
"""
from __future__ import annotations

import pytest

from tests._finance_builders import make_fleet_results, make_scenario_and_finance


class TestProjectMultiYearShape:
    """project_multi_year shape + energy aggregation tests."""

    def test_returns_multi_year_curve(self) -> None:
        """project_multi_year returns a MultiYearCurve."""
        from solar_challenge.finance import MultiYearCurve, project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert isinstance(curve, MultiYearCurve)

    def test_points_length_equals_asset_life(self) -> None:
        """len(curve.points) == finance.asset_life_years."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert len(curve.points) == 5

    def test_points_year_ascending(self) -> None:
        """points[i].year == i (ascending 0..asset_life-1)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for i, pt in enumerate(curve.points):
            assert pt.year == i

    def test_sampled_ages_sorted(self) -> None:
        """sampled_ages is sorted in ascending order."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert list(curve.sampled_ages) == sorted(curve.sampled_ages)

    def test_sampled_ages_within_range(self) -> None:
        """All sampled_ages are within [0, asset_life)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        for age in curve.sampled_ages:
            assert 0 <= age < 5

    def test_sampled_ages_includes_seed_endpoints(self) -> None:
        """sampled_ages includes age 0 (seed start) and asset_life-1 (seed end)."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]

        scenario, finance = make_scenario_and_finance(asset_life_years=5)
        fr = make_fleet_results(n_homes=1)
        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)
        assert 0 in curve.sampled_ages
        assert 4 in curve.sampled_ages  # asset_life-1

    def test_fleet_self_consumption_at_sampled_age(self) -> None:
        """fleet_self_consumption_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

        n_homes = 2
        sc_per_home = 1000.0
        scenario, finance = make_scenario_and_finance(n_homes=n_homes, asset_life_years=5)
        fr = make_fleet_results(n_homes=n_homes, self_kwh=sc_per_home)

        # Compute expected total from calculate_summary
        expected_sc = sum(
            calculate_summary(r).total_self_consumption_kwh
            for r in fr.per_home_results
        )

        curve = project_multi_year(scenario, finance, simulate=lambda fc, s, e: fr)

        # At age 0 (a seed point), the value should match the injected summary
        assert curve.points[0].fleet_self_consumption_kwh == pytest.approx(
            expected_sc, rel=1e-4
        )

    def test_fleet_export_at_sampled_age(self) -> None:
        """fleet_export_kwh at a sampled age equals sum of per-home totals."""
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

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
        from solar_challenge.finance import project_multi_year  # type: ignore[attr-defined]
        from solar_challenge.home import calculate_summary

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
