# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for tests/_finance_builders.py, the finance tests' synthetic homes, scenarios and constant-power simulation results."""

import pytest

from solar_challenge.home import calculate_summary
from tests._finance_builders import (
    make_fleet_results,
    make_home_config,
    make_scenario,
    make_scenario_and_finance,
    make_sim_results,
)


@pytest.mark.parametrize("days", [pytest.param(365, id="full-year"), pytest.param(3, id="short-window")])
def test_sim_results_summary_totals_are_the_arguments(days: int) -> None:
    summary = calculate_summary(
        make_sim_results(
            self_kwh=3000.0,
            export_kwh=1000.0,
            import_kwh=500.0,
            discharge_kwh=800.0,
            export_revenue_gbp=150.0,
            days=days,
        )
    )

    assert summary.simulation_days == days
    assert summary.total_self_consumption_kwh == pytest.approx(3000.0)
    assert summary.total_grid_export_kwh == pytest.approx(1000.0)
    assert summary.total_grid_import_kwh == pytest.approx(500.0)
    assert summary.total_battery_discharge_kwh == pytest.approx(800.0)
    assert summary.total_generation_kwh == pytest.approx(3000.0 + 1000.0)
    assert summary.total_demand_kwh == pytest.approx(3000.0 + 500.0 - 800.0)
    assert summary.total_export_revenue_gbp == pytest.approx(150.0)


def test_sim_results_default_to_a_full_year() -> None:
    assert calculate_summary(make_sim_results()).simulation_days == 365


def test_fleet_results_pair_each_default_home_with_the_given_annual_totals() -> None:
    fleet = make_fleet_results(
        n_homes=3,
        self_kwh=2000.0,
        export_kwh=800.0,
        import_kwh=1200.0,
        export_revenue_gbp_per_year=40.0,
    )

    assert fleet.home_configs == [make_home_config()] * 3
    per_home_totals = [
        (
            summary.total_self_consumption_kwh,
            summary.total_grid_export_kwh,
            summary.total_grid_import_kwh,
            summary.total_export_revenue_gbp,
            summary.simulation_days,
        )
        for summary in map(calculate_summary, fleet.per_home_results)
    ]
    assert per_home_totals == [pytest.approx((2000.0, 800.0, 1200.0, 40.0, 365))] * 3


def test_scenario_holds_n_default_homes_and_the_given_seg_rate() -> None:
    scenario = make_scenario(n_homes=2, seg_tariff_pence_per_kwh=5.0)

    assert scenario.homes == [make_home_config()] * 2
    assert scenario.seg_tariff_pence_per_kwh == 5.0

    default_scenario = make_scenario()

    assert default_scenario.homes == [make_home_config()]
    assert default_scenario.seg_tariff_pence_per_kwh is None


@pytest.mark.parametrize(
    "asset_life_years",
    [
        pytest.param(5, id="life-shorter-than-the-default-loan"),
        pytest.param(25, id="life-longer-than-the-default-loan"),
    ],
)
def test_scenario_and_finance_fit_the_loan_within_the_asset_life(asset_life_years: int) -> None:
    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=asset_life_years)

    assert len(scenario.homes) == 2
    assert finance.asset_life_years == asset_life_years
    assert finance.loan_term_years <= asset_life_years
