"""Tests for load profile generation."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.load import (
    LoadConfig,
    OFGEM_TDCV_BY_OCCUPANTS,
    RICHARDSONPY_AVAILABLE,
    calculate_annual_consumption,
    generate_load_profile,
    scale_profile_to_annual,
)


class TestLoadConfigBasics:
    """Test basic LoadConfig functionality."""

    def test_create_with_all_params(self):
        """LoadConfig can be created with all parameters."""
        config = LoadConfig(
            annual_consumption_kwh=4000.0,
            household_occupants=4,
            name="Test household",
            use_stochastic=False,
        )
        assert config.annual_consumption_kwh == 4000.0
        assert config.household_occupants == 4
        assert config.name == "Test household"
        assert config.use_stochastic is False

    def test_default_values(self):
        """LoadConfig uses sensible defaults."""
        config = LoadConfig()
        assert config.annual_consumption_kwh is None  # Derived from occupants
        assert config.household_occupants == 3  # UK average
        assert config.name == ""
        assert config.use_stochastic is True

    def test_get_annual_consumption_explicit(self):
        """get_annual_consumption returns explicit value if set."""
        config = LoadConfig(annual_consumption_kwh=4500.0)
        assert config.get_annual_consumption() == 4500.0

    def test_get_annual_consumption_from_occupants(self):
        """get_annual_consumption derives from occupants if not set."""
        config = LoadConfig(household_occupants=2)
        expected = OFGEM_TDCV_BY_OCCUPANTS[2]
        assert config.get_annual_consumption() == expected


class TestLoadConfigValidation:
    """Test parameter validation."""

    def test_consumption_must_be_positive(self):
        """Annual consumption <= 0 raises error."""
        with pytest.raises(ValueError, match="consumption"):
            LoadConfig(annual_consumption_kwh=0)
        with pytest.raises(ValueError, match="consumption"):
            LoadConfig(annual_consumption_kwh=-100)

    def test_occupants_must_be_at_least_one(self):
        """Household occupants < 1 raises error."""
        with pytest.raises(ValueError, match="occupant"):
            LoadConfig(household_occupants=0)

    def test_occupants_unrealistic_high_raises(self):
        """Unrealistically high occupants raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            LoadConfig(household_occupants=15)


