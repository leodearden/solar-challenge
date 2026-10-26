"""Tests for heat pump configuration and modelling."""

import dataclasses
import doctest
import re
from typing import get_args

import numpy as np
import pandas as pd
import pytest
import solar_challenge.heat_pump
from solar_challenge.errors import ConfigurationError
from solar_challenge.heat_pump import (
    HeatPumpConfig,
    BASE_TEMPERATURE_C,
    COP_CURVES,
    CopCurve,
    HEAT_PUMP_TYPES,
    HeatPumpType,
    calculate_cop,
    generate_heat_pump_load,
    heating_degree_deficit_c,
)
from solar_challenge.timebase import SimulationWindow
from tests._unusable_numbers import UNUSABLE_NUMBERS


class TestHeatPumpConfigBasics:
    """Test basic HeatPumpConfig functionality."""

    def test_create_with_all_params(self):
        """HeatPumpConfig can be created with all parameters."""
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=10.0,
            annual_heat_demand_kwh=12000.0,
            name="Test heat pump"
        )
        assert config.heat_pump_type == "ASHP"
        assert config.thermal_capacity_kw == 10.0
        assert config.annual_heat_demand_kwh == 12000.0
        assert config.name == "Test heat pump"

    def test_create_gshp(self):
        """HeatPumpConfig can be created with GSHP type."""
        config = HeatPumpConfig(
            heat_pump_type="GSHP",
            thermal_capacity_kw=8.0,
        )
        assert config.heat_pump_type == "GSHP"
        assert config.thermal_capacity_kw == 8.0

    def test_default_values(self):
        """HeatPumpConfig uses sensible defaults."""
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=8.0
        )
        assert config.annual_heat_demand_kwh == 8000.0  # Typical UK home
        assert config.name == ""


class TestHeatPumpConfigDefaults:
    """Test default heat pump configurations."""

    def test_default_ashp(self):
        """Default ASHP has correct values."""
        config = HeatPumpConfig.default_ashp()
        assert config.heat_pump_type == "ASHP"
        assert config.thermal_capacity_kw == 8.0
        assert config.annual_heat_demand_kwh == 8000.0
        assert config.name  # Has a name

    def test_default_gshp(self):
        """Default GSHP has correct values."""
        config = HeatPumpConfig.default_gshp()
        assert config.heat_pump_type == "GSHP"
        assert config.thermal_capacity_kw == 8.0
        assert config.annual_heat_demand_kwh == 8000.0
        assert config.name  # Has a name


