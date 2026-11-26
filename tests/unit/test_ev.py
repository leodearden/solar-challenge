"""Tests for EV charging configuration and profile generation."""

import dataclasses
import datetime
import itertools
from collections.abc import Iterator

import numpy as np
import pandas as pd
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import (
    CHARGER_TYPES,
    EVConfig,
    EVChargerType,
    RowWeights,
    SmartChargingMode,
    generate_ev_charging_profile,
    require_tariff_for_smart_charging,
)
from solar_challenge.tariff import TariffConfig
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR, ONE_MINUTE, SimulationWindow, minutes_of_day
from tests._ev_sessions import charging_sessions
from tests._off_peak_ev_on_each_tariff import (
    FIRST_ARRIVAL,
    FIRST_SESSION_ON_EACH_TARIFF,
    JANUARY_WINDOW,
    OFF_PEAK_EV,
)
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests._whole_number_forms import whole_number_forms

ECONOMY_7 = TariffConfig.economy_7()

OFF_PEAK_WITHOUT_A_TARIFF = (
    "smart_charging_mode 'off_peak' charges the EV in the tariff's cheap periods, "
    "but the home has no tariff; add a tariff or use smart_charging_mode 'none'"
)


def _charger_type_refusal(got: str) -> str:
    """The refusal of a charger_type given as *got*, its repr."""
    return f"charger_type must be one of 3.6kW, 7kW, 22kW, got {got}"


def _london_window(first: str, last: str, cadence: datetime.timedelta = ONE_MINUTE) -> SimulationWindow:
    """The window from the ISO date first to the ISO date last, both counted, at cadence on London's clock."""
    return SimulationWindow(
        datetime.date.fromisoformat(first), datetime.date.fromisoformat(last), cadence, "Europe/London"
    )


# June has no clock change, so each stay in these windows lasts exactly its hours.
JUNE_DAY = _london_window("2024-06-21", "2024-06-21")
JUNE_DAYS = _london_window("2024-06-21", "2024-06-22")


def _at(text: str) -> pd.Timestamp:
    """The time *text* in Europe/London."""
    return pd.Timestamp(text, tz="Europe/London")


def _minute_rows(dates: list[str], first: str, last: str) -> pd.DatetimeIndex:
    """The one-minute rows from the clock time *first* to *last*, both counted, on each of *dates* in London, at the microsecond resolution a window's rows have."""
    days = [pd.date_range(f"{date} {first}", f"{date} {last}", freq="1min", tz="Europe/London") for date in dates]
    return days[0].append(days[1:]).as_unit("us")


def _bell_generation(rows: pd.DatetimeIndex) -> np.ndarray:
    """A clear day's PV generation in kW on *rows*: a bell over the local hour that peaks at 4 kW at 13:00, 0 from 21:00 to 05:00."""
    hours = (rows.hour + rows.minute / MINUTES_PER_HOUR).to_numpy()
    generation: np.ndarray = np.where((hours >= 5) & (hours < 21), 4.0 * np.exp(-(((hours - 13) / 3) ** 2)), 0.0)
    return generation


def _step_between(first_hour: int, end_hour: int) -> RowWeights:
    """Weights of 1 on the rows from first_hour to end_hour on the local clock, end_hour excluded, and 0 elsewhere."""

    def weights(rows: pd.DatetimeIndex) -> np.ndarray:
        step: np.ndarray = np.where((rows.hour >= first_hour) & (rows.hour < end_hour), 1.0, 0.0)
        return step

    return weights


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


def _june_stays(config: EVConfig, profile: pd.Series) -> list[pd.Series]:
    """*profile*'s rows in each of *config*'s stays from an arrival on 20, 21 and 22 June, cut to the profile's rows."""
    stay_end = pd.Timedelta(hours=config.get_available_charging_hours()) - pd.Timedelta(minutes=1)
    arrivals = (_at(f"{date} {config.arrival_hour:02d}:00") for date in ("2024-06-20", "2024-06-21", "2024-06-22"))
    return [profile[arrival : arrival + stay_end] for arrival in arrivals]


