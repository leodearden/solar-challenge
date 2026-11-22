# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet and finance figures say which grid-charge forecast sized them, and refuse the one they may not use.

dispatch.distinct_grid_charge_forecasts is the one derivation of the forecasts a set of runs ran
under; FleetSummary and BillDistribution carry it. finance.annualise, which every bill and
projection passes through, refuses a summary whose grid charge perfect_foresight sized: it reads
the run's own future, an upper bound no board figure may use. project_multi_year and
solve_cost_recovery_rate refuse a scenario whose battery grid-charges by it before they simulate
it, through finance.refuse_analysis_only_forecasts. The summaries are priced, as finance refuses
an unpriced one.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable
from datetime import date

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.dispatch import GridChargeConfig, GridChargeForecast, distinct_grid_charge_forecasts
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import (
    FinanceConfig,
    annualise,
    basis_c_own_use_kwh,
    bill_distribution,
    householder_bill,
    project_multi_year,
    refuse_analysis_only_forecasts,
    solve_cost_recovery_rate,
)
from solar_challenge.fleet import FleetConfig, FleetResults, FleetRunner, aggregate_home_summaries
from solar_challenge.home import HomeConfig, RunPricing, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.location import Location
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.weather import PrefetchedWeather
from tests._finance_builders import make_home_config, make_scenario_and_finance, make_scenario_of, make_sim_results, make_window
from tests._synthetic_weather import synthetic_june_weather

_PRICING = RunPricing(0.245, 4.1)


def _summary(forecast: GridChargeForecast | None) -> SummaryStatistics:
    """A priced year's summary of a home whose grid charge forecast sized, None for a home that did not grid-charge."""
    return dataclasses.replace(calculate_summary(make_sim_results(pricing=_PRICING)), grid_charge_forecast=forecast)


def _finance() -> FinanceConfig:
    return make_scenario_and_finance()[1]


def _bill(summary: SummaryStatistics) -> object:
    """householder_bill of *summary*'s year at its physics own-use, as bill_distribution bills it."""
    return householder_bill(summary, basis_c_own_use_kwh(summary), _finance())


_MIXED_FLEET: tuple[GridChargeForecast | None, ...] = ("trailing_14_days", None, "pv_blind", "trailing_14_days")
"""A fleet's forecasts, out of their declared order, one home not grid-charging and one forecast twice."""


class TestDistinctGridChargeForecasts:
    """dispatch.distinct_grid_charge_forecasts: the distinct forecasts some run's grid charge ran under, in GRID_CHARGE_FORECASTS order."""

    def test_the_distinct_forecasts_in_their_declared_order(self) -> None:
        assert distinct_grid_charge_forecasts(each for each in _MIXED_FLEET) == ("pv_blind", "trailing_14_days")

    @pytest.mark.parametrize("forecasts", [pytest.param((None, None), id="no-home-grid-charged"), pytest.param((), id="no-home")])
    def test_none_when_no_run_grid_charged(self, forecasts: tuple[None, ...]) -> None:
        assert distinct_grid_charge_forecasts(each for each in forecasts) == ()


class TestFleetSummaryGridChargeForecasts:
    """aggregate_home_summaries says which forecasts sized its homes' grid charge."""

    def test_a_fleet_summary_names_its_homes_forecasts(self) -> None:
        fleet = aggregate_home_summaries([_summary(each) for each in _MIXED_FLEET])

        assert fleet.grid_charge_forecasts == ("pv_blind", "trailing_14_days")

    def test_a_fleet_whose_homes_did_not_grid_charge_names_none(self) -> None:
        assert aggregate_home_summaries([_summary(None), _summary(None)]).grid_charge_forecasts == ()


class TestBillDistributionGridChargeForecasts:
    """bill_distribution says which forecasts sized the bills it distributes, beside the window it annualised them from."""

    def test_a_distribution_names_its_homes_forecasts_beside_its_window(self) -> None:
        distribution = bill_distribution([_summary(each) for each in _MIXED_FLEET], _finance())

        assert distribution.grid_charge_forecasts == ("pv_blind", "trailing_14_days")
        assert distribution.annualised_from == make_window()

    def test_a_distribution_of_homes_that_did_not_grid_charge_names_none(self) -> None:
        distribution = bill_distribution([_summary(None), _summary(None)], _finance())

        assert distribution.grid_charge_forecasts == ()


_SUMMARY_FORECAST = "this SummaryStatistics' grid_charge_forecast"
"""Where annualise reads the forecast that sized a summary's grid charge."""