class TestHeatPumpConfigValidation:
    """Test parameter validation."""

    @pytest.mark.parametrize("thermal_capacity_kw", [0, -5.0])
    def test_capacity_must_be_positive(self, thermal_capacity_kw):
        """Thermal capacity <= 0 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=thermal_capacity_kw)
        assert str(exc_info.value) == (
            f"thermal_capacity_kw must be greater than 0 and at most 50, got {thermal_capacity_kw!r}"
        )

    def test_capacity_unrealistic_high_raises(self):
        """Unrealistically high capacity raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=100.0)
        assert str(exc_info.value) == "thermal_capacity_kw must be greater than 0 and at most 50, got 100.0"

    @pytest.mark.parametrize("annual_heat_demand_kwh", [0, -1000.0])
    def test_annual_demand_must_be_positive(self, annual_heat_demand_kwh):
        """Annual heat demand <= 0 raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=annual_heat_demand_kwh,
            )
        assert str(exc_info.value) == (
            f"annual_heat_demand_kwh must be greater than 0 and at most 50000, got {annual_heat_demand_kwh!r}"
        )

    def test_annual_demand_unrealistic_high_raises(self):
        """Unrealistically high annual demand raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=100000.0
            )
        assert str(exc_info.value) == (
            "annual_heat_demand_kwh must be greater than 0 and at most 50000, got 100000.0"
        )

    @pytest.mark.parametrize("field", ["thermal_capacity_kw", "annual_heat_demand_kwh"])
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_number_that_is_not_finite_is_refused_naming_its_field_and_the_value(self, field, value):
        """A NaN, an infinity, a bool or a word is refused by name, before any range is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(HeatPumpConfig.default_ashp(), **{field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    def test_whole_numbers_are_held_as_the_floats_they_equal(self):
        config = HeatPumpConfig("ASHP", 8, 8000)
        assert config.thermal_capacity_kw == 8.0
        assert type(config.thermal_capacity_kw) is float
        assert config.annual_heat_demand_kwh == 8000.0
        assert type(config.annual_heat_demand_kwh) is float


class TestCopCurve:
    """A CopCurve's COP is its line in the outdoor temperature, held between its minimum and maximum."""

    @pytest.mark.parametrize(
        ("outdoor_temp_c", "cop"),
        [
            pytest.param(-4.0, 2.0, id="line-at-1.0-held-up-to-minimum"),
            pytest.param(0.0, 3.0, id="intercept"),
            pytest.param(1.0, 3.5, id="on-the-line"),
            pytest.param(4.0, 4.0, id="line-at-5.0-held-down-to-maximum"),
        ],
    )
    def test_cop_is_the_line_held_between_minimum_and_maximum(self, outdoor_temp_c, cop):
        curve = CopCurve(intercept=3.0, slope=0.5, minimum=2.0, maximum=4.0)

        assert curve.cop(outdoor_temp_c) == cop

    def test_cops_is_each_rows_line_held_between_minimum_and_maximum(self):
        curve = CopCurve(intercept=3.0, slope=0.5, minimum=2.0, maximum=4.0)
        outdoor_temp_c = pd.Series(
            [-4.0, 0.0, 1.0, 4.0], index=pd.date_range("2025-01-15", periods=4, freq="1min", tz="UTC")
        )

        pd.testing.assert_series_equal(
            curve.cops(outdoor_temp_c),
            pd.Series([2.0, 3.0, 3.5, 4.0], index=outdoor_temp_c.index),
            check_exact=True,
        )

    def test_equal_bounds_give_a_constant_cop(self):
        curve = CopCurve(intercept=3.0, slope=0.5, minimum=3.0, maximum=3.0)

        assert curve.cop(-10.0) == 3.0
        assert curve.cop(10.0) == 3.0

    @pytest.mark.parametrize(
        ("minimum", "maximum"),
        [
            pytest.param(0.0, 4.0, id="zero-minimum"),
            pytest.param(-1.0, 4.0, id="negative-minimum"),
            pytest.param(4.5, 4.0, id="minimum-above-maximum"),
        ],
    )
    def test_bounds_must_satisfy_zero_below_minimum_at_most_maximum(self, minimum, maximum):
        with pytest.raises(ValueError, match=re.escape(f"got minimum={minimum}, maximum={maximum}")):
            CopCurve(intercept=3.0, slope=0.5, minimum=minimum, maximum=maximum)


class TestHeatPumpTypes:
    """HeatPumpType's Literal states the heat-pump types once; the runtime vocabulary and the COP curves follow it."""

    def test_the_literal_the_vocabulary_and_the_cop_curves_name_the_same_types(self):
        assert set(get_args(HeatPumpType)) == set(COP_CURVES) == set(HEAT_PUMP_TYPES)

    @pytest.mark.parametrize(
        "call_with_xshp",
        [
            pytest.param(lambda: HeatPumpConfig("XSHP", 8.0), id="heat-pump-config"),
            pytest.param(lambda: calculate_cop("XSHP", 0.0), id="calculate-cop"),
        ],
    )
    def test_a_type_outside_heat_pump_types_is_refused_naming_every_type(self, call_with_xshp):
        with pytest.raises(ConfigurationError, match=re.escape("Heat pump type must be one of ('ASHP', 'GSHP'), got 'XSHP'")):
            call_with_xshp()