def _contract_breaches(config: EVConfig, tariff: TariffConfig | None, generation_kw: RowWeights | None) -> list[str]:
    """How *config*'s JUNE_DAYS profile on *tariff* and *generation_kw* breaks the stay contract, each breach with its values."""
    profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=tariff, generation_kw=generation_kw)
    rating_kw = config.get_charger_power_kw()
    arrival = config.arrival_hour * MINUTES_PER_HOUR
    stay_minutes = round(config.get_available_charging_hours() * MINUTES_PER_HOUR)
    breaches = []

    charging = profile.index[profile.to_numpy() > 0.0]
    away = charging[(minutes_of_day(charging) - arrival) % MINUTES_PER_DAY >= stay_minutes]
    if away.size:
        breaches.append(f"charges while away at {away[0]}")

    above_rating = profile[profile > rating_kw]
    if not above_rating.empty:
        breaches.append(f"draws {above_rating.iloc[0]} kW at {above_rating.index[0]}, above the {rating_kw} kW rating")

    stays = _june_stays(config, profile)
    fractional_rows = [int(((stay > 0.0) & (stay != rating_kw)).sum()) for stay in stays]
    if max(fractional_rows) > 1:
        breaches.append(f"its stays charge {fractional_rows} rows below the {rating_kw} kW rating")

    first_stay = stays[1]
    delivered_kwh = JUNE_DAYS.energy_kwh(first_stay)
    if abs(delivered_kwh - config.required_charge_kwh) > 1e-9:
        breaches.append(f"the stay from 21 June delivers {delivered_kwh!r} kWh")

    runs = len(charging_sessions(first_stay))
    if runs != 1:
        breaches.append(f"the stay from 21 June charges in {runs} runs")
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

    def test_a_charger_type_is_held_as_its_member(self):
        assert EVConfig("7kW").charger_type is EVChargerType.FAST

    def test_a_smart_charging_mode_is_held_as_its_member(self):
        assert EVConfig("7kW", smart_charging_mode="off_peak").smart_charging_mode is SmartChargingMode.OFF_PEAK

    def test_the_default_smart_charging_mode_is_held_as_its_member(self):
        assert EVConfig("7kW").smart_charging_mode is SmartChargingMode.NONE

    def test_the_default_smart_charging_mode_beside_a_charger_type_given_as_a_member_is_held_as_its_member(self):
        assert EVConfig(EVChargerType.FAST, 18).smart_charging_mode is SmartChargingMode.NONE

    def test_a_member_given_is_held_as_that_member(self):
        config = EVConfig(EVChargerType.RAPID, smart_charging_mode=SmartChargingMode.SOLAR)

        assert (config.charger_type, config.smart_charging_mode) == (EVChargerType.RAPID, SmartChargingMode.SOLAR)
        assert config.charger_type is EVChargerType.RAPID
        assert config.smart_charging_mode is SmartChargingMode.SOLAR

    def test_a_held_member_still_reads_as_its_string(self):
        """A held member equals, formats and indexes as the string it was given."""
        charger_type = EVConfig("7kW").charger_type

        assert charger_type == "7kW"
        assert str(charger_type) == "7kW"
        assert f"{charger_type}" == "7kW"
        assert {"7kW": 1}[charger_type] == 1


