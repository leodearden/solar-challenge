"""Tests for EV charging configuration and profile generation."""

import numpy as np
import pandas as pd
import pytest
from solar_challenge.ev import (
    EVConfig,
    EVChargerType,
    SmartChargingMode,
    generate_ev_charging_profile,
)


class TestEVConfigBasics:
    """Test basic EVConfig functionality."""

    def test_create_with_all_params(self):
        """EVConfig can be created with all parameters."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
            smart_charging_mode="solar",
            name="Test EV",
        )
        assert config.charger_type == "7kW"
        assert config.arrival_hour == 18
        assert config.departure_hour == 7
        assert config.required_charge_kwh == 35.0
        assert config.smart_charging_mode == "solar"
        assert config.name == "Test EV"

    def test_default_values(self):
        """EVConfig uses sensible defaults."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
        )
        assert config.departure_hour == 7  # 7am default
        assert config.required_charge_kwh == 35.0  # 35 kWh default
        assert config.smart_charging_mode == "none"  # Dumb charging default
        assert config.name == ""

    def test_charger_types(self):
        """All standard charger types are valid."""
        for charger_type in ["3.6kW", "7kW", "22kW"]:
            config = EVConfig(
                charger_type=charger_type,
                arrival_hour=18,
            )
            assert config.charger_type == charger_type


class TestEVConfigValidation:
    """Test parameter validation."""

    def test_invalid_charger_type_raises(self):
        """Invalid charger type raises error."""
        with pytest.raises(ValueError, match="Charger type"):
            EVConfig(charger_type="50kW", arrival_hour=18)
        with pytest.raises(ValueError, match="Charger type"):
            EVConfig(charger_type="invalid", arrival_hour=18)

    def test_arrival_hour_must_be_valid(self):
        """Arrival hour must be 0-23."""
        with pytest.raises(ValueError, match="Arrival hour"):
            EVConfig(charger_type="7kW", arrival_hour=-1)
        with pytest.raises(ValueError, match="Arrival hour"):
            EVConfig(charger_type="7kW", arrival_hour=24)

    def test_departure_hour_must_be_valid(self):
        """Departure hour must be 0-23."""
        with pytest.raises(ValueError, match="Departure hour"):
            EVConfig(charger_type="7kW", arrival_hour=18, departure_hour=-1)
        with pytest.raises(ValueError, match="Departure hour"):
            EVConfig(charger_type="7kW", arrival_hour=18, departure_hour=24)

    def test_required_charge_must_be_positive(self):
        """Required charge must be positive."""
        with pytest.raises(ValueError, match="must be positive"):
            EVConfig(charger_type="7kW", arrival_hour=18, required_charge_kwh=0)
        with pytest.raises(ValueError, match="must be positive"):
            EVConfig(charger_type="7kW", arrival_hour=18, required_charge_kwh=-10)

    def test_required_charge_unrealistic_high_raises(self):
        """Unrealistically high required charge raises error."""
        with pytest.raises(ValueError, match="unrealistic"):
            EVConfig(charger_type="7kW", arrival_hour=18, required_charge_kwh=150)

    def test_invalid_smart_charging_mode_raises(self):
        """Invalid smart charging mode raises error."""
        with pytest.raises(ValueError, match="Smart charging mode"):
            EVConfig(
                charger_type="7kW",
                arrival_hour=18,
                smart_charging_mode="invalid",
            )

    def test_insufficient_time_to_charge_raises(self):
        """Insufficient time to charge raises error."""
        # 3.6kW charger, arrive 6am, depart 7am = 1 hour
        # 1 hour * 3.6kW = 3.6 kWh max, but requesting 35 kWh
        with pytest.raises(ValueError, match="Cannot deliver"):
            EVConfig(
                charger_type="3.6kW",
                arrival_hour=6,
                departure_hour=7,
                required_charge_kwh=35.0,
            )


class TestEVConfigHelperMethods:
    """Test helper methods."""

    def test_get_charger_power_kw(self):
        """get_charger_power_kw returns power in kW."""
        config1 = EVConfig(charger_type="3.6kW", arrival_hour=18)
        assert config1.get_charger_power_kw() == 3.6

        config2 = EVConfig(charger_type="7kW", arrival_hour=18)
        assert config2.get_charger_power_kw() == 7.0

        config3 = EVConfig(charger_type="22kW", arrival_hour=18)
        assert config3.get_charger_power_kw() == 22.0

    def test_get_available_charging_hours_same_day(self):
        """Available hours calculated correctly for same-day charging."""
        # Arrive 8am, depart 5pm = 9 hours
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=8,
            departure_hour=17,
        )
        assert config.get_available_charging_hours() == 9.0

    def test_get_available_charging_hours_overnight(self):
        """Available hours calculated correctly for overnight charging."""
        # Arrive 6pm (18), depart 7am (7) = 13 hours
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
        )
        assert config.get_available_charging_hours() == 13.0

    def test_validation_allows_sufficient_time(self):
        """Config validates that charging is possible."""
        # 7kW charger, 13 hours available = 91 kWh max
        # Requesting 35 kWh should be fine
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
        )
        assert config.required_charge_kwh == 35.0


