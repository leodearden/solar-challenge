# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for interpolate_to_minute_resolution, which holds each hour's PV power through that hour's 60 minutes, so the energy is unchanged."""

import pandas as pd
import pytest
from solar_challenge.pv import interpolate_to_minute_resolution


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
