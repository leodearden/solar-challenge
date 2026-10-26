"""Tests for load profile generation."""

import dataclasses
import datetime
import logging
import math
from collections.abc import Sequence
from typing import NoReturn

import numpy as np
import pandas as pd
import pytest
from solar_challenge.errors import ConfigurationError
from solar_challenge.load import (
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
from tests._unusable_numbers import UNUSABLE_NUMBERS


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


def _raise_simulated_richardsonpy_failure(*_: object) -> NoReturn:
    raise RuntimeError("Simulated richardsonpy internal failure")


class _RecordingRichardsonpyHousehold:
    """richardsonpy's household model, recording each window it builds a household for and each date that household simulates."""

    def __init__(self) -> None:
        self.windows: list[list[datetime.date]] = []
        self.days_simulated: list[datetime.date] = []

    def __call__(self, config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator:
        self.windows.append(list(days))
        simulate_day = richardsonpy_household(config, days)

        def simulate_and_record_day(day: datetime.date) -> np.ndarray:
            self.days_simulated.append(day)
            return simulate_day(day)

        return simulate_and_record_day


def _household_of_days(day_watts: DaySimulator) -> HouseholdModel:
    """A household model whose household, in any window, simulates each day with day_watts."""
    return lambda config, days: day_watts


class TestWindowedStochasticGeneration:
    """Test windowed stochastic generation (task #13 FIX windowing)."""

    def test_a_one_day_window_builds_one_household_and_simulates_its_one_day(self) -> None:
        """Only the window's day is simulated, not the full year richardsonpy's ElectricLoad simulates."""
        household = _RecordingRichardsonpyHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        day = pd.Timestamp("2024-06-21")

        generate_load_profile(config, day, day, household_model=household)

        assert household.windows == [[datetime.date(2024, 6, 21)]]
        assert household.days_simulated == [datetime.date(2024, 6, 21)]

    def test_a_three_day_window_simulates_each_of_its_days_once_in_order(self) -> None:
        household = _RecordingRichardsonpyHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = pd.Timestamp("2024-06-21")
        end = pd.Timestamp("2024-06-23")  # 3 days, no DST transition

        profile = generate_load_profile(config, start, end, household_model=household)

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
        start = pd.Timestamp("2024-06-29")
        end = pd.Timestamp("2024-07-02")  # June and July days; no clock change

        stochastic = generate_load_profile(config, start, end)
        elexon = generate_load_profile(
            dataclasses.replace(config, use_stochastic=False), start, end
        )

        assert not stochastic.equals(elexon)
        assert energy_kwh(stochastic) == pytest.approx(energy_kwh(elexon), rel=1e-9)

    def test_a_window_across_the_spring_clock_change_simulates_each_of_its_calendar_days(
        self,
    ) -> None:
        """The window's first and last midnights are 47 hours apart, since the clocks go forward on 2024-03-31, yet it holds three calendar days."""
        household = _RecordingRichardsonpyHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = pd.Timestamp("2024-03-30")
        end = pd.Timestamp("2024-04-01")

        profile = generate_load_profile(
            config, start, end, timezone="Europe/London", household_model=household
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
            pd.Timestamp("2024-10-26"),
            pd.Timestamp("2024-11-02"),
            timezone="Europe/London",
            household_model=_household_of_days(lambda day: np.ones(1440)),
        )

        assert energy_kwh(profile) == pytest.approx(
            3400.0 / 365.0 * (6 * SEASONAL_FACTORS[10] + 2 * SEASONAL_FACTORS[11]), rel=1e-9
        )

    @pytest.mark.parametrize(
        "household_model",
        [
            pytest.param(_raise_simulated_richardsonpy_failure, id="household"),
            pytest.param(_household_of_days(_raise_simulated_richardsonpy_failure), id="day"),
        ],
    )
    def test_a_household_model_that_raises_gives_the_elexon_profile_with_a_warning(
        self, household_model: HouseholdModel, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        day = pd.Timestamp("2024-06-21")

        with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
            profile = generate_load_profile(config, day, day, household_model=household_model)

        pd.testing.assert_series_equal(
            profile,
            generate_load_profile(dataclasses.replace(config, use_stochastic=False), day, day),
        )
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "solar_challenge.load"
        ] == [
            "richardsonpy stochastic generation failed; falling back to Elexon "
            "deterministic profile: RuntimeError: Simulated richardsonpy internal failure"
        ]

    def test_a_household_whose_days_have_no_energy_gives_the_elexon_profile_with_a_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A window whose days are all zeros cannot be scaled to its seasonal energy, so the Elexon profile replaces it and a warning names the cause."""
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        start = end = pd.Timestamp("2024-06-21")

        with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
            profile = generate_load_profile(
                config,
                start,
                end,
                household_model=_household_of_days(lambda day: np.zeros(1440)),
            )

        elexon = generate_load_profile(
            dataclasses.replace(config, use_stochastic=False), start, end
        )
        pd.testing.assert_series_equal(profile, elexon)
        assert [
            record.levelno
            for record in caplog.records
            if record.name == "solar_challenge.load"
            and "zero consumption" in record.getMessage()
        ] == [logging.WARNING]


class TestHouseholdModelSeam:
    """generate_load_profile builds one household per stochastic window and simulates each of its dates once, in order, placing each day's W; richardsonpy_household simulates only its window's dates."""

    def test_no_household_is_built_for_a_profile_that_is_not_stochastic(self) -> None:
        household = _RecordingRichardsonpyHousehold()
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=False)
        day = pd.Timestamp("2024-06-21")

        generate_load_profile(config, day, day, household_model=household)

        assert household.windows == []
        assert household.days_simulated == []

    def test_each_days_watts_land_on_that_days_rows_in_order(self) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)

        profile = generate_load_profile(
            config,
            pd.Timestamp("2024-06-21"),
            pd.Timestamp("2024-06-23"),
            household_model=_household_of_days(lambda day: np.full(1440, float(day.day))),
        )

        rows = profile.to_numpy().reshape(3, 1440)
        assert (rows == rows[:, :1]).all()
        assert rows[:, 0] / rows[0, 0] == pytest.approx([1, 22 / 21, 23 / 21])

    def test_a_day_of_the_wrong_length_gives_the_elexon_profile_with_a_warning_naming_the_day_and_its_length(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        config = LoadConfig(annual_consumption_kwh=3400.0, use_stochastic=True, seed=42)
        day = pd.Timestamp("2024-06-21")

        with caplog.at_level(logging.WARNING, logger="solar_challenge.load"):
            profile = generate_load_profile(
                config, day, day, household_model=_household_of_days(lambda _: np.ones(1439))
            )

        pd.testing.assert_series_equal(
            profile,
            generate_load_profile(dataclasses.replace(config, use_stochastic=False), day, day),
        )
        assert [
            record.getMessage()
            for record in caplog.records
            if record.name == "solar_challenge.load"
        ] == [
            "richardsonpy stochastic generation failed; falling back to Elexon "
            "deterministic profile: ValueError: the household model simulated 1439 "
            "minutes for 2024-06-21, not 1440"
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
