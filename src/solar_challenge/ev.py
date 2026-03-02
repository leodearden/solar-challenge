"""Electric vehicle charging configuration and load profile generation."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd


class EVChargerType(str, Enum):
    """Standard UK domestic EV charger types.

    Values represent typical charging power ratings:
    - SLOW: 3.6 kW single-phase (slow/granny charger)
    - FAST: 7 kW single-phase (typical home wallbox)
    - RAPID: 22 kW three-phase (high-power home installation)
    """

    SLOW = "3.6kW"
    FAST = "7kW"
    RAPID = "22kW"


class SmartChargingMode(str, Enum):
    """Smart charging scheduling strategies.

    - NONE: Dumb charging - start immediately on arrival
    - SOLAR: Solar-aware - shift charging to daylight hours
    - OFF_PEAK: Off-peak tariff - shift charging to cheapest hours
    """

    NONE = "none"
    SOLAR = "solar"
    OFF_PEAK = "off_peak"


@dataclass(frozen=True)
class EVConfig:
    """Configuration for electric vehicle charging.

    Attributes:
        charger_type: Charger power rating (3.6kW, 7kW, or 22kW)
        arrival_hour: Hour of day when EV arrives home (0-23)
        departure_hour: Hour of day when EV departs (0-23), default 7am
        required_charge_kwh: Energy required per day in kWh, default 35 kWh
            (typical UK EV doing ~100 miles/day at 3.5 miles/kWh)
        smart_charging_mode: Charging schedule optimization strategy
        name: Optional identifier for the EV configuration
    """

    charger_type: str
    arrival_hour: int
    departure_hour: int = 7
    required_charge_kwh: float = 35.0
    smart_charging_mode: str = "none"
    name: str = ""

    def __post_init__(self) -> None:
        """Validate EV configuration parameters."""
        # Validate charger_type
        valid_charger_types = ["3.6kW", "7kW", "22kW"]
        if self.charger_type not in valid_charger_types:
            raise ValueError(
                f"Charger type must be one of {valid_charger_types}, "
                f"got '{self.charger_type}'"
            )

        # Validate arrival_hour
        if not 0 <= self.arrival_hour <= 23:
            raise ValueError(
                f"Arrival hour must be 0-23, got {self.arrival_hour}"
            )

        # Validate departure_hour
        if not 0 <= self.departure_hour <= 23:
            raise ValueError(
                f"Departure hour must be 0-23, got {self.departure_hour}"
            )

        # Validate required_charge_kwh
        if self.required_charge_kwh <= 0:
            raise ValueError(
                f"Required charge must be positive, got {self.required_charge_kwh} kWh"
            )

        # Check for unrealistically high charging requirement
        if self.required_charge_kwh > 100:
            raise ValueError(
                f"Required charge seems unrealistic: {self.required_charge_kwh} kWh "
                "(typical UK EV battery is 40-75 kWh)"
            )

        # Validate smart_charging_mode
        valid_modes = ["none", "solar", "off_peak"]
        if self.smart_charging_mode not in valid_modes:
            raise ValueError(
                f"Smart charging mode must be one of {valid_modes}, "
                f"got '{self.smart_charging_mode}'"
            )

        # Validate that there's enough time to charge
        charger_power_kw = self._parse_charger_power()
        available_hours = self._calculate_available_hours()
        max_charge_kwh = charger_power_kw * available_hours

        if self.required_charge_kwh > max_charge_kwh:
            raise ValueError(
                f"Cannot deliver {self.required_charge_kwh} kWh with {self.charger_type} "
                f"charger in {available_hours:.1f} hours (max: {max_charge_kwh:.1f} kWh). "
                "Either reduce required_charge_kwh or adjust arrival/departure hours."
            )

    def _parse_charger_power(self) -> float:
        """Extract charger power in kW from charger_type string.

        Returns:
            Charger power in kW
        """
        # Parse "3.6kW" -> 3.6
        return float(self.charger_type.replace("kW", ""))

    def _calculate_available_hours(self) -> float:
        """Calculate available charging hours between arrival and departure.

        Returns:
            Available hours (handles overnight charging)
        """
        if self.departure_hour > self.arrival_hour:
            # Same day: e.g., arrive 8am, depart 5pm = 9 hours
            return float(self.departure_hour - self.arrival_hour)
        else:
            # Overnight: e.g., arrive 6pm (18), depart 7am (7) = 13 hours
            return float(24 - self.arrival_hour + self.departure_hour)

    def get_charger_power_kw(self) -> float:
        """Get charger power rating in kW.

        Returns:
            Charger power in kW
        """
        return self._parse_charger_power()

    def get_available_charging_hours(self) -> float:
        """Get available charging window in hours.

        Returns:
            Available charging hours between arrival and departure
        """
        return self._calculate_available_hours()


def generate_ev_charging_profile(
    config: EVConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
) -> pd.Series:
    """Generate EV charging load profile.

    Supports multiple charging strategies:
    - "none": Dumb charging - starts immediately on arrival
    - "solar": Solar-aware - prefers daylight hours (10:00-16:00)
    - "off_peak": Off-peak tariff - prefers Economy 7 hours (00:30-07:30)

    All strategies ensure the required charge is delivered before departure.

    Args:
        config: EV configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: Timezone for the simulation

    Returns:
        Time series of charging power in kW at 1-minute resolution
    """
    # Create minute-by-minute time index for the full period
    date_range = pd.date_range(
        start=start_date,
        end=end_date,
        freq="D",
        tz=timezone,
    )

    # Calculate total minutes in the period
    n_days = len(date_range)
    n_minutes = n_days * 1440

    # Initialize power array (kW) - zeros everywhere by default
    power_kw = np.zeros(n_minutes, dtype=np.float64)

    # Get charger power
    charger_power_kw = config.get_charger_power_kw()

    # Calculate how many minutes of charging are needed
    # Energy (kWh) = Power (kW) × Time (hours)
    # Time (hours) = Energy (kWh) / Power (kW)
    charging_hours_needed = config.required_charge_kwh / charger_power_kw
    charging_minutes_needed = int(np.ceil(charging_hours_needed * 60))

    # For each day, apply the charging schedule
    for day_idx in range(n_days):
        day_start_minute = day_idx * 1440
        arrival_minute = day_start_minute + (config.arrival_hour * 60)
        departure_minute = day_start_minute + (config.departure_hour * 60)

        # Handle overnight charging (departure before arrival next day)
        if config.departure_hour <= config.arrival_hour:
            # Overnight case: e.g., arrive 18:00, depart 07:00 next day
            departure_minute += 1440  # Next day

        # Calculate available charging window
        available_minutes = departure_minute - arrival_minute

        # Determine charging start time based on smart charging mode
        if config.smart_charging_mode == "solar":
            # Solar-aware charging: prefer daylight hours (10:00-16:00)
            solar_start_minute = day_start_minute + (10 * 60)  # 10:00
            solar_end_minute = day_start_minute + (16 * 60)  # 16:00

            # Find overlap between solar window and available charging window
            charging_start_minute = max(arrival_minute, solar_start_minute)
            charging_window_end = min(departure_minute, solar_end_minute)

            # Check if there's enough time in the solar window
            solar_window_minutes = max(0, charging_window_end - charging_start_minute)

            if solar_window_minutes >= charging_minutes_needed:
                # Enough time in solar window - charge during solar hours
                actual_charging_minutes = charging_minutes_needed
            else:
                # Not enough time in solar window - use as much solar time as possible
                # then charge immediately after solar window or from arrival
                if solar_window_minutes > 0:
                    # Partial solar charging + remaining time after solar window
                    charging_start_minute = max(arrival_minute, solar_start_minute)
                    actual_charging_minutes = min(charging_minutes_needed, available_minutes)
                else:
                    # No overlap with solar window - start charging at arrival
                    charging_start_minute = arrival_minute
                    actual_charging_minutes = min(charging_minutes_needed, available_minutes)
        elif config.smart_charging_mode == "off_peak":
            # Off-peak tariff charging: prefer Economy 7 hours (00:30-07:30)
            # Off-peak window for current day
            off_peak_start_minute = day_start_minute + (0 * 60 + 30)  # 00:30
            off_peak_end_minute = day_start_minute + (7 * 60 + 30)  # 07:30

            # For overnight charging, also consider next day's off-peak window
            if config.departure_hour <= config.arrival_hour:
                # Overnight case - look at next day's off-peak window
                next_day_off_peak_start = day_start_minute + 1440 + (0 * 60 + 30)  # Next day 00:30
                next_day_off_peak_end = day_start_minute + 1440 + (7 * 60 + 30)  # Next day 07:30

                # Find overlap with next day's off-peak window
                charging_start_minute = max(arrival_minute, next_day_off_peak_start)
                charging_window_end = min(departure_minute, next_day_off_peak_end)

                # Check if there's enough time in the off-peak window
                off_peak_window_minutes = max(0, charging_window_end - charging_start_minute)

                if off_peak_window_minutes >= charging_minutes_needed:
                    # Enough time in off-peak window - charge during off-peak hours
                    actual_charging_minutes = charging_minutes_needed
                else:
                    # Not enough time - use available off-peak time + fallback
                    if off_peak_window_minutes > 0:
                        charging_start_minute = max(arrival_minute, next_day_off_peak_start)
                        actual_charging_minutes = min(charging_minutes_needed, available_minutes)
                    else:
                        # No overlap - start at arrival
                        charging_start_minute = arrival_minute
                        actual_charging_minutes = min(charging_minutes_needed, available_minutes)
            else:
                # Same day charging - use current day's off-peak window
                charging_start_minute = max(arrival_minute, off_peak_start_minute)
                charging_window_end = min(departure_minute, off_peak_end_minute)

                off_peak_window_minutes = max(0, charging_window_end - charging_start_minute)

                if off_peak_window_minutes >= charging_minutes_needed:
                    # Enough time in off-peak window
                    actual_charging_minutes = charging_minutes_needed
                else:
                    # Not enough time in off-peak window
                    if off_peak_window_minutes > 0:
                        charging_start_minute = max(arrival_minute, off_peak_start_minute)
                        actual_charging_minutes = min(charging_minutes_needed, available_minutes)
                    else:
                        # No overlap - start at arrival
                        charging_start_minute = arrival_minute
                        actual_charging_minutes = min(charging_minutes_needed, available_minutes)
        else:
            # Dumb charging (mode="none")
            # Start charging immediately on arrival
            charging_start_minute = arrival_minute
            actual_charging_minutes = min(charging_minutes_needed, available_minutes)

        # Set power during charging period
        charging_end_minute = charging_start_minute + actual_charging_minutes
        power_kw[charging_start_minute:charging_end_minute] = charger_power_kw

    # Create time index for the full period at minute resolution
    time_index = pd.date_range(
        start=start_date,
        periods=n_minutes,
        freq="1min",
        tz=timezone,
    )

    # Create pandas Series
    profile = pd.Series(power_kw, index=time_index, name=config.name or "EV Charging")

    return profile
