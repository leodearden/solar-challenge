# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for parameter sweeps: the values a ParameterSweepConfig yields and the scenarios run_parameter_sweep simulates."""

import math
from collections.abc import Iterator
from dataclasses import replace

import pandas as pd
import pytest

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import (
    ParameterSweepConfig,
    ScenarioConfig,
    SimulationPeriod,
    SweepResult,
    run_parameter_sweep,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.weather import WeatherCache, default_weather
from tests._seeded_tmy import ClearJuneDays

_DAY = "2024-06-21"

_JUNE_DAYS = ClearJuneDays(first_day=pd.Timestamp(_DAY), count=1)


class TestParameterSweepConfig:
    """Tests for ParameterSweepConfig class."""

    def test_explicit_values(self) -> None:
        """Test sweep with explicit values."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            values=[0, 5, 10, 15],
        )
        assert sweep.get_values() == [0, 5, 10, 15]

    def test_range_with_step(self) -> None:
        """Test sweep with range and step."""
        sweep = ParameterSweepConfig(
            parameter_name="battery_capacity_kwh",
            min_value=0,
            max_value=10,
            step=2,
        )
        values = sweep.get_values()
        assert values == [0, 2, 4, 6, 8, 10]

    def test_range_with_n_steps(self) -> None:
        """Test sweep with range and n_steps."""
        sweep = ParameterSweepConfig(
            parameter_name="pv_capacity_kw",
            min_value=2,
            max_value=6,
            n_steps=4,
        )
        values = sweep.get_values()
        assert len(values) == 5
        assert values[0] == 2
        assert values[-1] == 6

    def test_empty_values_raises(self) -> None:
        """Test that empty values list raises error."""
        with pytest.raises(ConfigurationError, match="cannot be empty"):
            ParameterSweepConfig(
                parameter_name="test",
                values=[],
            )

    def test_invalid_range_raises(self) -> None:
        """Test that invalid range raises error."""
        with pytest.raises(ConfigurationError, match="must be less than"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=10,
                max_value=5,
                step=1,
            )

    def test_missing_step_raises(self) -> None:
        """Test that missing step raises error."""
        with pytest.raises(ConfigurationError, match="requires either"):
            ParameterSweepConfig(
                parameter_name="test",
                min_value=0,
                max_value=10,
            )


class TestPVParameterSweepPreservesDegradation:
    """A PV parameter sweep simulates the base home's aged array with only the swept parameter changed."""

    _AGED_ARRAY = PVConfig(
        capacity_kw=4.0,
        system_age_years=20.0,
        degradation_rate_per_year=0.008,
    )
    _LOAD = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)

    @pytest.fixture
    def synthetic_tmy(self, weather_cache: WeatherCache) -> None:
        """Serve a clear June day as Bristol's TMY, so the sweep and the reference simulation need no PVGIS call."""
        _JUNE_DAYS.seed_as_bristol_tmy(weather_cache)

    @pytest.mark.usefixtures("synthetic_tmy")
    @pytest.mark.parametrize(
        ("parameter_name", "pv_field", "value"),
        [
            ("pv_capacity_kw", "capacity_kw", 6.0),
            ("pv_tilt", "tilt", 45.0),
            ("pv_azimuth", "azimuth", 90.0),
        ],
    )
    def test_swept_array_keeps_its_age_and_degradation_rate(
        self, parameter_name: str, pv_field: str, value: float
    ) -> None:
        """Generation matches the aged array with *pv_field* set to *value*, so age and rate carried over."""
        period = SimulationPeriod(start_date=_DAY, end_date=_DAY)
        scenario = ScenarioConfig(
            name="aged array",
            period=period,
            home=HomeConfig(pv_config=self._AGED_ARRAY, load_config=self._LOAD),
        )

        [point] = run_parameter_sweep(
            scenario, ParameterSweepConfig(parameter_name=parameter_name, values=[value])
        )

        expected = simulate_home(
            HomeConfig(
                pv_config=replace(self._AGED_ARRAY, **{pv_field: value}),
                load_config=self._LOAD,
            ),
            period.get_start_timestamp(),
            period.get_end_timestamp(),
            weather=default_weather(),
        )
        assert point.parameter_value == value
        assert isinstance(point.results, SimulationResults)
        pd.testing.assert_series_equal(point.results.generation, expected.generation)