class TestCalculateCOP:
    """Test COP calculation for different heat pump types."""

    @pytest.mark.parametrize(
        ("heat_pump_type", "expected"),
        [
            pytest.param("ASHP", [1.8, 2.0, 2.5, 3.2, 4.5, 4.5], id="ASHP"),
            pytest.param("GSHP", [3.4, 3.7, 3.8, 3.94, 4.2, 4.6], id="GSHP"),
        ],
    )
    def test_cop_at_the_prds_temperatures(self, heat_pump_type, expected):
        """The COPs of the PRD's §3.3, written as literals rather than read from COP_CURVES, so that an edited curve fails."""
        temperatures = (-20.0, -5.0, 0.0, 7.0, 20.0, 40.0)

        assert [calculate_cop(heat_pump_type, t) for t in temperatures] == pytest.approx(expected, abs=1e-12)

    @pytest.mark.parametrize(
        ("heat_pump_type", "outdoor_temp_c", "cop"),
        [
            pytest.param("ASHP", -50.0, 1.8, id="ASHP-floor"),
            pytest.param("ASHP", 50.0, 4.5, id="ASHP-ceiling"),
            pytest.param("GSHP", -60.0, 3.2, id="GSHP-floor"),
            pytest.param("GSHP", 60.0, 4.8, id="GSHP-ceiling"),
        ],
    )
    def test_each_type_is_held_to_its_floor_and_ceiling(self, heat_pump_type, outdoor_temp_c, cop):
        assert calculate_cop(heat_pump_type, outdoor_temp_c) == pytest.approx(cop, abs=1e-12)

    def test_ashp_cop_increases_with_temperature(self):
        """ASHP COP increases with outdoor temperature."""
        cop_minus_10 = calculate_cop("ASHP", -10.0)
        cop_zero = calculate_cop("ASHP", 0.0)
        cop_plus_10 = calculate_cop("ASHP", 10.0)

        assert cop_minus_10 < cop_zero < cop_plus_10

    def test_gshp_cop_more_stable(self):
        """GSHP COP is more stable than ASHP across temperatures."""
        gshp_cop_cold = calculate_cop("GSHP", -10.0)
        gshp_cop_warm = calculate_cop("GSHP", 20.0)
        ashp_cop_cold = calculate_cop("ASHP", -10.0)
        ashp_cop_warm = calculate_cop("ASHP", 20.0)

        gshp_variation = abs(gshp_cop_warm - gshp_cop_cold)
        ashp_variation = abs(ashp_cop_warm - ashp_cop_cold)

        assert gshp_variation < ashp_variation

    def test_gshp_generally_higher_cop(self):
        """GSHP generally has higher COP than ASHP in cold weather."""
        temp = -5.0
        gshp_cop = calculate_cop("GSHP", temp)
        ashp_cop = calculate_cop("ASHP", temp)
        assert gshp_cop > ashp_cop


class TestHeatingDegreeDeficit:
    """Test the per-row temperature deficit below the heating base temperature."""

    def test_temperature_below_base(self):
        """Temperature below base produces a positive deficit."""
        temps = pd.Series([10.0, 12.0, 5.0])
        deficit_c = heating_degree_deficit_c(temps)

        # Base is 15.5°C by default
        # Deficits: 5.5, 3.5, 10.5
        assert deficit_c.iloc[0] == pytest.approx(5.5, rel=0.001)
        assert deficit_c.iloc[1] == pytest.approx(3.5, rel=0.001)
        assert deficit_c.iloc[2] == pytest.approx(10.5, rel=0.001)

    def test_temperature_above_base_gives_zero(self):
        """Temperature above base gives a zero deficit."""
        temps = pd.Series([20.0, 18.0, 16.0])
        deficit_c = heating_degree_deficit_c(temps)

        # All temperatures above base (15.5°C)
        assert (deficit_c >= 0).all()
        assert deficit_c.iloc[0] == 0.0
        assert deficit_c.iloc[1] == 0.0
        assert deficit_c.iloc[2] == 0.0

    def test_temperature_at_base_gives_zero(self):
        """Temperature exactly at base gives a zero deficit."""
        temps = pd.Series([BASE_TEMPERATURE_C])
        deficit_c = heating_degree_deficit_c(temps)
        assert deficit_c.iloc[0] == 0.0

    def test_custom_base_temperature(self):
        """Can use custom base temperature."""
        temps = pd.Series([18.0, 15.0])
        deficit_c = heating_degree_deficit_c(temps, base_temp_c=20.0)

        # Deficits from 20°C: 2.0, 5.0
        assert deficit_c.iloc[0] == pytest.approx(2.0, rel=0.001)
        assert deficit_c.iloc[1] == pytest.approx(5.0, rel=0.001)

    def test_negative_temperatures(self):
        """Handles negative temperatures correctly."""
        temps = pd.Series([-5.0, -10.0])
        deficit_c = heating_degree_deficit_c(temps)

        # Deficits from 15.5°C: 20.5, 25.5
        assert deficit_c.iloc[0] == pytest.approx(20.5, rel=0.001)
        assert deficit_c.iloc[1] == pytest.approx(25.5, rel=0.001)

    def test_returns_series_same_length(self):
        """Output series has same length as input."""
        temps = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        deficit_c = heating_degree_deficit_c(temps)
        assert len(deficit_c) == len(temps)

    def test_no_negative_values(self):
        """Output never contains negative values."""
        temps = pd.Series([5.0, 10.0, 15.0, 20.0, 25.0])
        deficit_c = heating_degree_deficit_c(temps)
        assert (deficit_c >= 0).all()


