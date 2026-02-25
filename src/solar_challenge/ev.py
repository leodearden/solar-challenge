"""Electric vehicle charging configuration and load profile generation."""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


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
