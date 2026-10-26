"""Tests for tariff configuration and rate matching."""

import dataclasses
import pickle
from collections.abc import Iterable
from datetime import datetime, time

import pandas as pd
import pytest

from solar_challenge.errors import ConfigurationError
from solar_challenge.tariff import (
    TariffConfig,
    TariffPeriod,
    calculate_bill,
    describe_minutes_of_day,
)
from tests._names_as_a_word import names_as_a_word
from tests._same_schedule_tariffs import (
    NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS,
    NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS,
)

REPEATED_OFF_PEAK_TARIFF = TariffConfig(
    periods=(
        TariffPeriod("00:00", "07:00", 0.10, "Night"),
        TariffPeriod("07:00", "16:00", 0.40, "Day"),
        TariffPeriod("16:00", "00:00", 0.10, "Evening"),
    ),
    name="Two cheap windows",
)


def _derived_values(tariff: TariffConfig) -> tuple[float, float, frozenset[int]]:
    return tariff.peak_rate, tariff.mean_period_rate, tariff.cheap_minutes_of_day


class TestTariffPeriodBasics:
    """Test basic TariffPeriod functionality."""

    def test_create_with_all_params(self):
        """TariffPeriod can be created with all parameters."""
        period = TariffPeriod(
            start_time="00:30",
            end_time="07:30",
            rate_per_kwh=0.09,
            name="Off-peak"
        )
        assert period.start_time == "00:30"
        assert period.end_time == "07:30"
        assert period.rate_per_kwh == 0.09
        assert period.name == "Off-peak"

    def test_default_name(self):
        """TariffPeriod uses empty string as default name."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        assert period.name == ""

    def test_frozen_dataclass(self):
        """TariffPeriod is immutable (frozen)."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        with pytest.raises(Exception):  # FrozenInstanceError
            period.rate_per_kwh = 0.30


class TestTariffPeriodValidation:
    """Test TariffPeriod parameter validation."""

    @pytest.mark.parametrize("rate", [-0.10, float("nan"), float("inf"), float("-inf")])
    def test_a_rate_that_is_negative_or_not_finite_is_refused_naming_it(self, rate: float) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            TariffPeriod(start_time="09:00", end_time="17:00", rate_per_kwh=rate)

        message = str(refusal.value)
        assert "rate_per_kwh" in message
        assert names_as_a_word(message, rate)

    def test_invalid_start_time_format(self):
        """Invalid start time format raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(
                start_time="9",  # Missing minutes
                end_time="17:00",
                rate_per_kwh=0.25
            )

    def test_invalid_end_time_format(self):
        """Invalid end time format raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(
                start_time="09:00",
                end_time="25:00",  # Hour out of range
                rate_per_kwh=0.25
            )

    def test_invalid_hour_raises(self):
        """Hour outside 0-23 range raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(
                start_time="24:00",
                end_time="23:59",
                rate_per_kwh=0.25
            )

    def test_invalid_minute_raises(self):
        """Minute outside 0-59 range raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(
                start_time="09:00",
                end_time="17:60",
                rate_per_kwh=0.25
            )

    def test_malformed_time_string(self):
        """Malformed time string raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(
                start_time="09-00",  # Wrong separator
                end_time="17:00",
                rate_per_kwh=0.25
            )

    def test_a_time_object_is_refused_as_a_time_that_is_not_hh_mm_text(self):
        """start_time and end_time are HH:MM strings only."""
        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffPeriod(start_time=time(9, 0), end_time="17:00", rate_per_kwh=0.25)


class TestTariffPeriodTimeParsing:
    """Test time parsing and conversion."""

    def test_get_start_time(self):
        """get_start_time returns time object."""
        period = TariffPeriod(
            start_time="09:30",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        start = period.get_start_time()
        assert start.hour == 9
        assert start.minute == 30

    def test_get_end_time(self):
        """get_end_time returns time object."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:45",
            rate_per_kwh=0.25
        )
        end = period.get_end_time()
        assert end.hour == 17
        assert end.minute == 45

    def test_midnight_times(self):
        """Can parse midnight (00:00) times."""
        period = TariffPeriod(
            start_time="00:00",
            end_time="23:59",
            rate_per_kwh=0.25
        )
        start = period.get_start_time()
        end = period.get_end_time()
        assert start.hour == 0
        assert start.minute == 0
        assert end.hour == 23
        assert end.minute == 59


