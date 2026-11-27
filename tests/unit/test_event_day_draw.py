# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for gridservices.drawn_event_days: the seeded draw of an event window's days over a simulated period.

The draw counts a window's events in proportion to the share of each calendar year's eligible days the period
holds, rounded half up and kept between 1 and the eligible days, and picks them with a generator of its own. The
tests assert those properties, never the dates a seed picks, so they hold whatever stream numpy's generator gives.
"""

import random
from datetime import date, datetime, timedelta

import numpy as np
import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import DEFAULT_EVENT_WINDOWS, EventWindow, drawn_event_days

WINDOW = DEFAULT_EVENT_WINDOWS[0]
"""November to February weekdays, 12 events a year: 2024 has 87 such days and 2025 has 86."""

_EVERY_WEEKDAY = (0, 1, 2, 3, 4, 5, 6)


def _days(first: date, last: date) -> list[date]:
    """Every date from *first* to *last*, both included."""
    return [first + timedelta(days=offset) for offset in range((last - first).days + 1)]


_YEAR_2024 = _days(date(2024, 1, 1), date(2024, 12, 31))


def _every_day_window(months: tuple[int, ...], events_per_year: int) -> EventWindow:
    return EventWindow(
        months=months, weekdays=_EVERY_WEEKDAY, hours=(17,), events_per_year=events_per_year, event_hours=1.0
    )


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
        days = drawn_event_days(WINDOW, _days(date(2024, 1, 1), date(2024, 2, 29)), 0, position=0)

        assert len(days) == 6
        assert all(day.year == 2024 and day.month in (1, 2) and day.weekday() < 5 for day in days)

    def test_two_full_years_draw_each_year_s_events(self) -> None:
        days = drawn_event_days(WINDOW, _days(date(2024, 1, 1), date(2025, 12, 31)), 0, position=0)

        assert len(days) == 24

    def test_a_half_event_rounds_up(self) -> None:
        window = _every_day_window((1, 2), events_per_year=5)

        days = drawn_event_days(window, _days(date(2024, 1, 1), date(2024, 1, 30)), 0, position=0)

        assert len(days) == 3

    def test_a_period_holding_an_eligible_day_draws_at_least_one(self) -> None:
        assert drawn_event_days(WINDOW, [date(2024, 1, 15)], 0, position=0) == (date(2024, 1, 15),)

    def test_no_more_days_are_drawn_than_are_eligible(self) -> None:
        january = _days(date(2024, 1, 1), date(2024, 1, 31))

        assert drawn_event_days(_every_day_window((1,), events_per_year=40), january, 0, position=0) == tuple(
            january
        )

    def test_a_period_with_no_eligible_day_draws_none(self) -> None:
        assert drawn_event_days(WINDOW, _days(date(2024, 6, 1), date(2024, 6, 30)), 0, position=0) == ()


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
