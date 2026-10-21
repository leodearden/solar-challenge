# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for PVConfig's settings, from their defaults and domains to the module and inverter parameters a built system takes from them.

test_pv_module_settings.py tests module_efficiency and temperature_coefficient.
"""

import dataclasses
import math
import re

import pvlib
import pytest
from solar_challenge.pv import (
    PVConfig,
    create_pv_system,
    create_pvwatts_inverter_params,
    create_simple_inverter_params,
    create_simple_module_params,
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

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    @pytest.mark.parametrize(
        ("field", "invariant"),
        [
            ("capacity_kw", "Capacity must be positive and finite"),
            ("inverter_capacity_kw", "Inverter capacity must be positive and finite"),
        ],
    )
    def test_a_capacity_that_is_not_finite_is_refused(
        self, field: str, invariant: str, value: float
    ) -> None:
        with pytest.raises(ValueError, match=re.escape(f"{invariant}, got {value} kW")):
            dataclasses.replace(PVConfig(capacity_kw=4.0), **{field: value})

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

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_a_system_age_that_is_not_finite_is_refused(self, value: float) -> None:
        with pytest.raises(
            ValueError,
            match=re.escape(f"System age must be non-negative and finite, got {value}"),
        ):
            dataclasses.replace(PVConfig(capacity_kw=4.0), system_age_years=value)

    def test_degradation_rate_must_be_zero_to_one(self):
        """degradation_rate_per_year outside [0, 1] raises ValueError with '0-1' message."""
        with pytest.raises(ValueError, match="0-1"):
            PVConfig(capacity_kw=4.0, degradation_rate_per_year=1.5)
        with pytest.raises(ValueError, match="0-1"):
            PVConfig(capacity_kw=4.0, degradation_rate_per_year=-0.1)

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_a_degradation_rate_that_is_not_finite_is_refused(self, value: float) -> None:
        with pytest.raises(
            ValueError,
            match=re.escape(f"Degradation rate must be 0-1, got {value}"),
        ):
            dataclasses.replace(PVConfig(capacity_kw=4.0), degradation_rate_per_year=value)

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


class TestSystemLossesConfig:
    """PVConfig.system_losses is the fraction of each array's DC power lost before the inverter."""

    def test_the_default_is_pvwatts_v5s_loss_budget(self) -> None:
        assert PVConfig(capacity_kw=4.0).system_losses == pytest.approx(
            pvlib.pvsystem.pvwatts_losses() / 100
        )

    @pytest.mark.parametrize("value", [-0.01, 1.0, 14.0, math.nan, math.inf, -math.inf])
    def test_a_loss_outside_zero_to_one_is_refused(self, value: float) -> None:
        with pytest.raises(
            ValueError,
            match=re.escape(f"System losses must be a fraction in [0, 1), got {value}"),
        ):
            dataclasses.replace(PVConfig(capacity_kw=4.0), system_losses=value)

    @pytest.mark.parametrize("value", [0.0, 0.05, 0.99])
    def test_a_loss_in_zero_to_one_is_kept(self, value: float) -> None:
        assert PVConfig(capacity_kw=4.0, system_losses=value).system_losses == value


class TestConfigurablePanelParameters:
    """Test PV-004: Configurable panel parameters."""

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
        assert params["A_c"] == pytest.approx(450.0 / (0.22 * 1000))
        assert "efficiency" not in params
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

    def test_create_pvwatts_inverter_params(self):
        """create_pvwatts_inverter_params describes a PVWatts inverter that clips at capacity_w."""
        params = create_pvwatts_inverter_params(efficiency=0.97, capacity_w=5000)
        overload_w = 1.5 * params["pdc0"]

        assert params["eta_inv_nom"] == 0.97
        assert pvlib.inverter.pvwatts(overload_w, **params) == pytest.approx(5000.0)

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