class TestTariffPeriodTimeMatching:
    """Test timestamp matching within periods."""

    def test_matches_time_within_period(self):
        """Timestamp within period matches."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25,
            name="Day"
        )
        timestamp = pd.Timestamp("2024-01-15 12:30:00")
        assert period.matches_time(timestamp) is True

    def test_matches_time_at_start(self):
        """Timestamp at period start matches."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        timestamp = pd.Timestamp("2024-01-15 09:00:00")
        assert period.matches_time(timestamp) is True

    def test_matches_time_at_end_exclusive(self):
        """Timestamp at period end does not match (exclusive end)."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        timestamp = pd.Timestamp("2024-01-15 17:00:00")
        assert period.matches_time(timestamp) is False

    def test_matches_time_before_period(self):
        """Timestamp before period does not match."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        timestamp = pd.Timestamp("2024-01-15 08:59:00")
        assert period.matches_time(timestamp) is False

    def test_matches_time_after_period(self):
        """Timestamp after period does not match."""
        period = TariffPeriod(
            start_time="09:00",
            end_time="17:00",
            rate_per_kwh=0.25
        )
        timestamp = pd.Timestamp("2024-01-15 17:01:00")
        assert period.matches_time(timestamp) is False


class TestTariffPeriodMidnightCrossing:
    """Test periods that cross midnight."""

    def test_matches_midnight_crossing_period_before_midnight(self):
        """Midnight-crossing period matches time before midnight."""
        period = TariffPeriod(
            start_time="23:00",
            end_time="07:00",
            rate_per_kwh=0.09,
            name="Night"
        )
        timestamp = pd.Timestamp("2024-01-15 23:30:00")
        assert period.matches_time(timestamp) is True

    def test_matches_midnight_crossing_period_after_midnight(self):
        """Midnight-crossing period matches time after midnight."""
        period = TariffPeriod(
            start_time="23:00",
            end_time="07:00",
            rate_per_kwh=0.09,
            name="Night"
        )
        timestamp = pd.Timestamp("2024-01-15 06:30:00")
        assert period.matches_time(timestamp) is True

    def test_matches_midnight_crossing_period_at_midnight(self):
        """Midnight-crossing period matches midnight."""
        period = TariffPeriod(
            start_time="23:00",
            end_time="07:00",
            rate_per_kwh=0.09
        )
        timestamp = pd.Timestamp("2024-01-15 00:00:00")
        assert period.matches_time(timestamp) is True

    def test_not_matches_midnight_crossing_outside(self):
        """Midnight-crossing period does not match outside times."""
        period = TariffPeriod(
            start_time="23:00",
            end_time="07:00",
            rate_per_kwh=0.09
        )
        # Test during the gap (07:00-23:00)
        timestamp = pd.Timestamp("2024-01-15 12:00:00")
        assert period.matches_time(timestamp) is False

    def test_midnight_crossing_at_boundaries(self):
        """Midnight-crossing period boundary behavior."""
        period = TariffPeriod(
            start_time="00:30",
            end_time="07:30",
            rate_per_kwh=0.09
        )
        # At start (inclusive)
        assert period.matches_time(pd.Timestamp("2024-01-15 00:30:00")) is True
        # Just before start
        assert period.matches_time(pd.Timestamp("2024-01-15 00:29:00")) is False
        # At end (exclusive)
        assert period.matches_time(pd.Timestamp("2024-01-15 07:30:00")) is False
        # Just before end
        assert period.matches_time(pd.Timestamp("2024-01-15 07:29:00")) is True

    def test_full_day_00_00_matches_all_times(self):
        """TariffPeriod("00:00","00:00") is a full-24h period covering every minute: an end equal to the start is the whole day, as flat_rate() relies on."""
        period = TariffPeriod(start_time="00:00", end_time="00:00", rate_per_kwh=0.20)
        assert period.matches_time(pd.Timestamp("2024-01-15 00:00:00")) is True
        assert period.matches_time(pd.Timestamp("2024-01-15 12:00:00")) is True
        assert period.matches_time(pd.Timestamp("2024-01-15 23:59:00")) is True


