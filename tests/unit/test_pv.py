"""Tests for PV configuration."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.location import Location
from solar_challenge.pv import (
    PVConfig,
    apply_degradation,
    calculate_degradation_factor,
    create_model_chain,
    create_pv_system,
    create_simple_inverter_params,
    create_simple_module_params,
    interpolate_to_minute_resolution,
    simulate_pv_output,
)


class TestPVConfigBasics:
    """Test basic PVConfig functionality."""

    def test_create_with_all_params(self):
        """PVConfig can be created with all parameters."""
        config = PVConfig(
            capacity_kw=5.0,
            azimuth=170.0,
            tilt=30.0,
            name="Test system"
        )
        assert config.capacity_kw == 5.0
        assert config.azimuth == 170.0
        assert config.tilt == 30.0
        assert config.name == "Test system"

    def test_default_values(self):
        """PVConfig uses correct defaults."""
        config = PVConfig(capacity_kw=4.0)
        assert config.azimuth == 180.0  # South-facing
        assert config.tilt == 35.0  # UK optimal
        assert config.name == ""

    def test_degradation_fields_default_values(self):
        """PVConfig exposes system_age_years and degradation_rate_per_year with correct defaults."""
        config = PVConfig(capacity_kw=4.0)
        assert config.system_age_years == 0.0
        assert config.degradation_rate_per_year == 0.005

    def test_degradation_fields_store_explicit_values(self):
        """PVConfig stores explicitly provided system_age_years and degradation_rate_per_year."""
        config = PVConfig(capacity_kw=4.0, system_age_years=20, degradation_rate_per_year=0.01)
        assert config.system_age_years == 20.0
        assert config.degradation_rate_per_year == 0.01


class TestPVConfigDefaults:
    """Test default system configurations."""

    def test_default_4kw(self):
        """Default 4 kW system has correct values."""
        config = PVConfig.default_4kw()
        assert config.capacity_kw == 4.0
        assert config.azimuth == 180.0
        assert config.tilt == 35.0
        assert config.name  # Has a name


class TestPVConfigValidation:
    """Test parameter validation."""

    def test_capacity_must_be_positive(self):
        """Capacity <= 0 raises error."""
        with pytest.raises(ValueError, match="Capacity"):
            PVConfig(capacity_kw=0)
        with pytest.raises(ValueError, match="Capacity"):
            PVConfig(capacity_kw=-1.0)

    def test_azimuth_range(self):
        """Azimuth must be 0-360."""
        # Valid boundary values
        PVConfig(capacity_kw=1.0, azimuth=0.0)
        PVConfig(capacity_kw=1.0, azimuth=360.0)

        # Invalid values
        with pytest.raises(ValueError, match="Azimuth"):
            PVConfig(capacity_kw=1.0, azimuth=-1.0)
        with pytest.raises(ValueError, match="Azimuth"):
            PVConfig(capacity_kw=1.0, azimuth=361.0)

    def test_tilt_range(self):
        """Tilt must be 0-90."""
        # Valid boundary values
        PVConfig(capacity_kw=1.0, tilt=0.0)
        PVConfig(capacity_kw=1.0, tilt=90.0)

        # Invalid values
        with pytest.raises(ValueError, match="Tilt"):
            PVConfig(capacity_kw=1.0, tilt=-1.0)
        with pytest.raises(ValueError, match="Tilt"):
            PVConfig(capacity_kw=1.0, tilt=91.0)


class TestCreatePVSystem:
    """Test PV-002: pvlib PVSystem creation from config."""

    def test_creates_pvsystem(self):
        """create_pv_system returns a pvlib PVSystem."""
        config = PVConfig(capacity_kw=4.0)
        system = create_pv_system(config)
        assert hasattr(system, "arrays")
        assert len(system.arrays) == 1

    def test_array_has_correct_orientation(self):
        """Array uses azimuth and tilt from config."""
        config = PVConfig(capacity_kw=4.0, azimuth=170.0, tilt=30.0)
        system = create_pv_system(config)
        array = system.arrays[0]
        assert array.mount.surface_azimuth == 170.0
        assert array.mount.surface_tilt == 30.0

    def test_uses_cec_module_params(self):
        """PVSystem uses CEC module parameters."""
        config = PVConfig(capacity_kw=4.0)
        system = create_pv_system(config)
        array = system.arrays[0]
        # CEC modules have these parameters
        assert "STC" in array.module_parameters or "a_ref" in array.module_parameters

    def test_uses_cec_inverter_params(self):
        """PVSystem uses CEC inverter parameters."""
        config = PVConfig(capacity_kw=4.0)
        system = create_pv_system(config)
        # CEC inverters have Paco (AC power output rating)
        assert "Paco" in system.inverter_parameters


class TestCreateModelChain:
    """Test PV-003: pvlib ModelChain creation."""

    def test_creates_model_chain(self):
        """create_model_chain returns a ModelChain."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        mc = create_model_chain(config, location)
        assert hasattr(mc, "run_model")
        assert hasattr(mc, "results")

    def test_model_chain_has_correct_location(self):
        """ModelChain uses provided location."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        mc = create_model_chain(config, location)
        assert mc.location.latitude == location.latitude
        assert mc.location.longitude == location.longitude


class TestSimulatePVOutput:
    """Test simulate_pv_output function."""

    @pytest.fixture
    def sample_weather_data(self) -> pd.DataFrame:
        """Create sample weather data for testing."""
        index = pd.date_range(
            "2024-06-21 06:00",
            periods=12,
            freq="1h",
            tz="Europe/London"
        )
        return pd.DataFrame(
            {
                "ghi": [100, 300, 500, 700, 800, 850, 800, 700, 500, 300, 100, 0],
                "dni": [150, 400, 600, 800, 900, 950, 900, 800, 600, 400, 150, 0],
                "dhi": [50, 100, 150, 200, 200, 200, 200, 200, 150, 100, 50, 0],
                "temp_air": [15, 17, 19, 21, 23, 24, 24, 23, 21, 19, 17, 15],
                "wind_speed": [2, 2, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2],
            },
            index=index,
        )

    def test_returns_series_with_same_index(self, sample_weather_data):
        """Output has same index as input weather data."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        output = simulate_pv_output(config, location, sample_weather_data)
        assert isinstance(output, pd.Series)
        assert len(output) == len(sample_weather_data)

    def test_output_in_kw(self, sample_weather_data):
        """AC power output is in kW."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        output = simulate_pv_output(config, location, sample_weather_data)
        # Peak should not exceed system capacity by much
        assert output.max() < config.capacity_kw * 1.2  # Allow some tolerance

    def test_no_negative_values(self, sample_weather_data):
        """AC power output has no negative values."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        output = simulate_pv_output(config, location, sample_weather_data)
        assert (output >= 0).all()

    def test_zero_at_night(self, sample_weather_data):
        """Output is zero when irradiance is zero."""
        config = PVConfig(capacity_kw=4.0)
        location = Location.bristol()
        output = simulate_pv_output(config, location, sample_weather_data)
        # Last entry has zero irradiance
        assert output.iloc[-1] == pytest.approx(0.0, abs=0.01)