class TestEVConfigValidation:
    """Test parameter validation."""

    @pytest.mark.parametrize("charger_type", ["50kW", "invalid", "9kW", 7, None])
    def test_invalid_charger_type_raises(self, charger_type):
        """An unknown charger type, or one that is not a str, is refused naming the field and the allowed values."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type=charger_type, arrival_hour=18)
        assert isinstance(exc_info.value, ValueError)
        assert str(exc_info.value) == _charger_type_refusal(repr(charger_type))

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
        """An unknown smart charging mode is refused naming the field and the allowed values."""
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(
                charger_type="7kW",
                arrival_hour=18,
                smart_charging_mode="invalid",
            )
        assert isinstance(exc_info.value, ValueError)
        assert str(exc_info.value) == "smart_charging_mode must be one of none, solar, off_peak, got 'invalid'"

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

    @pytest.mark.parametrize("charger_type", CHARGER_TYPES)
    def test_get_charger_power_kw_is_the_held_charger_types_power(self, charger_type):
        config = EVConfig(charger_type)

        assert config.get_charger_power_kw() == config.charger_type.power_kw

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
    """The profile's rows are its window's rows."""

    @pytest.fixture
    def config(self) -> EVConfig:
        """Standard test configuration."""
        return EVConfig(
            charger_type="7kW",
            arrival_hour=18,
            departure_hour=7,
            required_charge_kwh=35.0,
        )

    @pytest.mark.parametrize(
        "window",
        [
            pytest.param(JUNE_DAY, id="one-june-day"),
            pytest.param(_london_window("2024-06-21", "2024-06-23"), id="three-june-days"),
            pytest.param(_london_window("2024-03-29", "2024-04-02"), id="across-the-spring-change"),
        ],
    )
    def test_the_profile_is_non_negative_kw_on_the_windows_rows(self, config, window):
        profile = generate_ev_charging_profile(config, window)

        assert isinstance(profile, pd.Series)
        assert profile.index.equals(window.rows())
        assert str(profile.index.tz) == "Europe/London"
        assert (profile >= 0).all()


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
        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert profile[_at("2024-06-21 18:00")] == 7.0

    def test_delivers_required_energy(self, config):
        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(35.0, abs=1e-9)

    def test_charging_duration(self, config):
        """35 kWh at 7 kW is 300 one-minute rows."""
        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert (profile > 0).sum() == 300

    def test_each_wall_clock_day_charges_from_arrival_across_the_spring_change(self, config):
        """B4: 31 March starts at 18:00 BST, as every other day starts at 18:00 on its own clock."""
        window = _london_window("2024-03-29", "2024-04-02")
        dates = ["2024-03-29", "2024-03-30", "2024-03-31", "2024-04-01", "2024-04-02"]

        profile = generate_ev_charging_profile(config, window)

        assert list(profile.index[profile.to_numpy() > 0]) == list(_minute_rows(dates, "18:00", "22:59"))
        assert (profile[profile > 0] == 7.0).all()
        assert window.energy_kwh(profile) == pytest.approx(175.0, abs=1e-9)

    def test_a_stay_the_clocks_shorten_below_the_charge_charges_all_of_it(self):
        """30 March 18:00 GMT to 31 March 07:00 BST is 720 rows, short of the 780 that 46.8 kWh at 3.6 kW needs."""
        config = EVConfig("3.6kW", 18, 7, 46.8, "none")
        window = _london_window("2024-03-30", "2024-03-31")

        stay = generate_ev_charging_profile(config, window)[_at("2024-03-30 18:00") : _at("2024-03-31 06:59")]

        assert len(stay) == 720
        assert (stay == 3.6).all()
        assert window.energy_kwh(stay) == pytest.approx(43.2, abs=1e-9)

    def test_the_cadence_is_the_windows(self, config):
        """D8: on 30-minute rows, 35 kWh at 7 kW is 10 rows from 18:00 each day."""
        window = _london_window("2024-06-21", "2024-06-22", cadence=datetime.timedelta(minutes=30))

        profile = generate_ev_charging_profile(config, window)

        charging = profile[profile > 0]
        expected = [
            _at(f"{date} 18:00") + pd.Timedelta(minutes=30 * row)
            for date in ("2024-06-21", "2024-06-22")
            for row in range(10)
        ]
        assert list(charging.index) == expected
        assert (charging == 7.0).all()
        assert window.energy_kwh(profile) == pytest.approx(70.0, abs=1e-9)


class TestExactEnergy:
    """Each stay delivers exactly required_charge_kwh: whole rows at the rating, then one fractional row."""

    def test_a_charge_of_whole_rows_charges_exactly_those_rows(self):
        """30 kWh at 3.6 kW is 500 one-minute rows, 08:00-16:19, where a ceiling of minutes gave 501."""
        config = EVConfig("3.6kW", 8, 17, 30.0, "none")

        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert list(profile.index[profile.to_numpy() > 0]) == list(_minute_rows(["2024-06-21"], "08:00", "16:19"))
        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(30.0, abs=1e-9)

    def test_a_charge_ending_inside_a_row_charges_that_row_at_the_fraction_of_the_rating(self):
        """10 kWh at 7 kW is 85.714... rows: 85 rows at 7 kW, 9.91666... kWh, then the session's last row at 5 kW for the 0.08333... kWh left."""
        config = EVConfig("7kW", 18, 7, 10.0, "none")

        profile = generate_ev_charging_profile(config, JUNE_DAY)

        session = profile[profile > 0]
        assert list(session.index) == list(_minute_rows(["2024-06-21"], "18:00", "19:25"))
        assert (session.iloc[:85] == 7.0).all()
        assert session.iloc[85] == pytest.approx(5.0, abs=1e-9)
        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(10.0, abs=1e-9)


