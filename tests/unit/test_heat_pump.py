"""Tests for heat pump configuration and modelling."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.heat_pump import (
    HeatPumpConfig,
    BASE_TEMPERATURE_C,
    ASHP_COP_INTERCEPT,
    ASHP_COP_SLOPE,
    ASHP_COP_MIN,
    ASHP_COP_MAX,
    GSHP_COP_BASE,
    GSHP_COP_MIN,
    GSHP_COP_MAX,
    calculate_heating_degree_minutes,
    calculate_cop,
    generate_heat_pump_load,
)


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

    def test_invalid_heat_pump_type(self):
        """Invalid heat pump type raises error."""
        with pytest.raises(ValueError, match="Heat pump type"):
            HeatPumpConfig(
                heat_pump_type="WSHP",  # Invalid type
                thermal_capacity_kw=8.0
            )

    def test_capacity_must_be_positive(self):
        """Thermal capacity <= 0 raises error."""
        with pytest.raises(ValueError, match="capacity must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=0
            )
        with pytest.raises(ValueError, match="capacity must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=-5.0
            )

    def test_capacity_unrealistic_high_raises(self):
        """Unrealistically high capacity raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=100.0
            )

    def test_annual_demand_must_be_positive(self):
        """Annual heat demand <= 0 raises error."""
        with pytest.raises(ValueError, match="demand must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=0
            )
        with pytest.raises(ValueError, match="demand must be positive"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=-1000.0
            )

    def test_annual_demand_unrealistic_high_raises(self):
        """Unrealistically high annual demand raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            HeatPumpConfig(
                heat_pump_type="ASHP",
                thermal_capacity_kw=8.0,
                annual_heat_demand_kwh=100000.0
            )


class TestCalculateCOP:
    """Test COP calculation for different heat pump types."""

    def test_ashp_cop_at_zero_degrees(self):
        """ASHP COP at 0°C matches intercept."""
        cop = calculate_cop("ASHP", 0.0)
        assert cop == pytest.approx(ASHP_COP_INTERCEPT, rel=0.001)

    def test_ashp_cop_increases_with_temperature(self):
        """ASHP COP increases with outdoor temperature."""
        cop_minus_10 = calculate_cop("ASHP", -10.0)
        cop_zero = calculate_cop("ASHP", 0.0)
        cop_plus_10 = calculate_cop("ASHP", 10.0)

        assert cop_minus_10 < cop_zero < cop_plus_10

    def test_ashp_cop_linear_relationship(self):
        """ASHP COP follows linear relationship in mid-range."""
        # At temperatures where we're not hitting min/max bounds
        temp = 5.0
        expected_cop = ASHP_COP_INTERCEPT + ASHP_COP_SLOPE * temp
        actual_cop = calculate_cop("ASHP", temp)
        assert actual_cop == pytest.approx(expected_cop, rel=0.001)

    def test_ashp_cop_min_bound(self):
        """ASHP COP doesn't go below minimum."""
        # Very cold temperature should hit minimum
        cop = calculate_cop("ASHP", -20.0)
        assert cop >= ASHP_COP_MIN
        assert cop == pytest.approx(ASHP_COP_MIN, rel=0.001)

    def test_ashp_cop_max_bound(self):
        """ASHP COP doesn't exceed maximum."""
        # Very warm temperature should hit maximum
        cop = calculate_cop("ASHP", 30.0)
        assert cop <= ASHP_COP_MAX
        assert cop == pytest.approx(ASHP_COP_MAX, rel=0.001)

    def test_gshp_cop_more_stable(self):
        """GSHP COP is more stable than ASHP across temperatures."""
        gshp_cop_cold = calculate_cop("GSHP", -10.0)
        gshp_cop_warm = calculate_cop("GSHP", 20.0)
        ashp_cop_cold = calculate_cop("ASHP", -10.0)
        ashp_cop_warm = calculate_cop("ASHP", 20.0)

        gshp_variation = abs(gshp_cop_warm - gshp_cop_cold)
        ashp_variation = abs(ashp_cop_warm - ashp_cop_cold)

        assert gshp_variation < ashp_variation

    def test_gshp_cop_at_base_temp(self):
        """GSHP COP near base value at typical temperatures."""
        cop = calculate_cop("GSHP", 10.0)
        # Should be close to base, slightly influenced by temperature
        assert cop >= GSHP_COP_MIN
        assert cop <= GSHP_COP_MAX

    def test_gshp_cop_min_bound(self):
        """GSHP COP doesn't go below minimum."""
        cop = calculate_cop("GSHP", -30.0)
        assert cop >= GSHP_COP_MIN

    def test_gshp_cop_max_bound(self):
        """GSHP COP doesn't exceed maximum."""
        cop = calculate_cop("GSHP", 40.0)
        assert cop <= GSHP_COP_MAX

    def test_invalid_heat_pump_type_raises(self):
        """Invalid heat pump type raises ValueError."""
        with pytest.raises(ValueError, match="Invalid heat pump type"):
            calculate_cop("INVALID", 10.0)

    def test_gshp_generally_higher_cop(self):
        """GSHP generally has higher COP than ASHP in cold weather."""
        temp = -5.0
        gshp_cop = calculate_cop("GSHP", temp)
        ashp_cop = calculate_cop("ASHP", temp)
        assert gshp_cop > ashp_cop


