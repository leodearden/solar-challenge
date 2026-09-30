"""Tests for PV configuration."""

import dataclasses

import numpy as np
import pandas as pd
import pvlib
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

    def test_system_age_must_be_non_negative(self):
        """system_age_years < 0 raises ValueError with 'non-negative' message."""
        with pytest.raises(ValueError, match="non-negative"):
            PVConfig(capacity_kw=4.0, system_age_years=-1.0)
        with pytest.raises(ValueError, match="non-negative"):
            PVConfig(capacity_kw=4.0, system_age_years=-0.001)

    def test_degradation_rate_must_be_zero_to_one(self):
        """degradation_rate_per_year outside [0, 1] raises ValueError with '0-1' message."""
        with pytest.raises(ValueError, match="0-1"):
            PVConfig(capacity_kw=4.0, degradation_rate_per_year=1.5)
        with pytest.raises(ValueError, match="0-1"):
            PVConfig(capacity_kw=4.0, degradation_rate_per_year=-0.1)

    def test_system_age_valid_boundaries(self):
        """Valid boundary values for system_age_years are accepted without error."""
        PVConfig(capacity_kw=4.0, system_age_years=0.0)  # new system
        PVConfig(capacity_kw=4.0, system_age_years=5.5)  # fractional years
        PVConfig(capacity_kw=4.0, system_age_years=25.0)  # old system

    def test_degradation_rate_valid_boundaries(self):
        """Valid boundary values for degradation_rate_per_year are accepted without error."""
        PVConfig(capacity_kw=4.0, degradation_rate_per_year=0.0)   # no degradation
        PVConfig(capacity_kw=4.0, degradation_rate_per_year=1.0)   # max rate
        PVConfig(capacity_kw=4.0, degradation_rate_per_year=0.005) # default rate


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


class TestCECLibraryReuse:
    """The CEC module and inverter libraries are parsed once, and each system gets its own parameters."""

    def test_sam_libraries_are_read_at_most_once_across_systems(self, monkeypatch):
        reads = []
        real_retrieve_sam = pvlib.pvsystem.retrieve_sam

        def recording_retrieve_sam(name=None, path=None):
            reads.append(name)
            return real_retrieve_sam(name, path)

        monkeypatch.setattr(pvlib.pvsystem, "retrieve_sam", recording_retrieve_sam)

        for capacity_kw in (3.0, 4.0, 5.0):
            create_pv_system(PVConfig(capacity_kw=capacity_kw))

        assert reads.count("CECMod") <= 1, f"SAM library reads: {reads}"
        assert reads.count("CECInverter") <= 1, f"SAM library reads: {reads}"

    def test_customised_system_leaves_later_default_systems_unchanged(self):
        baseline = create_pv_system(PVConfig(capacity_kw=4.0))
        create_pv_system(
            PVConfig(capacity_kw=4.0, temperature_coefficient=-0.003, inverter_efficiency=0.90)
        )

        later = create_pv_system(PVConfig(capacity_kw=4.0))

        assert "gamma_pdc" not in later.arrays[0].module_parameters
        assert later.inverter_parameters["Pdco"] == baseline.inverter_parameters["Pdco"]


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

    def test_degradation_applied_in_live_path(self, sample_weather_data):
        """simulate_pv_output with system_age_years=20 returns 90% of the age-0 output.

        This is the live-path signal test: it verifies that degradation is wired into
        the production function, not just the standalone apply_degradation helper.
        The pre-degradation ac_power is identical for age-0 and age-20 (the new fields
        don't enter the pvlib model chain), so the ratio is exactly 0.90.
        """
        location = Location.bristol()
        age0_config = PVConfig(capacity_kw=4.0)
        age20_config = PVConfig(capacity_kw=4.0, system_age_years=20)

        age0 = simulate_pv_output(age0_config, location, sample_weather_data)
        age20 = simulate_pv_output(age20_config, location, sample_weather_data)

        # Ensure there is meaningful generation (not all-zero)
        assert age0.sum() > 0

        # age-20 output must be exactly 90% of age-0 (factor = 1 - 20*0.005 = 0.90)
        assert age20.sum() == pytest.approx(0.90 * age0.sum(), rel=1e-6)
        assert np.allclose(age20.values, (age0 * 0.90).values)

    def test_fully_degraded_system_yields_zero(self, sample_weather_data):
        """A fully degraded system (age*rate > 1) yields all-zero generation, not negative.

        calculate_degradation_factor clamps the factor to max(0.0, factor). With
        system_age_years=300 and degradation_rate_per_year=0.01 the raw factor would
        be 1 - 300*0.01 = -2.0, which is clamped to 0.0. This exercises that branch
        via the live simulate_pv_output path so negative output is never returned.
        """
        location = Location.bristol()
        # Confirm there is meaningful pre-degradation generation (non-trivial fixture)
        age0_config = PVConfig(capacity_kw=4.0)
        age0 = simulate_pv_output(age0_config, location, sample_weather_data)
        assert age0.sum() > 0, "fixture must produce non-zero generation for this test to be meaningful"

        # 300 years * 0.01/yr = raw factor -2.0 → clamped to 0.0 → all-zero output
        fully_degraded_config = PVConfig(
            capacity_kw=4.0,
            system_age_years=300,
            degradation_rate_per_year=0.01,
        )
        output = simulate_pv_output(fully_degraded_config, location, sample_weather_data)
        # Factor == 0.0 is exact (clamped integer multiplication), so == 0.0 is safe
        assert (output == 0.0).all(), (
            "Fully degraded system must produce zero output, not negative values"
        )


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
        config = PVConfig(
            capacity_kw=4.0,
            custom_module_params=custom_params,
            custom_inverter_params=create_simple_inverter_params(),
        )
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


