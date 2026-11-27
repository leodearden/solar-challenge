# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the grid-services events pricing of a fleet under each participation.

An observed fleet is priced from the firm spare capacity its own dispatch leaves, as it was before a fleet
could be enrolled: TestObservedPricesAsBefore pins those figures as literals measured before dispatched
pricing existed.  Under both participations the breakdown reports the battery export an event's window
holds (TestBatteryExportPerEvent).
"""

import dataclasses
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    GridServicesEventsConfig,
    compute_grid_services_at_events,
)
from solar_challenge.home import SimulationResults
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results

_FIRST_JANUARY_MONDAY = date(2024, 1, 15)
"""The first of two January weekdays, Monday 15 and Tuesday 16, both in the default window's months and weekdays."""

_WINDOW = DEFAULT_EVENT_WINDOWS[0]
"""November to February weekdays, 16:00 to 19:00, 12 events a year of 3 h."""


def _two_january_weekdays(cadence: timedelta = timedelta(hours=1)) -> SimulationResults:
    """make_sim_results over Monday 15 and Tuesday 16 January 2024, its rows *cadence* apart."""
    return make_sim_results(days=2, first_day=_FIRST_JANUARY_MONDAY, cadence=cadence)


def _dispatching_home(phase: int) -> SimulationResults:
    """A battery home's two January weekdays, hourly, its SOC, discharge, charge and tariff varying from row to row by *phase*.

    It charges before 05:00 each day, so an evening's discharge after the window runs to the next morning.
    """
    base = _two_january_weekdays()
    index = base.generation.index
    rows = np.arange(len(index))

    def series(values: np.ndarray) -> pd.Series:
        return pd.Series(values, index=index, dtype=float)

    return dataclasses.replace(
        base,
        battery_soc=series(1.2 + ((rows * 7 + phase) % 11) * 0.35),
        battery_discharge=series(((rows * 3 + phase) % 5) * 0.25),
        battery_charge=series(np.where(index.hour < 5, 0.8, 0.0)),
        tariff_rate=series(0.08 + ((rows + phase) % 4) * 0.05),
    )


def _observed_fleet() -> FleetResults:
    """Two battery homes, a 5 kWh battery of 2.5 kW and a 10 kWh battery of 3 kW, and a PV-only home, over two January weekdays."""
    return make_fleet_results_of(
        [_dispatching_home(phase=0), _dispatching_home(phase=3), _two_january_weekdays()],
        homes=[
            make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)),
            make_home_config(battery_config=BatteryConfig(capacity_kwh=10.0, max_discharge_kw=3.0)),
            make_home_config(),
        ],
    )


_OBSERVED_FIGURES = {
    "operational": {
        "annual_income_gbp": 5.318399999999999,
        "per_window_avail_kw": (0.5333333333333332,),
        "per_window_income_gbp": (5.318399999999999,),
        "per_window_avail_p50_kw": (0.6499999999999999,),
        "per_window_avail_p90_kw": (0.4166666666666666,),
        "per_window_displaced_self_use_kwh_per_event": (1.5999999999999996,),
        "per_window_displaced_import_gbp_per_year": (3.2190000000000003,),
    },
    "capacity": {
        "annual_income_gbp": 14.625600000000002,
        "per_window_avail_kw": (1.4666666666666668,),
        "per_window_income_gbp": (14.625600000000002,),
        "per_window_avail_p50_kw": (1.8166666666666669,),
        "per_window_avail_p90_kw": (1.1166666666666667,),
        "per_window_displaced_self_use_kwh_per_event": (4.15,),
        "per_window_displaced_import_gbp_per_year": (8.199000000000002,),
    },
}
"""_observed_fleet's figures under each delivery baseline, measured at main d6c04225, before a fleet's participation changed its pricing."""


