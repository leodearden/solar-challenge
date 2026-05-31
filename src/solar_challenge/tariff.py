# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electricity tariff configuration and rate matching.

Supports time-of-use (TOU) tariffs with multiple rate periods,
flat-rate tariffs, and preset UK tariff configurations.
"""

from dataclasses import dataclass
from datetime import time
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class TariffPeriod:
    """A time period with a specific electricity rate.

    Attributes:
        start_time: Period start time (HH:MM format or time object)
        end_time: Period end time (HH:MM format or time object)
        rate_per_kwh: Electricity rate in £/kWh
        name: Descriptive name for the period (e.g., "Off-peak", "Peak")
    """

    start_time: str
    end_time: str
    rate_per_kwh: float
    name: str = ""

    def __post_init__(self) -> None:
        """Validate tariff period parameters."""
        if self.rate_per_kwh < 0:
            raise ValueError(f"Rate cannot be negative, got {self.rate_per_kwh} £/kWh")

        # Validate time format
        try:
            self._parse_time(self.start_time)
            self._parse_time(self.end_time)
        except ValueError as e:
            raise ValueError(f"Invalid time format: {e}")

    @staticmethod
    def _parse_time(time_str: str) -> time:
        """Parse time string in HH:MM format.

        Args:
            time_str: Time string in HH:MM format (e.g., "07:00", "23:30")

        Returns:
            time object

        Raises:
            ValueError: If time format is invalid
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
            raise ValueError(f"Invalid time format '{time_str}': {e}")

    def get_start_time(self) -> time:
        """Get start time as time object."""
        return self._parse_time(self.start_time)

    def get_end_time(self) -> time:
        """Get end time as time object."""
        return self._parse_time(self.end_time)

    def matches_time(self, timestamp: pd.Timestamp) -> bool:
        """Check if a timestamp falls within this period.

        Args:
            timestamp: Timestamp to check

        Returns:
            True if timestamp falls within this period
        """
        time_of_day = timestamp.time()
        start = self.get_start_time()
        end = self.get_end_time()

        # Handle periods that cross midnight
        if start < end:
            # Normal period (e.g., 07:00-23:00)
            return start <= time_of_day < end  # type: ignore[no-any-return]
        else:
            # Crosses midnight (e.g., 23:00-07:00)
            return time_of_day >= start or time_of_day < end  # type: ignore[no-any-return]


@dataclass(frozen=True)
class TariffConfig:
    """Configuration for an electricity tariff.

    Supports both flat-rate and time-of-use (TOU) tariffs with
    multiple rate periods.

    Attributes:
        periods: Tuple of TariffPeriod objects defining rate schedule
        name: Descriptive name for the tariff
    """

    periods: tuple[TariffPeriod, ...]
    name: str = ""

    def __post_init__(self) -> None:
        """Validate tariff configuration."""
        if not self.periods:
            raise ValueError("Tariff must have at least one period")

        # Validate all periods have valid times
        for period in self.periods:
            period.get_start_time()
            period.get_end_time()

    def get_rate(self, timestamp: pd.Timestamp) -> float:
        """Get the electricity rate for a specific timestamp.

        Args:
            timestamp: Timestamp to get rate for

        Returns:
            Rate in £/kWh

        Raises:
            ValueError: If no period matches the timestamp
        """
        for period in self.periods:
            if period.matches_time(timestamp):
                return period.rate_per_kwh

        # If no period matches, raise error
        raise ValueError(
            f"No tariff period matches timestamp {timestamp}. "
            "Tariff periods may have gaps in coverage."
        )

    @classmethod
    def flat_rate(cls, rate_per_kwh: float, name: str = "") -> "TariffConfig":
        """Create a flat-rate tariff (single rate all day).

        Args:
            rate_per_kwh: Electricity rate in £/kWh
            name: Optional tariff name

        Returns:
            TariffConfig with single 24-hour period
        """
        if not name:
            name = f"Flat rate {rate_per_kwh:.2f} £/kWh"

        period = TariffPeriod(
            start_time="00:00",
            end_time="23:59",
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