class TestTariffConfigBasics:
    """Test basic TariffConfig functionality."""

    def test_create_with_single_period(self):
        """TariffConfig can be created with single period."""
        period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",
            rate_per_kwh=0.20
        )
        tariff = TariffConfig(periods=(period,), name="Flat")
        assert len(tariff.periods) == 1
        assert tariff.name == "Flat"

    def test_create_with_multiple_periods(self):
        """TariffConfig can be created with multiple periods."""
        periods = (
            TariffPeriod("00:30", "07:30", 0.09, "Off-peak"),
            TariffPeriod("07:30", "00:30", 0.25, "Peak"),
        )
        tariff = TariffConfig(periods=periods, name="Economy 7")
        assert len(tariff.periods) == 2
        assert tariff.name == "Economy 7"

    def test_frozen_dataclass(self):
        """TariffConfig is immutable (frozen)."""
        period = TariffPeriod("00:00", "00:00", 0.20)
        tariff = TariffConfig(periods=(period,))
        with pytest.raises(Exception):  # FrozenInstanceError
            tariff.name = "New name"


class TestTariffConfigValidation:
    """Test TariffConfig validation."""

    def test_empty_periods_raises(self):
        """Empty periods tuple raises ConfigurationError."""
        with pytest.raises(ConfigurationError, match="must have at least one period"):
            TariffConfig(periods=())

    def test_invalid_period_time_raises(self):
        """Invalid period time format raises during validation."""
        period = TariffPeriod.__new__(TariffPeriod)
        object.__setattr__(period, "start_time", "invalid")
        object.__setattr__(period, "end_time", "17:00")
        object.__setattr__(period, "rate_per_kwh", 0.25)
        object.__setattr__(period, "name", "")

        with pytest.raises(ConfigurationError, match="Invalid time format"):
            TariffConfig(periods=(period,))


class TestTariffConfigGetRate:
    """Test getting rates for timestamps."""

    def test_get_rate_single_period(self):
        """get_rate returns correct rate for single-period tariff."""
        period = TariffPeriod("00:00", "00:00", 0.20, "All day")
        tariff = TariffConfig(periods=(period,))

        timestamp = pd.Timestamp("2024-01-15 12:00:00")
        rate = tariff.get_rate(timestamp)
        assert rate == 0.20

    def test_get_rate_multiple_periods(self):
        """get_rate returns correct rate from multiple periods."""
        periods = (
            TariffPeriod("00:00", "07:00", 0.09, "Night"),
            TariffPeriod("07:00", "23:00", 0.25, "Day"),
            TariffPeriod("23:00", "00:00", 0.15, "Evening"),
        )
        tariff = TariffConfig(periods=periods)

        # Night rate
        assert tariff.get_rate(pd.Timestamp("2024-01-15 03:00:00")) == 0.09
        # Day rate
        assert tariff.get_rate(pd.Timestamp("2024-01-15 12:00:00")) == 0.25
        # Evening rate
        assert tariff.get_rate(pd.Timestamp("2024-01-15 23:30:00")) == 0.15

    def test_a_tariff_with_a_gap_is_refused_at_construction(self):
        """No constructed tariff has a minute without a rate: a 09:00-17:00 period alone is refused."""
        with pytest.raises(ConfigurationError, match="17:00-09:00"):
            TariffConfig(periods=(TariffPeriod("09:00", "17:00", 0.25),))


