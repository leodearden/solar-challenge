# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finance report's grid-services income value, its Grid Services Income section and the flex block's grid-services row (review-all S25 δ).

``GridServicesIncome`` holds what the scenario's grid-services pricing books on
the bill run's fleet, the same under every assumption mode, and refuses, naming
the values, a figure its pricing could not have printed.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from solar_challenge.board_report import GridServicesIncome
from solar_challenge.gridservices import (
    FlatGridServices,
    GridServicesAtEvents,
    GridServicesEventsConfig,
    NoGridServices,
)

_AT_EVENTS = GridServicesAtEvents(
    annual_income_gbp=14.958,
    per_window_avail_kw=(1.5,),
    per_window_income_gbp=(14.958,),
    per_window_avail_p50_kw=(2.0,),
    per_window_avail_p90_kw=(1.0,),
    per_window_displaced_self_use_kwh_per_event=(2.3,),
    per_window_displaced_import_gbp_per_year=(8.1,),
)
"""One event window's breakdown: £14.958 a year from 1.5 kW."""

_FLAT = FlatGridServices(4.0)
_EVENTS = GridServicesEventsConfig()


def _flat_income(**overrides: object) -> GridServicesIncome:
    """£4.0/kW-yr on 100 battery homes of 250 kW in all, £1,000 a year, with *overrides*."""
    fields: dict[str, object] = {
        "pricing": _FLAT,
        "annual_income_gbp": 1_000.0,
        "battery_homes": 100,
        "battery_discharge_kw": 250.0,
    }
    return GridServicesIncome(**{**fields, **overrides})


def _events_income(**overrides: object) -> GridServicesIncome:
    """The default events pricing booking _AT_EVENTS' £14.958 on one 2.5 kW battery home, with *overrides*."""
    fields: dict[str, object] = {
        "pricing": _EVENTS,
        "annual_income_gbp": _AT_EVENTS.annual_income_gbp,
        "battery_homes": 1,
        "battery_discharge_kw": 2.5,
        "at_events": _AT_EVENTS,
    }
    return GridServicesIncome(**{**fields, **overrides})


class TestGridServicesIncomeRefusals:
    """GridServicesIncome refuses a figure its pricing could not have printed, naming the offending values."""

    @pytest.mark.parametrize(
        ("build", "named"),
        [
            pytest.param(
                lambda: _flat_income(at_events=_AT_EVENTS), (repr(_FLAT), repr(_AT_EVENTS)), id="at-events-under-flat"
            ),
            pytest.param(lambda: _events_income(at_events=None), (repr(_EVENTS), "at_events=None"), id="events-without-at-events"),
            pytest.param(lambda: _events_income(annual_income_gbp=15.0), ("15.0", "14.958"), id="events-income-not-at-events"),
            pytest.param(lambda: _flat_income(annual_income_gbp=-1.0), ("annual_income_gbp=-1.0",), id="negative-income"),
            pytest.param(lambda: _flat_income(annual_income_gbp=math.nan), ("annual_income_gbp=nan",), id="nan-income"),
            pytest.param(lambda: _flat_income(annual_income_gbp=math.inf), ("annual_income_gbp=inf",), id="infinite-income"),
            pytest.param(lambda: _flat_income(battery_homes=-1), ("battery_homes=-1",), id="negative-battery-homes"),
            pytest.param(
                lambda: _flat_income(battery_discharge_kw=-250.0), ("battery_discharge_kw=-250.0",), id="negative-kw"
            ),
            pytest.param(lambda: _flat_income(battery_discharge_kw=math.nan), ("battery_discharge_kw=nan",), id="nan-kw"),
            pytest.param(lambda: _flat_income(battery_discharge_kw=math.inf), ("battery_discharge_kw=inf",), id="infinite-kw"),
            pytest.param(
                lambda: _events_income(battery_homes=0, battery_discharge_kw=0.0),
                ("annual_income_gbp=14.958", "battery_homes=0"),
                id="income-without-a-battery-home",
            ),
            pytest.param(
                lambda: _flat_income(annual_income_gbp=0.0, battery_homes=3, battery_discharge_kw=0.0),
                ("battery_homes=3", "battery_discharge_kw=0.0"),
                id="battery-homes-without-kw",
            ),
            pytest.param(
                lambda: _flat_income(annual_income_gbp=0.0, battery_homes=0, battery_discharge_kw=2.5),
                ("battery_homes=0", "battery_discharge_kw=2.5"),
                id="kw-without-battery-homes",
            ),
            pytest.param(
                lambda: _flat_income(annual_income_gbp=999.0), ("999.0", "4.0", "250.0"), id="flat-income-not-rate-times-kw"
            ),
            pytest.param(
                lambda: _flat_income(pricing=NoGridServices(), annual_income_gbp=0.0, battery_homes=0, battery_discharge_kw=0.0),
                ("NoGridServices()",),
                id="no-grid-services",
            ),
        ],
    )
    def test_it_refuses_a_figure_its_pricing_could_not_print(
        self, build: Callable[[], GridServicesIncome], named: tuple[str, ...]
    ) -> None:
        with pytest.raises(ValueError) as refused:
            build()

        for value in named:
            assert value in str(refused.value), (value, str(refused.value))

    def test_a_flat_income_is_its_rate_times_the_battery_discharge_kw(self) -> None:
        income = _flat_income()

        assert (income.annual_income_gbp, income.battery_homes, income.battery_discharge_kw) == (1_000.0, 100, 250.0)
        assert income.per_battery_home_gbp == 10.0
        assert income.per_discharge_kw_gbp == 4.0

    def test_an_events_income_is_its_breakdowns(self) -> None:
        income = _events_income()

        assert income.at_events is _AT_EVENTS
        assert income.per_battery_home_gbp == 14.958
        assert income.per_discharge_kw_gbp == pytest.approx(14.958 / 2.5)

    def test_a_fleet_with_no_battery_home_has_no_per_home_or_per_kw_figure(self) -> None:
        income = _flat_income(annual_income_gbp=0.0, battery_homes=0, battery_discharge_kw=0.0)

        assert income.per_battery_home_gbp is None
        assert income.per_discharge_kw_gbp is None
