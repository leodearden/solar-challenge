# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clear June days a test seeds as Bristol's TMY, so it simulates offline over a window within them.

Usage::

    from tests._seeded_tmy import ClearJuneDays

    june_days = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=3)
    june_days.seed_as_bristol_tmy(weather_cache)
    start, end = june_days.window(2)  # the first two days; window() spans all three
    results = simulate_fleet(config, start, end)

A module whose tests run on its days binds a fixture of them once, under the name its tests apply::

    _JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=7)
    bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()

    @pytest.mark.usefixtures("bristol_june_tmy")
    class TestFleetSimulation: ...

The days can also be given to simulate_home as one home's weather, with no cache::

    from tests._synthetic_weather import weather_for

    results = simulate_home(home, start, end, weather=weather_for(home, june_days.hourly_weather()))
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import synthetic_june_weather


@dataclass(frozen=True)
class ClearJuneDays:
    """*count* consecutive clear June days from *first_day*, for a test to seed as Bristol's TMY and simulate within.

    The days can also be given to simulate_home through ``weather_for(home, june_days.hourly_weather())``.
    """

    first_day: pd.Timestamp
    count: int

    def __post_init__(self) -> None:
        assert self.count >= 1, f"ClearJuneDays needs at least one day, not count={self.count}"

    def hourly_weather(self) -> pd.DataFrame:
        """The hourly weather of these days, each the clear June day."""
        return synthetic_june_weather(self.first_day, irradiance_scale_per_day=(1.0,) * self.count)

    def seed_as_bristol_tmy(self, weather_cache: WeatherCache) -> None:
        """Put these days in *weather_cache* as Bristol's TMY, which default_weather() then reads in place of PVGIS."""
        weather_cache.put(self.hourly_weather(), "tmy", Location.bristol())

    def bristol_tmy_fixture(self) -> object:
        """A pytest fixture that seeds these days as Bristol's TMY for each test that uses it.

        Bind it to a module-level name, which pytest makes the fixture's name::

            bristol_june_tmy = _JUNE_DAYS.bristol_tmy_fixture()
        """

        @pytest.fixture
        def seeded_bristol_tmy(weather_cache: WeatherCache) -> None:
            """Seed the clear June days this fixture was made of as Bristol's TMY, which default_weather() then serves in place of PVGIS."""
            self.seed_as_bristol_tmy(weather_cache)

        return seeded_bristol_tmy

    def window(self, days: int | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
        """The start and end dates of a simulation over the first *days* of these days, or over all of them."""
        if days is None:
            days = self.count
        assert 1 <= days <= self.count, (
            f"a window takes 1 to {self.count} of the clear June days from {self.first_day.date()}, not {days}; "
            "a day the seeded TMY lacks gets no sun"
        )
        return self.first_day, self.first_day + pd.Timedelta(days=days - 1)
