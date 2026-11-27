# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for PV ageing: calculate_degradation_factor's 1 - age x rate, floored at zero."""

import math

import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.pv import PVConfig, calculate_degradation_factor


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

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("system_age_years", -0.1),
            ("system_age_years", math.nan),
            ("system_age_years", True),
            ("system_age_years", "x"),
            ("degradation_rate_per_year", -0.1),
            ("degradation_rate_per_year", 1.5),
            ("degradation_rate_per_year", math.inf),
            ("degradation_rate_per_year", True),
        ],
    )
    def test_an_age_or_rate_is_refused_as_pv_config_refuses_it(self, field: str, value: object) -> None:
        with pytest.raises(ConfigurationError) as config_refusal:
            PVConfig(capacity_kw=4.0, **{field: value})
        with pytest.raises(ConfigurationError) as factor_refusal:
            calculate_degradation_factor(**{"system_age_years": 0.0, field: value})
        assert str(factor_refusal.value) == str(config_refusal.value)

    def test_factor_clamped_at_zero(self):
        """Factor can't go below zero."""
        # At 200 years with 1% rate, would be negative, but clamped
        factor = calculate_degradation_factor(200, degradation_rate_per_year=0.01)
        assert factor == 0.0


class TestApplyDegradationIsRetired:
    """Ageing has one home: neither the package nor solar_challenge.pv serves apply_degradation, the AC-side derate that aged simulate_pv_output's output twice."""

    @pytest.mark.parametrize(
        "module",
        [pytest.param("solar_challenge", id="the-package"), pytest.param("solar_challenge.pv", id="pv")],
    )
    def test_importing_apply_degradation_raises_import_error(self, module: str) -> None:
        with pytest.raises(ImportError, match="cannot import name 'apply_degradation'"):
            exec(f"from {module} import apply_degradation", {})
