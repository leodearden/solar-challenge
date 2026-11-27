# SPDX-License-Identifier: AGPL-3.0-or-later
"""A scenario whose events configuration is dispatched enrols each battery home in its drawn event windows.

docs/prds/event-dispatch-and-battery-sizing.md §5.3 has ScenarioConfig.simulated_homes resolve the
events configuration's windows to drawn days and give every battery home the same windows and the
site export limit; §9 B6 is the enrolment pinned here, B7 the site limit seen through it, and an
observed configuration, the default, leaves the homes as they were.
"""

import dataclasses
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import ScenarioConfig
from solar_challenge.dispatch import EventDischargeWindow
from solar_challenge.errors import ConfigurationError
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    EventParticipation,
    EventWindow,
    FlatGridServices,
    GridServicesEventsConfig,
    GridServicesModel,
    NoGridServices,
    drawn_event_days,
)
from solar_challenge.home import HomeConfig, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._exporting_runs import RUN_DAYS, home_of_the_runs
from tests._synthetic_weather import weather_for

_EVERY_WEEKDAY = (0, 1, 2, 3, 4, 5, 6)
_WINTER_EVENINGS = DEFAULT_EVENT_WINDOWS[0]
_SUMMER_WEEKEND_MIDDAYS = EventWindow(
    months=(6, 7, 8), weekdays=(5, 6), hours=(12, 13), events_per_year=4, event_hours=2.0
)
_SEED = 3

_HOMES = (
    HomeConfig(
        pv_config=PVConfig(capacity_kw=4.0),
        load_config=LoadConfig(annual_consumption_kwh=3400, use_stochastic=False),
        battery_config=BatteryConfig(capacity_kwh=5.0),
        name="small-battery",
    ),
    HomeConfig(
        pv_config=PVConfig(capacity_kw=6.0),
        load_config=LoadConfig(annual_consumption_kwh=4200, use_stochastic=False),
        battery_config=BatteryConfig(capacity_kwh=10.0, max_charge_kw=5.0, max_discharge_kw=5.0),
        name="large-battery",
    ),
    HomeConfig(
        pv_config=PVConfig(capacity_kw=3.0),
        load_config=LoadConfig(annual_consumption_kwh=2800, use_stochastic=False),
        name="pv-only",
    ),
)


def _dates(first: date, last: date) -> tuple[date, ...]:
    """Every date from *first* to *last*, both included."""
    return tuple(first + timedelta(days=offset) for offset in range((last - first).days + 1))


def _period(first: date, last: date) -> SimulationWindow:
    return SimulationWindow(first, last, ONE_MINUTE, "Europe/London")


def _dispatched(
    *,
    event_windows: tuple[EventWindow, ...] = DEFAULT_EVENT_WINDOWS,
    event_day_seed: int = 0,
    site_export_limit_kw: Optional[float] = None,
) -> GridServicesEventsConfig:
    return GridServicesEventsConfig(
        event_windows=event_windows,
        participation=EventParticipation.DISPATCHED,
        event_day_seed=event_day_seed,
        site_export_limit_kw=site_export_limit_kw,
    )


def _finance(model: GridServicesModel) -> FinanceConfig:
    return FinanceConfig(standing_charge_pence_per_day=60.0, grid_services_model=model)


def _scenario(
    finance: Optional[FinanceConfig],
    *,
    homes: tuple[HomeConfig, ...] = _HOMES,
    first: date = date(2024, 1, 1),
    last: date = date(2024, 12, 31),
    seg_rate: Optional[float] = None,
) -> ScenarioConfig:
    return ScenarioConfig(
        name="enrolment",
        period=_period(first, last),
        homes=homes,
        finance=finance,
        seg_tariff_pence_per_kwh=seg_rate,
    )


def _drawn_windows(
    windows: tuple[EventWindow, ...], first: date, last: date, seed: int
) -> tuple[EventDischargeWindow, ...]:
    """One EventDischargeWindow per window of *windows* that draws a day over *first* to *last*: the days drawn_event_days draws with *seed* at its position."""
    dates = _dates(first, last)
    drawn = (
        (window, drawn_event_days(window, dates, seed, position=position))
        for position, window in enumerate(windows)
    )
    return tuple(EventDischargeWindow(days=days, hours=window.hours) for window, days in drawn if days)


def _battery(home: HomeConfig) -> BatteryConfig:
    battery = home.battery_config
    assert isinstance(battery, BatteryConfig)
    return battery