def _utc_1990_minute_index() -> pd.DatetimeIndex:
    """The minutes of a PVGIS TMY year once interpolated to 1-minute resolution."""
    return pd.date_range("1990-01-01", periods=525_600, freq="1min", tz="UTC")


def _days_at(temperature_c: float, first_day: str, days: int = 1) -> pd.Series:
    """A constant temperature, minute by minute, over *days* whole Europe/London days from *first_day*."""
    index = pd.date_range(first_day, periods=days * 1440, freq="1min", tz="Europe/London")
    return pd.Series(temperature_c, index=index)


@pytest.fixture(scope="module")
def year_at_10c() -> pd.Series:
    """A reference year at a constant 10 °C: 5.5 heating degree-minutes in every minute."""
    return pd.Series(10.0, index=_utc_1990_minute_index())


@pytest.fixture(scope="module")
def seasonal_year() -> pd.Series:
    """A reference year that swings with the seasons and with the time of day.

    Its coldest minute is 0 °C at 03:00 on 15 January, its warmest 20 °C mid-afternoon in mid-July,
    when only the small hours fall below the 15.5 °C base temperature.
    """
    index = _utc_1990_minute_index()
    day_of_year_angle = 2 * np.pi * (index.dayofyear.to_numpy() - 15) / 365
    minute_of_day_angle = 2 * np.pi * (index.hour.to_numpy() * 60 + index.minute.to_numpy() - 180) / 1440
    return pd.Series(10.0 - 7.0 * np.cos(day_of_year_angle) - 3.0 * np.cos(minute_of_day_angle), index=index)


@pytest.fixture(scope="module")
def seasonal_year_load(seasonal_year) -> pd.Series:
    """The default ASHP's load over the whole of seasonal_year."""
    return generate_heat_pump_load(HeatPumpConfig.default_ashp(), seasonal_year, annual_temperature_c=seasonal_year)


