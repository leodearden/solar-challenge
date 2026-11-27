# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_synthetic_weather.py, the shared builder of the hourly weather that tests inject instead of calling PVGIS."""

from collections.abc import Callable, Sequence
from functools import partial

import numpy as np
import pandas as pd
import pytest

from solar_challenge.weather import TMY_HOURS
from tests._synthetic_weather import TMY_DAYS, sunless_tmy, sunless_weather, synthetic_june_weather, synthetic_tmy


def test_a_sunless_day_is_dark_every_hour_at_the_given_air_temperature() -> None:
    weather = sunless_weather("2024-01-15", temp_air=8.0)

    pd.testing.assert_frame_equal(
        weather,
        pd.DataFrame(
            {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": 8.0, "wind_speed": 2.0},
            index=pd.date_range("2024-01-15", periods=24, freq="h", tz="Europe/London"),
        ),
        check_exact=True,
    )


def test_the_clear_june_day_is_dark_at_midnight_and_peaks_at_noon() -> None:
    """The profile's values at two hours, written out: the other value checks compare the builder only with its own builds."""
    weather = synthetic_june_weather("2024-06-21")

    assert weather.iloc[[0, 12]].to_dict("list") == {
        "ghi": [0.0, 870.0],
        "dni": [0.0, 970.0],
        "dhi": [0.0, 200.0],
        "temp_air": [12.0, 23.0],
        "wind_speed": [2.0, 3.0],
    }


@pytest.mark.parametrize(
    ("first_day", "irradiance_scale_per_day"),
    [
        pytest.param("1990-01-01", np.linspace(0.2, 1.0, 365).tolist(), id="365-days-across-both-clock-changes"),
        pytest.param("2024-03-30", (1.0, 0.0, 0.5), id="3-days-across-the-spring-clock-change"),
    ],
)
def test_a_multi_day_build_is_its_days_built_one_at_a_time_and_joined_in_order(
    first_day: str, irradiance_scale_per_day: Sequence[float]
) -> None:
    """The rows are positional: row 24 * i + h holds day i's hour h, even across the spring clock change, whose clock skips 01:00."""
    days_built_one_at_a_time = [
        synthetic_june_weather(pd.Timestamp(first_day) + pd.Timedelta(days=i), irradiance_scale_per_day=(scale,))
        for i, scale in enumerate(irradiance_scale_per_day)
    ]
    index = pd.date_range(
        first_day, periods=24 * len(irradiance_scale_per_day), freq="h", tz="Europe/London", normalize=True
    )

    weather = synthetic_june_weather(first_day, irradiance_scale_per_day=irradiance_scale_per_day)

    assert set(weather.dtypes) == {np.dtype("float64")}
    pd.testing.assert_frame_equal(
        weather, pd.concat(days_built_one_at_a_time, ignore_index=True).set_axis(index), check_exact=True
    )


def test_a_days_scale_multiplies_its_irradiance_and_leaves_air_temperature_and_wind_speed_alone() -> None:
    clear = synthetic_june_weather("2024-06-21")

    pd.testing.assert_frame_equal(
        synthetic_june_weather("2024-06-21", irradiance_scale_per_day=(0.5,)),
        clear.assign(ghi=clear["ghi"] * 0.5, dni=clear["dni"] * 0.5, dhi=clear["dhi"] * 0.5),
        check_exact=True,
    )


def test_a_synthetic_tmy_is_a_pvgis_shaped_year_whose_every_utc_day_is_the_clear_june_day() -> None:
    clear_june_day = synthetic_june_weather("2024-06-21").to_numpy()

    tmy = synthetic_tmy()

    pd.testing.assert_index_equal(tmy.index, pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC"))
    for _, day in tmy.groupby(tmy.index.date):
        np.testing.assert_array_equal(day.to_numpy(), clear_june_day)


def test_a_scaled_synthetic_tmy_is_its_days_built_one_at_a_time_at_their_scales_and_joined_in_order() -> None:
    """UTC day i of the TMY is the clear June day with its irradiance scaled by entry i of irradiance_scale_per_day."""
    irradiance_scale_per_day = np.linspace(0.2, 1.0, TMY_DAYS).tolist()
    days_built_one_at_a_time = [
        synthetic_june_weather("2024-06-21", irradiance_scale_per_day=(scale,)) for scale in irradiance_scale_per_day
    ]

    pd.testing.assert_frame_equal(
        synthetic_tmy(irradiance_scale_per_day=irradiance_scale_per_day),
        pd.concat(days_built_one_at_a_time, ignore_index=True).set_axis(
            pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC")
        ),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "days",
    [
        pytest.param(TMY_DAYS - 1, id="a-day-short"),
        pytest.param(TMY_DAYS + 1, id="a-leap-years-days"),
        pytest.param(TMY_HOURS, id="one-per-hour"),
    ],
)
def test_a_synthetic_tmy_refuses_any_count_of_day_scales_but_one_per_day_of_the_tmy_year(days: int) -> None:
    with pytest.raises(ValueError, match=rf"\b{TMY_DAYS}\b.*\b{days}\b"):
        synthetic_tmy(irradiance_scale_per_day=(1.0,) * days)


@pytest.mark.parametrize(
    ("wind", "expected_wind_speed"),
    [
        pytest.param({}, 2.0, id="default-wind-is-a-sunless-days-2-m-s"),
        pytest.param({"wind_speed": 3.0}, 3.0, id="given-wind"),
    ],
)
def test_a_sunless_tmy_is_a_pvgis_shaped_year_dark_every_hour_at_its_air_temperature_and_wind_speed(
    wind: dict[str, float], expected_wind_speed: float
) -> None:
    pd.testing.assert_frame_equal(
        sunless_tmy(temp_air=25.0, **wind),
        pd.DataFrame(
            {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": 25.0, "wind_speed": expected_wind_speed},
            index=pd.date_range("1990-01-01", periods=TMY_HOURS, freq="h", tz="UTC"),
        ),
        check_exact=True,
    )


@pytest.mark.parametrize(
    "weather",
    [
        synthetic_june_weather("2024-06-21"),
        sunless_weather("2024-06-21", temp_air=12.0),
        synthetic_tmy(),
        sunless_tmy(temp_air=12.0),
    ],
    ids=["clear-june", "sunless", "tmy", "sunless-tmy"],
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
