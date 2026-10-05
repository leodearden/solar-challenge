# SPDX-License-Identifier: AGPL-3.0-or-later
# SPDX-FileCopyrightText: 2024 Solar Challenge Contributors
"""Unit tests for tests/_finance_builders.py, the finance tests' synthetic homes, scenarios and constant-power simulation results."""

import dataclasses

import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.home import calculate_summary
from tests._finance_builders import (
    make_fleet_results,
    make_fleet_results_of,
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
        export_revenue_gbp=40.0,
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


def test_fleet_results_pair_the_given_homes_with_the_totals_over_the_window() -> None:
    homes = [make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))]

    fleet = make_fleet_results(
        homes=homes,
        self_kwh=30.0,
        export_kwh=10.0,
        import_kwh=5.0,
        discharge_kwh=8.0,
        export_revenue_gbp=1.5,
        days=3,
    )

    assert fleet.home_configs == homes
    per_home_totals = [
        (
            summary.total_self_consumption_kwh,
            summary.total_grid_export_kwh,
            summary.total_grid_import_kwh,
            summary.total_battery_discharge_kwh,
            summary.total_export_revenue_gbp,
            summary.simulation_days,
        )
        for summary in map(calculate_summary, fleet.per_home_results)
    ]
    assert per_home_totals == [pytest.approx((30.0, 10.0, 5.0, 8.0, 1.5, 3))] * 2


def test_fleet_results_refuse_both_homes_and_n_homes() -> None:
    with pytest.raises(TypeError, match="homes or n_homes"):
        make_fleet_results(n_homes=2, homes=[make_home_config()])


def test_fleet_results_of_pair_each_given_result_in_order_with_a_default_home() -> None:
    per_home_results = [make_sim_results(self_kwh=18.0, days=1), make_sim_results(self_kwh=6.0, days=1)]

    fleet = make_fleet_results_of(per_home_results)

    assert fleet.home_configs == [make_home_config()] * 2
    assert [
        calculate_summary(results).total_self_consumption_kwh for results in fleet.per_home_results
    ] == pytest.approx([18.0, 6.0])


def test_fleet_results_of_pair_the_given_results_in_order_with_the_given_homes() -> None:
    homes = [make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))]
    per_home_results = [make_sim_results(self_kwh=18.0, days=1), make_sim_results(self_kwh=6.0, days=1)]

    fleet = make_fleet_results_of(per_home_results, homes=homes)

    assert fleet.home_configs == homes
    assert [
        calculate_summary(results).total_self_consumption_kwh for results in fleet.per_home_results
    ] == pytest.approx([18.0, 6.0])


@pytest.mark.parametrize(
    "n_homes",
    [pytest.param(1, id="fewer-homes-than-results"), pytest.param(3, id="more-homes-than-results")],
)
def test_fleet_results_of_refuse_unpaired_homes_as_fleet_results_does(n_homes: int) -> None:
    per_home_results = [make_sim_results(days=1), make_sim_results(days=1)]
    homes = [make_home_config()] * n_homes

    with pytest.raises(ValueError) as fleet_refusal:
        FleetResults(per_home_results=per_home_results, home_configs=homes)
    with pytest.raises(ValueError) as builder_refusal:
        make_fleet_results_of(per_home_results, homes=homes)

    assert str(builder_refusal.value) == str(fleet_refusal.value)


def test_home_config_is_the_default_home_with_the_given_battery() -> None:
    battery = BatteryConfig(capacity_kwh=5.0)

    home = make_home_config(battery_config=battery)

    assert make_home_config().battery_config is None
    assert home.battery_config == battery
    assert dataclasses.replace(home, battery_config=None) == make_home_config()


def test_scenario_holds_n_default_homes_and_the_given_seg_rate() -> None:
    scenario = make_scenario(n_homes=2, seg_tariff_pence_per_kwh=5.0)

    assert scenario.homes == [make_home_config()] * 2
    assert scenario.seg_tariff_pence_per_kwh == 5.0

    default_scenario = make_scenario()

    assert default_scenario.homes == [make_home_config()]
    assert default_scenario.seg_tariff_pence_per_kwh is None


def test_scenario_builders_give_every_home_the_given_battery() -> None:
    battery = BatteryConfig(capacity_kwh=5.0)
    battery_home = make_home_config(battery_config=battery)

    scenario, _ = make_scenario_and_finance(n_homes=2, battery_config=battery)

    assert make_scenario(n_homes=2, battery_config=battery).homes == [battery_home] * 2
    assert scenario.homes == [battery_home] * 2


@pytest.mark.parametrize(
    ("asset_life_years", "loan_term_years"),
    [
        pytest.param(5, 5, id="life-shorter-than-the-default-loan"),
        pytest.param(25, 15, id="life-longer-than-the-default-loan"),
    ],
)
def test_scenario_and_finance_cut_the_default_15_year_loan_to_the_asset_life(
    asset_life_years: int, loan_term_years: int
) -> None:
    scenario, finance = make_scenario_and_finance(n_homes=2, asset_life_years=asset_life_years)

    assert len(scenario.homes) == 2
    assert finance.asset_life_years == asset_life_years
    assert finance.loan_term_years == loan_term_years