class TestTariffConfigFlatRate:
    """Test flat-rate tariff factory method."""

    def test_flat_rate_creates_tariff(self):
        """flat_rate creates valid TariffConfig."""
        tariff = TariffConfig.flat_rate(0.20)
        assert len(tariff.periods) == 1
        assert tariff.periods[0].rate_per_kwh == 0.20

    def test_flat_rate_covers_full_day(self):
        """Flat rate tariff covers entire day."""
        tariff = TariffConfig.flat_rate(0.20)
        # Test various times throughout the day
        assert tariff.get_rate(pd.Timestamp("2024-01-15 00:00:00")) == 0.20
        assert tariff.get_rate(pd.Timestamp("2024-01-15 12:00:00")) == 0.20
        assert tariff.get_rate(pd.Timestamp("2024-01-15 23:58:00")) == 0.20

    def test_flat_rate_with_custom_name(self):
        """flat_rate accepts custom name."""
        tariff = TariffConfig.flat_rate(0.20, name="My Tariff")
        assert tariff.name == "My Tariff"

    def test_flat_rate_default_name(self):
        """flat_rate generates default name."""
        tariff = TariffConfig.flat_rate(0.20)
        assert "0.20" in tariff.name
        assert "Flat rate" in tariff.name

    def test_flat_rate_covers_2359_boundary(self):
        """flat_rate tariff covers 23:59:00 (last minute of the day).

        RED driver: TariffConfig.flat_rate() used end_time="23:59" (exclusive),
        so get_rate(23:59:00) raised ValueError because 23:59:00 < 23:59:00 is
        False.  The fix changes end_time to "00:00" (midnight-crossing period
        with start==end, covering every minute including 23:59:00).
        """
        tariff = TariffConfig.flat_rate(0.20)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 23:59:00")) == 0.20

    def test_flat_rate_full_day_1min_no_gap(self):
        """calculate_bill over a full-day 1-min series raises no ValueError.

        RED driver: the 23:59:00 step is outside the period when end_time="23:59",
        so calculate_bill raises on a 1440-step 00:00-23:59 series.
        After the fix the series prices cleanly and the total equals
        1440 * 1.0 kWh * £0.20/kWh.
        """
        idx = pd.date_range("2024-01-15 00:00", "2024-01-15 23:59", freq="min")
        assert len(idx) == 1440
        energy = pd.Series(1.0, index=idx)
        tariff = TariffConfig.flat_rate(0.20)
        # Must not raise ValueError; total = 1440 * 0.20 = 288.00
        result = calculate_bill(energy, tariff)
        assert result == pytest.approx(1440 * 0.20)


class TestTariffConfigEconomy7:
    """Test Economy 7 tariff factory method."""

    def test_economy_7_default_params(self):
        """Economy 7 creates tariff with default parameters."""
        tariff = TariffConfig.economy_7()
        assert len(tariff.periods) == 2
        assert "Economy 7" in tariff.name

    def test_economy_7_default_rates(self):
        """Economy 7 uses correct default rates."""
        tariff = TariffConfig.economy_7()
        # Off-peak time (00:30-07:30)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 03:00:00")) == 0.09
        # Peak time (07:30-00:30)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 12:00:00")) == 0.25

    def test_economy_7_custom_rates(self):
        """Economy 7 accepts custom rates."""
        tariff = TariffConfig.economy_7(
            off_peak_rate=0.08,
            peak_rate=0.28
        )
        assert tariff.get_rate(pd.Timestamp("2024-01-15 03:00:00")) == 0.08
        assert tariff.get_rate(pd.Timestamp("2024-01-15 12:00:00")) == 0.28

    def test_economy_7_custom_times(self):
        """Economy 7 accepts custom off-peak times."""
        tariff = TariffConfig.economy_7(
            off_peak_start="01:00",
            off_peak_end="08:00"
        )
        # Within custom off-peak
        assert tariff.get_rate(pd.Timestamp("2024-01-15 04:00:00")) == 0.09
        # Outside custom off-peak
        assert tariff.get_rate(pd.Timestamp("2024-01-15 12:00:00")) == 0.25

    def test_economy_7_off_peak_hours(self):
        """Economy 7 off-peak period is 7 hours."""
        tariff = TariffConfig.economy_7()  # Default: 00:30-07:30
        # Count off-peak hours by checking each hour
        off_peak_hours = 0
        for hour in range(24):
            timestamp = pd.Timestamp(f"2024-01-15 {hour:02d}:30:00")
            if tariff.get_rate(timestamp) == 0.09:
                off_peak_hours += 1
        assert off_peak_hours == 7

    def test_economy_7_boundary_times(self):
        """Economy 7 boundaries work correctly."""
        tariff = TariffConfig.economy_7()  # 00:30-07:30 off-peak
        # Just before off-peak starts (peak)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 00:29:00")) == 0.25
        # At off-peak start (off-peak)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 00:30:00")) == 0.09
        # Just before off-peak ends (off-peak)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 07:29:00")) == 0.09
        # At off-peak end (peak)
        assert tariff.get_rate(pd.Timestamp("2024-01-15 07:30:00")) == 0.25


