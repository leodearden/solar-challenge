# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the grid-services events pricing of a fleet under each participation.

An observed fleet is priced from the firm spare capacity its own dispatch leaves, as it was before a fleet
could be enrolled: TestObservedPricesAsBefore pins those figures as literals measured before dispatched
pricing existed.  Under both participations the breakdown reports the battery export an event's window
holds (TestBatteryExportPerEvent).  Pricing refuses a fleet whose battery homes carry other event windows
than its participation gives them (TestPricingRefusesAMismatchedEnrolment, PRD
docs/prds/event-dispatch-and-battery-sizing.md §9 B10).  A dispatched fleet is priced from the delivery
metered on its drawn event days: under the capacity baseline, its battery homes' whole in-window discharge
(TestCapacityMetering, §9 B8); under the operational baseline, the fall in their net import below its mean
over the nearest eligible days with no event (TestOperationalMetering, §9 B9).
"""

import dataclasses
import warnings
from collections.abc import Callable, Mapping
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetResults
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    OPERATIONAL_BASELINE_DAYS,
    EventParticipation,
    EventWindow,
    GridServicesEventsConfig,
    compute_grid_services_at_events,
    drawn_event_days,
    enrolled_event_windows,
)
from solar_challenge.home import HomeConfig, SimulationResults
from tests._calendar_dates import every_date
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


_JANUARY = (date(2024, 1, 1), date(2024, 1, 31))
"""January 2024: 23 weekdays, on 3 of which the default window's 12 events a year fall."""

_DISPATCHED = GridServicesEventsConfig(participation=EventParticipation.DISPATCHED)
_OBSERVED = GridServicesEventsConfig()

_PRICINGS = [
    pytest.param(compute_grid_services_at_events, id="breakdown"),
    pytest.param(lambda fleet, cfg: cfg.annual_income_gbp(fleet), id="annual-income"),
]
"""Each public pricing of a fleet under an events configuration."""

Pricing = Callable[[FleetResults, GridServicesEventsConfig], object]


def _january(**series: pd.Series) -> SimulationResults:
    """make_sim_results over January 2024, hourly, with *series* in place of its own."""
    return dataclasses.replace(make_sim_results(days=31, first_day=_JANUARY[0]), **series)


_BATTERY_HOMES = (
    dataclasses.replace(make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)), name="small-battery"),
    dataclasses.replace(
        make_home_config(battery_config=BatteryConfig(capacity_kwh=10.0, max_discharge_kw=3.0)), name="large-battery"
    ),
)
_PV_ONLY_HOME = dataclasses.replace(make_home_config(), name="pv-only")


def _enrolled(home: HomeConfig, enrolled_under: Optional[GridServicesEventsConfig], sim: SimulationResults) -> HomeConfig:
    """*home*, its battery carrying the windows enrolled_event_windows gives *enrolled_under* over *sim*'s days, or none when it is None."""
    battery = home.battery_config
    assert battery is not None
    windows = () if enrolled_under is None else enrolled_event_windows(enrolled_under, sim.window)
    return dataclasses.replace(home, battery_config=dataclasses.replace(battery, event_discharge=windows))


def _enrolled_fleet(
    enrolled_under: Optional[GridServicesEventsConfig], *battery_results: SimulationResults
) -> FleetResults:
    """Each of *battery_results* on _BATTERY_HOMES' home at its position, enrolled under *enrolled_under*, then a PV-only home over January."""
    pv_only = _january()
    return make_fleet_results_of(
        [*battery_results, pv_only],
        homes=[
            *(_enrolled(home, enrolled_under, sim) for home, sim in zip(_BATTERY_HOMES, battery_results, strict=False)),
            _PV_ONLY_HOME,
        ],
    )


def _iso_days(cfg: GridServicesEventsConfig) -> list[str]:
    """The ISO dates of the days *cfg*'s first window draws over January 2024."""
    return [day.isoformat() for day in drawn_event_days(cfg.event_windows[0], every_date(*_JANUARY), cfg.event_day_seed, position=0)]


