# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery storage configuration and modelling."""

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from solar_challenge.config import DispatchStrategyConfig


@dataclass(frozen=True)
class BatteryConfig:
    """Configuration for a battery storage system.

    Attributes:
        capacity_kwh: Total energy capacity in kilowatt-hours
        max_charge_kw: Maximum charging power in kilowatts
        max_discharge_kw: Maximum discharging power in kilowatts
        name: Optional identifier for the battery
        dispatch_strategy: Optional dispatch strategy configuration
    """

    capacity_kwh: float
    max_charge_kw: float = 2.5
    max_discharge_kw: float = 2.5
    name: str = ""
    dispatch_strategy: Optional["DispatchStrategyConfig"] = None

    def __post_init__(self) -> None:
        """Validate battery configuration parameters."""
        if self.capacity_kwh <= 0:
            raise ValueError(f"Capacity must be positive, got {self.capacity_kwh} kWh")
        if self.max_charge_kw <= 0:
            raise ValueError(
                f"Max charge power must be positive, got {self.max_charge_kw} kW"
            )
        if self.max_discharge_kw <= 0:
            raise ValueError(
                f"Max discharge power must be positive, got {self.max_discharge_kw} kW"
            )

    @classmethod
    def default_5kwh(cls) -> "BatteryConfig":
        """Create a typical UK domestic 5 kWh battery.

        Returns:
            BatteryConfig with 5 kWh, 2.5 kW charge/discharge
        """
        return cls(
            capacity_kwh=5.0,
            max_charge_kw=2.5,
            max_discharge_kw=2.5,
            name="5 kWh domestic battery"
        )


class Battery:
    """Battery with state of charge tracking.

    Tracks current SOC and enforces charge/discharge limits.

    Attributes:
        config: BatteryConfig defining capacity and power limits
        soc_kwh: Current state of charge in kWh
        min_soc_fraction: Minimum SOC as fraction of capacity (default 0.1)
        max_soc_fraction: Maximum SOC as fraction of capacity (default 0.9)
        charge_efficiency: Efficiency of charging (default 0.975)
        discharge_efficiency: Efficiency of discharging (default 0.975)
    """

    def __init__(
        self,
        config: BatteryConfig,
        initial_soc_kwh: Optional[float] = None,
        min_soc_fraction: float = 0.1,
        max_soc_fraction: float = 0.9,
        charge_efficiency: float = 0.975,
        discharge_efficiency: float = 0.975,
    ) -> None:
        """Initialize battery with configuration and state.

        Args:
            config: Battery configuration
            initial_soc_kwh: Initial SOC in kWh (default: mid-point of usable range)
            min_soc_fraction: Minimum SOC as fraction (0-1)
            max_soc_fraction: Maximum SOC as fraction (0-1)
            charge_efficiency: Charging efficiency (0-1)
            discharge_efficiency: Discharging efficiency (0-1)
        """
        self.config = config

        if not 0 <= min_soc_fraction < max_soc_fraction <= 1:
            raise ValueError(
                f"Invalid SOC limits: min={min_soc_fraction}, max={max_soc_fraction}"
            )
        self.min_soc_fraction = min_soc_fraction
        self.max_soc_fraction = max_soc_fraction

        if not 0 < charge_efficiency <= 1:
            raise ValueError(f"Charge efficiency must be (0, 1], got {charge_efficiency}")
        if not 0 < discharge_efficiency <= 1:
            raise ValueError(
                f"Discharge efficiency must be (0, 1], got {discharge_efficiency}"
            )
        self.charge_efficiency = charge_efficiency
        self.discharge_efficiency = discharge_efficiency

        # Set initial SOC
        if initial_soc_kwh is None:
            # Default to midpoint of usable range
            self._soc_kwh = (self.min_soc_kwh + self.max_soc_kwh) / 2
        else:
            if not self.min_soc_kwh <= initial_soc_kwh <= self.max_soc_kwh:
                raise ValueError(
                    f"Initial SOC {initial_soc_kwh} kWh outside allowed range "
                    f"[{self.min_soc_kwh}, {self.max_soc_kwh}]"
                )
            self._soc_kwh = initial_soc_kwh

    @property
    def soc_kwh(self) -> float:
        """Current state of charge in kWh."""
        return self._soc_kwh

    @property
    def soc_fraction(self) -> float:
        """Current state of charge as fraction of capacity."""
        return self._soc_kwh / self.config.capacity_kwh

    @property
    def min_soc_kwh(self) -> float:
        """Minimum allowed SOC in kWh."""
        return self.config.capacity_kwh * self.min_soc_fraction

    @property
    def max_soc_kwh(self) -> float:
        """Maximum allowed SOC in kWh."""
        return self.config.capacity_kwh * self.max_soc_fraction

    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity in kWh (max_soc - min_soc)."""
        return self.max_soc_kwh - self.min_soc_kwh

    @property
    def available_charge_capacity_kwh(self) -> float:
        """Energy that can still be stored in kWh."""
        return self.max_soc_kwh - self._soc_kwh

    @property
    def available_discharge_capacity_kwh(self) -> float:
        """Energy that can still be discharged in kWh."""
        return self._soc_kwh - self.min_soc_kwh

    def charge(self, power_kw: float, duration_minutes: float) -> float:
        """Charge the battery.

        Args:
            power_kw: Charging power in kW (before efficiency losses)
            duration_minutes: Duration of charging in minutes

        Returns:
            Actual energy charged in kWh (after efficiency losses)
        """
        if power_kw < 0:
            raise ValueError(f"Charge power must be non-negative, got {power_kw}")

        # Limit to max charge rate
        actual_power = min(power_kw, self.config.max_charge_kw)

        # Calculate energy input and stored (with efficiency)
        duration_hours = duration_minutes / 60
        energy_input_kwh = actual_power * duration_hours
        energy_stored_kwh = energy_input_kwh * self.charge_efficiency

        # Limit to available capacity
        max_storable = self.available_charge_capacity_kwh
        if energy_stored_kwh > max_storable:
            energy_stored_kwh = max_storable

        # Update SOC
        self._soc_kwh += energy_stored_kwh

        return energy_stored_kwh

    def discharge(self, power_kw: float, duration_minutes: float) -> float:
        """Discharge the battery.

        Args:
            power_kw: Requested discharge power in kW
            duration_minutes: Duration of discharging in minutes

        Returns:
            Actual energy output in kWh (after efficiency losses)
        """
        if power_kw < 0:
            raise ValueError(f"Discharge power must be non-negative, got {power_kw}")

        # Limit to max discharge rate
        actual_power = min(power_kw, self.config.max_discharge_kw)

        # Calculate energy requested
        duration_hours = duration_minutes / 60
        energy_requested_kwh = actual_power * duration_hours

        # Calculate energy needed from battery (before efficiency)
        # We need to withdraw more than we output due to losses
        energy_needed_kwh = energy_requested_kwh / self.discharge_efficiency

        # Limit to available discharge capacity
        max_available = self.available_discharge_capacity_kwh
        if energy_needed_kwh > max_available:
            energy_needed_kwh = max_available

        # Calculate actual output
        energy_output_kwh = energy_needed_kwh * self.discharge_efficiency

        # Update SOC
        self._soc_kwh -= energy_needed_kwh

        return energy_output_kwh
