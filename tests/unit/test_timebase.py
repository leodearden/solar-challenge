# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated series' window: the calendar days it covers and how long one of its rows lasts."""

from datetime import date, timedelta

import pandas as pd
import pytest

from solar_challenge.timebase import (
    HOURS_PER_MINUTE,
    SimulationWindow,
    covered_days,
    step_hours,
)

_MINUTE = timedelta(minutes=1)


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


@pytest.mark.parametrize(
    ("first", "last", "days", "year_days", "scale", "extrapolated"),
    [
        (date(2023, 1, 1), date(2023, 12, 31), 365, 365.0, 1.0, False),
        (date(2024, 1, 1), date(2024, 12, 31), 366, 366.0, 1.0, False),
        (date(2024, 6, 1), date(2024, 6, 30), 30, 366.0, 12.2, True),
        (date(2023, 1, 1), date(2024, 12, 31), 731, 365.25, 365.25 / 731, False),
        (date(2024, 1, 1), date(2025, 2, 3), 400, 365.25, 365.25 / 400, True),
        (date(2024, 4, 1), date(2025, 3, 31), 365, 365.25, 365.25 / 365, True),
    ],
)
def test_a_window_annualises_by_its_covered_year(
    first: date,
    last: date,
    days: int,
    year_days: float,
    scale: float,
    extrapolated: bool,
) -> None:
    window = SimulationWindow(first, last, _MINUTE)

    assert window.days == days
    assert window.year_days == year_days
    assert window.annualisation_scale == pytest.approx(scale, rel=1e-12)
    assert window.extrapolated is extrapolated


def test_a_window_refuses_a_last_day_before_its_first_naming_both() -> None:
    with pytest.raises(ValueError) as refusal:
        SimulationWindow(date(2024, 6, 2), date(2024, 6, 1), _MINUTE)

    assert "2024-06-01" in str(refusal.value)
    assert "2024-06-02" in str(refusal.value)


@pytest.mark.parametrize("cadence", [timedelta(0), timedelta(minutes=-1)])
def test_a_window_refuses_a_cadence_that_is_not_positive_naming_it(cadence: timedelta) -> None:
    with pytest.raises(ValueError) as refusal:
        SimulationWindow(date(2024, 6, 1), date(2024, 6, 1), cadence)

    assert "cadence" in str(refusal.value)
    assert repr(cadence) in str(refusal.value)


@pytest.mark.parametrize(
    ("cadence", "hours", "minutes"),
    [
        (timedelta(minutes=1), 1 / 60, 1.0),
        (timedelta(minutes=15), 0.25, 15.0),
        (timedelta(minutes=30), 0.5, 30.0),
        (timedelta(hours=1), 1.0, 60.0),
    ],
)
def test_step_hours_and_step_minutes_are_the_cadence_in_hours_and_minutes(
    cadence: timedelta, hours: float, minutes: float
) -> None:
    window = SimulationWindow(date(2024, 6, 1), date(2024, 6, 1), cadence)

    assert window.step_hours == pytest.approx(hours)
    assert window.step_minutes == minutes


def test_a_one_minute_cadence_lasts_exactly_hours_per_minute() -> None:
    window = SimulationWindow(date(2024, 6, 1), date(2024, 6, 1), _MINUTE)

    assert window.step_hours == HOURS_PER_MINUTE


def test_energy_kwh_sums_each_rows_kw_times_the_hours_it_lasts() -> None:
    half_hours = pd.date_range("2023-06-01", "2023-06-07 23:30", freq="30min", tz="Europe/London")
    half_hourly = SimulationWindow(date(2023, 6, 1), date(2023, 6, 7), timedelta(minutes=30))
    quarter_hourly = SimulationWindow(date(2023, 6, 1), date(2023, 6, 1), timedelta(minutes=15))

    assert half_hourly.energy_kwh(pd.Series(0.4, index=half_hours)) == pytest.approx(67.2, rel=1e-9)
    assert quarter_hourly.energy_kwh(pd.Series([1.0, 2.0, 3.0])) == pytest.approx(1.5)
