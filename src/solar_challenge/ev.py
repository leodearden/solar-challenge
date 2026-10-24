# SPDX-License-Identifier: AGPL-3.0-or-later
"""Electric vehicle charging configuration and load profile generation."""

import math
from dataclasses import dataclass
from enum import Enum
from typing import TypeAlias

import numpy as np
import pandas as pd

from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR

_MinuteFlags: TypeAlias = np.ndarray[tuple[int], np.dtype[np.bool_]]


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


_PREFERRED_WINDOWS: dict[SmartChargingMode, tuple[tuple[int, int], ...]] = {
    SmartChargingMode.NONE: (),
    SmartChargingMode.SOLAR: ((10 * MINUTES_PER_HOUR, 16 * MINUTES_PER_HOUR),),
    SmartChargingMode.OFF_PEAK: ((30, 7 * MINUTES_PER_HOUR + 30),),
}
"""Each mode's preferred charging windows, as [start, end) minutes of the day; generate_ev_charging_profile's docstring states them as clock times."""


@dataclass(frozen=True)
class EVConfig:
    """Configuration for electric vehicle charging.

    Attributes:
        charger_type: Charger power rating (3.6kW, 7kW, or 22kW)
        arrival_hour: Hour of day when EV arrives home (0-23), default 18, 6pm
        departure_hour: Hour of day when EV departs (0-23), default 7am
        required_charge_kwh: Energy required per day in kWh, default 35 kWh
            (typical UK EV doing ~100 miles/day at 3.5 miles/kWh)
        smart_charging_mode: Charging schedule optimization strategy
        name: Optional identifier for the EV configuration
    """

    charger_type: str
    arrival_hour: int = 18
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


def _preferred_minutes(mode: SmartChargingMode) -> _MinuteFlags:
    """One flag for each minute of the day, set where *mode* prefers to charge."""
    preferred = np.zeros(MINUTES_PER_DAY, dtype=np.bool_)
    for start, end in _PREFERRED_WINDOWS[mode]:
        preferred[start:end] = True
    return preferred


def _earliest_best_start(preferred: _MinuteFlags, charge_minutes: int) -> int:
    """The offset of the earliest run of *charge_minutes* flags in *preferred* that holds the most set flags."""
    covered = np.concatenate(([0], np.cumsum(preferred)))
    coverage = covered[charge_minutes:] - covered[: covered.size - charge_minutes]
    return int(np.argmax(coverage))


def _daily_session(config: EVConfig) -> range:
    """The minutes of one day's charging session, counted from the midnight before arrival."""
    arrival = config.arrival_hour * MINUTES_PER_HOUR
    stay_minutes = round(config.get_available_charging_hours() * MINUTES_PER_HOUR)
    hours_needed = config.required_charge_kwh / config.get_charger_power_kw()
    charge_minutes = min(math.ceil(hours_needed * MINUTES_PER_HOUR), stay_minutes)
    stay = (arrival + np.arange(stay_minutes)) % MINUTES_PER_DAY
    preferred = _preferred_minutes(SmartChargingMode(config.smart_charging_mode))[stay]
    start = arrival + _earliest_best_start(preferred, charge_minutes)
    return range(start, start + charge_minutes)


def generate_ev_charging_profile(
    config: EVConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
) -> pd.Series:
    """Generate EV charging load profile.

    Each day of the period the car is home from ``arrival_hour`` until
    ``departure_hour``, the next day when ``departure_hour`` is not after
    ``arrival_hour``. It charges in one unbroken session at the charger's full
    power, for as many whole minutes as ``required_charge_kwh`` needs. The
    session lies inside that stay, so the charge is always delivered before
    departure. Of all such sessions it is the one covering the most minutes of
    the mode's preferred window, on either day of an overnight stay, and the
    earliest on a tie. "solar" prefers 10:00-16:00 and "off_peak" Economy 7's
    00:30-07:30, the windows ``_PREFERRED_WINDOWS`` holds; "none" prefers no
    time, so it charges from arrival. A stay holding one window too short for
    the charge uses it whole, charging the rest just before it opens, or from
    arrival when that is later.

    The period is laid out as 1,440 minutes a day from its first midnight, so
    after a clock change inside it the times above run an hour off the wall
    clock. It holds only its own days' sessions: one still running when the
    period ends is cut there, and the first morning has none from the evening
    before.

    Args:
        config: EV configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: Timezone for the simulation

    Returns:
        Time series of charging power in kW at 1-minute resolution
    """
    date_range = pd.date_range(
        start=start_date,
        end=end_date,
        freq="D",
        tz=timezone,
    )
    n_minutes = len(date_range) * MINUTES_PER_DAY
    session = _daily_session(config)

    # One spare day holds the last day's session whole, until the cut below.
    power_kw = np.zeros(n_minutes + MINUTES_PER_DAY, dtype=np.float64)
    for day_start in range(0, n_minutes, MINUTES_PER_DAY):
        power_kw[day_start + session.start : day_start + session.stop] = config.get_charger_power_kw()

    time_index = pd.date_range(
        start=start_date,
        periods=n_minutes,
        freq="1min",
        tz=timezone,
    )
    return pd.Series(power_kw[:n_minutes], index=time_index, name=config.name or "EV Charging")
