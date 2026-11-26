# SPDX-License-Identifier: AGPL-3.0-or-later
"""The finance report's grid-services income value, its Grid Services Income section and the flex block's grid-services row (review-all S25 δ).

``GridServicesIncome`` holds what the scenario's grid-services pricing books on
the bill run's fleet, the same under every assumption mode, and refuses, naming
the values, a figure its pricing could not have printed.  Given one,
``generate_finance_report`` renders a Grid Services Income section after the
project economics: the pricing's model line, the income each mode's projection
booked at year 1 and year N when the sections carry projections, and this
window's fleet table, once.  The flexibility-value block's grid-services row
reads the booked figure, or, with no pricing, the consulting band labelled not
booked.
"""
from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from solar_challenge.board_report import AssumptionSection, FlexBlock, GridServicesIncome, generate_finance_report
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import OwnUseBasis
from solar_challenge.flex import FLEX_VALUE_BANDS
from solar_challenge.gridservices import (
    FlatGridServices,
    GridServicesAtEvents,
    GridServicesBand,
    GridServicesEventsConfig,
    NoGridServices,
)
from solar_challenge.projection import FleetProjection
from tests._assumption_sections import make_assumption_section, sections_of
from tests._factories import make_cost_recovery_solution, make_fleet_projection, make_project_economics
from tests._markdown_tables import row_cells, table_rows

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
            pytest.param(
                lambda: _flat_income(pricing="flat", annual_income_gbp=0.0, battery_homes=0, battery_discharge_kw=0.0),
                ("pricing='flat'", "FlatGridServices", "GridServicesEventsConfig"),
                id="a-value-that-is-no-pricing",
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


_SECTION_HEADING = "## Grid Services Income"
_BOOKED_HEADING = "### Booked by the projection (£ a year)"
_WINDOW_HEADING = "### This window's fleet, the same under every assumption"
_FLEX_HEADING = "## Flexibility Value (per battery home)"
_SPREADSHEET_AT_70 = "Spreadsheet (70% self-consumption)"

_TWO_WINDOWS = GridServicesAtEvents(
    annual_income_gbp=19.944,
    per_window_avail_kw=(1.5, 0.5),
    per_window_income_gbp=(14.958, 4.986),
    per_window_avail_p50_kw=(2.0, 0.5),
    per_window_avail_p90_kw=(1.0, 0.3),
    per_window_displaced_self_use_kwh_per_event=(2.25, 0.75),
    per_window_displaced_import_gbp_per_year=(8.1, 1.9),
)
"""Two event windows' breakdown: £19.944 a year."""


def _report(
    *sections: AssumptionSection, grid_services: GridServicesIncome | None, flex: FlexBlock | None = None
) -> str:
    """The finance report of *sections*, or of one plain physics section when none is given."""
    return generate_finance_report(
        sections_of(*(sections or (make_assumption_section(),))), grid_services=grid_services, flex=flex
    )


def _both_modes(physics: FleetProjection, spreadsheet: FleetProjection) -> tuple[AssumptionSection, ...]:
    """A physics section carrying *physics* and a spreadsheet section at 70% carrying *spreadsheet*."""
    return (
        make_assumption_section(OwnUseBasis.SIMULATED, projection=physics),
        make_assumption_section(OwnUseBasis.OVERRIDE, override=0.7, projection=spreadsheet),
    )


class TestGridServicesIncomeSection:
    """The Grid Services Income section: its model line, the projection's booked income and this window's fleet."""

    @pytest.mark.parametrize(
        ("income", "model"),
        [
            pytest.param(_events_income(), "capacity at events, central band, operational delivery baseline", id="events"),
            pytest.param(
                _events_income(pricing=GridServicesEventsConfig(band="high", delivery_baseline="capacity")),
                "capacity at events, high band, capacity delivery baseline",
                id="events-high-capacity",
            ),
            pytest.param(_flat_income(), "flat, £4.0/kW-yr", id="flat"),
        ],
    )
    def test_its_model_line_names_the_pricing(self, income: GridServicesIncome, model: str) -> None:
        report = _report(grid_services=income)

        assert _SECTION_HEADING in report.splitlines()
        assert f"Model: **{model}**" in report.splitlines(), report

    def test_under_flat_pricing_this_windows_table_holds_only_the_annual_fleet_income(self) -> None:
        report = _report(grid_services=_flat_income())

        assert table_rows(report, _WINDOW_HEADING) == [["Metric", "Value"], ["Annual fleet income", "£1,000"]]

    def test_under_events_pricing_this_windows_table_renders_the_breakdown_once_whatever_the_modes(self) -> None:
        projection = make_fleet_projection([(0, 20.0), (12, 18.0), (24, 15.0)], asset_life_years=25)

        report = _report(*_both_modes(projection, projection), grid_services=_events_income())

        assert report.count(_WINDOW_HEADING) == 1
        assert table_rows(report, _WINDOW_HEADING) == [
            ["Metric", "Value"],
            ["Annual fleet income", "£15"],
            ["Per-event available capacity", "1.5 kW"],
            ["Capacity on 50% of event days", "2.0 kW"],
            ["Capacity on 90% of event days", "1.0 kW"],
            ["Evening self-use displaced, per event", "2.3 kWh"],
            ["Evening self-use displaced, value per year", "£8"],
        ]
        assert "gross of the evening self-use an event displaces" in report
        assert "£0 for a home simulated without one" in report
        assert "is one event window's figure" not in report

    def test_with_several_event_windows_no_per_window_figure_is_summed(self) -> None:
        income = _events_income(annual_income_gbp=_TWO_WINDOWS.annual_income_gbp, at_events=_TWO_WINDOWS)

        report = _report(grid_services=income)

        for label in (
            "Per-event available capacity",
            "Capacity on 50% of event days",
            "Capacity on 90% of event days",
            "Evening self-use displaced, per event",
        ):
            assert row_cells(report, _WINDOW_HEADING, label) == ["—"], label
        assert row_cells(report, _WINDOW_HEADING, "Evening self-use displaced, value per year") == ["£10"]
        assert "is one event window's figure" in report

    def test_each_modes_column_books_its_own_projections_first_and_last_year(self) -> None:
        physics = make_fleet_projection([(0, 20.0), (12, 18.0), (24, 15.0)], asset_life_years=25)
        spreadsheet = make_fleet_projection([(0, 30.0), (6, 28.0), (12, 25.0), (24, 21.0)], asset_life_years=25)

        report = _report(*_both_modes(physics, spreadsheet), grid_services=_events_income())

        assert table_rows(report, _BOOKED_HEADING) == [
            ["Year", "Physics", _SPREADSHEET_AT_70],
            ["Year 1", "£20", "£30"],
            ["Year 25", "£15", "£21"],
        ]

    def test_sections_without_projections_book_no_table(self) -> None:
        report = _report(grid_services=_events_income())

        assert _SECTION_HEADING in report.splitlines()
        assert _BOOKED_HEADING not in report

    def test_projections_over_different_asset_lives_are_refused_naming_each_modes_years(self) -> None:
        physics = make_fleet_projection([(0, 20.0), (12, 18.0), (24, 15.0)], asset_life_years=25)
        spreadsheet = make_fleet_projection([(0, 20.0), (10, 18.0), (19, 15.0)], asset_life_years=20)

        with pytest.raises(ValueError) as refused:
            _report(*_both_modes(physics, spreadsheet), grid_services=_events_income())

        assert "'SIMULATED': 25" in str(refused.value)
        assert "'OVERRIDE': 20" in str(refused.value)

    def test_it_renders_between_the_project_economics_and_the_cost_recovery_analysis(self) -> None:
        section = make_assumption_section(
            projection=make_fleet_projection([(0, 20.0), (12, 18.0), (24, 15.0)], asset_life_years=25),
            economics=make_project_economics(),
            cost_recovery=make_cost_recovery_solution(own_use_rate_pence_per_kwh=15.0),
        )

        report = _report(section, grid_services=_events_income())

        assert (
            report.index("## Project Economics")
            < report.index(_SECTION_HEADING)
            < report.index("## Cost-Recovery Analysis")
        )

    def test_a_report_without_grid_services_has_no_section(self) -> None:
        assert _SECTION_HEADING not in _report(grid_services=None)


_CENTRAL = FlexBlock(GridServicesBand.CENTRAL)


class TestFlexBlockGridServicesRow:
    """The flexibility-value block reads the booked grid-services income, or labels the consulting band not booked."""

    def test_its_grid_services_row_is_the_booked_income_per_battery_home_and_per_kw(self) -> None:
        report = _report(grid_services=_flat_income(), flex=_CENTRAL)

        assert "| Grid services (booked) | £10 | £4.0/kW |" in report.splitlines()
        assert "| **Headline total** | **£260** | — |" in report.splitlines()
        assert row_cells(report, _FLEX_HEADING, "Time-shift (arbitrage)") == ["£250", "—"]

    def test_with_no_battery_home_the_booked_row_reads_a_dash_and_the_headline_is_the_time_shift(self) -> None:
        income = _flat_income(annual_income_gbp=0.0, battery_homes=0, battery_discharge_kw=0.0)

        report = _report(grid_services=income, flex=_CENTRAL)

        assert "| Grid services (booked) | — | — |" in report.splitlines()
        assert "| **Headline total** | **£250** | — |" in report.splitlines()

    def test_with_no_pricing_its_row_is_the_consulting_band_labelled_not_booked(self) -> None:
        report = _report(grid_services=None, flex=_CENTRAL)

        assert row_cells(
            report,
            _FLEX_HEADING,
            "Grid services (consulting planning band, not booked: the scenario prices no grid services)",
        ) == ["£30", "£12.0/kW"]
        assert "| **Headline total** | **£280** | — |" in report.splitlines()
        assert "£12.0/kW-discharge/yr" in report

    @pytest.mark.parametrize("income", [pytest.param(_flat_income(), id="booked"), pytest.param(None, id="not-booked")])
    def test_it_names_its_band_and_cites_the_flexibility_document(self, income: GridServicesIncome | None) -> None:
        report = _report(grid_services=income, flex=_CENTRAL)

        assert "Band: **central**" in report.splitlines()
        assert "PRD §6" not in report
        assert "docs/flexibility-buildability.md" in report

    def test_its_consulting_figures_are_its_bands(self) -> None:
        assert _CENTRAL.consulting is FLEX_VALUE_BANDS[GridServicesBand.CENTRAL]

    def test_it_holds_the_band_a_word_names(self) -> None:
        assert FlexBlock("high").band is GridServicesBand.HIGH

    def test_it_refuses_a_word_naming_no_band_naming_its_field_the_bands_and_the_word(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            FlexBlock("medium")

        assert str(refused.value) == "FlexBlock.band must be one of low, central, high, got 'medium'"
