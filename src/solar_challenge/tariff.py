# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electricity tariff configuration and rate matching.

Supports time-of-use (TOU) tariffs with multiple rate periods,
flat-rate tariffs, and preset UK tariff configurations.
"""

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, time
from functools import cached_property

import pandas as pd

from solar_challenge.errors import ConfigurationError
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR


def _minute_of_day(clock: time | datetime) -> int:
    """The minute of the day, 0 to 1439, that *clock* reads on its own wall clock."""
    return clock.hour * MINUTES_PER_HOUR + clock.minute


def _clock_text(minute: int) -> str:
    """Minute *minute* of the day written as HH:MM, the day's end (1440) as 00:00."""
    hours, minutes = divmod(minute % MINUTES_PER_DAY, MINUTES_PER_HOUR)
    return f"{hours:02d}:{minutes:02d}"


def _runs_of_consecutive_minutes(minutes: set[int]) -> list[tuple[int, int]]:
    """The [start, end) of each run of consecutive minutes, in order of start; a run across midnight is one, its end below its start."""
    starts = sorted(minute for minute in minutes if minute - 1 not in minutes)
    ends = sorted(minute + 1 for minute in minutes if minute + 1 not in minutes)
    runs = list(zip(starts, ends, strict=True))
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == MINUTES_PER_DAY:
        return [*runs[1:-1], (runs[-1][0], runs[0][1])]
    return runs


def describe_minutes_of_day(minutes: Iterable[int]) -> str:
    """Minutes of the day, 0 to 1439, as HH:MM-HH:MM clock ranges, each ending at the minute after its last, a run across midnight as one range, in order of their start."""
    present = set(minutes)
    outside = sorted(minute for minute in present if not 0 <= minute < MINUTES_PER_DAY)
    if outside:
        raise ValueError(
            f"A minute of the day is 0 to {MINUTES_PER_DAY - 1}, "
            f"got {', '.join(str(minute) for minute in outside)}"
        )
    return ", ".join(
        f"{_clock_text(start)}-{_clock_text(end)}"
        for start, end in _runs_of_consecutive_minutes(present)
    )


@dataclass(frozen=True)
class TariffPeriod:
    """A time period with a specific electricity rate.

    Attributes:
        start_time: Period start, an "HH:MM" string only: the local wall-clock minute
        end_time: Period end, an "HH:MM" string only; an end at or before the start
            wraps midnight, and an end equal to the start is the whole day
        rate_per_kwh: Electricity rate in £/kWh, at least 0 and finite
        name: Descriptive name for the period (e.g., "Off-peak", "Peak")
    """

    start_time: str
    end_time: str
    rate_per_kwh: float
    name: str = ""

    def __post_init__(self) -> None:
        """Refuse a rate that is negative or not finite, and parse the times once, refusing any that is not HH:MM."""
        if not 0 <= self.rate_per_kwh < math.inf:
            raise ConfigurationError(
                "Tariff period rate_per_kwh must be finite and not negative, "
                f"got {self.rate_per_kwh} £/kWh"
            )
        self.get_start_time()
        self.get_end_time()

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse time string in HH:MM format.

        Args:
            time_str: Time string in HH:MM format (e.g., "07:00", "23:30")

        Returns:
            time object

        Raises:
            ConfigurationError: If time format is invalid, naming the string and why
        """
        try:
            parts = time_str.split(":")
            if len(parts) != 2:
                raise ValueError(f"Expected HH:MM format, got '{time_str}'")
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23):
                raise ValueError(f"Hour must be 0-23, got {hour}")
            if not (0 <= minute <= 59):
                raise ValueError(f"Minute must be 0-59, got {minute}")
            return time(hour=hour, minute=minute)
        except (ValueError, AttributeError) as e:
            raise ConfigurationError(f"Invalid time format '{time_str}': {e}") from e

    # cached_property, not dataclass fields: the parsed times and the minutes they
    # bound go in the instance __dict__ and stay out of fields(). web/field_tree.py's
    # field tree walks fields(), and its JSON form has no encoding for a datetime.time
    # or a frozenset.
    @cached_property
    def _parsed_start(self) -> time:
        return self._parse_time(self.start_time)

    @cached_property
    def _parsed_end(self) -> time:
        return self._parse_time(self.end_time)

    @cached_property
    def _minutes_covered(self) -> frozenset[int]:
        return frozenset(_minutes_covered_by(self))

    def get_start_time(self) -> time:
        """Get start time as time object."""
        return self._parsed_start

    def get_end_time(self) -> time:
        """Get end time as time object."""
        return self._parsed_end

    def matches_time(self, timestamp: pd.Timestamp) -> bool:
        """Whether the timestamp's wall-clock minute is one this period covers."""
        return _minute_of_day(timestamp) in self._minutes_covered


