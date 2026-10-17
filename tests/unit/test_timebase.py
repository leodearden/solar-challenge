# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated series' window: the calendar days it covers and how long one of its rows lasts."""

from datetime import date

import pandas as pd
import pytest

from solar_challenge.timebase import HOURS_PER_MINUTE, covered_days, step_hours


def test_a_single_row_lasts_one_minute() -> None:
    index = pd.date_range("2024-06-21 12:00", periods=1, freq="h", tz="Europe/London")

    assert step_hours(index) == HOURS_PER_MINUTE == pytest.approx(1 / 60)


@pytest.mark.parametrize(
    ("freq", "hours"),
    [("min", 1 / 60), ("15min", 0.25), ("h", 1.0), ("2h", 2.0)],
)
def test_a_row_lasts_the_gap_between_the_first_two_rows(freq: str, hours: float) -> None:
    index = pd.date_range("2024-06-21 12:00", periods=3, freq=freq, tz="Europe/London")

    assert step_hours(index) == pytest.approx(hours)


@pytest.mark.parametrize(
    ("first", "last", "days"),
    [
        (date(2024, 10, 1), date(2024, 11, 30), 61),
        (date(2024, 3, 31), date(2024, 4, 1), 2),
        (date(2024, 7, 1), date(2024, 12, 31), 184),
        (date(2024, 6, 1), date(2024, 6, 1), 1),
        (date(2023, 1, 1), date(2024, 12, 31), 731),
    ],
)
def test_covered_days_counts_calendar_dates_first_to_last_inclusive(
    first: date, last: date, days: int
) -> None:
    assert covered_days(first, last) == days


def test_covered_days_refuses_a_last_day_before_the_first_naming_both() -> None:
    with pytest.raises(ValueError) as refusal:
        covered_days(date(2024, 6, 2), date(2024, 6, 1))

    assert "2024-06-01" in str(refusal.value)
    assert "2024-06-02" in str(refusal.value)