FLAT_INVERTER_EFFICIENCY = 0.96

SYSTEM_SIZE_CONFIGS = [
    *(
        PVConfig(capacity_kw=capacity_kw)
        for capacity_kw in (
            0.5, 1.0, 2.0, 3.0, 3.5, 3.68, 4.0, 4.5, 5.0, 5.5, 6.0, 6.8, 7.6, 10.0, 15.0, 20.0
        )
    ),
    PVConfig(capacity_kw=4.0, inverter_capacity_kw=3.0),
    PVConfig(capacity_kw=6.0, inverter_capacity_kw=3.68),
    PVConfig(capacity_kw=8.0, inverter_capacity_kw=3.68),
]

STOCKED_RATING_CONFIGS = [
    *(
        PVConfig(capacity_kw=capacity_kw)
        for capacity_kw in (3.0, 3.68, 4.0, 5.0, 5.5, 6.0)
    ),
    PVConfig(capacity_kw=4.0, inverter_capacity_kw=3.0),
    PVConfig(capacity_kw=6.0, inverter_capacity_kw=3.68),
]


def _config_id(config: PVConfig) -> str:
    return f"{config.capacity_kw}kW-dc-{config.effective_inverter_capacity_kw}kW-ac"


def _wiring(system: pvlib.pvsystem.PVSystem) -> list[tuple[int, int]]:
    """(modules per string, strings) for each array, one array per MPPT input."""
    return [(array.modules_per_string, array.strings) for array in system.arrays]


@pytest.fixture
def clear_june_day() -> pd.DataFrame:
    """Hourly weather for a cloudless midsummer day, 06:00-17:00 London time."""
    index = pd.date_range("2024-06-21 06:00", periods=12, freq="1h", tz="Europe/London")
    return pd.DataFrame(
        {
            "ghi": [100, 300, 500, 700, 800, 850, 800, 700, 500, 300, 100, 0],
            "dni": [150, 400, 600, 800, 900, 950, 900, 800, 600, 400, 150, 0],
            "dhi": [50, 100, 150, 200, 200, 200, 200, 200, 150, 100, 50, 0],
            "temp_air": 20,
            "wind_speed": 2,
        },
        index=index,
    )


@pytest.fixture
def overcast_january_day() -> pd.DataFrame:
    """Hourly weather for a dull midwinter day, 08:00-16:00 London time, diffuse light only."""
    index = pd.date_range("2024-01-15 08:00", periods=9, freq="1h", tz="Europe/London")
    diffuse = [5, 25, 50, 75, 90, 85, 60, 30, 5]
    return pd.DataFrame(
        {"ghi": diffuse, "dni": 0, "dhi": diffuse, "temp_air": 5, "wind_speed": 2},
        index=index,
    )


