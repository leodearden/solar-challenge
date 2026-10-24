# SPDX-License-Identifier: AGPL-3.0-or-later
"""A simulated series' window: the calendar days it covers and how long one of its rows lasts."""

from datetime import date, timedelta

import pandas as pd
import pytest

from solar_challenge.timebase import (
    HOURS_PER_MINUTE,
    MINUTES_PER_DAY,
    MINUTES_PER_HOUR,
    SimulationWindow,
    covered_days,
)

_MINUTE = timedelta(minutes=1)


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


def test_minutes_per_day_is_the_whole_minutes_in_24_hours() -> None:
    """An int, since its readers use it as an array length, a range and slice bound, and a modulus whose remainder is formatted :02d."""
    assert MINUTES_PER_DAY == timedelta(hours=24) // _MINUTE
    assert isinstance(MINUTES_PER_DAY, int)


def test_minutes_per_hour_is_the_whole_minutes_in_an_hour() -> None:
    """An int, since its readers build whole minute counts from it: range and slice bounds, an index into a minute table, and a divmod whose quotient and remainder are formatted :02d."""
    assert MINUTES_PER_HOUR == timedelta(hours=1) // _MINUTE
    assert isinstance(MINUTES_PER_HOUR, int)


def test_row_energy_kwh_is_each_rows_kw_times_the_hours_it_lasts_and_energy_kwh_their_sum() -> None:
    half_hours = pd.date_range("2023-06-01", periods=3, freq="30min", tz="Europe/London")
    half_hourly = SimulationWindow(date(2023, 6, 1), date(2023, 6, 1), timedelta(minutes=30))
    power_kw = pd.Series([1.0, 2.0, 3.0], index=half_hours)

    row_energy = half_hourly.row_energy_kwh(power_kw)

    pd.testing.assert_series_equal(row_energy, pd.Series([0.5, 1.0, 1.5], index=half_hours))
    assert half_hourly.energy_kwh(power_kw) == row_energy.sum()


def test_energy_kwh_sums_each_rows_kw_times_the_hours_it_lasts() -> None:
    half_hours = pd.date_range("2023-06-01", "2023-06-07 23:30", freq="30min", tz="Europe/London")
    half_hourly = SimulationWindow(date(2023, 6, 1), date(2023, 6, 7), timedelta(minutes=30))
    quarter_hourly = SimulationWindow(date(2023, 6, 1), date(2023, 6, 1), timedelta(minutes=15))

    assert half_hourly.energy_kwh(pd.Series(0.4, index=half_hours)) == pytest.approx(67.2, rel=1e-9)
    assert quarter_hourly.energy_kwh(pd.Series([1.0, 2.0, 3.0])) == pytest.approx(1.5)


def _whole_london_days(first: str, last: str) -> pd.DatetimeIndex:
    """One-minute rows over whole local days, as load.py indexes a period: first's midnight to last's 23:59."""
    return pd.date_range(first, f"{last} 23:59", freq="1min", tz="Europe/London")


@pytest.mark.parametrize(
    ("first", "last", "days", "timedelta_days"),
    [
        ("2024-10-01", "2024-11-30", 61, 62),
        ("2024-03-31", "2024-04-01", 2, 2),
        ("2024-07-01", "2024-12-31", 184, 185),
    ],
)
def test_of_index_counts_the_calendar_days_an_index_covers(
    first: str, last: str, days: int, timedelta_days: int
) -> None:
    index = _whole_london_days(first, last)
    assert (index[-1] - index[0]).days + 1 == timedelta_days

    assert SimulationWindow.of_index(index).days == days


def test_of_index_reads_an_index_with_a_freq() -> None:
    index = pd.date_range("2024-06-01", "2024-06-02 23:30", freq="30min", tz="Europe/London")

    assert SimulationWindow.of_index(index) == SimulationWindow(
        date(2024, 6, 1), date(2024, 6, 2), timedelta(minutes=30), "Europe/London"
    )


def test_of_index_reads_the_cadence_of_an_index_without_freq_from_its_even_spacing() -> None:
    stored = pd.DatetimeIndex(_whole_london_days("2024-03-30", "2024-04-01"), freq=None)
    assert stored.freq is None
    assert len(stored) == 4_260

    window = SimulationWindow.of_index(stored)

    assert window.cadence == timedelta(minutes=1)
    assert window.days == 3


def test_of_index_reads_a_one_row_index_s_cadence_from_its_freq() -> None:
    index = pd.date_range("2024-06-01 12:00", periods=1, freq="30min", tz="Europe/London")

    window = SimulationWindow.of_index(index)

    assert window.cadence == timedelta(minutes=30)
    assert window.days == 1


def test_of_index_reads_a_calendar_freq_through_the_index_s_spacing() -> None:
    index = pd.date_range("2024-06-01", periods=3, freq="D", tz="Europe/London")

    assert SimulationWindow.of_index(index).cadence == timedelta(days=1)


def test_of_index_refuses_a_daily_index_across_a_clock_change_naming_the_short_day() -> None:
    index = pd.date_range("2024-03-29", periods=4, freq="D", tz="Europe/London")

    with pytest.raises(ValueError) as refusal:
        SimulationWindow.of_index(index)

    assert "position 3" in str(refusal.value)
    assert str(pd.Timedelta(hours=23)) in str(refusal.value)
    assert str(pd.Timedelta(days=1)) in str(refusal.value)


def test_of_index_refuses_one_row_whose_freq_is_a_day() -> None:
    index = pd.date_range("2024-06-01", periods=1, freq="D", tz="Europe/London")

    with pytest.raises(ValueError, match="one row"):
        SimulationWindow.of_index(index)


def test_of_index_of_a_naive_index_has_no_timezone() -> None:
    naive = pd.date_range("2024-06-01", periods=3, freq="min")
    utc = pd.date_range("2024-06-01", periods=3, freq="min", tz="UTC")

    assert SimulationWindow.of_index(naive).timezone is None
    assert SimulationWindow.of_index(utc).timezone == "UTC"


def test_of_index_refuses_uneven_spacing_naming_the_first_differing_position_and_both_gaps() -> None:
    index = pd.date_range("2024-06-01", periods=1440, freq="1min", tz="Europe/London").delete(700)

    with pytest.raises(ValueError) as refusal:
        SimulationWindow.of_index(index)

    assert "position 700" in str(refusal.value)
    assert str(pd.Timedelta(minutes=2)) in str(refusal.value)
    assert str(pd.Timedelta(minutes=1)) in str(refusal.value)


def test_of_index_refuses_an_empty_index() -> None:
    with pytest.raises(ValueError, match="empty"):
        SimulationWindow.of_index(pd.DatetimeIndex([], tz="Europe/London"))


def test_of_index_refuses_one_row_without_a_freq() -> None:
    index = pd.DatetimeIndex([pd.Timestamp("2024-06-01 12:00", tz="Europe/London")])

    with pytest.raises(ValueError, match="one row"):
        SimulationWindow.of_index(index)


def test_of_index_refuses_an_index_that_is_not_a_datetimeindex_naming_its_type_and_dtype() -> None:
    index = pd.Index(["2024-03-31 00:59:00+00:00", "2024-03-31 02:00:00+01:00"])

    with pytest.raises(ValueError) as refusal:
        SimulationWindow.of_index(index)

    assert f"{type(index).__name__} of dtype {index.dtype}" in str(refusal.value)