def _without_enrolment(home: HomeConfig) -> HomeConfig:
    """*home* with its battery's event windows and site export limit put back to none."""
    if home.battery_config is None:
        return home
    return dataclasses.replace(
        home,
        battery_config=dataclasses.replace(home.battery_config, event_discharge=(), site_export_limit_kw=None),
    )


class TestADispatchedScenarioEnrolsEachBatteryHome:
    """§9 B6: every battery home is given the same drawn windows; a home with no battery is left as it is."""

    _WINDOWS = (_WINTER_EVENINGS, _SUMMER_WEEKEND_MIDDAYS)

    def _homes(self) -> tuple[HomeConfig, ...]:
        return _scenario(_finance(_dispatched(event_windows=self._WINDOWS, event_day_seed=_SEED))).simulated_homes()

    def test_every_battery_home_carries_the_windows_drawn_over_the_period(self) -> None:
        expected = _drawn_windows(self._WINDOWS, date(2024, 1, 1), date(2024, 12, 31), _SEED)
        assert len(expected) == 2

        small, large, _ = self._homes()

        assert _battery(small).event_discharge == expected
        assert _battery(large).event_discharge == expected

    def test_every_drawn_day_lies_within_the_period(self) -> None:
        small, _, _ = self._homes()

        days = [day for window in _battery(small).event_discharge for day in window.days]

        assert days
        assert all(date(2024, 1, 1) <= day <= date(2024, 12, 31) for day in days)

    def test_the_enrolment_changes_nothing_else_of_any_home(self) -> None:
        assert tuple(_without_enrolment(home) for home in self._homes()) == _HOMES

    def test_a_home_with_no_battery_is_simulated_as_stored(self) -> None:
        _, _, pv_only = self._homes()

        assert pv_only == _HOMES[2]

    def test_a_window_with_no_eligible_day_in_the_period_adds_no_window_and_is_not_refused(self) -> None:
        june = _scenario(_finance(_dispatched()), first=date(2024, 6, 1), last=date(2024, 6, 30))

        small, large, _ = june.simulated_homes()

        assert _battery(small).event_discharge == ()
        assert _battery(large).event_discharge == ()

    def test_a_new_window_redraws_the_days_over_its_own_dates(self) -> None:
        scenario = _scenario(_finance(_dispatched(event_windows=self._WINDOWS, event_day_seed=_SEED)))

        narrowed = scenario.with_window(first_day=date(2024, 1, 1), last_day=date(2024, 2, 29))

        small, _, _ = narrowed.simulated_homes()
        assert _battery(small).event_discharge == _drawn_windows(
            self._WINDOWS, date(2024, 1, 1), date(2024, 2, 29), _SEED
        )

    def test_a_seg_rate_is_filled_as_well_as_the_windows(self) -> None:
        scenario = _scenario(_finance(_dispatched(event_day_seed=_SEED)), seg_rate=15.0)

        small, _, pv_only = scenario.simulated_homes()

        assert small.seg_tariff == SEGTariff(name="", rate_pence_per_kwh=15.0)
        assert _battery(small).event_discharge == _drawn_windows(
            DEFAULT_EVENT_WINDOWS, date(2024, 1, 1), date(2024, 12, 31), _SEED
        )
        assert pv_only == dataclasses.replace(_HOMES[2], seg_tariff=SEGTariff(name="", rate_pence_per_kwh=15.0))

    def test_every_battery_home_carries_the_site_export_limit(self) -> None:
        scenario = _scenario(_finance(_dispatched(site_export_limit_kw=3.0)))

        small, large, _ = scenario.simulated_homes()

        assert _battery(small).site_export_limit_kw == 3.0
        assert _battery(large).site_export_limit_kw == 3.0


