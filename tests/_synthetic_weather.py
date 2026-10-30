# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hourly weather for tests that inject their own weather, so they need no PVGIS call.

``synthetic_june_weather`` repeats one clear June day over consecutive days, each day
with its irradiance scaled, so a test can put a sunny day next to a sunless one.
``sunless_weather`` is one day with no sun at a constant air temperature, on any date.
Both index their hours from midnight of the day they are given, in Europe/London, the
timezone of the simulated demand. ``weather_for`` gives such a frame to simulate_home as
one home's weather. ``synthetic_tmy`` is a whole TMY year of clear June days, in the
shape PvgisTmy fetches from PVGIS, for seeding a WeatherCache. Its days' irradiance can
be scaled too, one scale for each of its ``TMY_DAYS`` days. ``sunless_tmy`` is a whole
TMY year with no sun at a constant air temperature, in that same shape, e.g. the year of
weather simulate_home needs for a heat pump.

Usage::

    from tests._synthetic_weather import sunless_tmy, sunless_weather, synthetic_june_weather, synthetic_tmy, weather_for

    sunny_then_sunless = synthetic_june_weather("2024-06-21", irradiance_scale_per_day=(1.0, 0.0))
    results = simulate_home(config, start, end, weather=weather_for(config, sunny_then_sunless))

    no_pv_in_january = sunless_weather("2024-01-15", temp_air=8.0)

    WeatherCache(cache_dir=cache_dir).put(synthetic_tmy(), "tmy", location)

    dark_year_for_a_heat_pump = sunless_tmy(temp_air=10.0)
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from solar_challenge.weather import TMY_HOURS, PrefetchedWeather

if TYPE_CHECKING:
    from solar_challenge.home import HomeConfig

_HOURS_PER_DAY = 24
_TMY_YEAR_START = "1990-01-01"
_TIMEZONE = "Europe/London"
_SUNLESS_WIND_SPEED = 2.0
_IRRADIANCE_COLUMNS = ["ghi", "dni", "dhi"]

TMY_DAYS = TMY_HOURS // _HOURS_PER_DAY
"""The days of PVGIS's TMY year, and so the irradiance scales synthetic_tmy takes."""

# One clear June day, hour by hour: GHI peaks near 870 W/m² at solar noon.
_CLEAR_JUNE_DAY = {
    "ghi": [
        0, 0, 0, 0, 0, 50, 150, 300, 500, 650, 780, 850,
        870, 850, 780, 650, 500, 300, 150, 50, 0, 0, 0, 0,
    ],
    "dni": [
        0, 0, 0, 0, 0, 100, 250, 450, 650, 800, 900, 950,
        970, 950, 900, 800, 650, 450, 250, 100, 0, 0, 0, 0,
    ],
    "dhi": [
        0, 0, 0, 0, 0, 30, 70, 130, 180, 200, 200, 200,
        200, 200, 200, 200, 180, 130, 70, 30, 0, 0, 0, 0,
    ],
    "temp_air": [
        12, 11, 11, 11, 12, 13, 15, 17, 19, 21, 22, 23,
        23, 23, 22, 21, 19, 17, 16, 14, 13, 12, 12, 12,
    ],
    "wind_speed": [
        2, 2, 2, 2, 2, 2, 3, 3, 3, 3, 3, 3,
        3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 2, 2,
    ],
}


def synthetic_june_weather(
    first_day: str | pd.Timestamp,
    irradiance_scale_per_day: Sequence[float] = (1.0,),
) -> pd.DataFrame:
    """Hourly weather from *first_day*, one day per entry of *irradiance_scale_per_day*.

    Each day is the clear June day with ghi, dni and dhi multiplied by that day's scale:
    1.0 keeps the sun as is, 0.0 removes it. Air temperature and wind speed are never scaled.
    """
    return pd.DataFrame(
        _clear_june_days(irradiance_scale_per_day),
        index=_hourly_index(first_day, days=len(irradiance_scale_per_day)),
    )


