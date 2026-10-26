"""Tests for EV charging configuration and profile generation."""

import dataclasses
import itertools
from collections.abc import Iterator

import numpy as np
import pandas as pd
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import (
    EVConfig,
    EVChargerType,
    SmartChargingMode,
    generate_ev_charging_profile,
)
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests._whole_number_forms import whole_number_forms

# June has no clock change, so a profile's positional minutes are its wall-clock minutes.
FIRST_DAY = pd.Timestamp("2024-06-21")
SECOND_DAY = pd.Timestamp("2024-06-22")


def _at(text: str) -> pd.Timestamp:
    """The time *text* in Europe/London, generate_ev_charging_profile's default timezone."""
    return pd.Timestamp(text, tz="Europe/London")


def _sessions(profile: pd.Series) -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    """The (first minute, minute after the last) of each unbroken run of charging in *profile*.

    The minute after a run is counted from the profile's start, since a run can
    end with the profile, where the index has no entry.
    """
    charging = np.concatenate(([False], profile.to_numpy() > 0, [False]))
    edges = profile.index[0] + pd.to_timedelta(np.flatnonzero(np.diff(charging)), unit="min")
    return list(zip(edges[::2], edges[1::2]))


def _grid_configs(charger_type: str, mode: str) -> Iterator[EVConfig]:
    """Every valid EVConfig for *charger_type* and *mode* on a grid of arrival hours, departure hours and charges."""
    for arrival_hour, departure_hour, required_kwh in itertools.product(
        (0, 1, 6, 8, 12, 15, 18, 22), (0, 2, 7, 9, 11, 17, 20), (5.0, 20.0, 35.0, 60.0)
    ):
        try:
            config = EVConfig(charger_type, arrival_hour, departure_hour, required_kwh, mode)
        except ValueError:
            continue
        yield config