class TestSolarChargingMode:
    """A solar EV charges in the run of its stay with the most of the generation it is given (L11)."""

    def test_it_charges_in_the_run_with_the_most_generation(self):
        """On weights of 1 from 13:00 to 16:00, a two-hour charge takes the earliest run that holds them: 13:00-14:59."""
        config = EVConfig("7kW", 8, 17, 14.0, "solar")

        profile = generate_ev_charging_profile(config, JUNE_DAY, generation_kw=_step_between(13, 16))

        assert charging_sessions(profile) == [(_at("2024-06-21 13:00"), _at("2024-06-21 15:00"))]
        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(14.0, abs=1e-9)

    def test_other_generation_moves_the_session(self):
        config = EVConfig("7kW", 8, 17, 14.0, "solar")

        sessions = [
            charging_sessions(generate_ev_charging_profile(config, JUNE_DAY, generation_kw=generation))
            for generation in (_step_between(9, 12), _step_between(13, 16))
        ]

        assert sessions == [
            [(_at("2024-06-21 09:00"), _at("2024-06-21 11:00"))],
            [(_at("2024-06-21 13:00"), _at("2024-06-21 15:00"))],
        ]

    def test_a_stay_with_no_generation_charges_from_arrival(self):
        config = EVConfig("7kW", 8, 17, 14.0, "solar")

        profile = generate_ev_charging_profile(config, JUNE_DAY, generation_kw=lambda rows: np.zeros(len(rows)))

        assert charging_sessions(profile) == [(_at("2024-06-21 08:00"), _at("2024-06-21 10:00"))]

    def test_on_a_plateau_of_generation_the_earliest_run_wins(self):
        """Generation clipped at 3 kW is a plateau of one float, so the session starts on its first row."""
        config = EVConfig("7kW", 8, 17, 14.0, "solar")

        def clipped(rows: pd.DatetimeIndex) -> np.ndarray:
            return np.minimum(_bell_generation(rows), 3.0)

        profile = generate_ev_charging_profile(config, JUNE_DAY, generation_kw=clipped)

        plateau = JUNE_DAY.rows()[clipped(JUNE_DAY.rows()) == 3.0]
        assert charging_sessions(profile)[0][0] == plateau[0]

    def test_a_solar_ev_does_not_read_the_tariff(self):
        """Reading Economy 10's cheap minutes, 13:00-16:00 in this stay, would start the session at 13:00, after the bell's peak."""
        config = EVConfig("7kW", 8, 17, 14.0, "solar")

        pd.testing.assert_series_equal(
            generate_ev_charging_profile(
                config, JUNE_DAYS, tariff=TariffConfig.economy_10(), generation_kw=_bell_generation
            ),
            generate_ev_charging_profile(config, JUNE_DAYS, generation_kw=_bell_generation),
        )

    def test_generation_of_another_length_than_the_rows_is_refused_naming_both(self):
        config = EVConfig("7kW", 8, 17, 14.0, "solar")
        widened_rows = len(_london_window("2024-06-20", "2024-06-22").rows())

        with pytest.raises(ValueError) as exc_info:
            generate_ev_charging_profile(config, JUNE_DAY, generation_kw=lambda rows: np.zeros(len(rows) - 1))

        assert f"{widened_rows}" in str(exc_info.value)
        assert f"{widened_rows - 1}" in str(exc_info.value)

    @pytest.mark.parametrize("weight", [np.nan, np.inf, -np.inf], ids=["nan", "inf", "minus-inf"])
    def test_generation_that_is_not_a_finite_number_is_refused_naming_its_first_such_row_and_weight(self, weight):
        """A NaN would otherwise win np.argmax and place the session silently; the rows asked for start on 20 June."""
        config = EVConfig("7kW", 8, 17, 14.0, "solar")
        first_bad_row = _london_window("2024-06-20", "2024-06-22").rows()[997]

        def generation(rows: pd.DatetimeIndex) -> np.ndarray:
            with_bad_rows = _bell_generation(rows)
            with_bad_rows[997::997] = weight
            return with_bad_rows

        with pytest.raises(ValueError) as exc_info:
            generate_ev_charging_profile(config, JUNE_DAY, generation_kw=generation)

        assert f"{first_bad_row}" in str(exc_info.value)
        assert f" {weight} " in str(exc_info.value)

    def test_a_solar_ev_without_generation_is_refused_naming_the_mode_and_the_missing_generation(self):
        with pytest.raises(ConfigurationError) as exc_info:
            generate_ev_charging_profile(EVConfig("7kW", 8, 17, 14.0, "solar"), JUNE_DAY)

        assert "smart_charging_mode 'solar'" in str(exc_info.value)
        assert "generation_kw" in str(exc_info.value)


