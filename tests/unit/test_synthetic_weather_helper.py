# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_synthetic_weather.py, the shared builder of the hourly weather that tests inject instead of calling PVGIS."""

from collections.abc import Callable
from functools import partial

import pandas as pd
import pytest

from tests._synthetic_weather import sunless_weather, synthetic_june_weather


def test_a_sunless_day_is_dark_every_hour_at_the_given_air_temperature() -> None:
    weather = sunless_weather("2024-01-15", temp_air=8.0)

    pd.testing.assert_index_equal(
        weather.index, pd.date_range("2024-01-15", periods=24, freq="h", tz="Europe/London")
    )
    assert (weather[["ghi", "dni", "dhi"]] == 0.0).all().all()
    assert (weather["temp_air"] == 8.0).all()


@pytest.mark.parametrize(
    "weather",
    [synthetic_june_weather("2024-06-21"), sunless_weather("2024-06-21", temp_air=12.0)],
    ids=["clear-june", "sunless"],
)
def test_every_profile_carries_the_columns_the_pv_model_reads(weather: pd.DataFrame) -> None:
    """pvlib's ModelChain silently runs a missing temp_air at 20 °C and a missing wind_speed at 0 m/s, so a profile that loses a column fails nowhere else."""
    assert list(weather.columns) == ["ghi", "dni", "dhi", "temp_air", "wind_speed"]


@pytest.mark.parametrize(
    "build",
    [synthetic_june_weather, partial(sunless_weather, temp_air=12.0)],
    ids=["clear-june", "sunless"],
)
def test_every_profile_starts_at_midnight_of_the_day_it_is_given(
    build: Callable[[str], pd.DataFrame],
) -> None:
    weather = build("2024-06-21 06:00")

    pd.testing.assert_index_equal(
        weather.index, pd.date_range("2024-06-21", periods=24, freq="h", tz="Europe/London")
    )