class TestPricingRefusesAMismatchedEnrolment:
    """§9 B10: each pricing refuses a battery home whose event windows its participation would not give it, naming the participation, the home, and the days expected and found."""

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_a_dispatched_pricing_refuses_a_battery_home_that_is_not_enrolled(self, price: Pricing) -> None:
        with pytest.raises(ConfigurationError) as refused:
            price(_enrolled_fleet(None, _january(), _january()), _DISPATCHED)

        message = str(refused.value)
        assert "participation is dispatched" in message
        assert "home 0 'small-battery'" in message
        assert all(day in message for day in _iso_days(_DISPATCHED)), message
        assert "carries no event window" in message

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_an_observed_pricing_refuses_an_enrolled_battery_home(self, price: Pricing) -> None:
        with pytest.raises(ConfigurationError) as refused:
            price(_enrolled_fleet(_DISPATCHED, _january(), _january()), _OBSERVED)

        message = str(refused.value)
        assert "participation is observed" in message
        assert "home 0 'small-battery'" in message
        assert "expects no event window" in message
        assert all(day in message for day in _iso_days(_DISPATCHED)), message

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_a_dispatched_pricing_refuses_a_home_enrolled_on_other_days(self, price: Pricing) -> None:
        reseeded = dataclasses.replace(_DISPATCHED, event_day_seed=5)
        assert _iso_days(reseeded) != _iso_days(_DISPATCHED)

        with pytest.raises(ConfigurationError) as refused:
            price(_enrolled_fleet(reseeded, _january(), _january()), _DISPATCHED)

        message = str(refused.value)
        assert "participation is dispatched" in message
        assert all(day in message for day in [*_iso_days(_DISPATCHED), *_iso_days(reseeded)]), message

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_a_correctly_enrolled_dispatched_fleet_with_a_pv_only_home_prices(self, price: Pricing) -> None:
        price(_enrolled_fleet(_DISPATCHED, _january(), _january()), _DISPATCHED)

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_a_pv_only_home_never_trips_the_check(self, price: Pricing) -> None:
        price(_enrolled_fleet(_DISPATCHED), _DISPATCHED)
        price(_enrolled_fleet(_DISPATCHED), _OBSERVED)

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_an_observed_fleet_with_no_window_prices(self, price: Pricing) -> None:
        price(_enrolled_fleet(None, _january(), _january()), _OBSERVED)

    def test_an_observed_annual_income_still_reads_no_step_length(self) -> None:
        index = pd.DatetimeIndex(
            ["2024-01-15 16:00", "2024-01-15 17:00", "2024-01-15 17:30", "2024-01-15 19:00"], tz="Europe/London"
        )
        zeros = pd.Series(0.0, index=index)
        uneven = SimulationResults(
            generation=zeros,
            demand=zeros,
            self_consumption=zeros,
            battery_charge=zeros,
            battery_discharge=zeros,
            battery_soc=pd.Series(3.5, index=index),
            grid_import=zeros,
            grid_export=zeros,
            import_cost=zeros,
            export_revenue=zeros,
            tariff_rate=zeros,
        )
        fleet = make_fleet_results_of([uneven], homes=[_enrolled(_BATTERY_HOMES[0], None, _january())])

        # min(2.5 kW, (3.5 − 0.5) kWh / 3 h) = 1.0 kW on its one event day, at £9.972 per kW.
        assert _OBSERVED.annual_income_gbp(fleet) == pytest.approx(9.972)


_CAPACITY = GridServicesEventsConfig(participation=EventParticipation.DISPATCHED, delivery_baseline="capacity")
_CENTRAL_GBP_PER_KW = (1.00 * 12 + 0.6 * 3 * 0.060 * 12) * 0.75
"""The default window's central rates per kW booked: availability £1.00 × 12 events, utilisation 0.6 × 3 h × £0.060/kWh × 12, net of the 25% aggregator share; £9.972."""