class TestInverterMatchesStringVoltage:
    """The CEC inverter's MPPT window takes the array's string voltage, whatever the capacity.

    pvlib's Sandia model is a linear fit across the MPPT window and is not adjusted
    for it, so a string outside the window extrapolates the loss terms by hundreds of
    volts and the inverter loses (or invents) energy.
    """

    @pytest.mark.parametrize("config", SYSTEM_SIZE_CONFIGS, ids=_config_id)
    def test_every_string_operates_inside_the_inverters_mppt_window(
        self, config: PVConfig
    ) -> None:
        system = create_pv_system(config)
        window_low = system.inverter_parameters["Mppt_low"]
        window_high = system.inverter_parameters["Mppt_high"]

        for array in system.arrays:
            string_vmp = array.modules_per_string * array.module_parameters["V_mp_ref"]
            assert window_low <= string_vmp <= window_high, (
                f"{config.capacity_kw} kW wired as {_wiring(system)} "
                f"(modules per string, strings) runs a {string_vmp:.0f} V string "
                f"outside the inverter's {window_low:.0f}-{window_high:.0f} V MPPT window"
            )

    @pytest.mark.parametrize("config", SYSTEM_SIZE_CONFIGS, ids=_config_id)
    def test_wiring_keeps_the_dc_capacity(self, config: PVConfig) -> None:
        system = create_pv_system(config)
        module_w = system.arrays[0].module_parameters["STC"]
        wired_w = sum(a.modules_per_string * a.strings for a in system.arrays) * module_w

        assert abs(wired_w - config.capacity_kw * 1000) <= module_w / 2, (
            f"{config.capacity_kw} kW wired as {_wiring(system)} "
            f"(modules per string, strings) is {wired_w:.0f} W of {module_w:.0f} W modules"
        )

    @pytest.mark.parametrize("config", STOCKED_RATING_CONFIGS, ids=_config_id)
    def test_inverter_is_rated_at_the_configured_ac_capacity(
        self, config: PVConfig
    ) -> None:
        system = create_pv_system(config)

        assert system.inverter_parameters["Paco"] == pytest.approx(
            config.effective_inverter_capacity_kw * 1000
        )

    def test_equally_rated_candidates_break_ties_on_nominal_voltage(self) -> None:
        system = create_pv_system(PVConfig.default_4kw())
        assert [array.strings for array in system.arrays] == [1], (
            f"the default array should be wired as one string, got {_wiring(system)}"
        )
        array = system.arrays[0]
        string_vmp = array.modules_per_string * array.module_parameters["V_mp_ref"]
        chosen = system.inverter_parameters

        catalogue = pvlib.pvsystem.retrieve_sam("CECInverter")
        numbers = catalogue.loc[["Paco", "Vdco", "Mppt_low", "Mppt_high"]].T.apply(pd.to_numeric)
        equally_rated = numbers[
            (numbers["Paco"] == chosen["Paco"])
            & (numbers["Mppt_low"] <= string_vmp)
            & (string_vmp <= numbers["Mppt_high"])
        ]
        assert len(equally_rated) > 1, "the tie-break needs several equally rated inverters"

        chosen_distance_v = abs(chosen["Vdco"] - string_vmp)
        nearest_distance_v = (equally_rated["Vdco"] - string_vmp).abs().min()
        assert chosen_distance_v == pytest.approx(nearest_distance_v), (
            f"the {string_vmp:.0f} V string is {chosen_distance_v:.0f} V from the chosen "
            f"inverter's Vdco of {chosen['Vdco']:.0f} V, but {nearest_distance_v:.0f} V "
            "from the nearest equally rated candidate's"
        )

    @pytest.mark.parametrize("config", SYSTEM_SIZE_CONFIGS, ids=_config_id)
    @pytest.mark.parametrize(
        ("day", "floor"),
        [("clear_june_day", 0.92), ("overcast_january_day", 0.5)],
        ids=["clear", "overcast"],
    )
    def test_ac_energy_stays_a_physical_fraction_of_a_flat_inverter_of_the_same_rating(
        self, request: pytest.FixtureRequest, config: PVConfig, day: str, floor: float
    ) -> None:
        weather = request.getfixturevalue(day)
        flat_inverter = create_simple_inverter_params(
            efficiency=FLAT_INVERTER_EFFICIENCY,
            capacity_w=config.effective_inverter_capacity_kw * 1000,
        )
        flat_reference = dataclasses.replace(config, custom_inverter_params=flat_inverter)

        reference_kwh = simulate_pv_output(flat_reference, Location.bristol(), weather).sum()
        actual_kwh = simulate_pv_output(config, Location.bristol(), weather).sum()

        assert reference_kwh > 0
        ratio = actual_kwh / reference_kwh
        ceiling = 1 / FLAT_INVERTER_EFFICIENCY
        assert floor <= ratio <= ceiling, (
            f"{config.capacity_kw} kW dc on a {config.effective_inverter_capacity_kw} kW "
            f"inverter on the {day} gave {actual_kwh:.3f} kWh, {ratio:.3f} of the flat-"
            f"{FLAT_INVERTER_EFFICIENCY:.0%} reference's {reference_kwh:.3f} kWh "
            f"(physical range {floor} to {ceiling:.4f})"
        )

    def test_a_module_without_a_voltage_model_needs_an_explicit_inverter(self) -> None:
        config = PVConfig(capacity_kw=4.0, custom_module_params=create_simple_module_params())

        with pytest.raises(ValueError, match="V_mp_ref"):
            create_pv_system(config)

    def test_a_module_voltage_beyond_every_mppt_window_is_rejected(self) -> None:
        module = dict(create_pv_system(PVConfig(capacity_kw=4.0)).arrays[0].module_parameters)
        highest_mppt_ceiling_v = pd.to_numeric(
            pvlib.pvsystem.retrieve_sam("CECInverter").loc["Mppt_high"]
        ).max()
        module["V_mp_ref"] = 2 * highest_mppt_ceiling_v

        with pytest.raises(ValueError, match="MPPT window"):
            create_pv_system(PVConfig(capacity_kw=4.0, custom_module_params=module))
