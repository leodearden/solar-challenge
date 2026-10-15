# SPDX-License-Identifier: AGPL-3.0-or-later
"""Clear June days a test seeds as Bristol's TMY, so it simulates offline over a window within them.

Usage::

    from tests._seeded_tmy import ClearJuneDays

    june_days = ClearJuneDays(first_day=pd.Timestamp("2024-06-21"), count=3)
    june_days.seed_as_bristol_tmy(weather_cache)
    start, end = june_days.window(2)
    results = simulate_fleet(config, start, end)
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from tests._synthetic_weather import synthetic_june_weather


@dataclass(frozen=True)
class ClearJuneDays:
    """*count* consecutive clear June days from *first_day*, for a test to seed as Bristol's TMY and simulate within."""

    first_day: pd.Timestamp
    count: int

    def __post_init__(self) -> None:
        assert self.count >= 1, f"ClearJuneDays needs at least one day, not count={self.count}"

    def seed_as_bristol_tmy(self, weather_cache: WeatherCache) -> None:
        """Put these days in *weather_cache* as Bristol's TMY, which get_tmy_data then reads in place of PVGIS."""
        weather_cache.put(
            synthetic_june_weather(self.first_day, irradiance_scale_per_day=(1.0,) * self.count),
            "tmy",
            Location.bristol(),
        )

    def window(self, days: int) -> tuple[pd.Timestamp, pd.Timestamp]:
        """The start and end dates of a simulation over the first *days* of these days."""
        assert 1 <= days <= self.count, (
            f"a window takes 1 to {self.count} of the clear June days from {self.first_day.date()}, not {days}; "
            "a day the seeded TMY lacks gets no sun"
        )
        return self.first_day, self.first_day + pd.Timedelta(days=days - 1)