class TestOffPeakChargingMode:
    """Test off-peak tariff charging (mode='off_peak') on Economy 7, whose cheap minutes are 00:30-07:30."""

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
        """Each morning holds the session of the stay from the evening before; the second evening's falls after the window."""
        profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=ECONOMY_7)

        assert charging_sessions(profile) == [
            (_at("2024-06-21 00:30"), _at("2024-06-21 05:30")),
            (_at("2024-06-22 00:30"), _at("2024-06-22 05:30")),
        ]

    def test_delivers_required_energy(self, config):
        """Two mornings, the first from the evening before the window: 35 kWh each."""
        profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=ECONOMY_7)

        assert JUNE_DAYS.energy_kwh(profile) == pytest.approx(70.0, abs=1e-9)

    def test_a_one_day_window_charges_the_previous_evenings_stay(self, config):
        """B4: the one morning of 21 June charges the stay from 20 June's 18:00, 00:30-05:29 at 7 kW."""
        profile = generate_ev_charging_profile(config, JUNE_DAY, tariff=ECONOMY_7)

        assert list(profile.index[profile.to_numpy() > 0]) == list(_minute_rows(["2024-06-21"], "00:30", "05:29"))
        assert (profile[profile > 0] == 7.0).all()
        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(35.0, abs=1e-9)

    def test_a_week_charges_one_session_for_each_morning(self, config):
        """8-14 January has seven mornings, the first charging the stay from 7 January."""
        window = _london_window("2024-01-08", "2024-01-14")

        profile = generate_ev_charging_profile(config, window, tariff=ECONOMY_7)

        assert window.energy_kwh(profile) == pytest.approx(245.0, abs=1e-9)

    def test_a_session_after_the_autumn_change_starts_at_the_first_0030(self, config):
        """27 October's session starts at 00:30 BST and runs 300 rows, through the repeated hour, to 04:29 GMT."""
        profile = generate_ev_charging_profile(config, _london_window("2024-10-26", "2024-10-27"), tariff=ECONOMY_7)

        session = charging_sessions(profile[_at("2024-10-26 18:00") :])[0]
        assert session == (_at("2024-10-27 00:30"), _at("2024-10-27 04:30"))
        assert (profile[session[0] : session[1] - pd.Timedelta(minutes=1)] > 0).sum() == 300

    def test_overnight_charging_uses_next_day_off_peak(self):
        """Arrive 22:00, depart 08:00: the stay from 21 June charges 14 kWh in 22 June's 00:30-07:30."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=8,
            required_charge_kwh=14.0,
            smart_charging_mode="off_peak",
        )
        profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=ECONOMY_7)

        assert JUNE_DAYS.energy_kwh(profile[_at("2024-06-22 00:30") : _at("2024-06-22 07:29")]) == pytest.approx(
            14.0, abs=1e-9
        )


class TestOvernightCharging:
    """Test overnight charging scenarios."""

    def test_overnight_charging_window(self):
        """Overnight charging correctly spans midnight."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=6,
            required_charge_kwh=28.0,
        )

        profile = generate_ev_charging_profile(config, JUNE_DAYS)

        assert charging_sessions(profile[_at("2024-06-21 22:00") :])[0] == (
            _at("2024-06-21 22:00"),
            _at("2024-06-22 02:00"),
        )

    def test_delivers_energy_across_midnight(self):
        """21 June's first morning carries 14 kWh in from the evening before, its stay 28, and 22 June's evening 14 before the window ends."""
        config = EVConfig(
            charger_type="7kW",
            arrival_hour=22,
            departure_hour=6,
            required_charge_kwh=28.0,
        )

        profile = generate_ev_charging_profile(config, JUNE_DAYS)

        assert JUNE_DAYS.energy_kwh(profile) == pytest.approx(14.0 + 28.0 + 14.0, abs=1e-9)