class TestTariffConfigEconomy10:
    """Test Economy 10 tariff factory method."""

    def test_economy_10_default_params(self):
        """Economy 10 creates tariff with default parameters."""
        tariff = TariffConfig.economy_10()
        assert len(tariff.periods) == 6
        assert tariff.name == "Economy 10"

    def test_economy_10_default_rates(self):
        """Economy 10 uses correct default rates."""
        tariff = TariffConfig.economy_10()
        # Off-peak times
        assert tariff.get_rate(pd.Timestamp("2024-01-15 02:00:00")) == 0.08  # Night
        assert tariff.get_rate(pd.Timestamp("2024-01-15 14:00:00")) == 0.08  # Afternoon
        assert tariff.get_rate(pd.Timestamp("2024-01-15 21:00:00")) == 0.08  # Evening
        # Peak times
        assert tariff.get_rate(pd.Timestamp("2024-01-15 10:00:00")) == 0.27  # Morning
        assert tariff.get_rate(pd.Timestamp("2024-01-15 17:00:00")) == 0.27  # Afternoon peak

    def test_economy_10_custom_rates(self):
        """Economy 10 accepts custom rates."""
        tariff = TariffConfig.economy_10(
            off_peak_rate=0.07,
            peak_rate=0.30
        )
        assert tariff.get_rate(pd.Timestamp("2024-01-15 02:00:00")) == 0.07
        assert tariff.get_rate(pd.Timestamp("2024-01-15 10:00:00")) == 0.30

    def test_economy_10_custom_times(self):
        """Economy 10 accepts custom period times."""
        tariff = TariffConfig.economy_10(
            night_start="01:00",
            night_end="06:00",
            afternoon_start="14:00",
            afternoon_end="17:00",
            evening_start="21:00",
            evening_end="23:00"
        )
        # Check custom times work
        assert tariff.get_rate(pd.Timestamp("2024-01-15 03:00:00")) == 0.08
        assert tariff.get_rate(pd.Timestamp("2024-01-15 15:00:00")) == 0.08
        assert tariff.get_rate(pd.Timestamp("2024-01-15 22:00:00")) == 0.08

    def test_economy_10_off_peak_hours(self):
        """Economy 10 off-peak periods total 10 hours."""
        tariff = TariffConfig.economy_10()
        # Default: 00:00-05:00 (5h) + 13:00-16:00 (3h) + 20:00-22:00 (2h) = 10h
        off_peak_hours = 0
        for hour in range(24):
            timestamp = pd.Timestamp(f"2024-01-15 {hour:02d}:30:00")
            if tariff.get_rate(timestamp) == 0.08:
                off_peak_hours += 1
        assert off_peak_hours == 10

    def test_economy_10_period_names(self):
        """Economy 10 periods have descriptive names."""
        tariff = TariffConfig.economy_10()
        period_names = [p.name for p in tariff.periods]
        assert "Off-peak (night)" in period_names
        assert "Off-peak (afternoon)" in period_names
        assert "Off-peak (evening)" in period_names
        assert "Peak (morning)" in period_names


class TestTariffConfigPeakAndMeanPeriodRate:
    """The peak is the highest period rate; the mean counts each period once."""

    def test_flat_rate_has_its_one_rate_as_both_peak_and_mean(self) -> None:
        tariff = TariffConfig.flat_rate(0.25)

        assert tariff.peak_rate == 0.25
        assert tariff.mean_period_rate == 0.25

    @pytest.mark.parametrize(
        ("tariff", "expected_peak"),
        [
            pytest.param(TariffConfig.economy_7(), 0.25, id="economy_7"),
            pytest.param(TariffConfig.economy_10(), 0.27, id="economy_10"),
            # Its float mean is 0.10000000000000002; only an exact peak shows no spread.
            pytest.param(
                TariffConfig.economy_10(off_peak_rate=0.1, peak_rate=0.1),
                0.1,
                id="six_periods_one_rate",
            ),
            pytest.param(REPEATED_OFF_PEAK_TARIFF, 0.40, id="repeated_off_peak"),
        ],
    )
    def test_peak_rate_is_the_highest_period_rate_exactly(
        self, tariff: TariffConfig, expected_peak: float
    ) -> None:
        assert tariff.peak_rate == expected_peak

    def test_mean_period_rate_counts_each_period_once_whatever_its_length(self) -> None:
        """Economy 7 is 7 h at 0.09 and 17 h at 0.25; weighting by hours would give 0.2033."""
        assert TariffConfig.economy_7().mean_period_rate == pytest.approx(0.17)

    def test_mean_period_rate_counts_a_repeated_rate_once_per_period(self) -> None:
        """Averaging the distinct rates would give 0.25, and weighting by hours 0.2125."""
        assert REPEATED_OFF_PEAK_TARIFF.mean_period_rate == pytest.approx(0.20)


