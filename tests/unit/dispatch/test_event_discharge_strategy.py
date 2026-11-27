# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for a battery's grid-services event windows and the strategy that discharges it at full power in them.

docs/prds/event-dispatch-and-battery-sizing.md §5.2 defines EventDischargeWindow and
EventDischargeStrategy; §9 B4 is the behaviour they pin.
"""

import dataclasses
from datetime import date, datetime

import pandas as pd
import pytest

from solar_challenge.dispatch import EventDischargeWindow
from solar_challenge.errors import ConfigurationError


class TestEventDischargeWindow:
    def test_it_holds_its_days_and_hours_as_tuples(self) -> None:
        window = EventDischargeWindow(days=[date(2024, 1, 15), date(2024, 1, 16)], hours=[17, 18])

        assert window.days == (date(2024, 1, 15), date(2024, 1, 16))
        assert window.hours == (17, 18)
        assert isinstance(window.days, tuple)
        assert isinstance(window.hours, tuple)

    def test_it_is_frozen(self) -> None:
        window = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17,))

        with pytest.raises(dataclasses.FrozenInstanceError):
            window.days = (date(2024, 1, 16),)

    def test_two_equal_windows_are_equal_and_hash_equal(self) -> None:
        first = EventDischargeWindow(days=[date(2024, 1, 15)], hours=[17, 18])
        second = EventDischargeWindow(days=(date(2024, 1, 15),), hours=(17, 18))

        assert first == second
        assert hash(first) == hash(second)

    @pytest.mark.parametrize(
        ("days", "hours", "field"),
        [
            pytest.param((), (17,), "days", id="days"),
            pytest.param((date(2024, 1, 15),), (), "hours", id="hours"),
        ],
    )
    def test_an_empty_field_is_refused_naming_it(
        self, days: tuple[date, ...], hours: tuple[int, ...], field: str
    ) -> None:
        with pytest.raises(ConfigurationError, match=rf"^{field} must hold at least one"):
            EventDischargeWindow(days=days, hours=hours)

    @pytest.mark.parametrize("hour", [24, -1, 1.5, True], ids=["24", "-1", "1.5", "True"])
    def test_an_hour_that_is_not_a_whole_clock_hour_is_refused_naming_it(self, hour: object) -> None:
        with pytest.raises(ConfigurationError, match=r"^hours\[0\] must be"):
            EventDischargeWindow(days=(date(2024, 1, 15),), hours=(hour,))

    @pytest.mark.parametrize(
        "day",
        [datetime(2024, 1, 15, 17), pd.Timestamp("2024-01-15"), "2024-01-15"],
        ids=["datetime", "pd.Timestamp", "str"],
    )
    def test_a_day_that_is_not_exactly_a_date_is_refused_naming_it(self, day: object) -> None:
        with pytest.raises(ConfigurationError, match=r"^days\[0\] must be a date, got "):
            EventDischargeWindow(days=(day,), hours=(17,))

    @pytest.mark.parametrize(
        ("days", "hours", "field"),
        [
            pytest.param("2024-01-15", (17,), "days", id="days-str"),
            pytest.param({date(2024, 1, 15)}, (17,), "days", id="days-set"),
            pytest.param((date(2024, 1, 15),), "17", "hours", id="hours-str"),
            pytest.param((date(2024, 1, 15),), {17}, "hours", id="hours-set"),
        ],
    )
    def test_a_field_that_is_not_a_list_is_refused_naming_it(self, days: object, hours: object, field: str) -> None:
        with pytest.raises(ConfigurationError, match=rf"^{field} must be a list of "):
            EventDischargeWindow(days=days, hours=hours)