class TestChargingSessions:
    """Test where each day's charging session falls in the car's stay."""

    @pytest.mark.parametrize("charger_type", ["3.6kW", "7kW", "22kW"])
    @pytest.mark.parametrize(
        ("mode", "tariff", "generation_kw"),
        [
            pytest.param("none", None, None, id="none"),
            pytest.param("solar", None, _bell_generation, id="solar-on-a-bell-of-generation"),
            pytest.param("off_peak", ECONOMY_7, None, id="off_peak-economy-7"),
            pytest.param(
                "off_peak", TariffConfig.economy_10(), None, id="off_peak-economy-10-three-cheap-windows"
            ),
            pytest.param("off_peak", TariffConfig.flat_rate(0.25), None, id="off_peak-flat-rate-no-cheap-minute"),
        ],
    )
    def test_every_session_fits_its_stay_and_delivers_the_charge(self, mode, tariff, generation_kw, charger_type):
        """Each session runs unbroken at the charger's rating, but for at most one fractional row, while the car is home, and delivers the charge exactly."""
        configs = list(_grid_configs(charger_type, mode))
        failures = [
            f"{config}: {'; '.join(breaches)}"
            for config in configs
            if (breaches := _contract_breaches(config, tariff, generation_kw))
        ]

        assert configs, "no config on the grid is valid, so nothing was checked"
        assert not failures, (
            f"{len(failures)} of {len(configs)} configs break the charging contract; the first 10:\n"
            + "\n".join(failures[:10])
        )

    @pytest.mark.parametrize(
        ("config", "tariff", "session"),
        [
            pytest.param(
                EVConfig("7kW", 22, 8, 14.0, "off_peak"),
                ECONOMY_7,
                (_at("2024-06-22 00:30"), _at("2024-06-22 02:30")),
                id="off-peak-window-holds-the-charge",
            ),
            pytest.param(
                EVConfig("3.6kW", 18, 7, 35.0, "off_peak"),
                ECONOMY_7,
                (_at("2024-06-21 21:16"), _at("2024-06-22 07:00")),
                id="off-peak-rest-just-before-the-window",
            ),
            pytest.param(
                EVConfig("7kW", 2, 1, 14.0, "off_peak"),
                ECONOMY_7,
                (_at("2024-06-21 02:00"), _at("2024-06-21 04:00")),
                id="off-peak-window-with-more-room",
            ),
            pytest.param(
                EVConfig("7kW", 6, 5, 7.0, "off_peak"),
                ECONOMY_7,
                (_at("2024-06-21 06:00"), _at("2024-06-21 07:00")),
                id="off-peak-earliest-of-two-windows-that-fit",
            ),
            pytest.param(
                EVConfig("7kW", 0, 0, 5.0, "off_peak"),
                ECONOMY_7,
                (_at("2024-06-21 00:30"), _at("2024-06-21 01:13")),
                id="off-peak-waits-for-the-window-to-open",
            ),
            pytest.param(
                EVConfig("7kW", 18, 7, 35.0, "none"),
                None,
                (_at("2024-06-21 18:00"), _at("2024-06-21 23:00")),
                id="none-from-arrival",
            ),
        ],
    )
    def test_session_placement(self, config, tariff, session):
        """The session of the stay from 21 June's arrival covers as much of the tariff's cheap minutes as it can, as early as it can."""
        profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=tariff)

        assert charging_sessions(profile[_at(f"2024-06-21 {config.arrival_hour:02d}:00") :])[0] == session

    def test_a_cheap_window_too_short_for_the_charge_is_used_whole_and_the_session_ends_by_departure(self):
        config = EVConfig("3.6kW", 18, 7, 35.0, "off_peak")

        profile = generate_ev_charging_profile(config, JUNE_DAYS, tariff=ECONOMY_7)

        start, end = charging_sessions(profile[_at("2024-06-21 18:00") :])[0]
        session = profile[start : end - pd.Timedelta(minutes=1)]
        assert end <= _at("2024-06-22 07:00")
        assert JUNE_DAYS.energy_kwh(session) == pytest.approx(config.required_charge_kwh, abs=1e-9)
        assert (profile[_at("2024-06-22 00:30") : _at("2024-06-22 06:59")] > 0).all()

    def test_a_session_running_when_the_period_ends_is_cut_there(self):
        """The period's last session stops at the period's end, though the car is still home."""
        config = EVConfig("7kW", 22, 6, 28.0, "none")

        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert charging_sessions(profile)[-1] == (_at("2024-06-21 22:00"), _at("2024-06-22 00:00"))

    def test_the_first_morning_holds_the_previous_evenings_session(self):
        """A one-day window of this overnight off-peak EV charges the stay from 20 June's 22:00 on 21 June's 00:30-02:29."""
        config = EVConfig("7kW", 22, 8, 14.0, "off_peak")

        profile = generate_ev_charging_profile(config, JUNE_DAY, tariff=ECONOMY_7)

        assert charging_sessions(profile) == [(_at("2024-06-21 00:30"), _at("2024-06-21 02:30"))]
        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(14.0, abs=1e-9)