class TestGenerateHeatPumpLoad:
    """Test heat pump load profile generation."""

    @pytest.fixture
    def ashp_config(self) -> HeatPumpConfig:
        """Standard ASHP test configuration."""
        return HeatPumpConfig.default_ashp()

    @pytest.fixture
    def gshp_config(self) -> HeatPumpConfig:
        """Standard GSHP test configuration."""
        return HeatPumpConfig.default_gshp()

    @pytest.fixture
    def winter_temps(self) -> pd.Series:
        """Winter day temperature profile."""
        # Cold winter day, one day at 1-minute resolution
        index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        # Temperature varies between 2°C and 8°C
        temps = 5.0 + 3.0 * np.sin(np.linspace(0, 2*np.pi, 1440))
        return pd.Series(temps, index=index)

    @pytest.fixture
    def summer_temps(self) -> pd.Series:
        """Summer day temperature profile."""
        # Warm summer day, one day at 1-minute resolution
        index = pd.date_range("2024-06-21", periods=1440, freq="1min", tz="UTC")
        # Temperature varies between 16°C and 22°C (all above 15.5°C base temp)
        temps = 19.0 + 3.0 * np.sin(np.linspace(0, 2*np.pi, 1440))
        return pd.Series(temps, index=index)

    def test_returns_series_with_correct_index(self, ashp_config, winter_temps, year_at_10c):
        """Output has same index as input temperature."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)

        assert isinstance(load, pd.Series)
        assert len(load) == len(winter_temps)
        assert load.index.equals(winter_temps.index)

    def test_output_in_kw(self, ashp_config, winter_temps, year_at_10c):
        """Output values are electrical power in kW."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)

        # Typical domestic heat pump electrical load is 1-5 kW
        assert load.max() < 10.0  # Reasonable upper bound
        assert load.mean() > 0.1  # Non-trivial consumption in winter

    def test_no_negative_values(self, ashp_config, winter_temps, year_at_10c):
        """Output has no negative values."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)
        assert (load >= 0).all()

    def test_summer_has_zero_load(self, ashp_config, summer_temps, year_at_10c):
        """Summer temperatures above base temp produce zero load."""
        load = generate_heat_pump_load(ashp_config, summer_temps, annual_temperature_c=year_at_10c)
        # All temperatures above base, so no heating needed
        assert load.sum() == 0.0

    def test_winter_has_positive_load(self, ashp_config, winter_temps, year_at_10c):
        """Winter temperatures below base temp produce positive load."""
        load = generate_heat_pump_load(ashp_config, winter_temps, annual_temperature_c=year_at_10c)
        assert load.sum() > 0.0
        assert load.max() > 0.0

    def test_colder_weather_higher_load(self, ashp_config, year_at_10c):
        """Colder weather produces higher electrical load."""
        # Very cold day
        cold_index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        cold_temps = pd.Series([0.0] * 1440, index=cold_index)

        # Mild day
        mild_index = pd.date_range("2024-03-15", periods=1440, freq="1min", tz="UTC")
        mild_temps = pd.Series([10.0] * 1440, index=mild_index)

        cold_load = generate_heat_pump_load(ashp_config, cold_temps, annual_temperature_c=year_at_10c)
        mild_load = generate_heat_pump_load(ashp_config, mild_temps, annual_temperature_c=year_at_10c)

        # Cold day should have higher average load
        assert cold_load.mean() > mild_load.mean()

    def test_capacity_limiting(self, year_at_10c):
        """Heat is capped at the thermal capacity.

        Each minute of a -5 °C day would get 8.51 kW of heat from 20,000 kWh a year shared over a 10 °C year,
        more than the 5 kW capacity, so it draws 5 kW / COP.
        """
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=5.0,
            annual_heat_demand_kwh=20000.0,
        )
        day_at_minus_5c = _days_at(-5.0, "2025-01-15")

        load = generate_heat_pump_load(config, day_at_minus_5c, annual_temperature_c=year_at_10c)

        expected = pd.Series(5.0 / calculate_cop("ASHP", -5.0), index=day_at_minus_5c.index, name="heat_pump_load_kw")
        pd.testing.assert_series_equal(load, expected)

    def test_gshp_vs_ashp_efficiency(self, year_at_10c):
        """GSHP uses less electricity than ASHP for same thermal output."""
        # Cold weather where COP difference is significant
        index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        temps = pd.Series([0.0] * 1440, index=index)

        ashp_config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0
        )
        gshp_config = HeatPumpConfig(
            heat_pump_type="GSHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0
        )

        ashp_load = generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)
        gshp_load = generate_heat_pump_load(gshp_config, temps, annual_temperature_c=year_at_10c)

        # GSHP should use less electricity due to higher COP
        assert gshp_load.sum() < ashp_load.sum()

    def test_requires_datetime_index(self, ashp_config, year_at_10c):
        """Raises error if temperature doesn't have DatetimeIndex."""
        temps = pd.Series([10.0, 12.0, 14.0])  # No DatetimeIndex

        with pytest.raises(ValueError, match="DatetimeIndex"):
            generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

    def test_requires_timezone_aware_index(self, ashp_config, year_at_10c):
        """Raises error if index is not timezone-aware."""
        index = pd.date_range("2024-01-15", periods=1440, freq="1min")  # No tz
        temps = pd.Series([10.0] * 1440, index=index)

        with pytest.raises(ValueError, match="timezone-aware"):
            generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

    def test_multi_day_profile(self, ashp_config, year_at_10c):
        """Generates profile for multiple days."""
        # 3 days of cold winter weather
        index = pd.date_range("2024-01-15", periods=3*1440, freq="1min", tz="UTC")
        temps = pd.Series([5.0] * (3*1440), index=index)

        load = generate_heat_pump_load(ashp_config, temps, annual_temperature_c=year_at_10c)

        assert len(load) == 3 * 1440
        assert load.sum() > 0.0