def _minutes_covered_by(period: TariffPeriod) -> list[int]:
    """The minutes of the day *period* covers: from its start up to its end, across midnight when the end comes first, all day when they are equal."""
    start = _minute_of_day(period.get_start_time())
    length = (_minute_of_day(period.get_end_time()) - start) % MINUTES_PER_DAY or MINUTES_PER_DAY
    return [(start + offset) % MINUTES_PER_DAY for offset in range(length)]


def _periods_covering_each_minute(periods: Sequence[TariffPeriod]) -> list[tuple[int, ...]]:
    """For each minute of the day, the indices in *periods* of the periods that cover it."""
    covering: list[list[int]] = [[] for _ in range(MINUTES_PER_DAY)]
    for index, period in enumerate(periods):
        for minute in _minutes_covered_by(period):
            covering[minute].append(index)
    return [tuple(indices) for indices in covering]


def _period_label(period: TariffPeriod) -> str:
    """A period as a tiling refusal names it: its quoted name, when it has one, then the clock range it covers."""
    clock_range = describe_minutes_of_day(_minutes_covered_by(period))
    return f"'{period.name}' {clock_range}" if period.name else clock_range


def _tiling_refusal(
    tariff_name: str, periods: Sequence[TariffPeriod], covering: Sequence[tuple[int, ...]]
) -> str:
    """The message refusing *periods*, given the periods *covering* each minute: the minutes none covers, then each group of minutes the same periods cover, naming those periods."""
    gap = [minute for minute, indices in enumerate(covering) if not indices]
    overlaps: dict[tuple[int, ...], list[int]] = {}
    for minute, indices in enumerate(covering):
        if len(indices) > 1:
            overlaps.setdefault(indices, []).append(minute)
    findings = [f"no period covers {describe_minutes_of_day(gap)}"] if gap else []
    findings += [
        f"{describe_minutes_of_day(minutes)} is covered by "
        + ", ".join(_period_label(periods[index]) for index in indices)
        for indices, minutes in overlaps.items()
    ]
    subject = f"The periods of tariff '{tariff_name}'" if tariff_name else "Tariff periods"
    return f"{subject} must cover each minute of the day exactly once: {'; '.join(findings)}"