class TestOffPeakReadsTheTariff:
    """An off_peak EV charges in its tariff's cheap minutes, and is refused with no tariff (§9 row 15 of docs/prds/tariff-coverage-classifier-presets.md)."""

    @pytest.mark.parametrize(("tariff", "first_session"), FIRST_SESSION_ON_EACH_TARIFF)
    def test_the_first_session_covers_the_most_cheap_minutes_it_can_as_early_as_it_can(self, tariff, first_session):
        profile = generate_ev_charging_profile(OFF_PEAK_EV, JANUARY_WINDOW, tariff=tariff)

        assert charging_sessions(profile[FIRST_ARRIVAL:])[0] == first_session

    def test_on_economy_10_no_minute_of_the_session_is_at_the_peak_rate(self):
        """Economy 7's 00:30-07:30 would put 30 of the 300 minutes in Economy 10's peak from 05:00."""
        economy_10 = TariffConfig.economy_10()
        profile = generate_ev_charging_profile(OFF_PEAK_EV, JANUARY_WINDOW, tariff=economy_10)
        start, end = charging_sessions(profile[FIRST_ARRIVAL:])[0]

        rates = [economy_10.get_rate(minute) for minute in pd.date_range(start, end, freq="1min", inclusive="left")]

        assert len(rates) == 300
        assert all(rate < economy_10.peak_rate for rate in rates)

    def test_a_tariff_with_no_cheap_minute_charges_from_arrival_as_none_does(self):
        charging_from_arrival = dataclasses.replace(OFF_PEAK_EV, smart_charging_mode="none")

        pd.testing.assert_series_equal(
            generate_ev_charging_profile(OFF_PEAK_EV, JANUARY_WINDOW, tariff=TariffConfig.flat_rate(0.25)),
            generate_ev_charging_profile(charging_from_arrival, JANUARY_WINDOW),
        )

    def test_an_off_peak_ev_with_no_tariff_is_refused_naming_the_mode_and_the_missing_tariff(self):
        with pytest.raises(ConfigurationError) as exc_info:
            generate_ev_charging_profile(OFF_PEAK_EV, JUNE_DAYS)

        assert str(exc_info.value) == OFF_PEAK_WITHOUT_A_TARIFF