_JANUARY_WEEKEND_MORNINGS = EventWindow(months=(1,), weekdays=(5, 6), hours=(8,), events_per_year=4, event_hours=1.0)


def _drawn(cfg: GridServicesEventsConfig, position: int = 0) -> tuple[date, ...]:
    """The days *cfg*'s window at *position* draws over January 2024."""
    return drawn_event_days(cfg.event_windows[position], every_date(*_JANUARY), cfg.event_day_seed, position=position)


def _kw_series(
    kw_by_window_day: Mapping[tuple[EventWindow, date], float],
    *,
    elsewhere_kw: float,
    index: Optional[pd.DatetimeIndex] = None,
) -> pd.Series:
    """*index*, January 2024 hourly by default: each (window, day)'s kW on that day's rows in the window, *elsewhere_kw* in every other row."""
    index = _january().generation.index if index is None else index
    values = np.full(len(index), elsewhere_kw)
    dates = index.date
    for (window, day), kw in kw_by_window_day.items():
        values[window.mask(index).to_numpy() & (dates == day)] = kw
    return pd.Series(values, index=index)


def _metered_home(
    discharge_kw: Mapping[tuple[EventWindow, date], float],
    export_kw: Mapping[tuple[EventWindow, date], float] | None = None,
) -> SimulationResults:
    """January 2024's results of a battery home discharging *discharge_kw* and exporting *export_kw* in the windows' rows of their days, and 7.0 kW and 6.0 kW in every other row, which no metering may count."""
    return _january(
        battery_discharge=_kw_series(discharge_kw, elsewhere_kw=7.0),
        battery_export=_kw_series(export_kw or {}, elsewhere_kw=6.0),
    )