class TestInterpolateToMinuteResolution:
    """Test PV-007: 1-minute resolution interpolation."""

    @pytest.fixture
    def hourly_power(self) -> pd.Series:
        """Sample hourly power data."""
        index = pd.date_range("2024-06-21 10:00", periods=3, freq="1h")
        return pd.Series([2.0, 3.0, 1.5], index=index, name="power_kw")

    def test_output_has_minute_frequency(self, hourly_power):
        """Output has 1-minute frequency."""
        minute_power = interpolate_to_minute_resolution(hourly_power)
        # 3 hours = 180 minutes
        assert len(minute_power) == 180

    def test_preserves_energy_totals(self, hourly_power):
        """Total energy is preserved after interpolation."""
        minute_power = interpolate_to_minute_resolution(hourly_power)
        # Energy = power * time
        # Hourly energy: sum of (power_kW * 1 hour) = 6.5 kWh
        # Minute energy: sum of (power_kW * 1/60 hour)
        hourly_total = hourly_power.sum()  # kWh (assuming 1-hour intervals)
        minute_total = minute_power.sum() / 60  # Convert minute sum to kWh
        assert minute_total == pytest.approx(hourly_total, rel=0.01)

    def test_no_negative_values(self, hourly_power):
        """Output has no negative values."""
        minute_power = interpolate_to_minute_resolution(hourly_power)
        assert (minute_power >= 0).all()

    def test_values_within_hour_are_constant(self, hourly_power):
        """Values within each hour are the same (forward-fill)."""
        minute_power = interpolate_to_minute_resolution(hourly_power)
        # First 60 minutes should all equal 2.0
        first_hour = minute_power.iloc[:60]
        assert (first_hour == 2.0).all()

    def test_handles_timezone_aware_index(self):
        """Works with timezone-aware index."""
        index = pd.date_range(
            "2024-06-21 10:00", periods=2, freq="1h", tz="Europe/London"
        )
        hourly_power = pd.Series([2.0, 3.0], index=index)
        minute_power = interpolate_to_minute_resolution(hourly_power)
        assert minute_power.index.tz is not None