class TestRequireTariffForSmartCharging:
    """require_tariff_for_smart_charging refuses an off_peak EV with no tariff, and only that."""

    @pytest.mark.parametrize("mode", ["none", "solar"])
    def test_a_mode_that_reads_no_tariff_is_accepted_with_none(self, mode):
        require_tariff_for_smart_charging(EVConfig("7kW", 18, 7, 35.0, mode), None)

    def test_off_peak_with_a_tariff_is_accepted(self):
        require_tariff_for_smart_charging(OFF_PEAK_EV, ECONOMY_7)

    def test_off_peak_with_no_tariff_is_refused(self):
        with pytest.raises(ConfigurationError) as exc_info:
            require_tariff_for_smart_charging(OFF_PEAK_EV, None)

        assert str(exc_info.value) == OFF_PEAK_WITHOUT_A_TARIFF


class TestDifferentChargerTypes:
    """Each charger type charges at its rating and delivers the charge exactly; each evening's session ends before midnight, and the evening before the window's falls outside it."""

    @pytest.mark.parametrize(
        ("config", "rating_kw"),
        [
            pytest.param(EVConfig("3.6kW", 18, 8, 20.0), 3.6, id="slow-3.6kW"),
            pytest.param(EVConfig("7kW", 18, 7, 35.0), 7.0, id="fast-7kW"),
            pytest.param(EVConfig("22kW", 20, 6, 50.0), 22.0, id="rapid-22kW"),
        ],
    )
    def test_a_charger_delivers_the_charge_at_its_rating(self, config, rating_kw):
        profile = generate_ev_charging_profile(config, JUNE_DAY)

        assert JUNE_DAY.energy_kwh(profile) == pytest.approx(config.required_charge_kwh, abs=1e-9)
        assert profile.max() == rating_kw


class TestEnumTypes:
    """Test enum type definitions."""

    def test_charger_type_enum_values(self):
        """EVChargerType enum has correct values."""
        assert EVChargerType.SLOW == "3.6kW"
        assert EVChargerType.FAST == "7kW"
        assert EVChargerType.RAPID == "22kW"

    @pytest.mark.parametrize(
        ("charger_type", "power_kw"),
        [(EVChargerType.SLOW, 3.6), (EVChargerType.FAST, 7.0), (EVChargerType.RAPID, 22.0)],
    )
    def test_a_charger_types_power_is_its_rating_in_kw(self, charger_type, power_kw):
        assert charger_type.power_kw == power_kw

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
        assert config.charger_type is EVChargerType.FAST
        assert config.smart_charging_mode is SmartChargingMode.SOLAR


class TestChargerTypes:
    """CHARGER_TYPES is the charger vocabulary, the EVChargerType values, and EVConfig refuses by it."""

    def test_charger_types_are_the_charger_type_enum_values_in_member_order(self):
        assert CHARGER_TYPES == tuple(charger.value for charger in EVChargerType)

    @pytest.mark.parametrize("charger_type", ["50kW", "invalid"])
    def test_a_charger_type_outside_charger_types_is_refused_listing_each_one(self, charger_type):
        with pytest.raises(ConfigurationError) as exc_info:
            EVConfig(charger_type=charger_type)
        assert str(exc_info.value) == _charger_type_refusal(repr(charger_type))