class TestTariffConfigCheapMinutes:
    """A minute is cheap when its rate is below the peak and at or below the duration-weighted mean rate."""

    @pytest.mark.parametrize(
        ("tariff", "expected"),
        [
            pytest.param(TariffConfig.economy_7(), frozenset(range(30, 450)), id="economy_7"),
            pytest.param(
                TariffConfig.economy_10(),
                frozenset([*range(0, 300), *range(780, 960), *range(1200, 1320)]),
                id="economy_10",
            ),
            pytest.param(
                TariffConfig(
                    periods=(
                        TariffPeriod("00:00", "07:00", 0.10, "Night"),
                        TariffPeriod("07:00", "00:00", 0.30, "Day"),
                    )
                ),
                frozenset(range(420)),
                id="custom_two_rate",
            ),
            # Its weighted mean is 0.1125, 23 h at 0.10 and 1 h at 0.40.
            pytest.param(
                TariffConfig(
                    periods=(
                        TariffPeriod("17:00", "18:00", 0.40, "Peak"),
                        TariffPeriod("18:00", "17:00", 0.10, "Off-peak"),
                    )
                ),
                frozenset(range(1440)) - frozenset(range(1020, 1080)),
                id="low_rate_most_of_the_day",
            ),
        ],
    )
    def test_a_two_rate_tariffs_cheap_minutes_are_the_minutes_at_its_lower_rate(
        self, tariff: TariffConfig, expected: frozenset[int]
    ) -> None:
        assert tariff.cheap_minutes_of_day == expected

    @pytest.mark.parametrize(
        "tariff",
        [
            pytest.param(TariffConfig.flat_rate(0.25), id="flat_rate"),
            pytest.param(
                TariffConfig.economy_10(off_peak_rate=0.1, peak_rate=0.1),
                id="six_periods_one_rate",
            ),
        ],
    )
    def test_a_one_rate_tariff_has_no_cheap_minutes(self, tariff: TariffConfig) -> None:
        assert tariff.cheap_minutes_of_day == frozenset()

    @pytest.mark.parametrize(
        "tariff",
        [
            pytest.param(NIGHT_DAY_PEAK_DAY_AS_FOUR_PERIODS, id="four_periods"),
            pytest.param(NIGHT_DAY_PEAK_DAY_AS_FIVE_PERIODS, id="five_periods"),
        ],
    )
    def test_the_cheap_minutes_follow_the_schedule_not_its_period_list(
        self, tariff: TariffConfig
    ) -> None:
        assert tariff.cheap_minutes_of_day == frozenset(range(420))
        assert describe_minutes_of_day(tariff.cheap_minutes_of_day) == "00:00-07:00"

    def test_a_rate_at_or_below_the_weighted_mean_is_cheap_though_above_the_period_mean(
        self,
    ) -> None:
        """The weighted mean is 0.28375, the mean of the three period rates 0.17."""
        tariff = TariffConfig(
            periods=(
                TariffPeriod("00:00", "01:00", 0.01, "Night"),
                TariffPeriod("01:00", "02:00", 0.20, "Shoulder"),
                TariffPeriod("02:00", "00:00", 0.30, "Peak"),
            )
        )

        assert tariff.cheap_minutes_of_day == frozenset(range(120))

    @pytest.mark.parametrize(
        ("timestamp", "cheap"),
        [
            pytest.param(pd.Timestamp("2024-06-21 00:30", tz="Europe/London"), True, id="00:30"),
            pytest.param(
                pd.Timestamp("2024-06-21 00:29:59", tz="Europe/London"), False, id="00:29:59"
            ),
            pytest.param(
                pd.Timestamp("2024-06-21 07:29:59", tz="Europe/London"), True, id="07:29:59"
            ),
            pytest.param(pd.Timestamp("2024-06-21 07:30", tz="Europe/London"), False, id="07:30"),
            pytest.param(datetime(2024, 1, 10, 3, 0), True, id="naive-03:00"),
        ],
    )
    def test_is_cheap_at_reads_the_timestamps_wall_clock_minute(
        self, timestamp: datetime, cheap: bool
    ) -> None:
        assert TariffConfig.economy_7().is_cheap_at(timestamp) is cheap

    def test_one_instant_is_cheap_on_the_clock_that_reads_it_in_the_cheap_window(self) -> None:
        """23:30 UTC on 2024-06-20 is 00:30 BST on 2024-06-21."""
        instant = pd.Timestamp("2024-06-20 23:30", tz="UTC")
        tariff = TariffConfig.economy_7()

        assert tariff.is_cheap_at(instant) is False
        assert tariff.is_cheap_at(instant.tz_convert("Europe/London")) is True