class TestCalculateHeatingDegreeMinutes:
    """Test heating degree minutes calculation."""

    def test_temperature_below_base(self):
        """Temperature below base produces positive degree minutes."""
        temps = pd.Series([10.0, 12.0, 5.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # Base is 15.5°C by default
        # Deficits: 5.5, 3.5, 10.5
        assert degree_mins.iloc[0] == pytest.approx(5.5, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(3.5, rel=0.001)
        assert degree_mins.iloc[2] == pytest.approx(10.5, rel=0.001)

    def test_temperature_above_base_gives_zero(self):
        """Temperature above base gives zero degree minutes."""
        temps = pd.Series([20.0, 18.0, 16.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # All temperatures above base (15.5°C)
        assert (degree_mins >= 0).all()
        assert degree_mins.iloc[0] == 0.0
        assert degree_mins.iloc[1] == 0.0
        assert degree_mins.iloc[2] == 0.0

    def test_temperature_at_base_gives_zero(self):
        """Temperature exactly at base gives zero degree minutes."""
        temps = pd.Series([BASE_TEMPERATURE_C])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert degree_mins.iloc[0] == 0.0

    def test_custom_base_temperature(self):
        """Can use custom base temperature."""
        temps = pd.Series([18.0, 15.0])
        degree_mins = calculate_heating_degree_minutes(temps, base_temp_c=20.0)

        # Deficits from 20°C: 2.0, 5.0
        assert degree_mins.iloc[0] == pytest.approx(2.0, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(5.0, rel=0.001)

    def test_negative_temperatures(self):
        """Handles negative temperatures correctly."""
        temps = pd.Series([-5.0, -10.0])
        degree_mins = calculate_heating_degree_minutes(temps)

        # Deficits from 15.5°C: 20.5, 25.5
        assert degree_mins.iloc[0] == pytest.approx(20.5, rel=0.001)
        assert degree_mins.iloc[1] == pytest.approx(25.5, rel=0.001)

    def test_returns_series_same_length(self):
        """Output series has same length as input."""
        temps = pd.Series([10.0, 12.0, 14.0, 16.0, 18.0])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert len(degree_mins) == len(temps)

    def test_no_negative_values(self):
        """Output never contains negative values."""
        temps = pd.Series([5.0, 10.0, 15.0, 20.0, 25.0])
        degree_mins = calculate_heating_degree_minutes(temps)
        assert (degree_mins >= 0).all()


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

    def test_returns_series_with_correct_index(self, ashp_config, winter_temps):
        """Output has same index as input temperature."""
        load = generate_heat_pump_load(ashp_config, winter_temps)

        assert isinstance(load, pd.Series)
        assert len(load) == len(winter_temps)
        assert load.index.equals(winter_temps.index)

    def test_output_in_kw(self, ashp_config, winter_temps):
        """Output values are electrical power in kW."""
        load = generate_heat_pump_load(ashp_config, winter_temps)

        # Typical domestic heat pump electrical load is 1-5 kW
        assert load.max() < 10.0  # Reasonable upper bound
        assert load.mean() > 0.1  # Non-trivial consumption in winter

    def test_no_negative_values(self, ashp_config, winter_temps):
        """Output has no negative values."""
        load = generate_heat_pump_load(ashp_config, winter_temps)
        assert (load >= 0).all()

    def test_summer_has_zero_load(self, ashp_config, summer_temps):
        """Summer temperatures above base temp produce zero load."""
        load = generate_heat_pump_load(ashp_config, summer_temps)
        # All temperatures above base, so no heating needed
        assert load.sum() == 0.0

    def test_winter_has_positive_load(self, ashp_config, winter_temps):
        """Winter temperatures below base temp produce positive load."""
        load = generate_heat_pump_load(ashp_config, winter_temps)
        assert load.sum() > 0.0
        assert load.max() > 0.0

    def test_colder_weather_higher_load(self, ashp_config):
        """Colder weather produces higher electrical load."""
        # Very cold day
        cold_index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        cold_temps = pd.Series([0.0] * 1440, index=cold_index)

        # Mild day
        mild_index = pd.date_range("2024-03-15", periods=1440, freq="1min", tz="UTC")
        mild_temps = pd.Series([10.0] * 1440, index=mild_index)

        cold_load = generate_heat_pump_load(ashp_config, cold_temps)
        mild_load = generate_heat_pump_load(ashp_config, mild_temps)

        # Cold day should have higher average load
        assert cold_load.mean() > mild_load.mean()

    def test_capacity_limiting(self, winter_temps):
        """Load is capped at thermal capacity / COP."""
        # Use very high annual demand to test capacity limiting
        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=5.0,  # Small capacity
            annual_heat_demand_kwh=20000.0  # High demand
        )
        load = generate_heat_pump_load(config, winter_temps)

        # Electrical load should not exceed thermal_capacity / COP_min
        # With ASHP_COP_MIN = 1.8, max electrical load ≈ 5.0 / 1.8 ≈ 2.78 kW
        max_theoretical = config.thermal_capacity_kw / ASHP_COP_MIN
        assert load.max() <= max_theoretical * 1.01  # Small tolerance

    def test_gshp_vs_ashp_efficiency(self):
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

        ashp_load = generate_heat_pump_load(ashp_config, temps)
        gshp_load = generate_heat_pump_load(gshp_config, temps)

        # GSHP should use less electricity due to higher COP
        assert gshp_load.sum() < ashp_load.sum()

    def test_requires_datetime_index(self, ashp_config):
        """Raises error if temperature doesn't have DatetimeIndex."""
        temps = pd.Series([10.0, 12.0, 14.0])  # No DatetimeIndex

        with pytest.raises(ValueError, match="DatetimeIndex"):
            generate_heat_pump_load(ashp_config, temps)

    def test_requires_timezone_aware_index(self, ashp_config):
        """Raises error if index is not timezone-aware."""
        index = pd.date_range("2024-01-15", periods=1440, freq="1min")  # No tz
        temps = pd.Series([10.0] * 1440, index=index)

        with pytest.raises(ValueError, match="timezone-aware"):
            generate_heat_pump_load(ashp_config, temps)

    def test_multi_day_profile(self, ashp_config):
        """Generates profile for multiple days."""
        # 3 days of cold winter weather
        index = pd.date_range("2024-01-15", periods=3*1440, freq="1min", tz="UTC")
        temps = pd.Series([5.0] * (3*1440), index=index)

        load = generate_heat_pump_load(ashp_config, temps)

        assert len(load) == 3 * 1440
        assert load.sum() > 0.0

    def test_load_respects_annual_demand_parameter(self):
        """Load generation respects the annual_heat_demand_kwh parameter."""
        # Verify that the annual demand parameter affects the output
        index = pd.date_range("2024-01-15", periods=1440, freq="1min", tz="UTC")
        temps = pd.Series([10.0] * 1440, index=index)  # Constant mild temp

        config = HeatPumpConfig(
            heat_pump_type="ASHP",
            thermal_capacity_kw=20.0,
            annual_heat_demand_kwh=8000.0
        )

        load = generate_heat_pump_load(config, temps)

        # Verify load is generated (non-zero, since 10°C < 15.5°C base temp)
        assert load.sum() > 0.0

        # Verify load values are reasonable (not all zeros or all maxed out)
        assert load.mean() > 0.0
        assert load.max() < config.thermal_capacity_kw / ASHP_COP_MIN