class TestCapacityMetering:
    """§9 B8: under the capacity baseline a drawn day delivers the battery homes' in-window discharge over the event's hours, D(d) = Σ_home Σ_{t∈d∩w} discharge(t)·Δt / h."""

    def _fleet(self) -> tuple[FleetResults, list[float], list[float]]:
        """Two battery homes discharging a_k = 1 + k/2 and b_k = (k + 1)/4 kW, and exporting k/10 and 0.2 kW, through drawn day k's window, of January's three drawn days; and each D(d_k) = a_k + b_k, 1.25, 2.0 and 2.75 kW, and in-window export 3·(k/10 + 0.2) kWh."""
        days = _drawn(_CAPACITY)
        assert len(days) == 3
        home_a = _metered_home(
            {(_WINDOW, day): 1.0 + k / 2 for k, day in enumerate(days)},
            {(_WINDOW, day): k / 10 for k, day in enumerate(days)},
        )
        home_b = _metered_home(
            {(_WINDOW, day): (k + 1) / 4 for k, day in enumerate(days)},
            {(_WINDOW, day): 0.2 for day in days},
        )
        delivered = [(1.0 + k / 2) + (k + 1) / 4 for k in range(len(days))]
        exported = [3 * (k / 10 + 0.2) for k in range(len(days))]
        return _enrolled_fleet(_CAPACITY, home_a, home_b), delivered, exported

    def test_the_booked_delivery_is_the_mean_over_the_drawn_days(self) -> None:
        fleet, delivered, _ = self._fleet()

        breakdown = compute_grid_services_at_events(fleet, _CAPACITY)

        assert breakdown.per_window_avail_kw == pytest.approx((sum(delivered) / len(delivered),))

    def test_its_reliability_figures_rank_the_drawn_days_deliveries(self) -> None:
        fleet, delivered, _ = self._fleet()
        assert delivered == pytest.approx([1.25, 2.0, 2.75])

        breakdown = compute_grid_services_at_events(fleet, _CAPACITY)

        assert breakdown.per_window_avail_p50_kw == pytest.approx((2.0,)), "the ⌈0.5·3⌉ = 2nd largest"
        assert breakdown.per_window_avail_p90_kw == pytest.approx((1.25,)), "the ⌈0.9·3⌉ = 3rd largest"

    def test_the_income_books_the_mean_delivery_at_the_central_rates(self) -> None:
        fleet, delivered, _ = self._fleet()

        breakdown = compute_grid_services_at_events(fleet, _CAPACITY)

        assert breakdown.annual_income_gbp == pytest.approx(sum(delivered) / len(delivered) * _CENTRAL_GBP_PER_KW)
        assert breakdown.annual_income_gbp == _CAPACITY.annual_income_gbp(fleet)
        assert sum(breakdown.per_window_income_gbp) == breakdown.annual_income_gbp

    def test_the_battery_export_per_event_is_the_mean_in_window_export_on_the_drawn_days(self) -> None:
        fleet, _, exported = self._fleet()

        breakdown = compute_grid_services_at_events(fleet, _CAPACITY)

        assert breakdown.per_window_battery_export_kwh_per_event == pytest.approx((sum(exported) / len(exported),))

    def test_no_displaced_self_use_is_reported(self) -> None:
        fleet, _, _ = self._fleet()

        breakdown = compute_grid_services_at_events(fleet, _CAPACITY)

        assert breakdown.per_window_displaced_self_use_kwh_per_event == ()
        assert breakdown.per_window_displaced_import_gbp_per_year == ()

    def test_each_window_is_metered_on_the_days_drawn_at_its_own_position(self) -> None:
        cfg = dataclasses.replace(_CAPACITY, event_windows=(_WINDOW, _JANUARY_WEEKEND_MORNINGS))
        evenings, mornings = _drawn(cfg, 0), _drawn(cfg, 1)
        assert evenings and mornings
        home = _metered_home(
            {
                **{(_WINDOW, day): 1.0 + k for k, day in enumerate(evenings)},
                **{(_JANUARY_WEEKEND_MORNINGS, day): 2.0 + k for k, day in enumerate(mornings)},
            }
        )

        breakdown = compute_grid_services_at_events(_enrolled_fleet(cfg, home), cfg)

        assert breakdown.per_window_avail_kw == pytest.approx(
            (
                sum(1.0 + k for k in range(len(evenings))) / len(evenings),
                sum(2.0 + k for k in range(len(mornings))) / len(mornings),
            )
        )

    def test_a_window_that_draws_no_day_prices_0_and_warns_once_naming_it_to_the_caller(self) -> None:
        june = EventWindow(months=(6,), weekdays=(0, 1, 2, 3, 4), hours=(17,), events_per_year=6, event_hours=1.0)
        cfg = dataclasses.replace(_CAPACITY, event_windows=(june,))
        fleet = _enrolled_fleet(cfg, _metered_home({}), _metered_home({}))
        assert fleet.home_configs[0].battery_config is not None
        assert fleet.home_configs[0].battery_config.event_discharge == ()

        with warnings.catch_warnings(record=True) as breakdown_warnings:
            warnings.simplefilter("always")
            breakdown = compute_grid_services_at_events(fleet, cfg)
        with warnings.catch_warnings(record=True) as income_warnings:
            warnings.simplefilter("always")
            income = cfg.annual_income_gbp(fleet)

        assert breakdown.per_window_avail_kw == (0.0,)
        assert breakdown.annual_income_gbp == income == 0.0
        for record in (breakdown_warnings, income_warnings):
            texts = [(str(w.message), w.filename) for w in record if issubclass(w.category, UserWarning)]
            assert len(texts) == 1, texts
            assert "months=(6,)" in texts[0][0]
            assert texts[0][1] == __file__


_OPERATIONAL = GridServicesEventsConfig(participation=EventParticipation.DISPATCHED)
_ONE_EVENT_A_WINTER = EventWindow(
    months=(1, 2), weekdays=(0, 1, 2, 3, 4), hours=(17,), events_per_year=1, event_hours=1.0
)
"""January and February weekdays at 17:00, one event a year: six winter weeks, 30 of their 44 weekdays, draw one day."""
_SIX_WINTER_WEEKS = (date(2024, 1, 1), date(2024, 2, 11))