class TestDegradationFactor:
    """Test PV-006: Annual degradation calculation."""

    def test_year_zero_no_degradation(self):
        """Year 0 = 100% capacity (factor = 1.0)."""
        factor = calculate_degradation_factor(0)
        assert factor == 1.0

    def test_year_one_default_rate(self):
        """Year 1 with default rate = 99.5%."""
        factor = calculate_degradation_factor(1)
        assert factor == pytest.approx(0.995, rel=1e-6)

    def test_year_ten_default_rate(self):
        """Year 10 with default rate = 95%."""
        factor = calculate_degradation_factor(10)
        assert factor == pytest.approx(0.95, rel=1e-6)

    def test_year_twenty_default_rate(self):
        """Year 20 with default rate = 90%."""
        factor = calculate_degradation_factor(20)
        assert factor == pytest.approx(0.90, rel=1e-6)

    def test_custom_degradation_rate(self):
        """Custom degradation rate applied correctly."""
        # 1% per year, year 10 = 90%
        factor = calculate_degradation_factor(10, degradation_rate_per_year=0.01)
        assert factor == pytest.approx(0.90, rel=1e-6)

    def test_fractional_years(self):
        """Fractional years work correctly."""
        factor = calculate_degradation_factor(5.5, degradation_rate_per_year=0.01)
        # 1 - (5.5 * 0.01) = 0.945
        assert factor == pytest.approx(0.945, rel=1e-6)

    def test_negative_age_raises(self):
        """Negative system age raises error."""
        with pytest.raises(ValueError, match="non-negative"):
            calculate_degradation_factor(-1)

    def test_invalid_rate_raises(self):
        """Invalid degradation rate raises error."""
        with pytest.raises(ValueError, match="0-1"):
            calculate_degradation_factor(5, degradation_rate_per_year=1.5)
        with pytest.raises(ValueError, match="0-1"):
            calculate_degradation_factor(5, degradation_rate_per_year=-0.1)

    def test_factor_clamped_at_zero(self):
        """Factor can't go below zero."""
        # At 200 years with 1% rate, would be negative, but clamped
        factor = calculate_degradation_factor(200, degradation_rate_per_year=0.01)
        assert factor == 0.0


class TestApplyDegradation:
    """Test applying degradation to generation series."""

    @pytest.fixture
    def sample_generation(self) -> pd.Series:
        """Sample generation data."""
        index = pd.date_range("2024-06-21 10:00", periods=5, freq="1h")
        return pd.Series([1.0, 2.0, 3.0, 2.0, 1.0], index=index, name="generation_kw")

    def test_year_zero_no_change(self, sample_generation):
        """Year 0 degradation doesn't change values."""
        degraded = apply_degradation(sample_generation, system_age_years=0)
        assert (degraded == sample_generation).all()

    def test_year_ten_reduces_by_five_percent(self, sample_generation):
        """Year 10 reduces generation by 5% (default rate)."""
        degraded = apply_degradation(sample_generation, system_age_years=10)
        expected = sample_generation * 0.95
        assert np.allclose(degraded.values, expected.values)

    def test_preserves_index(self, sample_generation):
        """Degradation preserves the series index."""
        degraded = apply_degradation(sample_generation, system_age_years=5)
        assert (degraded.index == sample_generation.index).all()

    def test_custom_rate(self, sample_generation):
        """Custom degradation rate applied correctly."""
        # 2% per year, year 5 = 10% loss = 90% remaining
        degraded = apply_degradation(
            sample_generation,
            system_age_years=5,
            degradation_rate_per_year=0.02
        )
        expected = sample_generation * 0.90
        assert np.allclose(degraded.values, expected.values)