def synthetic_tmy(*, irradiance_scale_per_day: Sequence[float] = (1.0,) * TMY_DAYS) -> pd.DataFrame:
    """A TMY year of clear June days, shaped as PVGIS's: TMY_HOURS hourly rows from 1990-01-01 00:00 UTC, each UTC day the clear June day.

    UTC day i's ghi, dni and dhi are multiplied by entry i of *irradiance_scale_per_day*, as
    synthetic_june_weather scales its days. It takes TMY_DAYS scales, all 1.0 by default, and
    refuses any other count with ValueError.
    """
    if len(irradiance_scale_per_day) != TMY_DAYS:
        raise ValueError(
            f"synthetic_tmy takes {TMY_DAYS} irradiance scales, one per day of the TMY year, "
            f"not {len(irradiance_scale_per_day)}"
        )
    return pd.DataFrame(
        _clear_june_days(irradiance_scale_per_day),
        index=_tmy_index(),
    )


def sunless_weather(day: str | pd.Timestamp, *, temp_air: float) -> pd.DataFrame:
    """A day with no sun at a constant *temp_air* °C, for tests that need PV generation to be zero."""
    return _sunless_hours(_hourly_index(day, days=1), temp_air=temp_air, wind_speed=_SUNLESS_WIND_SPEED)


def sunless_tmy(*, temp_air: float, wind_speed: float = _SUNLESS_WIND_SPEED) -> pd.DataFrame:
    """A TMY year with no sun at a constant *temp_air* °C, shaped as PVGIS's (TMY_HOURS hourly rows from 1990-01-01 00:00 UTC), at sunless_weather's 2 m/s of wind unless *wind_speed* is given."""
    return _sunless_hours(_tmy_index(), temp_air=temp_air, wind_speed=wind_speed)


def weather_for(home: HomeConfig, frame: pd.DataFrame) -> PrefetchedWeather:
    """*frame* given to simulate_home as *home*'s weather.

    It is held at the home's location alone, so a run of a home elsewhere is refused, naming both locations.
    """
    return PrefetchedWeather({home.location: frame})


def _clear_june_days(irradiance_scale_per_day: Sequence[float]) -> dict[str, np.ndarray]:
    """The clear June day's hourly values by column, for one day per entry of *irradiance_scale_per_day*, each day's ghi, dni and dhi multiplied by its scale."""
    days = len(irradiance_scale_per_day)
    hour_scales = np.repeat(np.asarray(irradiance_scale_per_day, dtype=float), _HOURS_PER_DAY)
    clear_days = {column: np.tile(np.asarray(hours, dtype=float), days) for column, hours in _CLEAR_JUNE_DAY.items()}
    scaled_irradiance = {column: clear_days[column] * hour_scales for column in _IRRADIANCE_COLUMNS}
    return clear_days | scaled_irradiance


def _sunless_hours(index: pd.DatetimeIndex, *, temp_air: float, wind_speed: float) -> pd.DataFrame:
    """Weather with no sun at a constant *temp_air* °C and *wind_speed* m/s, every column float64, one row per hour of *index*."""
    return pd.DataFrame(
        {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": temp_air, "wind_speed": wind_speed},
        index=index,
        dtype=float,
    )


def _hourly_index(first_day: str | pd.Timestamp, days: int) -> pd.DatetimeIndex:
    """The hours of *days* consecutive days from midnight of *first_day*, in London."""
    return pd.date_range(first_day, periods=_HOURS_PER_DAY * days, freq="h", tz=_TIMEZONE, normalize=True)


def _tmy_index() -> pd.DatetimeIndex:
    """The hours of PVGIS's TMY year, TMY_HOURS hourly rows from 1990-01-01 00:00 UTC."""
    return pd.date_range(_TMY_YEAR_START, periods=TMY_HOURS, freq="h", tz="UTC")