def _importing_home(
    window: EventWindow,
    import_kw: Mapping[date, float],
    export_kw: Mapping[date, float],
    period: tuple[date, date] = _JANUARY,
) -> SimulationResults:
    """A battery home over *period*, hourly, importing *import_kw* and exporting *export_kw* in *window*'s rows of each day they give; 500 kW import in every other row, outside the window or on a day *import_kw* does not give, and no export."""
    first, last = period
    base = make_sim_results(days=(last - first).days + 1, first_day=first)
    index = base.generation.index
    return dataclasses.replace(
        base,
        grid_import=_kw_series({(window, day): kw for day, kw in import_kw.items()}, elsewhere_kw=500.0, index=index),
        grid_export=_kw_series({(window, day): kw for day, kw in export_kw.items()}, elsewhere_kw=0.0, index=index),
    )


def _eligible(window: EventWindow, period: tuple[date, date]) -> list[date]:
    """The days of *period* whose month and weekday *window* admits."""
    return [day for day in every_date(*period) if day.month in window.months and day.weekday() in window.weekdays]


class TestOperationalMetering:
    """§9 B9: under the operational baseline a drawn day delivers D(d) = max(0, B(d) − N(d)), N the battery homes' summed mean in-window net import and B its mean over the ten nearest eligible days with no event."""

    def test_a_drawn_day_delivers_its_fall_in_net_import_below_the_non_event_days(self) -> None:
        drawn = _drawn(_OPERATIONAL)
        quiet = [day for day in _eligible(_WINDOW, _JANUARY) if day not in drawn]
        imports = {**dict.fromkeys(quiet, 0.8), **dict.fromkeys(drawn, 0.0)}
        exports = dict.fromkeys(drawn, 1.2)
        home = _importing_home(_WINDOW, imports, exports)

        breakdown = compute_grid_services_at_events(_enrolled_fleet(_OPERATIONAL, home, home), _OPERATIONAL)

        # Each of two homes: 0.8 kW imported on a quiet day, 1.2 kW exported on a drawn one.
        assert breakdown.per_window_avail_kw == pytest.approx((2 * (0.8 + 1.2),))
        assert breakdown.annual_income_gbp == pytest.approx(2 * (0.8 + 1.2) * _CENTRAL_GBP_PER_KW)
        assert breakdown.annual_income_gbp == _OPERATIONAL.annual_income_gbp(_enrolled_fleet(_OPERATIONAL, home, home))

    def test_the_baseline_is_the_ten_nearest_eligible_days_before_the_drawn_day(self) -> None:
        cfg = dataclasses.replace(_OPERATIONAL, event_windows=(_ONE_EVENT_A_WINTER,), event_day_seed=2)
        eligible = _eligible(_ONE_EVENT_A_WINTER, _SIX_WINTER_WEEKS)
        (drawn,) = drawn_event_days(_ONE_EVENT_A_WINTER, every_date(*_SIX_WINTER_WEEKS), 2, position=0)
        before = [day for day in eligible if day < drawn]
        assert drawn == date(2024, 2, 5) and len(before) == 25
        imports = {**dict.fromkeys(eligible, 50.0), **dict.fromkeys(before[-10:], 1.0), drawn: 0.0}
        home = _importing_home(_ONE_EVENT_A_WINTER, imports, {drawn: 0.5}, _SIX_WINTER_WEEKS)

        breakdown = compute_grid_services_at_events(_enrolled_fleet(cfg, home, home), cfg)

        assert breakdown.per_window_avail_kw == pytest.approx((2 * (1.0 + 0.5),))

    def test_fewer_than_ten_days_before_are_completed_with_the_nearest_after(self) -> None:
        cfg = dataclasses.replace(_OPERATIONAL, event_windows=(_ONE_EVENT_A_WINTER,), event_day_seed=11)
        eligible = _eligible(_ONE_EVENT_A_WINTER, _SIX_WINTER_WEEKS)
        (drawn,) = drawn_event_days(_ONE_EVENT_A_WINTER, every_date(*_SIX_WINTER_WEEKS), 11, position=0)
        before = [day for day in eligible if day < drawn]
        after = [day for day in eligible if day > drawn]
        assert drawn == date(2024, 1, 5) and len(before) == 4
        imports = {**dict.fromkeys(eligible, 50.0), **dict.fromkeys([*before, *after[:6]], 1.0), drawn: 0.0}
        home = _importing_home(_ONE_EVENT_A_WINTER, imports, {drawn: 0.5}, _SIX_WINTER_WEEKS)

        breakdown = compute_grid_services_at_events(_enrolled_fleet(cfg, home, home), cfg)

        assert breakdown.per_window_avail_kw == pytest.approx((2 * (1.0 + 0.5),))

    def test_another_window_s_drawn_day_is_never_a_baseline_day(self) -> None:
        mornings = dataclasses.replace(_ONE_EVENT_A_WINTER, hours=(8,))
        cfg = dataclasses.replace(_OPERATIONAL, event_windows=(_ONE_EVENT_A_WINTER, mornings), event_day_seed=0)
        dates = every_date(*_SIX_WINTER_WEEKS)
        (drawn,) = drawn_event_days(_ONE_EVENT_A_WINTER, dates, 0, position=0)
        (morning_event,) = drawn_event_days(mornings, dates, 0, position=1)
        eligible = _eligible(_ONE_EVENT_A_WINTER, _SIX_WINTER_WEEKS)
        assert morning_event in [day for day in eligible if day < drawn][-10:]
        quiet_before = [day for day in eligible if day < drawn and day != morning_event]
        imports = {**dict.fromkeys(eligible, 50.0), **dict.fromkeys(quiet_before[-10:], 1.0), drawn: 0.0}
        home = _importing_home(_ONE_EVENT_A_WINTER, imports, {drawn: 0.5}, _SIX_WINTER_WEEKS)

        breakdown = compute_grid_services_at_events(_enrolled_fleet(cfg, home, home), cfg)

        assert breakdown.per_window_avail_kw[0] == pytest.approx(2 * (1.0 + 0.5))

    def test_a_drawn_day_importing_more_than_its_baseline_delivers_0(self) -> None:
        drawn = _drawn(_OPERATIONAL)
        quiet = [day for day in _eligible(_WINDOW, _JANUARY) if day not in drawn]
        home = _importing_home(_WINDOW, {**dict.fromkeys(quiet, 0.8), **dict.fromkeys(drawn, 1.8)}, {})

        breakdown = compute_grid_services_at_events(_enrolled_fleet(_OPERATIONAL, home, home), _OPERATIONAL)

        assert breakdown.per_window_avail_kw == (0.0,)
        assert breakdown.annual_income_gbp == 0.0

    def test_the_baseline_reads_the_ten_days_the_prd_sets(self) -> None:
        assert OPERATIONAL_BASELINE_DAYS == 10

    @pytest.mark.parametrize("price", _PRICINGS)
    def test_a_period_whose_every_eligible_day_is_drawn_has_no_baseline_and_is_refused(self, price: Pricing) -> None:
        every_day = EventWindow(months=(1,), weekdays=tuple(range(7)), hours=(17,), events_per_year=366, event_hours=1.0)
        cfg = dataclasses.replace(_OPERATIONAL, event_windows=(every_day,))
        assert _drawn(cfg) == every_date(*_JANUARY)

        with pytest.raises(ConfigurationError) as refused:
            price(_enrolled_fleet(cfg, _january(), _january()), cfg)

        assert "months=(1,)" in str(refused.value)
        assert "operational" in str(refused.value)
