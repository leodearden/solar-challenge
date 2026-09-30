# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hourly weather for tests that inject their own weather, so they need no PVGIS call.

``synthetic_june_weather`` repeats one clear June day over consecutive days, each day
with its irradiance scaled, so a test can put a sunny day next to a sunless one.
``sunless_weather`` is one day with no sun at a constant air temperature, on any date.
Both index their hours from midnight of the day they are given, in Europe/London, the
timezone of the simulated demand.

Usage::

    from tests._synthetic_weather import sunless_weather, synthetic_june_weather

    sunny_then_sunless = synthetic_june_weather("2024-06-21", irradiance_scale_per_day=(1.0, 0.0))
    results = simulate_home(config, start, end, weather_data=sunny_then_sunless)

    no_pv_in_january = sunless_weather("2024-01-15", temp_air=8.0)
"""

from __future__ import annotations

from collections.abc import Sequence

import pandas as pd

_HOURS_PER_DAY = 24
_TIMEZONE = "Europe/London"
_IRRADIANCE_COLUMNS = ["ghi", "dni", "dhi"]

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
    return _consecutive_days(
        first_day, [_clear_june_day(scale) for scale in irradiance_scale_per_day]
    )


def sunless_weather(day: str | pd.Timestamp, *, temp_air: float) -> pd.DataFrame:
    """A day with no sun at a constant *temp_air* °C, for tests that need PV generation to be zero."""
    return _consecutive_days(day, [_sunless_day(temp_air)])


def _consecutive_days(
    first_day: str | pd.Timestamp, days: Sequence[pd.DataFrame]
) -> pd.DataFrame:
    index = pd.date_range(
        first_day, periods=_HOURS_PER_DAY * len(days), freq="h", tz=_TIMEZONE
    )
    return pd.concat(days, ignore_index=True).set_axis(index)


def _clear_june_day(irradiance_scale: float) -> pd.DataFrame:
    day = pd.DataFrame(_CLEAR_JUNE_DAY, dtype=float)
    day[_IRRADIANCE_COLUMNS] *= irradiance_scale
    return day


def _sunless_day(temp_air: float) -> pd.DataFrame:
    return pd.DataFrame(
        {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": temp_air, "wind_speed": 2.0},
        index=range(_HOURS_PER_DAY),
        dtype=float,
    )