class TestGenerateHeatPumpLoadSharesTheAnnualHeatDemand:
    """Each minute gets the annual heat demand in proportion to its share of the reference year's heating degree-minutes.

    Delivered heat is recovered from the electrical load as load × COP.
    """

    @pytest.mark.parametrize("days", [1, 30])
    def test_a_window_gets_its_days_share_of_a_constant_years_heat(self, days, year_at_10c):
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=20.0,
            annual_heat_demand_kwh=12000.0,
        )
        window = _days_at(10.0, "2025-01-15", days)

        load = generate_heat_pump_load(config, window, annual_temperature_c=year_at_10c)

        heat_delivered_kwh = (load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(days * 12000.0 / 365)

    @pytest.mark.parametrize(
        ("first_minute", "last_minute"),
        [
            pytest.param("1990-01-15", "1990-01-15 23:59", id="one-january-day"),
            pytest.param("1990-01-01", "1990-01-30 23:59", id="thirty-january-days"),
            pytest.param("1990-07-15", "1990-07-15 23:59", id="one-july-day"),
        ],
    )
    def test_a_window_draws_the_same_load_as_those_minutes_of_the_full_year_run(
        self, first_minute, last_minute, seasonal_year, seasonal_year_load
    ):
        window = seasonal_year.loc[first_minute:last_minute]

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), window, annual_temperature_c=seasonal_year)

        pd.testing.assert_series_equal(load, seasonal_year_load.loc[first_minute:last_minute])

    def test_a_summer_day_with_one_cool_hour_draws_only_that_hours_share(self, year_at_10c):
        summer_day = _days_at(20.0, "2025-07-15")
        summer_day.iloc[180:240] = 14.5

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), summer_day, annual_temperature_c=year_at_10c)

        year_heating_degree_minutes = 5.5 * 525_600
        cool_hour_heating_degree_minutes = 1.0 * 60
        cool_hour_heat_kwh = 8000.0 * cool_hour_heating_degree_minutes / year_heating_degree_minutes
        assert load.sum() / 60 == pytest.approx(cool_hour_heat_kwh / calculate_cop("ASHP", 14.5))

    def test_a_year_that_never_needs_heating_gives_no_load(self):
        year_at_20c = pd.Series(20.0, index=_utc_1990_minute_index())
        day_at_0c = _days_at(0.0, "2025-01-15")

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), day_at_0c, annual_temperature_c=year_at_20c)

        pd.testing.assert_series_equal(load, pd.Series(0.0, index=day_at_0c.index, name="heat_pump_load_kw"))


_MINUTE_YEAR_DESCRIPTION = "rows 0:01:00 apart (525,600 to 527,040)"


class TestGenerateHeatPumpLoadRejectsAReferenceThatIsNotAYear:
    """annual_temperature_c must be one year of its own rows, and any other reference raises ValueError naming what it got.

    One year is 365 to 366 days of rows at the spacing its index's window reads, and that spacing must divide one day.
    """

    @pytest.mark.parametrize(
        ("rows", "freq", "one_year"),
        [
            pytest.param(1440, "1min", _MINUTE_YEAR_DESCRIPTION, id="one-day-of-minutes"),
            pytest.param(365 * 1440 - 1, "1min", _MINUTE_YEAR_DESCRIPTION, id="one-minute-short-of-a-year"),
            pytest.param(366 * 1440 + 1, "1min", _MINUTE_YEAR_DESCRIPTION, id="one-minute-past-a-leap-year"),
            pytest.param(2 * 525_600, "1min", _MINUTE_YEAR_DESCRIPTION, id="two-years-of-minutes"),
            pytest.param(
                525_600, "30min", "rows 0:30:00 apart (17,520 to 17,568)", id="a-minute-years-count-of-half-hours"
            ),
            pytest.param(24, "1h", "rows 1:00:00 apart (8,760 to 8,784)", id="one-day-of-hours"),
        ],
    )
    def test_a_reference_that_is_not_one_year_of_its_rows_raises_naming_its_length_and_spacing(
        self, rows, freq, one_year
    ):
        reference = pd.Series(10.0, index=pd.date_range("1990-01-01", periods=rows, freq=freq, tz="UTC"))

        with pytest.raises(
            ValueError,
            match=re.escape(f"annual_temperature_c has {rows:,} rows, not one year of {one_year}"),
        ):
            generate_heat_pump_load(
                HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
            )

    @pytest.mark.parametrize(
        ("rows", "freq", "spacing"),
        [
            pytest.param(525_600, "7min", "0:07:00", id="a-minute-years-count-of-7-minute-rows"),
            pytest.param(183, "48h", "2 days, 0:00:00", id="a-years-span-of-2-day-rows"),
        ],
    )
    def test_a_reference_whose_spacing_does_not_divide_a_day_is_refused_naming_it(self, rows, freq, spacing):
        reference = pd.Series(10.0, index=pd.date_range("1990-01-01", periods=rows, freq=freq, tz="UTC"))

        with pytest.raises(
            ValueError,
            match=re.escape(f"annual_temperature_c's rows are {spacing} apart, which does not divide one day"),
        ):
            generate_heat_pump_load(
                HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
            )

    @pytest.mark.parametrize(
        ("days", "freq", "rows_per_day"),
        [
            pytest.param(365, "1min", 1440, id="365-days-of-minutes"),
            pytest.param(366, "1min", 1440, id="366-days-of-minutes"),
            pytest.param(365, "30min", 48, id="365-days-of-half-hours"),
            pytest.param(366, "30min", 48, id="366-days-of-half-hours"),
            pytest.param(365, "1h", 24, id="365-days-of-hours"),
            pytest.param(366, "1h", 24, id="366-days-of-hours"),
        ],
    )
    def test_a_whole_year_of_rows_at_a_spacing_that_divides_a_day_shares_the_demand_over_its_days(
        self, days, freq, rows_per_day
    ):
        reference = pd.Series(
            10.0, index=pd.date_range("1992-01-01", periods=days * rows_per_day, freq=freq, tz="UTC")
        )

        load = generate_heat_pump_load(
            HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
        )

        heat_delivered_kwh = (load * calculate_cop("ASHP", 10.0)).sum() / 60
        assert heat_delivered_kwh == pytest.approx(8000.0 / days)