class TestTariffConfigDerivedRatesStayOutOfIdentity:
    """Reading the derived values must not change a tariff's equality, fields or clones."""

    def test_reading_the_rates_leaves_equality_hash_and_repr_alone(self) -> None:
        read = TariffConfig.economy_7()
        _derived_values(read)
        unread = TariffConfig.economy_7()

        assert read == unread
        assert hash(read) == hash(unread)
        assert repr(read) == repr(unread)

    def test_a_tariff_rebuilt_from_its_fields_equals_the_original(self) -> None:
        """web/field_tree.py's field_tree writes fields() and its read_field_tree passes them back to the constructor."""
        tariff = TariffConfig.economy_7()
        _derived_values(tariff)

        rebuilt = TariffConfig(
            **{f.name: getattr(tariff, f.name) for f in dataclasses.fields(tariff)}
        )

        assert rebuilt == tariff

    def test_a_pickled_tariff_carries_the_same_rates(self) -> None:
        """fleet.py's process pool pickles each home's config, its tariff included."""
        tariff = TariffConfig.economy_10()
        expected = _derived_values(tariff)

        unpickled: TariffConfig = pickle.loads(pickle.dumps(tariff))

        assert unpickled == tariff
        assert hash(unpickled) == hash(tariff)
        assert _derived_values(unpickled) == expected

    def test_replace_derives_the_replacement_periods_rates(self) -> None:
        tariff = TariffConfig.economy_7()
        peak, mean, cheap_minutes = _derived_values(tariff)

        replaced = dataclasses.replace(tariff, periods=TariffConfig.flat_rate(0.30).periods)

        assert _derived_values(replaced) == (0.30, 0.30, frozenset())
        assert (peak, mean) == pytest.approx((0.25, 0.17))
        assert cheap_minutes == frozenset(range(30, 450))