@pytest.mark.parametrize(
    "finance",
    [
        pytest.param(_finance(GridServicesEventsConfig()), id="participation-omitted"),
        pytest.param(
            _finance(GridServicesEventsConfig(participation=EventParticipation.OBSERVED, site_export_limit_kw=3.0)),
            id="observed",
        ),
        pytest.param(_finance(FlatGridServices(income_per_kw_per_year_gbp=20.0)), id="flat"),
        pytest.param(_finance(NoGridServices()), id="no-grid-services"),
        pytest.param(None, id="no-finance"),
    ],
)
@pytest.mark.parametrize("seg_rate", [pytest.param(None, id="no-seg"), pytest.param(15.0, id="seg")])
def test_a_scenario_that_is_not_dispatched_simulates_its_stored_homes(
    finance: Optional[FinanceConfig], seg_rate: Optional[float]
) -> None:
    expected = (
        _HOMES
        if seg_rate is None
        else tuple(dataclasses.replace(home, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=seg_rate)) for home in _HOMES)
    )

    homes = _scenario(finance, seg_rate=seg_rate).simulated_homes()

    assert homes == expected
    for home in homes:
        if home.battery_config is not None:
            assert home.battery_config.event_discharge == ()
            assert home.battery_config.site_export_limit_kw is None


class TestADispatchedScenarioWithNoBatteryHomeIsRefused:
    """A dispatched fleet with no battery to discharge in an event is refused at construction."""

    _PV_ONLY = (_HOMES[2],)

    @staticmethod
    def _assert_names_the_dispatched_participation(message: str) -> None:
        assert "Scenario 'enrolment'" in message
        assert "finance.grid_services_model.participation" in message
        assert "dispatched" in message

    def test_at_construction(self) -> None:
        with pytest.raises(ConfigurationError) as refused:
            _scenario(_finance(_dispatched()), homes=self._PV_ONLY)

        self._assert_names_the_dispatched_participation(str(refused.value))

    def test_when_map_homes_strips_every_battery(self) -> None:
        scenario = _scenario(_finance(_dispatched()))

        with pytest.raises(ConfigurationError) as refused:
            scenario.map_homes(lambda home: dataclasses.replace(home, battery_config=None))

        self._assert_names_the_dispatched_participation(str(refused.value))

    def test_an_observed_scenario_with_no_battery_home_is_not_refused(self) -> None:
        assert _scenario(_finance(GridServicesEventsConfig()), homes=self._PV_ONLY).simulated_homes() == self._PV_ONLY


_CLEAR_DAYS_ID = "2024-06-20_to_21-clear"
_MIDDAY_HOURS = (10, 11, 12, 13, 14)
_EVERY_JUNE_DAY = EventWindow(
    months=(6,), weekdays=_EVERY_WEEKDAY, hours=_MIDDAY_HOURS, events_per_year=30, event_hours=2.0
)
"""Eligible on every June day, 30 events a year: over two June days, 30 × 2/30 draws both."""
_SITE_EXPORT_LIMIT_KW = 3.0
"""Above the clear day's PV excess at 10:00 and 11:00, and below that excess plus the battery's 2.5 kW discharge limit."""


def test_an_enrolled_home_exports_in_its_drawn_windows_within_the_site_export_limit() -> None:
    """§9 B7 seen through the enrolment: the scenario's site export limit bounds the home's export whenever its battery exports, and the battery exports only in the drawn windows."""
    scenario = ScenarioConfig(
        name="b7",
        period=_period(date(2024, 6, 20), date(2024, 6, 21)),
        home=home_of_the_runs(),
        finance=_finance(
            _dispatched(event_windows=(_EVERY_JUNE_DAY,), site_export_limit_kw=_SITE_EXPORT_LIMIT_KW)
        ),
    )
    (home,) = scenario.simulated_homes()
    battery = _battery(home)
    assert battery.event_discharge == (
        EventDischargeWindow(days=(date(2024, 6, 20), date(2024, 6, 21)), hours=_MIDDAY_HOURS),
    )
    weather, start, end = RUN_DAYS[_CLEAR_DAYS_ID]

    results = simulate_home(
        home, pd.Timestamp(start), pd.Timestamp(end), validate_balance=True, weather=weather_for(home, weather)
    )

    export = results.battery_export
    assert export is not None
    exporting = export > 0
    assert exporting.any()
    assert (results.grid_export[exporting] <= _SITE_EXPORT_LIMIT_KW + 1e-9).all()
    shortfall = (results.demand - results.generation).clip(lower=0)
    assert (export[exporting] < battery.max_discharge_kw - shortfall[exporting] - 1e-9).any()
    index = export.index
    assert isinstance(index, pd.DatetimeIndex)
    local = index if index.tz is None else index.tz_convert("Europe/London")
    in_the_windows = pd.Index(local.date).isin(battery.event_discharge[0].days) & local.hour.isin(_MIDDAY_HOURS)
    assert not exporting[~in_the_windows].any()