class TestObservedPricesAsBefore:
    """An observed fleet prices at the figures it priced at before dispatched pricing existed, whatever the settings only an enrolled fleet reads."""

    @pytest.mark.parametrize("baseline", ["operational", "capacity"])
    def test_its_breakdown_holds_the_figures_it_held_before(self, baseline: str) -> None:
        breakdown = compute_grid_services_at_events(
            _observed_fleet(), GridServicesEventsConfig(delivery_baseline=baseline)
        )

        assert {name: getattr(breakdown, name) for name in _OBSERVED_FIGURES[baseline]} == _OBSERVED_FIGURES[baseline]

    @pytest.mark.parametrize("baseline", ["operational", "capacity"])
    def test_its_annual_income_is_the_income_it_was_before(self, baseline: str) -> None:
        income = GridServicesEventsConfig(delivery_baseline=baseline).annual_income_gbp(_observed_fleet())

        assert income == _OBSERVED_FIGURES[baseline]["annual_income_gbp"]

    @pytest.mark.parametrize("baseline", ["operational", "capacity"])
    def test_the_seed_and_the_site_export_limit_change_no_observed_figure(self, baseline: str) -> None:
        default = GridServicesEventsConfig(delivery_baseline=baseline)
        enrolment_settings = dataclasses.replace(default, event_day_seed=7, site_export_limit_kw=3.0)

        assert compute_grid_services_at_events(_observed_fleet(), enrolment_settings) == (
            compute_grid_services_at_events(_observed_fleet(), default)
        )
        assert enrolment_settings.annual_income_gbp(_observed_fleet()) == default.annual_income_gbp(_observed_fleet())


def _exporting_home(
    export_kw_by_day: tuple[float, float], *, cadence: timedelta = timedelta(hours=1), outside_kw: float = 2.0
) -> SimulationResults:
    """A battery home's two January weekdays whose battery exports *export_kw_by_day*'s kW on each day's in-window rows, and *outside_kw* at 20:00, outside the window."""
    base = _two_january_weekdays(cadence)
    index = base.generation.index
    in_window = _WINDOW.mask(index).to_numpy()
    day_kw = np.where(index.day == _FIRST_JANUARY_MONDAY.day, *export_kw_by_day)
    export = np.where(in_window, day_kw, np.where(index.hour == 20, outside_kw, 0.0))
    return dataclasses.replace(base, battery_export=pd.Series(export, index=index, dtype=float))


def _exporting_fleet(*per_home_results: SimulationResults) -> FleetResults:
    """Each of *per_home_results* on a home with a 5 kWh battery, then a PV-only home."""
    return make_fleet_results_of(
        [*per_home_results, _two_january_weekdays()],
        homes=[
            *(make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)) for _ in per_home_results),
            make_home_config(),
        ],
    )


class TestBatteryExportPerEvent:
    """The breakdown reports the mean over a window's event days of the fleet's in-window battery export."""

    def test_it_is_the_mean_over_the_event_days_of_the_in_window_export(self) -> None:
        fleet = _exporting_fleet(_exporting_home((0.5, 1.0)), _exporting_home((0.25, 0.25)))

        breakdown = compute_grid_services_at_events(fleet, GridServicesEventsConfig())

        # Monday 3 h × (0.5 + 0.25) kW = 2.25 kWh, Tuesday 3 h × (1.0 + 0.25) kW = 3.75 kWh; 20:00's export is outside.
        assert breakdown.per_window_battery_export_kwh_per_event == (3.0,)

    def test_each_row_counts_the_hours_it_lasts(self) -> None:
        fleet = _exporting_fleet(_exporting_home((0.5, 1.0), cadence=timedelta(minutes=30)))

        breakdown = compute_grid_services_at_events(fleet, GridServicesEventsConfig())

        assert breakdown.per_window_battery_export_kwh_per_event == (2.25,)

    def test_a_fleet_whose_batteries_export_nothing_reports_0(self) -> None:
        fleet = _exporting_fleet(_two_january_weekdays(), _two_january_weekdays())

        breakdown = compute_grid_services_at_events(fleet, GridServicesEventsConfig())

        assert breakdown.per_window_battery_export_kwh_per_event == (0.0,)
