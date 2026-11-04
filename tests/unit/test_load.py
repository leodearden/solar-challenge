"""Tests for load profile generation."""

import dataclasses
import datetime
import logging
import math
import re
from collections.abc import Sequence
from typing import NoReturn

import numpy as np
import pandas as pd
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.load import (
    ELEXON_PROFILE_CLASS_1,
    DaySimulator,
    HouseholdModel,
    LoadConfig,
    OFGEM_TDCV_BY_OCCUPANTS,
    SEASONAL_FACTORS,
    energy_kwh,
    generate_load_profile,
    household_occupant_count,
    richardsonpy_household,
    scale_profile_to_energy,
)
from solar_challenge.timebase import ONE_MINUTE, SimulationWindow
from tests._non_booleans import NON_BOOLEANS
from tests._unusable_numbers import UNUSABLE_NUMBERS


def _window(
    first: str,
    last: str,
    *,
    cadence: datetime.timedelta = ONE_MINUTE,
    timezone: str = "Europe/London",
) -> SimulationWindow:
    """The window from the ISO date first to the ISO date last, both counted, at cadence on timezone's clock."""
    return SimulationWindow(
        datetime.date.fromisoformat(first), datetime.date.fromisoformat(last), cadence, timezone
    )


def _seasonal_energy_kwh(annual_kwh: float, day: datetime.date) -> float:
    """The household's energy on day, E_d of docs/prds/load-composition-and-calendar-days.md decision 6, with the seasonal factors summed date by date over day's calendar year."""
    new_years_day = datetime.date(day.year, 1, 1)
    year_dates = [
        new_years_day + datetime.timedelta(days=offset)
        for offset in range((datetime.date(day.year + 1, 1, 1) - new_years_day).days)
    ]
    return annual_kwh * SEASONAL_FACTORS[day.month] / sum(SEASONAL_FACTORS[date.month] for date in year_dates)


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
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(household_occupants=11)
        assert str(exc_info.value) == "household_occupants must be between 1 and 10, got 11"

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
    def test_an_annual_consumption_that_is_not_finite_is_refused(self, value: float) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(annual_consumption_kwh=value)
        assert str(exc_info.value) == f"annual_consumption_kwh must be a finite number, got {value!r}"

    @pytest.mark.parametrize("occupants", [math.nan, -math.inf, math.inf])
    def test_an_occupant_count_that_is_not_finite_is_refused(self, occupants: float) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(household_occupants=occupants)
        assert str(exc_info.value) == f"household_occupants must be a finite number, got {occupants!r}"

    @pytest.mark.parametrize(
        ("occupants", "requirement"),
        [
            pytest.param(2.5, "a whole number", id="2.5"),
            pytest.param(7.5, "a whole number", id="7.5"),
            pytest.param(True, "a finite number", id="True"),
            pytest.param(np.True_, "a finite number", id="numpy-bool"),
        ],
    )
    def test_an_occupant_count_that_is_not_a_whole_number_is_refused(
        self, occupants: object, requirement: str
    ) -> None:
        """A fraction is refused as not whole, and a bool, Python's or numpy's, as not a finite number."""
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(household_occupants=occupants)
        assert str(exc_info.value) == f"household_occupants must be {requirement}, got {occupants!r}"

    @pytest.mark.parametrize("occupants", [0.5, 10.5])
    def test_a_fractional_occupant_count_is_refused_as_not_whole_wherever_it_lies(
        self, occupants: float
    ) -> None:
        """The whole-number rule comes before the range, so a fraction outside 1 to 10 is refused as not whole."""
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(household_occupants=occupants)
        assert str(exc_info.value) == f"household_occupants must be a whole number, got {occupants!r}"

    @pytest.mark.parametrize("field", ["annual_consumption_kwh", "household_occupants"])
    @pytest.mark.parametrize("value", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_number_that_is_not_finite_is_refused_naming_its_field_and_the_value(
        self, field: str, value: object
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(**{field: value})
        assert str(exc_info.value) == f"{field} must be a finite number, got {value!r}"

    def test_a_whole_number_annual_consumption_is_held_as_the_float_it_equals(self) -> None:
        consumption = LoadConfig(annual_consumption_kwh=3400).annual_consumption_kwh
        assert consumption == 3400.0
        assert type(consumption) is float

    @pytest.mark.parametrize(
        "occupants",
        [pytest.param(3.0, id="float"), pytest.param(np.int64(3), id="numpy-int64")],
    )
    def test_a_whole_number_occupant_count_of_another_numeric_type_is_held_as_an_int(
        self, occupants: object
    ) -> None:
        config = LoadConfig(household_occupants=occupants)

        assert type(config.household_occupants) is int
        assert config.household_occupants == 3


class TestHouseholdOccupantCount:
    """household_occupant_count is LoadConfig's occupant rule, for a caller holding a count that is not an int."""

    @pytest.mark.parametrize(
        "occupants",
        [pytest.param(3.0, id="float"), pytest.param(np.int64(3), id="numpy-int64")],
    )
    def test_a_whole_number_count_is_given_as_the_int_it_equals(self, occupants: float) -> None:
        count = household_occupant_count(occupants)

        assert type(count) is int
        assert count == 3

    @pytest.mark.parametrize(
        ("occupants", "refusal"),
        [
            pytest.param(0.0, "household_occupants must be between 1 and 10, got 0.0", id="below-one"),
            pytest.param(11, "household_occupants must be between 1 and 10, got 11", id="above-ten"),
            pytest.param(2.5, "household_occupants must be a whole number, got 2.5", id="fraction"),
            pytest.param(True, "household_occupants must be a finite number, got True", id="boolean"),
        ],
    )
    def test_a_count_that_is_not_a_whole_number_from_1_to_10_is_refused_naming_it(
        self, occupants: float, refusal: str
    ) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            household_occupant_count(occupants)
        assert str(exc_info.value) == refusal


class TestLoadConfigSeed:
    """LoadConfig reads its seed as a whole number, holding the int it is; None draws fresh entropy."""

    @pytest.mark.parametrize("seed", [*UNUSABLE_NUMBERS, pytest.param("x", id="word")])
    def test_a_seed_that_is_not_a_finite_number_is_refused_naming_it(self, seed: object) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(seed=seed)
        assert str(exc_info.value) == f"seed must be a finite number, got {seed!r}"

    def test_a_seed_with_a_fractional_part_is_refused_not_truncated(self) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(seed=2.5)
        assert str(exc_info.value) == "seed must be a whole number, got 2.5"

    @pytest.mark.parametrize(
        "seed",
        [
            pytest.param(np.int64(42), id="numpy-int64"),
            pytest.param(2**53 + 1, id="beyond-a-floats-precision"),
        ],
    )
    def test_an_integer_seed_is_held_as_the_python_int_it_is(self, seed: int | np.int64) -> None:
        held = LoadConfig(seed=seed).seed
        assert held == int(seed)
        assert type(held) is int

    def test_no_seed_stays_none(self) -> None:
        assert LoadConfig(seed=None).seed is None


class TestLoadConfigUseStochastic:
    """LoadConfig reads use_stochastic as true or false, holding the Python bool; any other value is refused, not read by its truthiness."""

    @pytest.mark.parametrize("value", (*NON_BOOLEANS, pytest.param(None, id="null")))
    def test_a_value_that_is_not_a_bool_is_refused_naming_it(self, value: object) -> None:
        with pytest.raises(ConfigurationError) as exc_info:
            LoadConfig(use_stochastic=value)
        assert str(exc_info.value) == f"use_stochastic must be true or false, got {value!r}"

    @pytest.mark.parametrize(
        "value", [pytest.param(np.True_, id="numpy-true"), pytest.param(np.False_, id="numpy-false")]
    )
    def test_a_numpy_bool_is_held_as_the_python_bool_it_is(self, value: np.bool_) -> None:
        assert LoadConfig(use_stochastic=value).use_stochastic is bool(value)


class TestGenerateLoadProfile:
    """Test LOAD-002/LOAD-006: Elexon profile generation."""

    @pytest.fixture
    def config(self) -> LoadConfig:
        """Standard test configuration."""
        return LoadConfig(annual_consumption_kwh=3400.0)

    def test_returns_series_with_minute_index(self, config):
        """Output has 1-minute frequency DatetimeIndex."""
        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-21"))

        assert isinstance(profile, pd.Series)
        assert isinstance(profile.index, pd.DatetimeIndex)
        # One day = 1440 minutes
        assert len(profile) == 1440

    def test_output_in_kw(self, config):
        """Output values are power in kW."""
        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-21"))

        # Typical UK domestic peak is around 5-10 kW
        assert profile.max() < 15.0  # Reasonable upper bound
        assert profile.mean() > 0.1  # Non-trivial consumption

    def test_no_negative_values(self, config):
        """Output has no negative values."""
        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-21"))

        assert (profile >= 0).all()

    def test_timezone_aware_index(self, config):
        """Output index is timezone-aware."""
        profile = generate_load_profile(
            config, _window("2024-06-21", "2024-06-21", timezone="Europe/London")
        )

        assert profile.index.tz is not None

    def test_multi_day_profile(self, config):
        """Generates profile for multiple days."""
        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-23"))  # 3 days

        # 3 days = 3 * 1440 minutes
        assert len(profile) == 3 * 1440

    def test_week_profile_scales_to_annual(self):
        """Week profile scales approximately to annual target (Elexon profile)."""
        # Use Elexon profile explicitly for deterministic seasonal scaling test
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        profile = generate_load_profile(config, _window("2024-06-01", "2024-06-07"))  # 7 days

        # Calculate consumption for this week
        weekly_kwh = energy_kwh(profile)

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
        return generate_load_profile(config, _window("2024-06-21", "2024-06-21"))

    @pytest.fixture
    def winter_profile(self) -> pd.Series:
        """Winter day profile (Elexon)."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        return generate_load_profile(config, _window("2024-01-15", "2024-01-15"))

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


class TestEnergyKwh:
    """energy_kwh integrates a kW profile, each row over the hours its row lasts, to its energy in kWh."""

    def test_calculates_from_minute_profile(self):
        """A day at a constant 1 kW is 24 kWh: the window's own energy."""
        # Create 1 day profile at constant 1 kW
        index = pd.date_range("2024-01-01", periods=1440, freq="1min")
        profile = pd.Series([1.0] * 1440, index=index)

        # 1 kW for 1440 minutes = 1440/60 = 24 kWh
        total = energy_kwh(profile)
        assert total == pytest.approx(24.0, rel=0.001)

    def test_a_half_hourly_profile_counts_each_row_as_half_an_hour(self):
        """A week at a constant 0.4 kW is 67.2 kWh, whatever the cadence of its rows."""
        week_of_half_hours = pd.date_range(
            "2023-06-01", "2023-06-07 23:30", freq="30min", tz="Europe/London"
        )
        profile = pd.Series(0.4, index=week_of_half_hours)

        assert energy_kwh(profile) == pytest.approx(67.2, rel=1e-9)

    @pytest.mark.parametrize(
        ("profile", "match"),
        [
            pytest.param(
                pd.Series([], index=pd.DatetimeIndex([], tz="Europe/London"), dtype=float),
                "empty",
                id="empty",
            ),
            pytest.param(pd.Series([1.0, 2.0, 3.0]), "RangeIndex", id="range-index"),
        ],
    )
    def test_a_profile_no_window_describes_is_refused(self, profile: pd.Series, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            energy_kwh(profile)


class TestScaleProfileToEnergy:
    """Test LOAD-003: scaling a profile to a target energy."""

    def test_scales_to_target(self):
        """Scales a profile so that its energy is the target."""
        index = pd.date_range("2024-01-01", periods=1440, freq="1min")
        profile = pd.Series([1.0] * 1440, index=index)  # 24 kWh

        scaled = scale_profile_to_energy(profile, target_kwh=48.0)
        total = energy_kwh(scaled)

        assert total == pytest.approx(48.0, rel=0.001)

    def test_preserves_shape(self):
        """Scaling preserves temporal shape."""
        index = pd.date_range("2024-01-01", periods=100, freq="1min")
        profile = pd.Series(np.arange(100, dtype=float), index=index)

        scaled = scale_profile_to_energy(profile, target_kwh=100.0)

        # Relative values should be preserved
        assert (scaled.iloc[50] / scaled.iloc[25]) == pytest.approx(
            profile.iloc[50] / profile.iloc[25], rel=0.001
        )

    def test_raises_on_zero_consumption(self):
        """Raises error when profile has zero consumption."""
        profile = pd.Series(0.0, index=pd.date_range("2024-01-01", periods=100, freq="1min"))
        with pytest.raises(ValueError, match="zero"):
            scale_profile_to_energy(profile, target_kwh=100.0)


class TestHouseholdSizeParameter:
    """Test LOAD-004: Household size affecting consumption."""

    def test_larger_household_higher_consumption(self):
        """Larger households have higher consumption."""
        config_2 = LoadConfig(household_occupants=2)
        config_4 = LoadConfig(household_occupants=4)

        assert config_4.get_annual_consumption() > config_2.get_annual_consumption()

    def test_one_to_five_occupants_default_to_their_table_value(self):
        """Without an annual total, one to five occupants take their OFGEM_TDCV_BY_OCCUPANTS value, the simulator's own default."""
        for occupants in range(1, 6):
            config = LoadConfig(household_occupants=occupants)
            expected = OFGEM_TDCV_BY_OCCUPANTS[occupants]
            assert config.get_annual_consumption() == expected

    def test_occupants_above_five_extrapolated(self):
        """Occupants > 5 extrapolate from 5-person baseline."""
        config_7 = LoadConfig(household_occupants=7)

        # Each extra person adds 400 kWh
        expected = OFGEM_TDCV_BY_OCCUPANTS[5] + 2 * 400.0
        assert config_7.get_annual_consumption() == expected

    def test_profile_scales_with_household_size(self):
        """Generated profile scales with household size."""
        config_small = LoadConfig(household_occupants=1, use_stochastic=False)
        config_large = LoadConfig(household_occupants=5, use_stochastic=False)

        window = _window("2024-06-21", "2024-06-21")

        profile_small = generate_load_profile(config_small, window)
        profile_large = generate_load_profile(config_large, window)

        total_small = energy_kwh(profile_small)
        total_large = energy_kwh(profile_large)

        # Larger household should use more energy
        assert total_large > total_small

        expected_ratio = OFGEM_TDCV_BY_OCCUPANTS[5] / OFGEM_TDCV_BY_OCCUPANTS[1]
        actual_ratio = total_large / total_small
        assert actual_ratio == pytest.approx(expected_ratio, rel=0.01)


class TestRichardsonpyIntegration:
    """Test LOAD-001: richardsonpy integration."""

    def test_disable_stochastic_uses_elexon(self):
        """use_stochastic=False always uses Elexon profile."""
        config = LoadConfig(
            annual_consumption_kwh=3400.0,
            use_stochastic=False,
        )

        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-21"))
        assert isinstance(profile, pd.Series)
        assert len(profile) == 1440

    def test_richardsonpy_generates_valid_profile(self):
        """richardsonpy (now a hard dep) generates a valid profile."""
        config = LoadConfig(
            annual_consumption_kwh=3400.0,
            household_occupants=3,
            use_stochastic=True,
        )

        profile = generate_load_profile(config, _window("2024-06-21", "2024-06-21"))

        assert isinstance(profile, pd.Series)
        assert len(profile) == 1440
        assert (profile >= 0).all()
        assert profile.index.tz is not None


def _raise_simulated_household_failure(*_: object) -> NoReturn:
    raise RuntimeError("Simulated household failure")


class _RecordingHousehold:
    """A household model, richardsonpy's unless another is given, recording each window it builds a household for and each date that household simulates."""

    def __init__(self, household_model: HouseholdModel = richardsonpy_household) -> None:
        self._household_model = household_model
        self.windows: list[list[datetime.date]] = []
        self.days_simulated: list[datetime.date] = []

    def __call__(self, config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator:
        self.windows.append(list(days))
        simulate_day = self._household_model(config, days)

        def simulate_and_record_day(day: datetime.date) -> np.ndarray:
            self.days_simulated.append(day)
            return simulate_day(day)

        return simulate_and_record_day


def _household_of_days(day_watts: DaySimulator) -> HouseholdModel:
    """A household model whose household, in any window, simulates each day with day_watts."""
    return lambda config, days: day_watts


def _day_of_year_watts(day: datetime.date) -> np.ndarray:
    """A day at as many W as its day of the year, all day: 95 W on 4 April 2024."""
    return np.full(1440, float(day.timetuple().tm_yday))


def _minute_of_day_watts(day: datetime.date) -> np.ndarray:
    """A day at one W more each minute of its wall clock: 1 W at 00:00, 1,440 W at 23:59."""
    return 1.0 + np.arange(1440, dtype=np.float64)


_DETERMINISTIC_LOAD = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
_STOCHASTIC_LOAD = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
_EACH_PATH = [
    pytest.param(_DETERMINISTIC_LOAD, id="deterministic"),
    pytest.param(_STOCHASTIC_LOAD, id="stochastic"),
]


class TestWindowedStochasticGeneration:
    """Test windowed stochastic generation (task #13 FIX windowing)."""

    def test_a_one_day_window_builds_one_household_and_simulates_its_one_day(self) -> None:
        """Only the window's day is simulated, not the full year richardsonpy's ElectricLoad simulates."""
        household = _RecordingHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        generate_load_profile(config, _window("2024-06-21", "2024-06-21"), household_model=household)

        assert household.windows == [[datetime.date(2024, 6, 21)]]
        assert household.days_simulated == [datetime.date(2024, 6, 21)]

    def test_a_three_day_window_simulates_each_of_its_days_once_in_order(self) -> None:
        household = _RecordingHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        window = _window("2024-06-21", "2024-06-23")  # 3 days, no DST transition

        profile = generate_load_profile(config, window, household_model=household)

        june_days = [datetime.date(2024, 6, day) for day in (21, 22, 23)]
        assert household.windows == [june_days]
        assert household.days_simulated == june_days

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

        Both stochastic and Elexon paths target the same seasonal daily energy, E_d:
          annual × SEASONAL_FACTORS[June=0.80] / the factors summed over 2024's days ≈ 7.59 kWh
        so they should be within 35% of each other, and both within [2, 30] kWh.
        """
        config_stochastic = LoadConfig(
            annual_consumption_kwh=3400.0, use_stochastic=True, seed=42
        )
        config_elexon = LoadConfig(
            annual_consumption_kwh=3400.0, use_stochastic=False
        )
        window = _window("2024-06-21", "2024-06-21")

        profile_stochastic = generate_load_profile(config_stochastic, window)
        profile_elexon = generate_load_profile(config_elexon, window)

        stochastic_kwh = energy_kwh(profile_stochastic)
        elexon_kwh = energy_kwh(profile_elexon)

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

    def test_a_richardsonpy_window_is_scaled_to_the_energy_of_the_elexon_profile_for_the_same_days(
        self,
    ):
        """The stochastic shape is scaled to the Elexon path's seasonal energy, each day at its own month's factor."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        window = _window("2024-06-29", "2024-07-02")  # June and July days; no clock change

        stochastic = generate_load_profile(config, window)
        elexon = generate_load_profile(dataclasses.replace(config, use_stochastic=False), window)

        assert not stochastic.equals(elexon)
        assert energy_kwh(stochastic) == pytest.approx(energy_kwh(elexon), rel=1e-9)

    def test_a_window_across_the_spring_clock_change_simulates_each_of_its_calendar_days(
        self,
    ) -> None:
        """The window's first and last midnights are 47 hours apart, since the clocks go forward on 2024-03-31, yet it holds three calendar days."""
        household = _RecordingHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        profile = generate_load_profile(
            config,
            _window("2024-03-30", "2024-04-01", timezone="Europe/London"),
            household_model=household,
        )

        assert household.days_simulated == [
            datetime.date(2024, 3, 30),
            datetime.date(2024, 3, 31),
            datetime.date(2024, 4, 1),
        ]
        assert profile.index.tz is not None, "Index must be tz-aware"
        assert (profile >= 0).all(), "No negative power values"

    def test_a_window_across_the_autumn_clock_change_is_scaled_to_the_seasonal_energy_of_its_calendar_days(
        self,
    ) -> None:
        """The window holds six October days and two November days: the clocks go back on 2024-10-27, so 1 November begins 145 hours after the window, not 6 × 24, and still counts at November's factor."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        profile = generate_load_profile(
            config,
            _window("2024-10-26", "2024-11-02", timezone="Europe/London"),
            household_model=_household_of_days(lambda day: np.ones(1440)),
        )

        assert energy_kwh(profile) == pytest.approx(
            sum(_seasonal_energy_kwh(3400.0, day) for day in pd.date_range("2024-10-26", "2024-11-02").date),
            rel=1e-9,
        )

    @pytest.mark.parametrize(
        "household_model",
        [
            pytest.param(_raise_simulated_household_failure, id="household"),
            pytest.param(_household_of_days(_raise_simulated_household_failure), id="day"),
        ],
    )
    def test_a_household_model_that_raises_gives_the_elexon_profile_with_a_warning(
        self, household_model: HouseholdModel, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        window = _window("2024-06-21", "2024-06-21")

        with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
            profile = generate_load_profile(config, window, household_model=household_model)

        pd.testing.assert_series_equal(
            profile,
            generate_load_profile(dataclasses.replace(config, use_stochastic=False), window),
        )
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "solar_challenge.load"
        ] == [
            "the household model failed; falling back to Elexon deterministic profile: "
            "RuntimeError: Simulated household failure"
        ]

    def test_a_window_whose_simulated_days_have_no_energy_raises_instead_of_falling_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Scaling a window is the project's own step, not the household model's, so its refusal of a window with no energy propagates, and no warning announces a fallback."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        with (
            caplog.at_level(logging.WARNING, logger="solar_challenge.load"),
            pytest.raises(ValueError, match="zero consumption"),
        ):
            generate_load_profile(
                config,
                _window("2024-06-21", "2024-06-21"),
                household_model=_household_of_days(lambda day: np.zeros(1440)),
            )

        assert [record for record in caplog.records if record.name == "solar_challenge.load"] == []


class TestHouseholdModelSeam:
    """generate_load_profile builds one household per stochastic window and simulates each of its dates once, in order, placing each day's W; richardsonpy_household simulates only its window's dates."""

    def test_no_household_is_built_for_a_profile_that_is_not_stochastic(self) -> None:
        household = _RecordingHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)

        generate_load_profile(config, _window("2024-06-21", "2024-06-21"), household_model=household)

        assert household.windows == []
        assert household.days_simulated == []

    def test_each_days_watts_land_on_that_days_rows_in_order(self) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        profile = generate_load_profile(
            config,
            _window("2024-06-21", "2024-06-23"),
            household_model=_household_of_days(lambda day: np.full(1440, float(day.day))),
        )

        rows = profile.to_numpy().reshape(3, 1440)
        assert (rows == rows[:, :1]).all()
        assert rows[:, 0] / rows[0, 0] == pytest.approx([1, 22 / 21, 23 / 21])

    def test_a_day_of_the_wrong_length_gives_the_elexon_profile_with_a_warning_naming_the_day_and_its_length(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        window = _window("2024-06-21", "2024-06-21")

        with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
            profile = generate_load_profile(
                config, window, household_model=_household_of_days(lambda _: np.ones(1439))
            )

        pd.testing.assert_series_equal(
            profile,
            generate_load_profile(dataclasses.replace(config, use_stochastic=False), window),
        )
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "solar_challenge.load"
        ] == [
            "the household model failed; falling back to Elexon deterministic profile: "
            "ValueError: the household model simulated 1439 minutes for 2024-06-21, not 1440"
        ]

    def test_a_richardsonpy_household_refuses_a_date_outside_its_window(self) -> None:
        simulate_day = richardsonpy_household(
            LoadConfig(annual_consumption_kwh=3400.0), [datetime.date(2024, 6, 21)]
        )

        with pytest.raises(ValueError) as refusal:
            simulate_day(datetime.date(2024, 6, 22))

        assert str(refusal.value) == (
            "richardsonpy_household was built for 2024-06-21 to 2024-06-21; "
            "it cannot simulate 2024-06-22"
        )


_ACROSS_THE_SPRING_CHANGE = pytest.param("2024-03-30", "2024-04-01", id="across-the-spring-change")
_ACROSS_THE_AUTUMN_CHANGE = pytest.param("2024-10-26", "2024-10-28", id="across-the-autumn-change")


class TestHouseholdOnLocalDays:
    """The household is built on its window's local calendar days by wall clock, so a day's profile depends only on its date and config, and a calendar year delivers annual_consumption_kwh.

    docs/prds/load-composition-and-calendar-days.md decisions 5 and 6, boundary tests B2 and B3.
    """

    def test_a_deterministic_days_profile_is_the_same_whatever_window_holds_it(self) -> None:
        """4 April 2024 follows the spring clock change in a window from 25 March and not in one from 3 April, and both give it one profile, first peaking at 17:30 BST."""
        from_march = generate_load_profile(_DETERMINISTIC_LOAD, _window("2024-03-25", "2024-04-05"))
        from_april = generate_load_profile(_DETERMINISTIC_LOAD, _window("2024-04-03", "2024-04-05"))

        april_4th = from_march.loc["2024-04-04"]
        assert april_4th.equals(from_april.loc["2024-04-04"])
        assert april_4th.idxmax() == pd.Timestamp("2024-04-04 17:30", tz="Europe/London")

    @pytest.mark.parametrize("load_config", _EACH_PATH)
    @pytest.mark.parametrize(
        ("first", "last", "last_row"),
        [
            pytest.param("2024-03-30", "2024-03-31", "2024-03-31 23:59+01:00", id="ending-on-the-spring-change"),
            pytest.param("2024-10-26", "2024-10-27", "2024-10-27 23:59+00:00", id="ending-on-the-autumn-change"),
        ],
    )
    def test_a_profile_runs_on_its_windows_rows_to_the_last_minute_of_its_last_day(
        self, load_config: LoadConfig, first: str, last: str, last_row: str
    ) -> None:
        window = _window(first, last)

        profile = generate_load_profile(
            load_config, window, household_model=_household_of_days(_day_of_year_watts)
        )

        assert profile.index.equals(window.rows())
        assert profile.index[-1] == pd.Timestamp(last_row)

    @pytest.mark.parametrize(("first", "last"), [_ACROSS_THE_SPRING_CHANGE, _ACROSS_THE_AUTUMN_CHANGE])
    def test_each_deterministic_row_is_the_elexon_shape_at_its_wall_clock_minute(
        self, first: str, last: str
    ) -> None:
        """Each day is the Elexon shape at each row's local minute of the day, at one scale for the day: the spring day lacks 01:00-01:59, and the autumn day plays it twice."""
        window = _window(first, last)
        minute_shape = np.repeat(ELEXON_PROFILE_CLASS_1, 30)

        profile = generate_load_profile(_DETERMINISTIC_LOAD, window)

        for day in window.local_days():
            scale = profile.loc[day.rows].to_numpy() / minute_shape[day.minute_of_day()]
            assert scale == pytest.approx(np.full(len(day.rows), scale[0]), rel=1e-12), day.date

    @pytest.mark.parametrize(
        ("first", "last"),
        [
            _ACROSS_THE_SPRING_CHANGE,
            _ACROSS_THE_AUTUMN_CHANGE,
            pytest.param("2023-12-30", "2024-01-02", id="across-new-year"),
        ],
    )
    def test_each_deterministic_day_delivers_its_seasonal_energy(self, first: str, last: str) -> None:
        """A 23- or 25-hour day keeps its seasonal share, and across New Year each day takes its own year's weights."""
        window = _window(first, last)

        profile = generate_load_profile(_DETERMINISTIC_LOAD, window)

        days = list(window.local_days())
        assert [window.energy_kwh(profile.loc[day.rows]) for day in days] == pytest.approx(
            [_seasonal_energy_kwh(3400.0, day.date) for day in days], rel=1e-9
        )

    @pytest.mark.parametrize("load_config", _EACH_PATH)
    @pytest.mark.parametrize("year", [2023, 2024])
    def test_a_calendar_year_delivers_the_annual_consumption(self, load_config: LoadConfig, year: int) -> None:
        """2023 has 365 days and 2024 has 366; each delivers annual_consumption_kwh."""
        window = _window(f"{year}-01-01", f"{year}-12-31")

        profile = generate_load_profile(
            load_config, window, household_model=_household_of_days(_day_of_year_watts)
        )

        assert window.energy_kwh(profile) == pytest.approx(3400.0, rel=1e-9)

    @pytest.mark.parametrize(
        ("first", "last"),
        [pytest.param("2024-04-03", "2024-04-05", id="after-the-spring-change"), _ACROSS_THE_SPRING_CHANGE],
    )
    def test_each_stochastic_row_carries_the_simulated_day_of_its_own_local_date(
        self, first: str, last: str
    ) -> None:
        """The household simulates the window's dates once each, in order, and every row carries its own local date's day, 00:00-00:59 BST included: every row of 4 April 2024 carries day 95, and every row of 1 April day 92."""
        household = _RecordingHousehold(_household_of_days(_day_of_year_watts))

        profile = generate_load_profile(_STOCHASTIC_LOAD, _window(first, last), household_model=household)

        dates = list(pd.date_range(first, last).date)
        assert household.windows == [dates]
        assert household.days_simulated == dates
        day_of_year = profile.index.dayofyear.to_numpy()
        assert (profile / profile.iloc[0]).to_numpy() == pytest.approx(day_of_year / day_of_year[0], rel=1e-12)

    @pytest.mark.parametrize(("first", "last"), [_ACROSS_THE_SPRING_CHANGE, _ACROSS_THE_AUTUMN_CHANGE])
    def test_each_stochastic_minute_lands_on_the_rows_whose_wall_clock_reads_it(
        self, first: str, last: str
    ) -> None:
        """A day at 1 + m W in its minute m gives every row 1 + its local minute of the day, at one scale for the window."""
        profile = generate_load_profile(
            _STOCHASTIC_LOAD, _window(first, last), household_model=_household_of_days(_minute_of_day_watts)
        )

        wall_clock_minute = (profile.index.hour * 60 + profile.index.minute).to_numpy()
        assert (profile / profile.iloc[0]).to_numpy() == pytest.approx(1 + wall_clock_minute, rel=1e-12)

    def test_a_half_hourly_deterministic_profile_is_the_one_minute_profile_at_each_half_hour(self) -> None:
        """Each row is the mean of the minutes it spans, and Elexon's shape holds each half hour's value at each of its minutes, so a half-hourly row is the one-minute profile at its start, and each day still delivers its seasonal energy."""
        half_hourly_window = _window("2024-03-30", "2024-04-01", cadence=datetime.timedelta(minutes=30))

        half_hourly = generate_load_profile(_DETERMINISTIC_LOAD, half_hourly_window)

        one_minute = generate_load_profile(_DETERMINISTIC_LOAD, _window("2024-03-30", "2024-04-01"))
        assert half_hourly.index.equals(half_hourly_window.rows())
        assert half_hourly.to_numpy() == pytest.approx(one_minute.loc[half_hourly.index].to_numpy(), rel=1e-12)
        days = list(half_hourly_window.local_days())
        assert [half_hourly_window.energy_kwh(half_hourly.loc[day.rows]) for day in days] == pytest.approx(
            [_seasonal_energy_kwh(3400.0, day.date) for day in days], rel=1e-9
        )

    def test_a_half_hourly_stochastic_row_is_the_mean_of_the_minutes_it_spans(self) -> None:
        """A day at 1 + m W in its minute m gives the row from minute t its mean, 15.5 + t, at one scale for the window."""
        profile = generate_load_profile(
            _STOCHASTIC_LOAD,
            _window("2024-03-30", "2024-04-01", cadence=datetime.timedelta(minutes=30)),
            household_model=_household_of_days(_minute_of_day_watts),
        )

        wall_clock_minute = (profile.index.hour * 60 + profile.index.minute).to_numpy()
        assert (profile / profile.iloc[0]).to_numpy() == pytest.approx(
            (15.5 + wall_clock_minute) / 15.5, rel=1e-12
        )

    @pytest.mark.parametrize("load_config", _EACH_PATH)
    def test_a_cadence_of_part_of_a_minute_is_refused_before_any_household_is_built(
        self, load_config: LoadConfig
    ) -> None:
        household = _RecordingHousehold(_household_of_days(_day_of_year_watts))
        window = _window("2024-06-21", "2024-06-21", cadence=datetime.timedelta(seconds=30))

        with pytest.raises(ValueError, match=re.escape(f"cadence={datetime.timedelta(seconds=30)!r}")):
            generate_load_profile(load_config, window, household_model=household)

        assert household.windows == []


class TestEVChargingOnTheProfile:
    """generate_load_profile lays EV charging out a minute to a row, so it adds it only to a profile on one-minute rows."""

    @pytest.mark.parametrize("load_config", _EACH_PATH)
    def test_ev_charging_on_rows_longer_than_a_minute_is_refused_naming_the_cadence_before_any_household_is_built(
        self, load_config: LoadConfig
    ) -> None:
        """A half-hourly row would read the charging at its first minute alone, so a session starting or ending inside the row would carry the wrong energy."""
        household = _RecordingHousehold(_household_of_days(_day_of_year_watts))
        half_hourly = datetime.timedelta(minutes=30)

        with pytest.raises(ValueError, match=f"ev_config.*{re.escape(repr(half_hourly))}"):
            generate_load_profile(
                load_config,
                _window("2024-06-21", "2024-06-22", cadence=half_hourly),
                EVConfig(charger_type="3.6kW"),
                household_model=household,
            )

        assert household.windows == []