def _assert_refuses_perfect_foresight(refused: pytest.ExceptionInfo[ConfigurationError], held_as: str) -> None:
    """The refusal names where the forecast is held and its value, says why no board figure may use it, and names the forecasts to run instead."""
    message = str(refused.value)
    assert f"{held_as} is 'perfect_foresight'" in message
    assert "reads the run's own future" in message
    assert "upper-bound analysis mode board figures never use" in message
    assert "with forecast 'pv_blind' or 'trailing_14_days' instead" in message


def _home_grid_charging_by(forecast: GridChargeForecast) -> HomeConfig:
    """make_home_config's home with a 5 kWh battery grid-charging to 90% on Economy 7 under tou_optimized, its fill sized by *forecast*, exporting at 4.1p."""
    return dataclasses.replace(
        make_home_config(),
        battery_config=BatteryConfig(5.0, grid_charging=GridChargeConfig(0.9, forecast=forecast)),
        tariff_config=TariffConfig.economy_7(),
        seg_tariff=SEGTariff(name="SEG", rate_pence_per_kwh=4.1),
        dispatch_strategy="tou_optimized",
    )


def _never_simulated(fleet: FleetConfig, start: pd.Timestamp, end: pd.Timestamp) -> FleetResults:
    """A fleet simulator for a call that must refuse its scenario before simulating any fleet."""
    pytest.fail(f"simulated fleet {fleet.name!r}, which the call was to refuse before any simulation")


class TestFinanceRefusesPerfectForesight:
    """finance.annualise, the one annualisation rule, refuses a perfect_foresight summary, so no bill or projection uses one."""

    def test_annualise_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            annualise(_summary("perfect_foresight"))

        _assert_refuses_perfect_foresight(refused, _SUMMARY_FORECAST)

    def test_householder_bill_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            _bill(_summary("perfect_foresight"))

        _assert_refuses_perfect_foresight(refused, _SUMMARY_FORECAST)

    def test_bill_distribution_refuses_a_fleet_with_one_such_home(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            bill_distribution([_summary("pv_blind"), _summary("perfect_foresight")], _finance())

        _assert_refuses_perfect_foresight(refused, _SUMMARY_FORECAST)

    def test_bill_distribution_refuses_the_summaries_of_a_fleet_simulated_under_it(self) -> None:
        """Two June days of synthetic weather through the real FleetRunner, as `finance run` simulates before it bills: simulate_home records the forecast, calculate_summary copies it, and the bills' annualise refuses it."""
        scenario = make_scenario_of([_home_grid_charging_by("perfect_foresight")]).with_window(
            first_day=date(2021, 6, 1), last_day=date(2021, 6, 2)
        )
        weather = PrefetchedWeather({Location.bristol(): synthetic_june_weather(pd.Timestamp("2021-06-01"), (1.0, 1.0))})
        runner = FleetRunner(weather=weather, home_simulator=simulate_home, parallel=False)
        results = runner.simulate(FleetConfig(homes=list(scenario.simulated_homes())), *scenario.simulation_bounds())
        summaries = [calculate_summary(each) for each in results.per_home_results]

        with pytest.raises(ConfigurationError) as refused:
            bill_distribution(summaries, _finance())

        _assert_refuses_perfect_foresight(refused, _SUMMARY_FORECAST)

    @pytest.mark.parametrize(
        "project",
        [
            pytest.param(lambda scenario: project_multi_year(scenario, _finance(), simulate=_never_simulated), id="project_multi_year"),
            pytest.param(lambda scenario: solve_cost_recovery_rate(scenario, _finance(), simulate=_never_simulated), id="solve_cost_recovery_rate"),
        ],
    )
    def test_a_projection_refuses_a_scenario_whose_battery_forecast_is_it_before_simulating_it(
        self, project: Callable[[ScenarioConfig], object]
    ) -> None:
        scenario = make_scenario_of([_home_grid_charging_by("pv_blind"), _home_grid_charging_by("perfect_foresight")])

        with pytest.raises(ConfigurationError) as refused:
            project(scenario)

        _assert_refuses_perfect_foresight(refused, "home 1's battery_config.grid_charging.forecast")

    def test_homes_none_of_whose_batteries_grid_charge_by_it_are_not_refused(self) -> None:
        refuse_analysis_only_forecasts(
            [
                make_home_config(),
                make_home_config(battery_config=BatteryConfig(5.0)),
                _home_grid_charging_by("pv_blind"),
                _home_grid_charging_by("trailing_14_days"),
            ]
        )

    @pytest.mark.parametrize("forecast", ["pv_blind", "trailing_14_days"])
    def test_a_realistic_forecast_annualises_and_bills_as_a_home_that_did_not_grid_charge(
        self, forecast: GridChargeForecast
    ) -> None:
        """The forecast is provenance only: the figures are the summary's totals'."""
        sized, unsized = _summary(forecast), _summary(None)

        assert annualise(sized) == annualise(unsized)
        assert _bill(sized) == _bill(unsized)
