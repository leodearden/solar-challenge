# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery storage configuration and modelling."""

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig


def _validate_soc_and_efficiency(
    min_soc: float,
    max_soc: float,
    charge_eff: float,
    discharge_eff: float,
) -> None:
    """Validate SOC limits and per-direction efficiency values.

    This is the single source of truth for these bounds; called from both
    BatteryConfig.__post_init__ and Battery.__init__ so the checks stay in sync.

    Args:
        min_soc: Minimum SOC fraction (must satisfy 0 <= min_soc < max_soc <= 1)
        max_soc: Maximum SOC fraction
        charge_eff: Charging efficiency (must satisfy 0 < charge_eff <= 1)
        discharge_eff: Discharging efficiency (must satisfy 0 < discharge_eff <= 1)

    Raises:
        ValueError: If any argument is out of range.
    """
    if not 0 <= min_soc < max_soc <= 1:
        raise ValueError(f"Invalid SOC limits: min={min_soc}, max={max_soc}")
    if not 0 < charge_eff <= 1:
        raise ValueError(f"Charge efficiency must be (0, 1], got {charge_eff}")
    if not 0 < discharge_eff <= 1:
        raise ValueError(f"Discharge efficiency must be (0, 1], got {discharge_eff}")


def compute_soh(
    system_age_years: float,
    cumulative_throughput_kwh: float,
    usable_capacity_kwh: float,
    params: "BatteryConfig",
) -> float:
    """Compute battery State of Health from calendar + cycle degradation.

    Uses a linear calendar fade and equivalent-full-cycle (EFC) cycle fade:

    - ``calendar_fade = params.calendar_fade_rate_per_year * system_age_years``
    - ``efc = cumulative_throughput_kwh / (2 * usable_capacity_kwh)`` if
      ``usable_capacity_kwh > 0`` else ``0.0``
    - ``cycle_fade = params.cycle_fade_per_equivalent_full_cycle * efc``
    - ``soh = clamp(1 - calendar_fade - cycle_fade, [soh_floor, 1.0])``

    The result is monotone non-increasing in both *system_age_years* and
    *cumulative_throughput_kwh* (both partial derivatives are ≤ 0).  The
    clamp preserves this property.

    Args:
        system_age_years: Age of the battery in years (≥ 0).
        cumulative_throughput_kwh: Total energy discharged over the battery's
            lifetime in kWh (≥ 0).
        usable_capacity_kwh: Nominal usable capacity in kWh; used to convert
            throughput to EFC.  Pass 0.0 to disable cycle fade (safe).
        params: BatteryConfig carrying the fade-rate and floor parameters.

    Returns:
        SOH in [params.soh_floor, 1.0].
    """
    calendar_fade = params.calendar_fade_rate_per_year * system_age_years
    efc = (
        cumulative_throughput_kwh / (2.0 * usable_capacity_kwh)
        if usable_capacity_kwh > 0
        else 0.0
    )
    cycle_fade = params.cycle_fade_per_equivalent_full_cycle * efc
    raw_soh = 1.0 - calendar_fade - cycle_fade
    return max(params.soh_floor, min(1.0, raw_soh))