@dataclass(frozen=True)
class TariffConfig:
    """Configuration for an electricity tariff.

    Supports both flat-rate and time-of-use (TOU) tariffs with
    multiple rate periods. Its periods cover each minute of the local day exactly
    once, and construction refuses a gap or an overlap (invariant 2,
    tests/unit/test_tariff_tiling.py).

    Attributes:
        periods: Tuple of TariffPeriod objects defining rate schedule
        name: Descriptive name for the tariff
    """

    periods: tuple[TariffPeriod, ...]
    name: str = ""

    def __post_init__(self) -> None:
        """Refuse a tariff without periods, then build the minute table, so construction, not the first rate read, refuses a gap or an overlap."""
        if not self.periods:
            raise ConfigurationError("Tariff must have at least one period")
        _ = self._rate_by_minute

    # Derived from periods; cached_property keeps them out of fields(), as for
    # TariffPeriod's parsed times.
    @cached_property
    def _rate_by_minute(self) -> tuple[float, ...]:
        """The rate in £/kWh at each minute of the local day, refusing periods that leave a minute uncovered or cover one twice."""
        covering = _periods_covering_each_minute(self.periods)
        if any(len(indices) != 1 for indices in covering):
            raise ConfigurationError(_tiling_refusal(self.name, self.periods, covering))
        return tuple(self.periods[index].rate_per_kwh for (index,) in covering)

    @cached_property
    def peak_rate(self) -> float:
        """Highest period rate in £/kWh."""
        return max(period.rate_per_kwh for period in self.periods)

    @cached_property
    def mean_period_rate(self) -> float:
        """Mean of the period rates in £/kWh, each period counted once whatever its length."""
        rates = [period.rate_per_kwh for period in self.periods]
        return sum(rates) / len(rates)

    @cached_property
    def cheap_minutes_of_day(self) -> frozenset[int]:
        """The minutes of the local day, 0 to 1439, whose rate is below peak_rate and at or below the duration-weighted mean rate; a tariff whose minutes share one rate has none."""
        weighted_mean_rate = math.fsum(self._rate_by_minute) / MINUTES_PER_DAY
        return frozenset(
            minute
            for minute, rate in enumerate(self._rate_by_minute)
            if rate < self.peak_rate and rate <= weighted_mean_rate
        )

    def get_rate(self, timestamp: pd.Timestamp) -> float:
        """Get the electricity rate at the timestamp's wall-clock minute, from the minute table built at construction.

        Args:
            timestamp: Timestamp to get rate for

        Returns:
            Rate in £/kWh
        """
        return self._rate_by_minute[_minute_of_day(timestamp)]

    def is_cheap_at(self, timestamp: datetime) -> bool:
        """Whether the timestamp's wall-clock minute is one of cheap_minutes_of_day."""
        return _minute_of_day(timestamp) in self.cheap_minutes_of_day

    @classmethod
    def flat_rate(cls, rate_per_kwh: float, name: str = "") -> "TariffConfig":
        """Create a flat-rate tariff (single rate all day).

        Its one period runs from 00:00 to 00:00: a period whose end equals its
        start covers the whole day.

        Args:
            rate_per_kwh: Electricity rate in £/kWh
            name: Optional tariff name

        Returns:
            TariffConfig with a single full-24h midnight-crossing period
            ("00:00"–"00:00") covering every minute of the day.
        """
        if not name:
            name = f"Flat rate {rate_per_kwh:.2f} £/kWh"

        period = TariffPeriod(
            start_time="00:00",
            end_time="00:00",
            rate_per_kwh=rate_per_kwh,
            name="All day"
        )
        return cls(periods=(period,), name=name)

    @classmethod
    def economy_7(
        cls,
        off_peak_rate: float = 0.09,
        peak_rate: float = 0.25,
        off_peak_start: str = "00:30",
        off_peak_end: str = "07:30",
    ) -> "TariffConfig":
        """Create an Economy 7 tariff (7 hours off-peak overnight).

        Economy 7 provides cheaper electricity for 7 hours overnight,
        typically 00:30-07:30 (times vary by region).

        Args:
            off_peak_rate: Off-peak rate in £/kWh (default: 0.09)
            peak_rate: Peak rate in £/kWh (default: 0.25)
            off_peak_start: Off-peak period start time HH:MM (default: "00:30")
            off_peak_end: Off-peak period end time HH:MM (default: "07:30")

        Returns:
            TariffConfig with Economy 7 structure
        """
        off_peak = TariffPeriod(
            start_time=off_peak_start,
            end_time=off_peak_end,
            rate_per_kwh=off_peak_rate,
            name="Off-peak"
        )
        # Peak period: from off-peak end to off-peak start (next day)
        peak = TariffPeriod(
            start_time=off_peak_end,
            end_time=off_peak_start,
            rate_per_kwh=peak_rate,
            name="Peak"
        )
        return cls(
            periods=(off_peak, peak),
            name=f"Economy 7 (off-peak {off_peak_start}-{off_peak_end})"
        )

    @classmethod
    def economy_10(
        cls,
        off_peak_rate: float = 0.08,
        peak_rate: float = 0.27,
        night_start: str = "00:00",
        night_end: str = "05:00",
        afternoon_start: str = "13:00",
        afternoon_end: str = "16:00",
        evening_start: str = "20:00",
        evening_end: str = "22:00",
    ) -> "TariffConfig":
        """Create an Economy 10 tariff (10 hours off-peak across day/night).

        Economy 10 provides cheaper electricity for 10 hours split across
        night, afternoon, and evening periods.

        Args:
            off_peak_rate: Off-peak rate in £/kWh (default: 0.08)
            peak_rate: Peak rate in £/kWh (default: 0.27)
            night_start: Night off-peak start (default: "00:00")
            night_end: Night off-peak end (default: "05:00")
            afternoon_start: Afternoon off-peak start (default: "13:00")
            afternoon_end: Afternoon off-peak end (default: "16:00")
            evening_start: Evening off-peak start (default: "20:00")
            evening_end: Evening off-peak end (default: "22:00")

        Returns:
            TariffConfig with Economy 10 structure
        """
        night_off_peak = TariffPeriod(
            start_time=night_start,
            end_time=night_end,
            rate_per_kwh=off_peak_rate,
            name="Off-peak (night)"
        )
        morning_peak = TariffPeriod(
            start_time=night_end,
            end_time=afternoon_start,
            rate_per_kwh=peak_rate,
            name="Peak (morning)"
        )
        afternoon_off_peak = TariffPeriod(
            start_time=afternoon_start,
            end_time=afternoon_end,
            rate_per_kwh=off_peak_rate,
            name="Off-peak (afternoon)"
        )
        afternoon_peak = TariffPeriod(
            start_time=afternoon_end,
            end_time=evening_start,
            rate_per_kwh=peak_rate,
            name="Peak (afternoon)"
        )
        evening_off_peak = TariffPeriod(
            start_time=evening_start,
            end_time=evening_end,
            rate_per_kwh=off_peak_rate,
            name="Off-peak (evening)"
        )
        late_peak = TariffPeriod(
            start_time=evening_end,
            end_time=night_start,
            rate_per_kwh=peak_rate,
            name="Peak (late)"
        )

        return cls(
            periods=(
                night_off_peak,
                morning_peak,
                afternoon_off_peak,
                afternoon_peak,
                evening_off_peak,
                late_peak,
            ),
            name="Economy 10"
        )


def calculate_bill(
    energy_kwh: pd.Series,
    tariff: TariffConfig,
) -> float:
    """Calculate electricity bill using time-varying tariff rates.

    Applies the appropriate tariff rate to each timestep based on its
    timestamp, then sums to get the total bill cost.

    Args:
        energy_kwh: Time series of energy consumption in kWh (must have DatetimeIndex)
        tariff: Tariff configuration with rate periods

    Returns:
        Total bill cost in £

    Raises:
        ValueError: If energy_kwh doesn't have a DatetimeIndex
    """
    if not isinstance(energy_kwh.index, pd.DatetimeIndex):
        raise ValueError("energy_kwh must have a DatetimeIndex")

    total_cost = 0.0

    for timestamp, energy in energy_kwh.items():
        rate = tariff.get_rate(timestamp)
        total_cost += energy * rate

    return total_cost


def FlatRateTariff(rate_per_kwh: float, name: str = "") -> TariffConfig:
    """Convenience function to create a flat-rate tariff.

    Args:
        rate_per_kwh: Electricity rate in £/kWh
        name: Optional tariff name

    Returns:
        TariffConfig with single 24-hour period
    """
    return TariffConfig.flat_rate(rate_per_kwh, name)
