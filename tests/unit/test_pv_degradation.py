# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for PV ageing: calculate_degradation_factor's 1 - age x rate, floored at zero, and apply_degradation's scaling of a generation series by it."""

import math

import numpy as np
import pandas as pd
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import apply_degradation, calculate_degradation_factor


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
        with pytest.raises(ConfigurationError) as exc_info:
            calculate_degradation_factor(-1)
        assert str(exc_info.value) == "system_age_years must be at least 0, got -1"

    @pytest.mark.parametrize("age", [math.nan, math.inf, -math.inf])
    def test_a_non_finite_age_raises(self, age: float) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            calculate_degradation_factor(age)
        assert str(exc_info.value) == f"system_age_years must be a finite number, got {age!r}"

    @pytest.mark.parametrize("rate", [1.5, -0.1])
    def test_invalid_rate_raises(self, rate):
        """Invalid degradation rate raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            calculate_degradation_factor(5, degradation_rate_per_year=rate)
        assert str(exc_info.value) == f"degradation_rate_per_year must be between 0 and 1, got {rate!r}"

    @pytest.mark.parametrize("rate", [math.nan, math.inf, -math.inf])
    def test_a_non_finite_rate_raises(self, rate: float) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            calculate_degradation_factor(5, degradation_rate_per_year=rate)
        assert str(exc_info.value) == f"degradation_rate_per_year must be a finite number, got {rate!r}"

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