class TestBatteryCapacitySweepRefusesAValueThatIsNotACapacity:
    """A battery_capacity_kwh sweep refuses a value that is negative or not finite, naming the parameter, instead of simulating it as no battery."""

    @pytest.fixture
    def synthetic_tmy(self, weather_cache: WeatherCache) -> None:
        """Serve a clear June day as Bristol's TMY, so a sweep that simulates a value as no battery fails its assertion instead of reaching PVGIS."""
        _JUNE_DAYS.seed_as_bristol_tmy(weather_cache)

    @pytest.mark.usefixtures("synthetic_tmy")
    @pytest.mark.parametrize(
        "battery",
        [
            pytest.param(None, id="no-battery"),
            pytest.param(BatteryConfig(capacity_kwh=5.0), id="battery"),
        ],
    )
    @pytest.mark.parametrize("value", [math.nan, math.inf, -1.0])
    def test_a_value_that_is_not_a_capacity_is_refused_naming_the_parameter(
        self, value: float, battery: BatteryConfig | None
    ) -> None:
        scenario = ScenarioConfig(
            name="battery sweep",
            period=SimulationPeriod(start_date=_DAY, end_date=_DAY),
            home=HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False),
                battery_config=battery,
            ),
        )
        sweep = run_parameter_sweep(
            scenario, ParameterSweepConfig(parameter_name="battery_capacity_kwh", values=[value])
        )

        with pytest.raises(ValueError) as exc_info:
            next(sweep)
        assert str(exc_info.value) == (
            f"battery_capacity_kwh must be >= 0 and finite (0 for no battery), got {value} kWh"
        )


class TestHouseholdOccupantsSweepHoldsEachValueToLoadConfigsRule:
    """A household_occupants sweep holds each value, as given, to LoadConfig's occupant rule: it refuses a fraction or a boolean, which the sweep truncated to an int, and reads a whole-number float as the int it equals."""

    @pytest.fixture
    def synthetic_tmy(self, weather_cache: WeatherCache) -> None:
        """Serve a clear June day as Bristol's TMY, so a sweep that simulates a truncated count fails its assertion instead of reaching PVGIS."""
        _JUNE_DAYS.seed_as_bristol_tmy(weather_cache)

    @staticmethod
    def _home(household_occupants: int) -> HomeConfig:
        """A 4 kW home whose deterministic load follows Ofgem's TDCV for *household_occupants*."""
        return HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(household_occupants=household_occupants, use_stochastic=False),
        )

    def _sweep(self, value: float) -> Iterator[SweepResult]:
        """Sweep a 3-occupant home's household_occupants over the one *value*, for one June day."""
        return run_parameter_sweep(
            ScenarioConfig(
                name="occupants sweep",
                period=SimulationPeriod(start_date=_DAY, end_date=_DAY),
                home=self._home(3),
            ),
            ParameterSweepConfig(parameter_name="household_occupants", values=[value]),
        )

    @pytest.mark.usefixtures("synthetic_tmy")
    @pytest.mark.parametrize(
        ("value", "refusal"),
        [
            pytest.param(2.5, "household_occupants must be a whole number, got 2.5", id="fraction"),
            pytest.param(True, "household_occupants must be a finite number, got True", id="boolean"),
        ],
    )
    def test_a_value_that_is_not_a_whole_number_is_refused_as_load_config_refuses_it(
        self, value: float, refusal: str
    ) -> None:
        """The sweep point is refused with LoadConfig's message, never simulated with a truncated count."""
        with pytest.raises(ValueError) as exc_info:
            next(self._sweep(value))
        assert str(exc_info.value) == refusal

    @pytest.mark.usefixtures("synthetic_tmy")
    def test_a_whole_number_float_simulates_that_many_occupants(self) -> None:
        """A swept 2.0, as a linear sweep's points are floats, simulates the 2-occupant home: its demand follows TDCV's 2700 kWh/yr, not the base home's 3200."""
        [point] = self._sweep(2.0)

        period = SimulationPeriod(start_date=_DAY, end_date=_DAY)
        expected = simulate_home(
            self._home(2), period.get_start_timestamp(), period.get_end_timestamp(), weather=default_weather()
        )
        assert point.parameter_value == 2.0
        assert isinstance(point.results, SimulationResults)
        pd.testing.assert_series_equal(point.results.demand, expected.demand)
