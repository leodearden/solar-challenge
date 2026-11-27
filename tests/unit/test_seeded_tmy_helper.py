# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_seeded_tmy.py: the clear June days a test seeds as Bristol's TMY, the fixture a module binds to seed them, and the simulation windows within them."""

from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import PvgisTmy, WeatherCache, default_weather
from tests._seeded_tmy import ClearJuneDays
from tests._synthetic_weather import synthetic_june_weather

_THREE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=3)
bristol_june_tmy = _THREE_DAYS.bristol_tmy_fixture()


def test_the_days_are_the_clear_june_day_once_each_from_the_first_day() -> None:
    pd.testing.assert_frame_equal(
        _THREE_DAYS.hourly_weather(),
        synthetic_june_weather("2024-06-21", irradiance_scale_per_day=(1.0, 1.0, 1.0)),
        check_exact=True,
    )


def test_days_seeded_into_weather_cache_are_the_bristol_tmy_default_weather_serves(weather_cache: WeatherCache) -> None:
    _THREE_DAYS.seed_as_bristol_tmy(weather_cache)

    pd.testing.assert_frame_equal(
        default_weather().get(Location.bristol()), _THREE_DAYS.hourly_weather(), check_exact=True
    )


def test_days_seeded_into_a_cache_of_the_tests_own_are_the_bristol_tmy_a_provider_over_it_serves(
    tmp_path: Path,
) -> None:
    """The way a child process, a script given --cache-dir or the e2e live server reads them."""
    cache = WeatherCache(cache_dir=tmp_path / "weather")

    _THREE_DAYS.seed_as_bristol_tmy(cache)

    pd.testing.assert_frame_equal(
        PvgisTmy(cache).get(Location.bristol()), _THREE_DAYS.hourly_weather(), check_exact=True
    )


@pytest.mark.usefixtures("bristol_june_tmy")
def test_the_fixture_a_module_binds_seeds_the_days_as_the_bristol_tmy_default_weather_serves() -> None:
    pd.testing.assert_frame_equal(
        default_weather().get(Location.bristol()), _THREE_DAYS.hourly_weather(), check_exact=True
    )


@pytest.mark.parametrize(
    "first_day",
    [pd.Timestamp("2024-06-21"), pd.Timestamp("2024-06-21", tz="Europe/London")],
    ids=["naive", "in-london"],
)
def test_a_window_runs_from_the_first_day_over_whole_days_in_the_first_days_timezone(
    first_day: pd.Timestamp,
) -> None:
    june_days = ClearJuneDays(first_day=first_day, count=3)

    assert june_days.window(1) == (first_day, first_day)
    assert june_days.window(3) == (first_day, first_day + pd.Timedelta(days=2))
    assert {day.tz for day in june_days.window(3)} == {first_day.tz}


def test_a_window_of_no_stated_days_spans_every_one_of_the_days() -> None:
    assert _THREE_DAYS.window() == _THREE_DAYS.window(_THREE_DAYS.count)


@pytest.mark.parametrize("days", [0, 4])
def test_a_window_of_no_days_or_of_more_days_than_were_seeded_is_refused_naming_both(days: int) -> None:
    with pytest.raises(
        AssertionError, match=f"a window takes 1 to 3 of the clear June days from 2024-06-21, not {days};"
    ):
        _THREE_DAYS.window(days)


def test_clear_june_days_are_at_least_one_day() -> None:
    with pytest.raises(AssertionError, match="ClearJuneDays needs at least one day, not count=0"):
        ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=0)