def _contract_breaches(config: EVConfig) -> list[str]:
    """How *config*'s FIRST_DAY..SECOND_DAY profile breaks the charging contract, each breach with its values."""
    profile = generate_ev_charging_profile(config, FIRST_DAY, SECOND_DAY)
    power_kw = profile.to_numpy()
    rating_kw = config.get_charger_power_kw()
    arrival = config.arrival_hour * 60
    stay = round(config.get_available_charging_hours() * 60)
    breaches = []

    charged = np.flatnonzero(power_kw)
    away = charged[(charged - arrival) % 1440 >= stay]
    if away.size:
        breaches.append(f"charges while away at minute {away[0]}")

    off_rating = np.unique(power_kw[(power_kw != 0.0) & (power_kw != rating_kw)])
    if off_rating.size:
        breaches.append(f"draws {off_rating.tolist()} kW, neither 0 nor the {rating_kw} kW rating")

    first_stay = profile.iloc[arrival : arrival + stay]
    delivered_kwh = first_stay.sum() / 60
    if not config.required_charge_kwh - 1e-9 <= delivered_kwh <= config.required_charge_kwh + rating_kw / 60 + 1e-9:
        breaches.append(f"first stay delivers {delivered_kwh:.3f} kWh")

    runs = len(_sessions(first_stay))
    if runs != 1:
        breaches.append(f"first stay charges in {runs} runs")
    return breaches


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
        with pytest.raises(ConfigurationError, match="Charger type"):
            EVConfig(charger_type="50kW", arrival_hour=18)
        with pytest.raises(ConfigurationError, match="Charger type"):
            EVConfig(charger_type="invalid", arrival_hour=18)
        with pytest.raises(ConfigurationError, match="Charger type"):
            EVConfig("9kW", 18)

    @pytest.mark.parametrize("arrival_hour", [-1, 24])
    def test_arrival_hour_must_be_valid(self, arrival_hour):
        """Arrival hour must be 0-23."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type="7kW", arrival_hour=arrival_hour)
        assert str(exc_info.value) == f"arrival_hour must be between 0 and 23, got {arrival_hour}"

    @pytest.mark.parametrize("departure_hour", [-1, 24])
    def test_departure_hour_must_be_valid(self, departure_hour):
        """Departure hour must be 0-23."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type="7kW", arrival_hour=18, departure_hour=departure_hour)
        assert str(exc_info.value) == f"departure_hour must be between 0 and 23, got {departure_hour}"

    @pytest.mark.parametrize("required_charge_kwh", [0, -10])
    def test_required_charge_must_be_positive(self, required_charge_kwh):
        """Required charge must be positive."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type="7kW", arrival_hour=18, required_charge_kwh=required_charge_kwh)
        assert str(exc_info.value) == (
            f"required_charge_kwh must be greater than 0 and at most 100, got {required_charge_kwh}"
        )

    def test_required_charge_unrealistic_high_raises(self):
        """Unrealistically high required charge raises error."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type="7kW", arrival_hour=18, required_charge_kwh=150)
        assert str(exc_info.value) == "required_charge_kwh must be greater than 0 and at most 100, got 150"

    @pytest.mark.parametrize("field", ["arrival_hour", "departure_hour"])
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_an_hour_that_is_not_a_finite_number_is_refused_naming_it_and_the_value(self, field, value):
        """A NaN, an infinity, a bool or a word is refused by name, before the hour's range is checked."""
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(EVConfig("7kW"), **{field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    @pytest.mark.parametrize("field", ["arrival_hour", "departure_hour"])
    def test_an_hour_with_a_fractional_part_is_refused_not_truncated(self, field):
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(EVConfig("7kW"), **{field: 17.5})
        assert str(exc_info.value) == f"{field} must be a whole number, got 17.5"

    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_required_charge_that_is_not_a_finite_number_is_refused_naming_it_and_the_value(self, value):
        with pytest.raises(ConfigurationError) as exc_info:
            dataclasses.replace(EVConfig("7kW"), required_charge_kwh=value)
        assert str(exc_info.value) == f"required_charge_kwh must be a finite number, got {value!r}"

    @pytest.mark.parametrize("field", ["arrival_hour", "departure_hour"])
    @pytest.mark.parametrize("value", whole_number_forms(18))
    def test_an_hour_given_as_another_form_of_a_whole_number_is_held_as_that_int(self, field, value):
        hour = getattr(dataclasses.replace(EVConfig("7kW"), **{field: value}), field)
        assert hour == 18
        assert type(hour) is int

    def test_invalid_smart_charging_mode_raises(self):
        """Invalid smart charging mode raises error."""
        with pytest.raises(ConfigurationError, match="Smart charging mode"):
            EVConfig(
                charger_type="7kW",
                arrival_hour=18,
                smart_charging_mode="invalid",
            )

    def test_insufficient_time_to_charge_raises(self):
        """Insufficient time to charge raises error."""
        # 3.6kW charger, arrive 6am, depart 7am = 1 hour
        # 1 hour * 3.6kW = 3.6 kWh max, but requesting 35 kWh
        with pytest.raises(ConfigurationError, match="Cannot deliver"):
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
        profile = generate_ev_charging_profile(config, FIRST_DAY, SECOND_DAY)

        # The second day's session falls on the morning after the period.
        assert _sessions(profile) == [(_at("2024-06-22 00:30"), _at("2024-06-22 05:30"))]

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

        profile = generate_ev_charging_profile(config, FIRST_DAY, SECOND_DAY)

        assert _sessions(profile)[0] == (_at("2024-06-21 22:00"), _at("2024-06-22 02:00"))

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


class TestChargingSessions:
    """Test where each day's charging session falls in the car's stay."""

    @pytest.mark.parametrize("charger_type", ["3.6kW", "7kW", "22kW"])
    @pytest.mark.parametrize("mode", ["none", "solar", "off_peak"])
    def test_every_session_fits_its_stay_and_delivers_the_charge(self, mode, charger_type):
        """Each session runs unbroken at the charger's rating while the car is home, and delivers the charge."""
        configs = list(_grid_configs(charger_type, mode))
        failures = [f"{config}: {'; '.join(breaches)}" for config in configs if (breaches := _contract_breaches(config))]

        assert configs, "no config on the grid is valid, so nothing was checked"
        assert not failures, (
            f"{len(failures)} of {len(configs)} configs break the charging contract; the first 10:\n"
            + "\n".join(failures[:10])
        )

    @pytest.mark.parametrize(
        ("config", "first_session"),
        [
            pytest.param(
                EVConfig("7kW", 8, 17, 14.0, "solar"),
                (_at("2024-06-21 10:00"), _at("2024-06-21 12:00")),
                id="solar-window-holds-the-charge",
            ),
            pytest.param(
                EVConfig("7kW", 22, 8, 14.0, "off_peak"),
                (_at("2024-06-22 00:30"), _at("2024-06-22 02:30")),
                id="off-peak-window-holds-the-charge",
            ),
            pytest.param(
                EVConfig("3.6kW", 18, 7, 35.0, "off_peak"),
                (_at("2024-06-21 21:16"), _at("2024-06-22 07:00")),
                id="off-peak-rest-just-before-the-window",
            ),
            pytest.param(
                EVConfig("7kW", 7, 17, 49.0, "solar"),
                (_at("2024-06-21 09:00"), _at("2024-06-21 16:00")),
                id="solar-rest-just-before-the-window",
            ),
            pytest.param(
                EVConfig("7kW", 9, 18, 56.0, "solar"),
                (_at("2024-06-21 09:00"), _at("2024-06-21 17:00")),
                id="solar-from-arrival-past-the-window",
            ),
            pytest.param(
                EVConfig("7kW", 18, 8, 35.0, "solar"),
                (_at("2024-06-21 18:00"), _at("2024-06-21 23:00")),
                id="solar-no-window-in-the-stay",
            ),
            pytest.param(
                EVConfig("7kW", 18, 12, 35.0, "solar"),
                (_at("2024-06-22 07:00"), _at("2024-06-22 12:00")),
                id="solar-next-mornings-window",
            ),
            pytest.param(
                EVConfig("7kW", 2, 1, 14.0, "off_peak"),
                (_at("2024-06-21 02:00"), _at("2024-06-21 04:00")),
                id="off-peak-window-with-more-room",
            ),
            pytest.param(
                EVConfig("7kW", 6, 5, 7.0, "off_peak"),
                (_at("2024-06-21 06:00"), _at("2024-06-21 07:00")),
                id="off-peak-earliest-of-two-windows-that-fit",
            ),
            pytest.param(
                EVConfig("7kW", 0, 0, 5.0, "off_peak"),
                (_at("2024-06-21 00:30"), _at("2024-06-21 01:13")),
                id="off-peak-waits-for-the-window-to-open",
            ),
            pytest.param(
                EVConfig("7kW", 18, 7, 35.0, "none"),
                (_at("2024-06-21 18:00"), _at("2024-06-21 23:00")),
                id="none-from-arrival",
            ),
        ],
    )
    def test_session_placement(self, config, first_session):
        """The session covers as much of the mode's window as it can, as early as it can."""
        profile = generate_ev_charging_profile(config, FIRST_DAY, SECOND_DAY)

        assert _sessions(profile)[0] == first_session

    @pytest.mark.parametrize(
        ("config", "window_overlap", "departure"),
        [
            pytest.param(
                EVConfig("3.6kW", 18, 7, 35.0, "off_peak"),
                (_at("2024-06-22 00:30"), _at("2024-06-22 07:00")),
                _at("2024-06-22 07:00"),
                id="off-peak",
            ),
            pytest.param(
                EVConfig("3.6kW", 8, 17, 30.0, "solar"),
                (_at("2024-06-21 10:00"), _at("2024-06-21 16:00")),
                _at("2024-06-21 17:00"),
                id="solar",
            ),
        ],
    )
    def test_measured_configs_finish_by_departure(self, config, window_overlap, departure):
        """A window too short for the charge is used whole, and the session still ends by departure."""
        profile = generate_ev_charging_profile(config, FIRST_DAY, SECOND_DAY)
        start, end = _sessions(profile)[0]
        overlap_start, overlap_end = window_overlap
        minute = pd.Timedelta(minutes=1)

        assert end <= departure
        assert profile[start : end - minute].sum() / 60 >= config.required_charge_kwh
        assert (profile[overlap_start : overlap_end - minute] > 0).all()

    def test_a_session_running_when_the_period_ends_is_cut_there(self):
        """The period's last session stops at the period's end, though the car is still home."""
        config = EVConfig("7kW", 22, 6, 28.0, "none")

        profile = generate_ev_charging_profile(config, FIRST_DAY, FIRST_DAY)

        assert _sessions(profile)[-1] == (_at("2024-06-21 22:00"), _at("2024-06-22 00:00"))

    def test_the_first_morning_holds_no_session_from_the_evening_before(self):
        """A known limitation, not a requirement: no session carries over from the evening before the period.

        So a one-day period of this overnight off-peak EV charges nothing. Task 725
        decides whether to model that carry-over, which would change this expectation.
        """
        config = EVConfig("7kW", 22, 8, 14.0, "off_peak")

        profile = generate_ev_charging_profile(config, FIRST_DAY, FIRST_DAY)

        assert profile.sum() == 0


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
