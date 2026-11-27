# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for gridservices.drawn_event_days: the seeded draw of an event window's days over a simulated period.

The draw counts a window's events in proportion to the share of each calendar year's eligible days the period
holds, rounded half up and kept between 1 and the eligible days, and picks them with a generator of its own. The
tests assert those properties, never the dates a seed picks, so they hold whatever stream numpy's generator gives.

gridservices.enrolled_event_windows resolves an events configuration's windows over a period to the
EventDischargeWindows enrolment gives each battery home and pricing expects them to carry.
"""

import random
from collections.abc import Iterator
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from solar_challenge.dispatch import EventDischargeWindow
from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import (
    DEFAULT_EVENT_WINDOWS,
    EventWindow,
    GridServicesEventsConfig,
    drawn_event_days,
    enrolled_event_windows,
)
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._calendar_dates import every_date

WINDOW = DEFAULT_EVENT_WINDOWS[0]
"""November to February weekdays, 12 events a year: 2024 has 87 such days and 2025 has 86."""

_EVERY_WEEKDAY = (0, 1, 2, 3, 4, 5, 6)


_YEAR_2024 = every_date(date(2024, 1, 1), date(2024, 12, 31))


def _every_day_window(months: tuple[int, ...], events_per_year: int) -> EventWindow:
    return EventWindow(
        months=months, weekdays=_EVERY_WEEKDAY, hours=(17,), events_per_year=events_per_year, event_hours=1.0
    )


@pytest.fixture
def global_generators_restored() -> Iterator[None]:
    """Put numpy's and the stdlib's global generators back as the test found them, so a test that seeds them leaves no later test on its worker a fixed stream."""
    numpy_state, stdlib_state = np.random.get_state(), random.getstate()
    yield
    np.random.set_state(numpy_state)
    random.setstate(stdlib_state)


class TestTheDaysDrawn:
    """A window draws its events' days from the period's eligible days, the same days for the same arguments."""

    def test_a_full_year_draws_the_window_s_events_per_year_on_distinct_eligible_days_in_order(self) -> None:
        days = drawn_event_days(WINDOW, _YEAR_2024, 0, position=0)

        assert len(days) == 12
        assert len(set(days)) == 12
        assert list(days) == sorted(days)
        assert all(type(day) is date for day in days)
        assert all(day.year == 2024 and day.month in (11, 12, 1, 2) and day.weekday() < 5 for day in days)

    def test_the_same_arguments_draw_the_same_days(self) -> None:
        assert drawn_event_days(WINDOW, _YEAR_2024, 0, position=0) == drawn_event_days(
            WINDOW, _YEAR_2024, 0, position=0
        )

    def test_another_seed_draws_other_days(self) -> None:
        assert drawn_event_days(WINDOW, _YEAR_2024, 1, position=0) != drawn_event_days(
            WINDOW, _YEAR_2024, 0, position=0
        )

    def test_another_position_draws_other_days(self) -> None:
        assert drawn_event_days(WINDOW, _YEAR_2024, 0, position=1) != drawn_event_days(
            WINDOW, _YEAR_2024, 0, position=0
        )

    def test_the_days_are_read_as_a_set_of_dates(self) -> None:
        in_order = drawn_event_days(WINDOW, _YEAR_2024, 0, position=0)

        assert drawn_event_days(WINDOW, list(reversed(_YEAR_2024)), 0, position=0) == in_order
        assert drawn_event_days(WINDOW, [*_YEAR_2024, date(2024, 1, 15)], 0, position=0) == in_order

    @pytest.mark.usefixtures("global_generators_restored")
    def test_the_draw_reads_and_advances_neither_global_generator(self) -> None:
        np.random.seed(11)
        random.seed(11)
        undisturbed = (np.random.random(), random.random())

        np.random.seed(11)
        random.seed(11)
        drawn_event_days(WINDOW, _YEAR_2024, 0, position=0)

        assert (np.random.random(), random.random()) == undisturbed


class TestHowManyDaysAreDrawn:
    """The count is the window's events per year times the share of each year's eligible days the period holds, rounded half up, from 1 to the eligible days."""

    def test_two_months_draw_their_share_of_the_year_s_events(self) -> None:
        days = drawn_event_days(WINDOW, every_date(date(2024, 1, 1), date(2024, 2, 29)), 0, position=0)

        assert len(days) == 6
        assert all(day.year == 2024 and day.month in (1, 2) and day.weekday() < 5 for day in days)

    def test_two_full_years_draw_each_year_s_events(self) -> None:
        days = drawn_event_days(WINDOW, every_date(date(2024, 1, 1), date(2025, 12, 31)), 0, position=0)

        assert len(days) == 24

    def test_each_year_s_days_count_over_that_year_s_own_eligible_days(self) -> None:
        february_2024_and_2025 = every_date(date(2024, 2, 1), date(2025, 2, 28))

        days = drawn_event_days(_every_day_window((2,), events_per_year=28), february_2024_and_2025, 0, position=0)

        # 28 × 29/29 + 28 × 28/28; over 2024's 29 eligible days alone, 28 × 57/29 would round to 55.
        assert len(days) == 56

    def test_a_period_across_new_year_counts_each_side_over_its_own_year(self) -> None:
        december_2023_and_january_2024 = every_date(date(2023, 12, 1), date(2024, 1, 31))
        winter_weekends = EventWindow(months=(12, 1), weekdays=(5, 6), hours=(17,), events_per_year=10, event_hours=1.0)

        days = drawn_event_days(winter_weekends, december_2023_and_january_2024, 0, position=0)

        # 10 × (10/19 + 8/17) = 9.97: 2023 has 19 such weekend days, 10 of them in December, and 2024 17, 8 in
        # January; over 2023's alone 10 × 18/19 would round to 9, and over 2024's alone 10 × 18/17 to 11.
        assert len(days) == 10
        assert all(
            (day.year, day.month) in ((2023, 12), (2024, 1)) and day.weekday() in (5, 6) for day in days
        )

    def test_a_half_event_rounds_up(self) -> None:
        window = _every_day_window((1, 2), events_per_year=5)

        days = drawn_event_days(window, every_date(date(2024, 1, 1), date(2024, 1, 30)), 0, position=0)

        assert len(days) == 3

    def test_a_period_holding_an_eligible_day_draws_at_least_one(self) -> None:
        assert drawn_event_days(WINDOW, [date(2024, 1, 15)], 0, position=0) == (date(2024, 1, 15),)

    def test_no_more_days_are_drawn_than_are_eligible(self) -> None:
        january = every_date(date(2024, 1, 1), date(2024, 1, 31))

        assert drawn_event_days(_every_day_window((1,), events_per_year=40), january, 0, position=0) == january

    def test_a_period_with_no_eligible_day_draws_none(self) -> None:
        assert drawn_event_days(WINDOW, every_date(date(2024, 6, 1), date(2024, 6, 30)), 0, position=0) == ()


class TestRefusals:
    """Each argument it cannot read is refused naming it."""

    def test_a_moment_among_the_days_is_refused_naming_its_position(self) -> None:
        moment = datetime(2024, 1, 16)

        with pytest.raises(ConfigurationError) as exc_info:
            drawn_event_days(WINDOW, [date(2024, 1, 15), moment], 0, position=0)

        assert str(exc_info.value) == f"days[1] must be a date, got {moment!r}"

    @pytest.mark.parametrize(
        ("seed", "requirement"),
        [pytest.param(-1, "at least 0", id="negative"), pytest.param(True, "a finite number", id="boolean")],
    )
    def test_a_seed_that_is_not_a_whole_number_of_at_least_0_is_refused_naming_it(
        self, seed: object, requirement: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            drawn_event_days(WINDOW, _YEAR_2024, seed, position=0)  # type: ignore[arg-type]

        assert str(exc_info.value) == f"seed must be {requirement}, got {seed!r}"

    def test_a_negative_position_is_refused_naming_it(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            drawn_event_days(WINDOW, _YEAR_2024, 0, position=-1)

        assert str(exc_info.value) == "position must be at least 0, got -1"


_JUNE_WEEKDAY_EVENINGS = EventWindow(
    months=(6,), weekdays=(0, 1, 2, 3, 4), hours=(17, 18), events_per_year=6, event_hours=2.0
)
_JANUARY_WEEKEND_MORNINGS = EventWindow(months=(1,), weekdays=(5, 6), hours=(8,), events_per_year=4, event_hours=1.0)


def _period(first: date, last: date, cadence: timedelta = ONE_MINUTE) -> SimulationWindow:
    return SimulationWindow(first, last, cadence, "Europe/London")


class TestTheWindowsAnEnrolledHomeCarries:
    """enrolled_event_windows gives one EventDischargeWindow per window that draws a day of the period, in window order."""

    _EVENTS = GridServicesEventsConfig(event_windows=(WINDOW, _JANUARY_WEEKEND_MORNINGS), event_day_seed=5)
    _JANUARY = (date(2024, 1, 1), date(2024, 1, 31))

    def test_each_window_carries_the_days_drawn_at_its_position_in_its_hours(self) -> None:
        dates = every_date(*self._JANUARY)

        assert enrolled_event_windows(self._EVENTS, _period(*self._JANUARY)) == (
            EventDischargeWindow(days=drawn_event_days(WINDOW, dates, 5, position=0), hours=WINDOW.hours),
            EventDischargeWindow(
                days=drawn_event_days(_JANUARY_WEEKEND_MORNINGS, dates, 5, position=1),
                hours=_JANUARY_WEEKEND_MORNINGS.hours,
            ),
        )

    def test_a_window_with_no_eligible_day_in_the_period_is_omitted(self) -> None:
        events = GridServicesEventsConfig(event_windows=(_JUNE_WEEKDAY_EVENINGS, WINDOW), event_day_seed=5)
        dates = every_date(*self._JANUARY)

        assert enrolled_event_windows(events, _period(*self._JANUARY)) == (
            EventDischargeWindow(days=drawn_event_days(WINDOW, dates, 5, position=1), hours=WINDOW.hours),
        )

    def test_the_same_arguments_give_equal_windows(self) -> None:
        assert enrolled_event_windows(self._EVENTS, _period(*self._JANUARY)) == enrolled_event_windows(
            self._EVENTS, _period(*self._JANUARY)
        )

    def test_only_the_period_s_dates_are_read(self) -> None:
        assert enrolled_event_windows(self._EVENTS, _period(*self._JANUARY, timedelta(hours=1))) == (
            enrolled_event_windows(self._EVENTS, _period(*self._JANUARY))
        )
