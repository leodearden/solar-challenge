# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for aligning TMY weather to the simulated demand by UTC instant."""

import time

import numpy as np
import pandas as pd
import pytest
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, _align_tmy_to_demand, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig


@pytest.fixture
def tmy_minute_year() -> pd.Series:
    """A UTC 1990 year at 1-minute resolution, the shape of a PVGIS TMY after interpolation.

    Every value is distinct and non-zero, so an aligned 0.0 can only mean "no TMY match".
    """
    index = pd.date_range("1990-01-01", periods=525_600, freq="1min", tz="UTC")
    return pd.Series(np.arange(1, len(index) + 1, dtype=float), index=index)


def _london_minute_demand(first: str, last: str) -> pd.Series:
    return pd.Series(1.0, index=pd.date_range(first, last, freq="1min", tz="Europe/London"))


def _expected_alignment(demand: pd.Series, *value_runs: pd.Series | np.ndarray) -> pd.Series:
    """The aligned series of value_runs, in order, on the demand's index; unnamed, like the TMY series aligned here."""
    return pd.Series(np.concatenate(value_runs), index=demand.index)


class TestAlignTMYToDemand:
    """Test TMY data alignment."""

    def test_aligns_by_time_of_year(self):
        """TMY data aligned by month-day-hour-minute."""
        # TMY data for June 21
        tmy_index = pd.date_range("2024-06-21 10:00", periods=60, freq="1min")
        tmy_gen = pd.Series(range(60), index=tmy_index, dtype=float)

        # Demand for same time in a different year
        demand_index = pd.date_range("2025-06-21 10:00", periods=60, freq="1min")
        demand = pd.Series([1.0] * 60, index=demand_index)

        aligned = _align_tmy_to_demand(tmy_gen, demand)

        assert len(aligned) == 60
        # Values should be preserved from TMY
        assert aligned.iloc[0] == 0.0
        assert aligned.iloc[59] == 59.0

    def test_missing_tmy_data_returns_zero(self):
        """Missing TMY timestamps return zero."""
        # TMY data only for noon
        tmy_index = pd.date_range("2024-06-21 12:00", periods=1, freq="1min")
        tmy_gen = pd.Series([5.0], index=tmy_index)

        # Demand for earlier time
        demand_index = pd.date_range("2025-06-21 10:00", periods=60, freq="1min")
        demand = pd.Series([1.0] * 60, index=demand_index)

        aligned = _align_tmy_to_demand(tmy_gen, demand)

        # Most values should be zero since TMY data doesn't cover this time
        assert aligned.iloc[0] == 0.0

    def test_leap_day_has_no_tmy_match_and_maps_to_zero(self, tmy_minute_year):
        demand = _london_minute_demand("2024-02-28 00:00", "2024-03-01 23:59")

        aligned = _align_tmy_to_demand(tmy_minute_year, demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-02-28"],
            np.zeros(1440),
            tmy_minute_year.loc["1990-03-01"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_spring_forward_day_matches_tmy_by_utc_instant(self, tmy_minute_year):
        demand = _london_minute_demand("2024-03-31 00:00", "2024-03-31 23:59")
        assert len(demand) == 1380

        aligned = _align_tmy_to_demand(tmy_minute_year, demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-03-31 00:00":"1990-03-31 22:59"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_fall_back_day_repeated_local_hour_takes_consecutive_utc_hours(self, tmy_minute_year):
        demand = _london_minute_demand("2024-10-27 00:00", "2024-10-27 23:59")
        assert len(demand) == 1500

        aligned = _align_tmy_to_demand(tmy_minute_year, demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-10-26 23:00":"1990-10-27 23:59"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_bst_day_matches_tmy_by_utc_instant(self, tmy_minute_year):
        demand = _london_minute_demand("2024-06-21 00:00", "2024-06-21 23:59")

        aligned = _align_tmy_to_demand(tmy_minute_year, demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-06-20 23:00":"1990-06-21 22:59"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_naive_tmy_is_read_as_utc(self, tmy_minute_year):
        demand = _london_minute_demand("2024-06-21 00:00", "2024-06-21 23:59")

        aligned = _align_tmy_to_demand(tmy_minute_year.tz_localize(None), demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-06-20 23:00":"1990-06-21 22:59"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_tmy_in_the_demands_timezone_aligns_minute_for_minute(self):
        tmy = pd.Series(
            np.arange(1, 1441, dtype=float),
            index=pd.date_range("1990-06-21", periods=1440, freq="1min", tz="Europe/London"),
        )
        demand = _london_minute_demand("2024-06-21 00:00", "2024-06-21 23:59")

        aligned = _align_tmy_to_demand(tmy, demand)

        expected = _expected_alignment(demand, np.arange(1, 1441, dtype=float))
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_range_crossing_year_end_wraps_to_start_of_tmy_year(self, tmy_minute_year):
        demand = _london_minute_demand("2024-12-31 00:00", "2025-01-01 23:59")

        aligned = _align_tmy_to_demand(tmy_minute_year, demand)

        expected = _expected_alignment(
            demand,
            tmy_minute_year.loc["1990-12-31"],
            tmy_minute_year.loc["1990-01-01"],
        )
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_repeated_tmy_time_of_year_keeps_the_later_value(self):
        earlier = pd.Series(
            np.arange(1, 1441, dtype=float),
            index=pd.date_range("1990-06-21", periods=1440, freq="1min"),
        )
        later = pd.Series(
            np.arange(10_001, 11_441, dtype=float),
            index=pd.date_range("1991-06-21", periods=1440, freq="1min"),
        )
        demand = pd.Series(1.0, index=pd.date_range("2024-06-21", periods=1440, freq="1min"))

        aligned = _align_tmy_to_demand(pd.concat([earlier, later]), demand)

        pd.testing.assert_series_equal(aligned, _expected_alignment(demand, later), check_exact=True)

    def test_nan_in_tmy_is_kept_and_only_unmatched_minutes_map_to_zero(self):
        tmy = pd.Series([np.nan], index=pd.to_datetime(["1990-06-21 12:00"]))
        demand = pd.Series(1.0, index=pd.date_range("2024-06-21 12:00", periods=2, freq="1min"))

        aligned = _align_tmy_to_demand(tmy, demand)

        expected = _expected_alignment(demand, np.array([np.nan, 0.0]))
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_repeated_tmy_time_of_year_keeps_a_later_nan(self):
        tmy = pd.Series([5.0, np.nan], index=pd.to_datetime(["1990-06-21 12:00", "1991-06-21 12:00"]))
        demand = pd.Series(1.0, index=pd.to_datetime(["2024-06-21 12:00"]))

        aligned = _align_tmy_to_demand(tmy, demand)

        expected = _expected_alignment(demand, np.array([np.nan]))
        pd.testing.assert_series_equal(aligned, expected, check_exact=True)

    def test_result_takes_the_tmy_series_name_not_the_demands(self):
        tmy = pd.Series([7.0], index=pd.to_datetime(["1990-06-21 12:00"]), name="temp_air")
        demand = pd.Series(1.0, index=pd.to_datetime(["2024-06-21 12:00"]), name="demand_kw")

        aligned = _align_tmy_to_demand(tmy, demand)

        assert aligned.name == "temp_air"

    def test_full_year_minute_tmy_aligns_within_cpu_budget(self, tmy_minute_year):
        demand = _london_minute_demand("2024-06-01 00:00", "2024-06-01 23:59")
        budget_cpu_seconds = 1.0

        started = time.thread_time()
        _align_tmy_to_demand(tmy_minute_year, demand)
        cpu_seconds = time.thread_time() - started

        assert cpu_seconds < budget_cpu_seconds, (
            f"aligning a full-year minute TMY took {cpu_seconds:.2f} s of CPU; "
            f"the budget is {budget_cpu_seconds} s"
        )


def _utc_tmy_with_one_marked_hour(marked_hour_utc: str, **marked: float) -> pd.DataFrame:
    """Two days of hourly UTC 1990 weather, the shape of a PVGIS TMY.

    It is dark and 25 °C except for the marked hour's columns. It spans 20-21 June UTC, so every
    minute of the BST day 21 June has weather.
    """
    weather = pd.DataFrame(
        {"ghi": 0.0, "dni": 0.0, "dhi": 0.0, "temp_air": 25.0, "wind_speed": 2.0},
        index=pd.date_range("1990-06-20 00:00", "1990-06-21 23:00", freq="1h", tz="UTC"),
    )
    for column, value in marked.items():
        weather.loc[pd.Timestamp(marked_hour_utc, tz="UTC"), column] = value
    return weather


_NOON_HOUR_BST_ON_2024_06_21 = pd.date_range(
    "2024-06-21 12:00", periods=60, freq="1min", tz="Europe/London"
)


class TestSimulateHomeAlignsWeatherByUTCInstant:
    """A TMY hour reaches simulate_home's results at its UTC instant, whatever the local clock says."""

    def test_pv_output_during_bst_lands_at_the_tmy_hours_utc_instant(self):
        weather = _utc_tmy_with_one_marked_hour("1990-06-21 11:00", ghi=800.0, dni=850.0, dhi=150.0)
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(seed=42),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=weather,
        )

        pd.testing.assert_index_equal(
            results.generation.index[results.generation > 0],
            _NOON_HOUR_BST_ON_2024_06_21,
            check_names=False,
        )

    def test_heat_pump_during_bst_sees_the_tmy_hours_utc_instant(self):
        weather = _utc_tmy_with_one_marked_hour("1990-06-21 11:00", temp_air=5.0)
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(seed=42),
            heat_pump_config=HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=8000.0,
            ),
            location=Location.bristol(),
        )

        results = simulate_home(
            config,
            start_date=pd.Timestamp("2024-06-21"),
            end_date=pd.Timestamp("2024-06-21"),
            weather_data=weather,
        )

        assert results.heat_pump_load is not None
        pd.testing.assert_index_equal(
            results.heat_pump_load.index[results.heat_pump_load > 0],
            _NOON_HOUR_BST_ON_2024_06_21,
            check_names=False,
        )