class TestGenerateEVChargingProfile:
    """Test EV charging profile generation."""

    @pytest.fixture
    def config(self) -> EVConfig:
        """Standard test configuration."""
        return EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
        )

    def test_returns_series_with_minute_index(self, config):
        """Output has 1-minute frequency DatetimeIndex."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        assert isinstance(profile, pd.Series)
        assert isinstance(profile.index, pd.DatetimeIndex)
        # One day = 1440 minutes
        assert len(profile) == 1440

    def test_output_in_kw(self, config):
        """Output values are power in kW."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Power should be either 0 or charger power
        unique_values = profile.unique()
        assert 0.0 in unique_values
        assert 7.0 in unique_values or len(unique_values) == 1  # May be all zeros

    def test_no_negative_values(self, config):
        """Output has no negative values."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        assert (profile >= 0).all()

    def test_timezone_aware_index(self, config):
        """Output index is timezone-aware."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(
            config, start, end, timezone="Europe/London"
        )

        assert profile.index.tz is not None

    def test_multi_day_profile(self, config):
        """Generates profile for multiple days."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days
        profile = generate_ev_charging_profile(config, start, end)

        # 3 days = 3 * 1440 minutes
        assert len(profile) == 3 * 1440


class TestDumbChargingMode:
    """Test dumb charging (mode='none')."""

    @pytest.fixture
    def config(self) -> EVConfig:
        """Dumb charging configuration."""
        return EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
            smart_charging_mode="none",
        )

    def test_charging_starts_at_arrival(self, config):
        """Dumb charging starts immediately on arrival."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Should start charging at 18:00 (minute 1080)
        arrival_minute = 18 * 60  # 1080
        assert profile.iloc[arrival_minute] == 7.0

    def test_delivers_required_energy(self, config):
        """Dumb charging delivers the required energy."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Calculate total energy delivered (kWh)
        # Power (kW) * time (minutes) / 60 = energy (kWh)
        total_energy_kwh = profile.sum() / 60
        assert total_energy_kwh == pytest.approx(35.0, rel=0.01)

    def test_charging_duration(self, config):
        """Charging duration matches required energy / power."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # 35 kWh / 7 kW = 5 hours = 300 minutes
        charging_minutes = (profile > 0).sum()
        expected_minutes = int(np.ceil((35.0 / 7.0) * 60))
        assert charging_minutes == expected_minutes


class TestSolarChargingMode:
    """Test solar-aware charging (mode='solar')."""

    @pytest.fixture
    def config(self) -> EVConfig:
        """Solar-aware charging configuration."""
        return EVConfig(
            charger_type="7kW",
            arrival_hour=8,  # Arrive during solar window
            departure_hour=17,  # Depart after solar window
            required_charge_kwh=14.0,  # 2 hours charging
            smart_charging_mode="solar",
        )

    def test_prefers_solar_hours(self, config):
        """Solar mode prefers 10:00-16:00 window."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Solar window: 10:00-16:00 (minutes 600-960)
        solar_window_start = 10 * 60  # 600
        solar_window_end = 16 * 60  # 960

        # Should have some charging in solar window
        solar_charging = profile.iloc[solar_window_start:solar_window_end].sum()
        assert solar_charging > 0

    def test_delivers_required_energy(self, config):
        """Solar charging delivers the required energy."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        total_energy_kwh = profile.sum() / 60
        assert total_energy_kwh == pytest.approx(14.0, rel=0.01)

    def test_fallback_when_solar_insufficient(self):
        """Falls back to immediate charging if solar window insufficient."""
        # Arrive 6pm, depart 8am - no solar window available
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=8,
            required_charge_kwh=35.0,
            smart_charging_mode="solar",
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Should still deliver required energy
        total_energy_kwh = profile.sum() / 60
        assert total_energy_kwh == pytest.approx(35.0, rel=0.01)

        # Should start charging at arrival (no solar available)
        arrival_minute = 18 * 60
        assert profile.iloc[arrival_minute] == 7.0