@dataclass(frozen=True)
class BatteryConfig:
    """Configuration for a battery storage system.

    Attributes:
        capacity_kwh: Total energy capacity in kilowatt-hours
        max_charge_kw: Maximum charging power in kilowatts
        max_discharge_kw: Maximum discharging power in kilowatts
        name: Optional identifier for the battery
        dispatch_strategy: Optional dispatch strategy configuration
        grid_charging: Optional grid-charge (arbitrage) configuration; None means disabled
        min_soc_fraction: Minimum state of charge as fraction of capacity (default 0.1)
        max_soc_fraction: Maximum state of charge as fraction of capacity (default 0.9)
        charge_efficiency: Charging efficiency, fraction of energy stored (default 0.975)
        discharge_efficiency: Discharging efficiency, fraction of stored energy output (default 0.975)
        efficiency: Round-trip efficiency; when set, derives
            ``charge_efficiency = discharge_efficiency = sqrt(efficiency)``,
            silently overriding any explicitly-supplied per-direction values.
            The raw value is retained on the field so pickle round-trips are
            idempotent (``__post_init__`` always re-derives from ``efficiency``,
            never from the already-split values).
            **Caveat:** ``dataclasses.replace(cfg, charge_efficiency=x)`` on a
            config that has ``efficiency`` set will not take effect, because
            ``__post_init__`` re-derives charge/discharge from the retained
            ``efficiency``.  To change per-direction values, also clear
            ``efficiency`` (``dataclasses.replace(cfg, efficiency=None,
            charge_efficiency=x, discharge_efficiency=y)``).
        system_age_years: Age of the battery system in years (≥ 0); used to
            compute calendar fade when no ``soh`` override is provided.
        calendar_fade_rate_per_year: Linear calendar SOH fade rate per year
            (≥ 0; default 0.02/yr ≈ 70 % SOH at 15-yr warranty horizon).
        cycle_fade_per_equivalent_full_cycle: SOH fade per equivalent full
            cycle (≥ 0; default 5e-5/EFC ≈ 30 % fade over ~6 000 EFC).
        soh_floor: Minimum allowed SOH after clamping (0 < soh_floor ≤ 1;
            default 0.5, reflecting end-of-useful-life convention).
        soh: Optional direct SOH override (0 < soh ≤ 1).  When set, the
            computed calendar+cycle fade is bypassed and this value is used
            directly by ``Battery.__init__``.
    """

    capacity_kwh: float
    max_charge_kw: float = 2.5
    max_discharge_kw: float = 2.5
    name: str = ""
    dispatch_strategy: Optional["DispatchStrategyConfig"] = None
    grid_charging: Optional["GridChargeConfig"] = None
    min_soc_fraction: float = 0.1
    max_soc_fraction: float = 0.9
    charge_efficiency: float = 0.975
    discharge_efficiency: float = 0.975
    efficiency: Optional[float] = None
    system_age_years: float = 0.0
    calendar_fade_rate_per_year: float = 0.02
    cycle_fade_per_equivalent_full_cycle: float = 5e-5
    soh_floor: float = 0.5
    soh: Optional[float] = None

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
        if self.efficiency is not None:
            if not 0 < self.efficiency <= 1:
                raise ValueError(
                    f"Round-trip efficiency must be (0, 1], got {self.efficiency}"
                )
            object.__setattr__(self, "charge_efficiency", math.sqrt(self.efficiency))
            object.__setattr__(self, "discharge_efficiency", math.sqrt(self.efficiency))

        _validate_soc_and_efficiency(
            self.min_soc_fraction,
            self.max_soc_fraction,
            self.charge_efficiency,
            self.discharge_efficiency,
        )

        if self.system_age_years < 0:
            raise ValueError(
                f"system_age_years must be >= 0, got {self.system_age_years}"
            )
        if self.calendar_fade_rate_per_year < 0:
            raise ValueError(
                f"calendar_fade_rate_per_year must be >= 0, got {self.calendar_fade_rate_per_year}"
            )
        if self.cycle_fade_per_equivalent_full_cycle < 0:
            raise ValueError(
                f"cycle_fade_per_equivalent_full_cycle must be >= 0, "
                f"got {self.cycle_fade_per_equivalent_full_cycle}"
            )
        if not 0 < self.soh_floor <= 1:
            raise ValueError(
                f"soh_floor must be in (0, 1], got {self.soh_floor}"
            )
        if self.soh is not None and not 0 < self.soh <= 1:
            raise ValueError(
                f"soh override must be in (0, 1], got {self.soh}"
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
        min_soc_fraction: Optional[float] = None,
        max_soc_fraction: Optional[float] = None,
        charge_efficiency: Optional[float] = None,
        discharge_efficiency: Optional[float] = None,
    ) -> None:
        """Initialize battery with configuration and state.

        Args:
            config: Battery configuration
            initial_soc_kwh: Initial SOC in kWh (default: mid-point of usable range)
            min_soc_fraction: Minimum SOC as fraction (0-1); defaults to config.min_soc_fraction
            max_soc_fraction: Maximum SOC as fraction (0-1); defaults to config.max_soc_fraction
            charge_efficiency: Charging efficiency (0-1); defaults to config.charge_efficiency
            discharge_efficiency: Discharging efficiency (0-1); defaults to config.discharge_efficiency
        """
        self.config = config

        # Resolve optional params from config when not explicitly supplied
        resolved_min_soc: float = config.min_soc_fraction if min_soc_fraction is None else min_soc_fraction
        resolved_max_soc: float = config.max_soc_fraction if max_soc_fraction is None else max_soc_fraction
        resolved_charge_eff: float = config.charge_efficiency if charge_efficiency is None else charge_efficiency
        resolved_discharge_eff: float = config.discharge_efficiency if discharge_efficiency is None else discharge_efficiency

        _validate_soc_and_efficiency(
            resolved_min_soc, resolved_max_soc, resolved_charge_eff, resolved_discharge_eff
        )
        self.min_soc_fraction = resolved_min_soc
        self.max_soc_fraction = resolved_max_soc
        self.charge_efficiency = resolved_charge_eff
        self.discharge_efficiency = resolved_discharge_eff

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
