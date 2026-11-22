# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fleet and finance figures say which grid-charge forecast sized them, and refuse the one they may not use.

home.grid_charge_forecasts_of is the one derivation of the forecasts a set of summaries ran
under; FleetSummary and BillDistribution carry it. finance.annualise, which every bill and
projection passes through, refuses a summary whose grid charge perfect_foresight sized: it reads
the run's own future, an upper bound no board figure may use. The summaries are priced, as
finance refuses an unpriced one.
"""

from __future__ import annotations

import dataclasses
from datetime import date

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import GridChargeConfig, GridChargeForecast
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig, annualise, bill_distribution, householder_bill, project_multi_year
from solar_challenge.fleet import FleetRunner, aggregate_home_summaries
from solar_challenge.home import RunPricing, SummaryStatistics, calculate_summary, grid_charge_forecasts_of, simulate_home
from solar_challenge.location import Location
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.weather import PrefetchedWeather
from tests._finance_builders import make_home_config, make_scenario_and_finance, make_scenario_of, make_sim_results, make_window
from tests._synthetic_weather import synthetic_june_weather

_PRICING = RunPricing(0.245, 4.1)
_YEAR_DAYS = 365
_OWN_USE_KWH = 500.0


def _summary(forecast: GridChargeForecast | None) -> SummaryStatistics:
    """A priced year's summary of a home whose grid charge forecast sized, None for a home that did not grid-charge."""
    return dataclasses.replace(calculate_summary(make_sim_results(pricing=_PRICING)), grid_charge_forecast=forecast)


def _finance() -> FinanceConfig:
    return make_scenario_and_finance()[1]


_MIXED_FLEET: tuple[GridChargeForecast | None, ...] = ("trailing_14_days", None, "pv_blind", "trailing_14_days")
"""A fleet's forecasts, out of their declared order, one home not grid-charging and one forecast twice."""


class TestGridChargeForecastsOf:
    """home.grid_charge_forecasts_of: the distinct forecasts some summary's grid charge ran under, in GRID_CHARGE_FORECASTS order."""

    def test_the_distinct_forecasts_in_their_declared_order(self) -> None:
        assert grid_charge_forecasts_of(_summary(each) for each in _MIXED_FLEET) == ("pv_blind", "trailing_14_days")

    @pytest.mark.parametrize("forecasts", [pytest.param((None, None), id="no-home-grid-charged"), pytest.param((), id="no-home")])
    def test_none_when_no_summary_grid_charged(self, forecasts: tuple[None, ...]) -> None:
        assert grid_charge_forecasts_of(_summary(each) for each in forecasts) == ()


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
        distribution = bill_distribution([_summary(each) for each in _MIXED_FLEET], _finance(), _YEAR_DAYS)

        assert distribution.grid_charge_forecasts == ("pv_blind", "trailing_14_days")
        assert distribution.annualised_from == make_window()

    def test_a_distribution_of_homes_that_did_not_grid_charge_names_none(self) -> None:
        distribution = bill_distribution([_summary(None), _summary(None)], _finance(), _YEAR_DAYS)

        assert distribution.grid_charge_forecasts == ()


def _assert_refuses_perfect_foresight(refused: pytest.ExceptionInfo[ConfigurationError]) -> None:
    """The refusal names the field and the value, says why no board figure may use it, and names the forecasts to run instead."""
    message = str(refused.value)
    assert "grid_charge_forecast" in message
    assert "'perfect_foresight'" in message
    assert "reads the run's own future" in message
    assert "upper-bound analysis mode board figures never use" in message
    assert "'pv_blind'" in message
    assert "'trailing_14_days'" in message


class TestFinanceRefusesPerfectForesight:
    """finance.annualise, the one annualisation rule, refuses a perfect_foresight summary, so no bill or projection uses one."""

    def test_annualise_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            annualise(_summary("perfect_foresight"))

        _assert_refuses_perfect_foresight(refused)

    def test_householder_bill_refuses_it(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            householder_bill(_summary("perfect_foresight"), _OWN_USE_KWH, _finance(), _YEAR_DAYS)

        _assert_refuses_perfect_foresight(refused)

    def test_bill_distribution_refuses_a_fleet_with_one_such_home(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            bill_distribution([_summary("pv_blind"), _summary("perfect_foresight")], _finance(), _YEAR_DAYS)

        _assert_refuses_perfect_foresight(refused)

    def test_project_multi_year_refuses_a_scenario_whose_battery_forecast_is_it(self) -> None:
        """Two June days of synthetic weather through the real FleetRunner: simulate_home records the forecast, and the projection's annualise refuses it."""
        home = dataclasses.replace(
            make_home_config(battery_config=BatteryConfig(5.0, grid_charging=GridChargeConfig(0.9, forecast="perfect_foresight"))),
            tariff_config=TariffConfig.economy_7(),
            seg_tariff=SEGTariff(name="SEG", rate_pence_per_kwh=4.1),
            dispatch_strategy="tou_optimized",
        )
        scenario = make_scenario_of([home]).with_window(first_day=date(2021, 6, 1), last_day=date(2021, 6, 2))
        weather = PrefetchedWeather({Location.bristol(): synthetic_june_weather(pd.Timestamp("2021-06-01"), (1.0, 1.0))})
        runner = FleetRunner(weather=weather, home_simulator=simulate_home, parallel=False)

        with pytest.raises(ConfigurationError) as refused:
            project_multi_year(scenario, _finance(), simulate=runner.simulate)

        _assert_refuses_perfect_foresight(refused)

    @pytest.mark.parametrize("forecast", ["pv_blind", "trailing_14_days"])
    def test_a_realistic_forecast_annualises_and_bills_as_a_home_that_did_not_grid_charge(
        self, forecast: GridChargeForecast
    ) -> None:
        """The forecast is provenance only: the figures are the summary's totals'."""
        sized, unsized = _summary(forecast), _summary(None)

        assert annualise(sized) == annualise(unsized)
        assert householder_bill(sized, _OWN_USE_KWH, _finance(), _YEAR_DAYS) == householder_bill(
            unsized, _OWN_USE_KWH, _finance(), _YEAR_DAYS
        )