class TestGenerateHeatPumpLoadIntegratesTheReferenceYearOverItsCadence:
    """The reference year's heating degrees are integrated over the cadence its index's window reads, so a window at any cadence gets its share, and a reference whose index no window describes is refused."""

    @pytest.mark.parametrize(
        ("build_reference", "match"),
        [
            pytest.param(
                lambda: pd.Series(10.0, index=pd.RangeIndex(525_600)),
                "RangeIndex",
                id="values-only-heating-year",
            ),
            pytest.param(
                lambda: pd.Series(20.0, index=pd.RangeIndex(525_600)),
                "RangeIndex",
                id="values-only-year-without-heating",
            ),
            pytest.param(
                lambda: pd.Series(10.0, index=pd.RangeIndex(1440)),
                "RangeIndex",
                id="values-only-day",
            ),
            pytest.param(
                lambda: pd.Series(
                    10.0,
                    index=pd.date_range("1992-01-01", periods=527_040, freq="1min", tz="UTC").delete(100_000),
                ),
                "position 100000",
                id="leap-year-missing-a-minute",
            ),
        ],
    )
    def test_a_reference_no_window_describes_is_refused(self, build_reference, match):
        reference = build_reference()

        with pytest.raises(ValueError, match=match):
            generate_heat_pump_load(
                HeatPumpConfig.default_ashp(), _days_at(10.0, "2025-01-15"), annual_temperature_c=reference
            )

    def test_a_half_hourly_window_gets_its_days_share_of_a_minute_years_heat(self, year_at_10c):
        window = pd.Series(10.0, index=pd.date_range("2025-01-15", periods=48, freq="30min", tz="Europe/London"))

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), window, annual_temperature_c=year_at_10c)

        heat_delivered_kwh = SimulationWindow.of_index(load.index).energy_kwh(load) * calculate_cop("ASHP", 10.0)
        assert heat_delivered_kwh == pytest.approx(8000.0 / 365)


class TestGenerateHeatPumpLoadNamesItsLoad:
    """generate_heat_pump_load names its load heat_pump_load_kw, not after its temperature input.

    That holds whether or not the reference year has any heating degree-minutes.
    The inputs are named temp_air, as simulate_home's are,
    so that naming the load only when it would otherwise be unnamed fails this test.
    """

    @pytest.mark.parametrize(
        "reference_temperature_c",
        [
            pytest.param(10.0, id="heating-year"),
            pytest.param(20.0, id="no-heating-year"),
        ],
    )
    def test_load_is_named_heat_pump_load_kw(self, reference_temperature_c):
        reference_year = pd.Series(reference_temperature_c, index=_utc_1990_minute_index(), name="temp_air")
        cold_day = _days_at(5.0, "2025-01-15").rename("temp_air")

        load = generate_heat_pump_load(HeatPumpConfig.default_ashp(), cold_day, annual_temperature_c=reference_year)

        assert load.name == "heat_pump_load_kw"


class TestHeatPumpDocstringExamples:
    """The examples in solar_challenge.heat_pump's docstrings run and hold."""

    def test_every_example_holds(self):
        failed, attempted = doctest.testmod(solar_challenge.heat_pump, verbose=False)

        assert attempted > 0
        assert failed == 0