class TestGenerateLoadProfile:
    """Test LOAD-002/LOAD-006: Elexon profile generation."""

    @pytest.fixture
    def config(self) -> LoadConfig:
        """Standard test configuration."""
        return LoadConfig(annual_consumption_kwh=3400.0)

    def test_returns_series_with_minute_index(self, config):
        """Output has 1-minute frequency DatetimeIndex."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_load_profile(config, start, end)

        assert isinstance(profile, pd.Series)
        assert isinstance(profile.index, pd.DatetimeIndex)
        # One day = 1440 minutes
        assert len(profile) == 1440

    def test_output_in_kw(self, config):
        """Output values are power in kW."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_load_profile(config, start, end)

        # Typical UK domestic peak is around 5-10 kW
        assert profile.max() < 15.0  # Reasonable upper bound
        assert profile.mean() > 0.1  # Non-trivial consumption

    def test_no_negative_values(self, config):
        """Output has no negative values."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_load_profile(config, start, end)

        assert (profile >= 0).all()

    def test_timezone_aware_index(self, config):
        """Output index is timezone-aware."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_load_profile(config, start, end, timezone="Europe/London")

        assert profile.index.tz is not None

    def test_multi_day_profile(self, config):
        """Generates profile for multiple days."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days
        profile = generate_load_profile(config, start, end)

        # 3 days = 3 * 1440 minutes
        assert len(profile) == 3 * 1440

    def test_week_profile_scales_to_annual(self):
        """Week profile scales approximately to annual target (Elexon profile)."""
        # Use Elexon profile explicitly for deterministic seasonal scaling test
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        start = pd.Timestamp("2024-06-01")
        end = pd.Timestamp("2024-06-07")  # 7 days
        profile = generate_load_profile(config, start, end)

        # Calculate consumption for this week
        weekly_kwh = calculate_annual_consumption(profile)

        # Should be approximately 3400 / 52 ≈ 65 kWh per week
        # Allow some variation due to seasonal factors (June is lower)
        expected_weekly = 3400.0 / 52.0 * 0.8  # June factor
        assert weekly_kwh == pytest.approx(expected_weekly, rel=0.2)


class TestElexonProfileShape:
    """Test Elexon Profile Class 1 characteristics.

    These tests explicitly use use_stochastic=False to test the
    deterministic Elexon profile shape.
    """

    @pytest.fixture
    def summer_profile(self) -> pd.Series:
        """Summer day profile (Elexon)."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        return generate_load_profile(
            config,
            pd.Timestamp("2024-06-21"),
            pd.Timestamp("2024-06-21"),
        )

    @pytest.fixture
    def winter_profile(self) -> pd.Series:
        """Winter day profile (Elexon)."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        return generate_load_profile(
            config,
            pd.Timestamp("2024-01-15"),
            pd.Timestamp("2024-01-15"),
        )

    def test_evening_peak_higher_than_overnight(self, summer_profile):
        """Evening peak is higher than overnight baseline."""
        # Evening: 18:00-20:00 (minutes 1080-1200)
        # Overnight: 02:00-04:00 (minutes 120-240)
        evening_avg = summer_profile.iloc[1080:1200].mean()
        overnight_avg = summer_profile.iloc[120:240].mean()
        assert evening_avg > overnight_avg * 2

    def test_winter_consumption_higher_than_summer(
        self, summer_profile, winter_profile
    ):
        """Winter daily consumption is higher than summer."""
        summer_total = summer_profile.sum() / 60  # kWh
        winter_total = winter_profile.sum() / 60  # kWh
        assert winter_total > summer_total


class TestCalculateAnnualConsumption:
    """Test annual consumption calculation."""

    def test_calculates_from_minute_profile(self):
        """Correctly calculates total consumption."""
        # Create 1 day profile at constant 1 kW
        index = pd.date_range("2024-01-01", periods=1440, freq="1min")
        profile = pd.Series([1.0] * 1440, index=index)

        # 1 kW for 1440 minutes = 1440/60 = 24 kWh
        total = calculate_annual_consumption(profile)
        assert total == pytest.approx(24.0, rel=0.001)

    def test_empty_profile_returns_zero(self):
        """Empty profile returns zero consumption."""
        profile = pd.Series([], dtype=float)
        assert calculate_annual_consumption(profile) == 0.0


class TestScaleProfileToAnnual:
    """Test LOAD-003: Profile scaling to annual target."""

    def test_scales_to_target(self):
        """Scales profile to match target annual consumption."""
        # Create simple 1-year profile (simplified)
        index = pd.date_range("2024-01-01", periods=1440, freq="1min")
        profile = pd.Series([1.0] * 1440, index=index)  # 24 kWh

        scaled = scale_profile_to_annual(profile, target_annual_kwh=48.0)
        total = calculate_annual_consumption(scaled)

        assert total == pytest.approx(48.0, rel=0.001)

    def test_preserves_shape(self):
        """Scaling preserves temporal shape."""
        index = pd.date_range("2024-01-01", periods=100, freq="1min")
        profile = pd.Series(np.arange(100, dtype=float), index=index)

        scaled = scale_profile_to_annual(profile, target_annual_kwh=100.0)

        # Relative values should be preserved
        assert (scaled.iloc[50] / scaled.iloc[25]) == pytest.approx(
            profile.iloc[50] / profile.iloc[25], rel=0.001
        )

    def test_raises_on_zero_consumption(self):
        """Raises error when profile has zero consumption."""
        profile = pd.Series([0.0] * 100)
        with pytest.raises(ValueError, match="zero"):
            scale_profile_to_annual(profile, target_annual_kwh=100.0)


class TestHouseholdSizeParameter:
    """Test LOAD-004: Household size affecting consumption."""

    def test_larger_household_higher_consumption(self):
        """Larger households have higher consumption."""
        config_2 = LoadConfig(household_occupants=2)
        config_4 = LoadConfig(household_occupants=4)

        assert config_4.get_annual_consumption() > config_2.get_annual_consumption()

    def test_ofgem_tdcv_values_used(self):
        """Uses Ofgem TDCV values for standard sizes."""
        for occupants in range(1, 6):
            config = LoadConfig(household_occupants=occupants)
            expected = OFGEM_TDCV_BY_OCCUPANTS[occupants]
            assert config.get_annual_consumption() == expected

    def test_occupants_above_five_extrapolated(self):
        """Occupants > 5 extrapolate from 5-person baseline."""
        config_5 = LoadConfig(household_occupants=5)
        config_7 = LoadConfig(household_occupants=7)

        # Each extra person adds 400 kWh
        expected = OFGEM_TDCV_BY_OCCUPANTS[5] + 2 * 400.0
        assert config_7.get_annual_consumption() == expected

    def test_profile_scales_with_household_size(self):
        """Generated profile scales with household size."""
        config_small = LoadConfig(household_occupants=1, use_stochastic=False)
        config_large = LoadConfig(household_occupants=5, use_stochastic=False)

        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        profile_small = generate_load_profile(config_small, start, end)
        profile_large = generate_load_profile(config_large, start, end)

        total_small = calculate_annual_consumption(profile_small)
        total_large = calculate_annual_consumption(profile_large)

        # Larger household should use more energy
        assert total_large > total_small

        # Ratio should match TDCV ratio
        expected_ratio = OFGEM_TDCV_BY_OCCUPANTS[5] / OFGEM_TDCV_BY_OCCUPANTS[1]
        actual_ratio = total_large / total_small
        assert actual_ratio == pytest.approx(expected_ratio, rel=0.01)


class TestRichardsonpyIntegration:
    """Test LOAD-001: richardsonpy integration."""

    def test_richardsonpy_availability_flag(self):
        """RICHARDSONPY_AVAILABLE correctly indicates availability."""
        # This test just documents the current state
        assert isinstance(RICHARDSONPY_AVAILABLE, bool)

    def test_fallback_to_elexon_when_unavailable(self):
        """Falls back to Elexon profile when richardsonpy unavailable."""
        # Even with use_stochastic=True, should fall back gracefully
        config = LoadConfig(
            annual_consumption_kwh=3400.0,
            use_stochastic=True,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        # Should not raise, should return valid profile
        profile = generate_load_profile(config, start, end)
        assert isinstance(profile, pd.Series)
        assert len(profile) == 1440

    def test_disable_stochastic_uses_elexon(self):
        """use_stochastic=False always uses Elexon profile."""
        config = LoadConfig(
            annual_consumption_kwh=3400.0,
            use_stochastic=False,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        profile = generate_load_profile(config, start, end)
        assert isinstance(profile, pd.Series)
        assert len(profile) == 1440

    def test_richardsonpy_generates_valid_profile(self):
        """richardsonpy (now a hard dep) generates a valid profile."""
        config = LoadConfig(
            annual_consumption_kwh=3400.0,
            household_occupants=3,
            use_stochastic=True,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        profile = generate_load_profile(config, start, end)

        assert isinstance(profile, pd.Series)
        assert len(profile) == 1440
        assert (profile >= 0).all()
        assert profile.index.tz is not None


class TestWindowedStochasticGeneration:
    """Test windowed stochastic generation (task #13 FIX windowing)."""

    def test_window_1day_calls_run_simulation_exactly_once(self, monkeypatch):
        """1-day stochastic request triggers exactly 1 run_application_simulation call.

        The original ElectricLoad-based code calls run_application_simulation
        365 times regardless of the requested window. The windowed implementation
        must call it exactly window_days times.
        """
        import richardsonpy.classes.appliance as _app_mod

        call_count = [0]
        _original = _app_mod.run_application_simulation

        def _counting_wrapper(*args, **kwargs):
            call_count[0] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(_app_mod, "run_application_simulation", _counting_wrapper)

        assert RICHARDSONPY_AVAILABLE is True, (
            "richardsonpy must be a hard dependency so this path is always exercised"
        )

        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        generate_load_profile(config, start, end)

        # Exactly ONE day simulated — not 365 (the full-year bug)
        assert call_count[0] == 1, (
            f"Expected 1 simulated day for a 1-day window, got {call_count[0]}"
        )

    def test_window_3day_calls_run_simulation_exactly_three_times(self, monkeypatch):
        """3-day stochastic request triggers exactly 3 run_application_simulation calls.

        Ensures window scaling is proportional to the requested range, not pinned
        to a constant (365 or otherwise).  Also checks structural invariants on
        the returned Series.
        """
        import richardsonpy.classes.appliance as _app_mod

        call_count = [0]
        _original = _app_mod.run_application_simulation

        def _counting_wrapper(*args, **kwargs):
            call_count[0] += 1
            return _original(*args, **kwargs)

        monkeypatch.setattr(_app_mod, "run_application_simulation", _counting_wrapper)

        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days, no DST transition

        profile = generate_load_profile(config, start, end)

        # Exactly THREE simulated days
        assert call_count[0] == 3, (
            f"Expected 3 simulated days for a 3-day window, got {call_count[0]}"
        )

        # Structural invariants
        assert isinstance(profile, pd.Series)
        assert len(profile) == 3 * 1440, (
            f"Expected {3 * 1440} rows, got {len(profile)}"
        )
        assert isinstance(profile.index, pd.DatetimeIndex)
        assert profile.index.tz is not None, "Index must be timezone-aware"
        assert (profile >= 0).all(), "No negative power values expected"
        assert profile.max() < 15.0, (
            f"Peak power {profile.max():.2f} kW exceeds sane domestic bound of 15 kW"
        )

    def test_normalization_does_not_force_annual_demand_into_single_day(self):
        """Stochastic 1-day energy must be close to Elexon 1-day energy.

        Guards against the do_normalization landmine: if we accidentally passed
        do_normalization=True to ElectricLoad on a 1-day window, it would scale
        the output so its total equals the annual demand (~3400 kWh/day instead
        of ~7-8 kWh/day).

        Both stochastic and Elexon paths target the same seasonal daily energy:
          annual/365 × SEASONAL_FACTORS[June=0.80] ≈ 7.45 kWh
        so they should be within 35% of each other, and both within [2, 30] kWh.
        """
        config_stochastic = LoadConfig(
            annual_consumption_kwh=3400.0, use_stochastic=True, seed=42
        )
        config_elexon = LoadConfig(
            annual_consumption_kwh=3400.0, use_stochastic=False
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        profile_stochastic = generate_load_profile(config_stochastic, start, end)
        profile_elexon = generate_load_profile(config_elexon, start, end)

        stochastic_kwh = calculate_annual_consumption(profile_stochastic)
        elexon_kwh = calculate_annual_consumption(profile_elexon)

        # Both should be in a sane daily band
        assert 2.0 <= stochastic_kwh <= 30.0, (
            f"Stochastic daily energy {stochastic_kwh:.2f} kWh is outside "
            f"sane [2, 30] kWh band — possible do_normalization mis-use"
        )
        assert 2.0 <= elexon_kwh <= 30.0, (
            f"Elexon daily energy {elexon_kwh:.2f} kWh is outside [2, 30] kWh band"
        )

        # Stochastic energy should be within 35% of Elexon (both target same seasonal daily)
        assert stochastic_kwh == pytest.approx(elexon_kwh, rel=0.35), (
            f"Stochastic ({stochastic_kwh:.2f} kWh) deviates more than 35% "
            f"from Elexon ({elexon_kwh:.2f} kWh)"
        )

    def test_richardsonpy_runtime_error_falls_back_to_elexon(self, monkeypatch):
        """A runtime exception inside _simulate_stochastic_day falls back to Elexon.

        With richardsonpy as a hard dependency the Elexon path is a *defensive*
        fallback, not a missing-extra gate.  Any richardsonpy runtime error must
        degrade gracefully to the deterministic profile instead of crashing the
        simulation.

        The returned profile must still be a valid 1-minute Series (Elexon shape).
        """
        import solar_challenge.load as load_module

        def _always_raise(*args, **kwargs):
            raise RuntimeError("Simulated richardsonpy internal failure")

        monkeypatch.setattr(load_module, "_simulate_stochastic_day", _always_raise)

        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")

        # Must NOT raise — must degrade to Elexon fallback
        profile = generate_load_profile(config, start, end)

        assert isinstance(profile, pd.Series), "Fallback must return a Series"
        assert len(profile) == 1440, "Fallback must return a full 1-day profile"
        assert (profile >= 0).all(), "Fallback profile must have no negative values"
        assert profile.index.tz is not None, "Fallback profile index must be tz-aware"
