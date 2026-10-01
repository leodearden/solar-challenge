"""Tests for configuration file support."""

import json
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any, TypeAlias

import pandas as pd
import pytest
import yaml

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityConfig
from solar_challenge.config import (
    BatteryDistributionConfig,
    ConfigurationError,
    DispatchStrategyConfig,
    FinanceConfig,
    FleetDistributionConfig,
    GridChargeConfig,
    HeatPumpDistributionConfig,
    LoadDistributionConfig,
    NormalDistribution,
    OutputConfig,
    ParameterSweepConfig,
    PVDistributionConfig,
    ScenarioConfig,
    SimulationPeriod,
    UniformDistribution,
    WeightedDiscreteDistribution,
    load_community_config,
    generate_homes_from_distribution,
    load_config,
    load_config_json,
    load_config_yaml,
    load_fleet_config,
    load_home_config,
    load_scenarios,
    parse_dispatch_strategy_config,
    parse_finance_config,
    parse_fleet_distribution_config,
    parse_home_block,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
    run_parameter_sweep,
)
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, calculate_degradation_factor
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig, TariffPeriod
from solar_challenge.weather import WeatherCache, set_weather_cache
from tests._synthetic_weather import synthetic_june_weather


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

    _DAY = "2024-06-21"
    _AGED_ARRAY = PVConfig(
        capacity_kw=4.0,
        system_age_years=20.0,
        degradation_rate_per_year=0.008,
    )
    _LOAD = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)

    @pytest.fixture
    def synthetic_tmy(self, tmp_path: Path) -> Iterator[None]:
        """Serve a clear June day as Bristol's TMY, so the sweep and the reference simulation need no PVGIS call."""
        cache = WeatherCache(cache_dir=tmp_path / "weather")
        cache.put(synthetic_june_weather(self._DAY), "tmy", Location.bristol())
        set_weather_cache(cache)
        yield
        set_weather_cache(None)

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
        period = SimulationPeriod(start_date=self._DAY, end_date=self._DAY)
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
        )
        assert point.parameter_value == value
        assert isinstance(point.results, SimulationResults)
        pd.testing.assert_series_equal(point.results.generation, expected.generation)