class TestCalculateBill:
    """Test bill calculation function."""

    def test_calculate_bill_flat_rate(self):
        """Calculate bill with flat-rate tariff."""
        # Create 24 hours of 1 kWh/hour consumption
        index = pd.date_range("2024-01-15 00:00", periods=24, freq="h")
        energy = pd.Series([1.0] * 24, index=index)

        tariff = TariffConfig.flat_rate(0.20)
        bill = calculate_bill(energy, tariff)

        # 24 hours * 1 kWh * £0.20/kWh = £4.80
        assert bill == pytest.approx(4.80)

    def test_calculate_bill_economy_7(self):
        """Calculate bill with Economy 7 tariff."""
        # Create 24 hours of 1 kWh/hour consumption
        index = pd.date_range("2024-01-15 00:00", periods=24, freq="h")
        energy = pd.Series([1.0] * 24, index=index)

        tariff = TariffConfig.economy_7(
            off_peak_rate=0.10,
            peak_rate=0.30,
            off_peak_start="00:00",
            off_peak_end="07:00"
        )
        bill = calculate_bill(energy, tariff)

        # 7 hours off-peak: 7 * 1 * 0.10 = £0.70
        # 17 hours peak: 17 * 1 * 0.30 = £5.10
        # Total: £5.80
        assert bill == pytest.approx(5.80)

    def test_calculate_bill_varying_consumption(self):
        """Calculate bill with varying consumption."""
        index = pd.date_range("2024-01-15 00:00", periods=4, freq="h")
        energy = pd.Series([0.5, 1.0, 1.5, 2.0], index=index)

        tariff = TariffConfig.flat_rate(0.20)
        bill = calculate_bill(energy, tariff)

        # (0.5 + 1.0 + 1.5 + 2.0) * 0.20 = £1.00
        assert bill == pytest.approx(1.00)

    def test_calculate_bill_minute_resolution(self):
        """Calculate bill with minute-resolution data."""
        # 60 minutes of 0.1 kWh/minute consumption
        index = pd.date_range("2024-01-15 12:00", periods=60, freq="min")
        energy = pd.Series([0.1] * 60, index=index)

        tariff = TariffConfig.flat_rate(0.20)
        bill = calculate_bill(energy, tariff)

        # 60 * 0.1 * 0.20 = £1.20
        assert bill == pytest.approx(1.20)

    def test_calculate_bill_empty_series(self):
        """Calculate bill with empty series returns zero."""
        index = pd.DatetimeIndex([])
        energy = pd.Series([], index=index)

        tariff = TariffConfig.flat_rate(0.20)
        bill = calculate_bill(energy, tariff)

        assert bill == 0.0

    def test_calculate_bill_requires_datetime_index(self):
        """Calculate bill raises error without DatetimeIndex."""
        # Create series with integer index
        energy = pd.Series([1.0, 2.0, 3.0])

        tariff = TariffConfig.flat_rate(0.20)

        with pytest.raises(ValueError, match="must have a DatetimeIndex"):
            calculate_bill(energy, tariff)

    def test_calculate_bill_negative_consumption(self):
        """Calculate bill handles negative consumption (export)."""
        index = pd.date_range("2024-01-15 00:00", periods=4, freq="h")
        energy = pd.Series([1.0, -0.5, 1.5, -1.0], index=index)

        tariff = TariffConfig.flat_rate(0.20)
        bill = calculate_bill(energy, tariff)

        # (1.0 - 0.5 + 1.5 - 1.0) * 0.20 = £0.20
        assert bill == pytest.approx(0.20)

    def test_calculate_bill_tou_cost_difference(self):
        """Calculate bill shows cost difference with TOU shifting."""
        # Same total energy, different timing
        index = pd.date_range("2024-01-15 00:00", periods=24, freq="h")

        tariff = TariffConfig.economy_7(
            off_peak_rate=0.10,
            peak_rate=0.30,
            off_peak_start="00:00",
            off_peak_end="07:00"
        )

        # Scenario 1: Use 10 kWh during peak hours
        energy_peak = pd.Series([0.0] * 24, index=index)
        energy_peak.iloc[12] = 10.0  # All consumption at noon (peak)
        bill_peak = calculate_bill(energy_peak, tariff)

        # Scenario 2: Use 10 kWh during off-peak hours
        energy_offpeak = pd.Series([0.0] * 24, index=index)
        energy_offpeak.iloc[3] = 10.0  # All consumption at 3am (off-peak)
        bill_offpeak = calculate_bill(energy_offpeak, tariff)

        # Peak: 10 * 0.30 = £3.00
        # Off-peak: 10 * 0.10 = £1.00
        assert bill_peak == pytest.approx(3.00)
        assert bill_offpeak == pytest.approx(1.00)
        assert bill_peak > bill_offpeak


class TestDescribeMinutesOfDay:
    """describe_minutes_of_day writes minutes of the day as the clock ranges a tariff refusal names."""

    @pytest.mark.parametrize(
        ("minutes", "expected"),
        [
            pytest.param(range(360, 720), "06:00-12:00", id="one-range"),
            pytest.param(
                [*range(1380, 1440), *range(0, 420)], "23:00-07:00", id="across-midnight"
            ),
            pytest.param(
                [*range(0, 420), *range(720, 780), *range(1380, 1440)],
                "12:00-13:00, 23:00-07:00",
                id="ranges-in-order-of-their-start",
            ),
            pytest.param(range(1380, 1440), "23:00-00:00", id="ending-at-midnight"),
            pytest.param(range(0, 60), "00:00-01:00", id="starting-at-midnight"),
            pytest.param([1439], "23:59-00:00", id="the-last-minute"),
            pytest.param(range(1440), "00:00-00:00", id="the-whole-day"),
            pytest.param([], "", id="no-minutes"),
        ],
    )
    def test_each_run_of_consecutive_minutes_is_one_clock_range(
        self, minutes: Iterable[int], expected: str
    ) -> None:
        assert describe_minutes_of_day(minutes) == expected

    def test_an_unordered_input_with_duplicates_reads_as_its_sorted_minutes(self) -> None:
        unordered = [721, 0, 720, 1, 0]

        assert describe_minutes_of_day(unordered) == describe_minutes_of_day(sorted(unordered))
        assert describe_minutes_of_day(unordered) == "00:00-00:02, 12:00-12:02"

    @pytest.mark.parametrize("minute", [1440, -1])
    def test_a_minute_outside_the_day_is_refused_naming_it(self, minute: int) -> None:
        with pytest.raises(ValueError) as refusal:
            describe_minutes_of_day([0, minute])

        assert names_as_a_word(str(refusal.value), minute)