class TestConfigurablePanelParameters:
    """Test PV-004: Configurable panel parameters."""

    def test_default_module_efficiency(self):
        """Default module efficiency is 20%."""
        config = PVConfig(capacity_kw=4.0)
        assert config.module_efficiency == 0.20

    def test_custom_module_efficiency(self):
        """Module efficiency can be customized."""
        config = PVConfig(capacity_kw=4.0, module_efficiency=0.22)
        assert config.module_efficiency == 0.22

    def test_invalid_module_efficiency_raises(self):
        """Invalid module efficiency raises error."""
        with pytest.raises(ValueError, match="Module efficiency"):
            PVConfig(capacity_kw=4.0, module_efficiency=0)
        with pytest.raises(ValueError, match="Module efficiency"):
            PVConfig(capacity_kw=4.0, module_efficiency=1.5)

    def test_default_temperature_coefficient(self):
        """Default temperature coefficient is -0.4%/°C."""
        config = PVConfig(capacity_kw=4.0)
        assert config.temperature_coefficient == -0.004

    def test_custom_temperature_coefficient(self):
        """Temperature coefficient can be customized."""
        config = PVConfig(capacity_kw=4.0, temperature_coefficient=-0.003)
        assert config.temperature_coefficient == -0.003

    def test_invalid_temperature_coefficient_raises(self):
        """Invalid temperature coefficient raises error."""
        with pytest.raises(ValueError, match="Temperature coefficient"):
            PVConfig(capacity_kw=4.0, temperature_coefficient=0)
        with pytest.raises(ValueError, match="Temperature coefficient"):
            PVConfig(capacity_kw=4.0, temperature_coefficient=-1.5)

    def test_custom_module_params(self):
        """Custom module parameters can be provided."""
        custom_params = {"STC": 450, "pdc0": 450}
        config = PVConfig(capacity_kw=4.0, custom_module_params=custom_params)
        assert config.custom_module_params == custom_params

    def test_create_simple_module_params(self):
        """create_simple_module_params creates valid parameters."""
        params = create_simple_module_params(
            efficiency=0.22,
            temperature_coefficient=-0.003,
            module_power_w=450.0
        )
        assert params["gamma_pdc"] == -0.003
        assert params["efficiency"] == 0.22
        assert params["STC"] == 450.0

    def test_custom_module_params_used_in_system(self):
        """Custom module parameters are used when creating PVSystem."""
        custom_params = create_simple_module_params(
            efficiency=0.22,
            temperature_coefficient=-0.003
        )
        config = PVConfig(capacity_kw=4.0, custom_module_params=custom_params)
        system = create_pv_system(config)
        array_params = system.arrays[0].module_parameters
        assert array_params["gamma_pdc"] == -0.003


class TestConfigurableInverterParameters:
    """Test PV-005: Configurable inverter parameters."""

    def test_default_inverter_efficiency(self):
        """Default inverter efficiency is 96%."""
        config = PVConfig(capacity_kw=4.0)
        assert config.inverter_efficiency == 0.96

    def test_custom_inverter_efficiency(self):
        """Inverter efficiency can be customized."""
        config = PVConfig(capacity_kw=4.0, inverter_efficiency=0.97)
        assert config.inverter_efficiency == 0.97

    def test_invalid_inverter_efficiency_raises(self):
        """Invalid inverter efficiency raises error."""
        with pytest.raises(ValueError, match="Inverter efficiency"):
            PVConfig(capacity_kw=4.0, inverter_efficiency=0)
        with pytest.raises(ValueError, match="Inverter efficiency"):
            PVConfig(capacity_kw=4.0, inverter_efficiency=1.1)

    def test_default_inverter_capacity(self):
        """Default inverter capacity matches DC capacity."""
        config = PVConfig(capacity_kw=4.0)
        assert config.inverter_capacity_kw is None
        assert config.effective_inverter_capacity_kw == 4.0

    def test_custom_inverter_capacity(self):
        """Inverter capacity can be customized."""
        config = PVConfig(capacity_kw=4.0, inverter_capacity_kw=3.5)
        assert config.inverter_capacity_kw == 3.5
        assert config.effective_inverter_capacity_kw == 3.5

    def test_invalid_inverter_capacity_raises(self):
        """Invalid inverter capacity raises error."""
        with pytest.raises(ValueError, match="Inverter capacity"):
            PVConfig(capacity_kw=4.0, inverter_capacity_kw=0)
        with pytest.raises(ValueError, match="Inverter capacity"):
            PVConfig(capacity_kw=4.0, inverter_capacity_kw=-1)

    def test_custom_inverter_params(self):
        """Custom inverter parameters can be provided."""
        custom_params = {"Paco": 3500, "Pdco": 3700}
        config = PVConfig(capacity_kw=4.0, custom_inverter_params=custom_params)
        assert config.custom_inverter_params == custom_params

    def test_create_simple_inverter_params(self):
        """create_simple_inverter_params creates valid parameters."""
        params = create_simple_inverter_params(
            efficiency=0.97,
            capacity_w=5000
        )
        assert params["Paco"] == 5000.0
        assert params["efficiency"] == 0.97

    def test_custom_inverter_params_used_in_system(self):
        """Custom inverter parameters are used when creating PVSystem."""
        custom_params = create_simple_inverter_params(
            efficiency=0.97,
            capacity_w=3500
        )
        config = PVConfig(capacity_kw=4.0, custom_inverter_params=custom_params)
        system = create_pv_system(config)
        assert system.inverter_parameters["Paco"] == 3500.0

    def test_undersized_inverter_causes_clipping(self):
        """Undersized inverter causes output clipping."""
        # Create system with 4 kW DC but only 3 kW inverter
        config_undersized = PVConfig(capacity_kw=4.0, inverter_capacity_kw=3.0)
        system = create_pv_system(config_undersized)
        # Inverter should be sized to approximately 3 kW
        # (CEC database finds closest match)
        assert system.inverter_parameters["Paco"] < 4000