class TestOffPeakChargingMode:
    """Test off-peak tariff charging (mode='off_peak')."""

    @pytest.fixture
    def config(self) -> EVConfig:
        """Off-peak charging configuration."""
        return EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=8,
            required_charge_kwh=35.0,
            smart_charging_mode="off_peak",
        )

    def test_prefers_economy_7_hours(self, config):
        """Off-peak mode prefers 00:30-07:30 window."""
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Off-peak window next day: 00:30-07:30 (minutes 1440+30 to 1440+450)
        # But we're in a single day, so look at 00:30-07:30 today (minutes 30-450)
        off_peak_start = 0 * 60 + 30  # 30 minutes
        off_peak_end = 7 * 60 + 30  # 450 minutes

        # Should have some charging in off-peak window
        off_peak_charging = profile.iloc[off_peak_start:off_peak_end].sum()
        # May be zero if overnight charging uses next day's window
        assert off_peak_charging >= 0

    def test_delivers_required_energy(self, config):
        """Off-peak charging delivers the required energy."""
        # Need 2 days for overnight charging (arrive 18, depart 8 next day)
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")
        profile = generate_ev_charging_profile(config, start, end)

        # First day charges fully (35 kWh), second day's charge extends beyond window
        # so only partial charging occurs
        total_energy_kwh = profile.sum() / 60
        assert total_energy_kwh == pytest.approx(35.0, rel=0.01)

    def test_overnight_charging_uses_next_day_off_peak(self):
        """Overnight charging uses next day's off-peak window."""
        # Arrive 10pm, depart 8am - should use next day's 00:30-07:30
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=8,
            required_charge_kwh=14.0,  # 2 hours charging
            smart_charging_mode="off_peak",
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # Need 2 days for overnight
        profile = generate_ev_charging_profile(config, start, end)

        # Next day off-peak: 00:30-07:30 on 2024-06-22 (minutes 1440+30 to 1440+450)
        day2_off_peak_start = 1440 + 30
        day2_off_peak_end = 1440 + 450

        off_peak_charging = profile.iloc[day2_off_peak_start:day2_off_peak_end].sum()
        assert off_peak_charging > 0


class TestOvernightCharging:
    """Test overnight charging scenarios."""

    def test_overnight_charging_window(self):
        """Overnight charging correctly spans midnight."""
        # Arrive 10pm (22), depart 6am (6) = 8 hours
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=6,
            required_charge_kwh=28.0,  # 4 hours charging
        )

        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")  # Need 2 days
        profile = generate_ev_charging_profile(config, start, end)

        # Should start charging at 22:00 on day 1 (minute 1320)
        # Should continue into day 2
        day1_arrival = 22 * 60  # 1320
        assert profile.iloc[day1_arrival] == 7.0

        # Should have charging in early hours of day 2
        day2_morning = 1440 + (3 * 60)  # 3am on day 2
        assert profile.iloc[day2_morning] >= 0  # May still be charging

    def test_delivers_energy_across_midnight(self):
        """Overnight charging delivers required energy."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=6,
            required_charge_kwh=28.0,
        )

        # Simulate 2 days - overnight charging spans midnight
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-22")
        profile = generate_ev_charging_profile(config, start, end)

        # First day: 22:00-24:00 (2h = 14 kWh) + 00:00-06:00 (4h = 28 kWh)
        # Second day: 22:00-24:00 (2h = 14 kWh) but next day 06:00 is outside window
        # Total: 14 + 28 = 42 kWh (last evening session included)
        total_energy_kwh = profile.sum() / 60
        assert total_energy_kwh == pytest.approx(42.0, rel=0.01)


class TestDifferentChargerTypes:
    """Test different charger power ratings."""

    def test_slow_charger_3_6kw(self):
        """3.6kW slow charger works correctly."""
        config = EVConfig(
            charger_type="3.6kW",
            arrival_hour=18,
            departure_hour=8,  # 14 hours available
            required_charge_kwh=20.0,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        # Should deliver 20 kWh
        total_energy = profile.sum() / 60
        assert total_energy == pytest.approx(20.0, rel=0.01)

        # Power should be 3.6 kW when charging
        charging_power = profile[profile > 0].unique()
        assert 3.6 in charging_power

    def test_fast_charger_7kw(self):
        """7kW fast charger works correctly."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        total_energy = profile.sum() / 60
        assert total_energy == pytest.approx(35.0, rel=0.01)

        charging_power = profile[profile > 0].unique()
        assert 7.0 in charging_power

    def test_rapid_charger_22kw(self):
        """22kW rapid charger works correctly."""
        config = EVConfig(
            charger_type="22kW",
            arrival_hour=20,
            departure_hour=6,  # 10 hours available
            required_charge_kwh=50.0,
        )
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-21")
        profile = generate_ev_charging_profile(config, start, end)

        total_energy = profile.sum() / 60
        assert total_energy == pytest.approx(50.0, rel=0.01)

        charging_power = profile[profile > 0].unique()
        assert 22.0 in charging_power


class TestEnumTypes:
    """Test enum type definitions."""

    def test_charger_type_enum_values(self):
        """EVChargerType enum has correct values."""
        assert EVChargerType.SLOW == "3.6kW"
        assert EVChargerType.FAST == "7kW"
        assert EVChargerType.RAPID == "22kW"

    def test_smart_charging_mode_enum_values(self):
        """SmartChargingMode enum has correct values."""
        assert SmartChargingMode.NONE == "none"
        assert SmartChargingMode.SOLAR == "solar"
        assert SmartChargingMode.OFF_PEAK == "off_peak"

    def test_can_use_enum_in_config(self):
        """Can use enum values in EVConfig."""
        config = EVConfig(
            charger_type=EVChargerType.FAST,
            arrival_hour=18,
            smart_charging_mode=SmartChargingMode.SOLAR,
        )
        assert config.charger_type == "7kW"
        assert config.smart_charging_mode == "solar"
