"""Heat pump configuration and modelling."""

from dataclasses import dataclass
from typing import Literal, Optional


# Valid heat pump types
HeatPumpType = Literal["ASHP", "GSHP"]


# COP curve parameters for Air Source Heat Pumps (ASHP)
# Based on typical ASHP performance characteristics
# COP = a + b * T_outdoor (linear approximation)
ASHP_COP_INTERCEPT: float = 2.5  # COP at 0°C
ASHP_COP_SLOPE: float = 0.1  # COP increase per degree C
ASHP_COP_MIN: float = 1.8  # Minimum COP at very low temperatures
ASHP_COP_MAX: float = 4.5  # Maximum COP at high temperatures


# COP curve parameters for Ground Source Heat Pumps (GSHP)
# More stable performance due to constant ground temperature
GSHP_COP_BASE: float = 3.8  # Base COP (relatively constant)
GSHP_COP_SLOPE: float = 0.02  # Small temperature dependency
GSHP_COP_MIN: float = 3.2  # Minimum COP
GSHP_COP_MAX: float = 4.8  # Maximum COP


def calculate_cop(heat_pump_type: HeatPumpType, outdoor_temp_c: float) -> float:
    """Calculate Coefficient of Performance (COP) based on outdoor temperature.

    The COP represents the ratio of heat output to electrical input.
    ASHP performance is strongly temperature-dependent (lower COP in cold weather).
    GSHP performance is more stable due to constant ground temperature.

    Args:
        heat_pump_type: Type of heat pump ("ASHP" or "GSHP")
        outdoor_temp_c: Outdoor air temperature in degrees Celsius

    Returns:
        Coefficient of Performance (dimensionless, typically 2-5)

    Raises:
        ValueError: If heat_pump_type is not valid
    """
    if heat_pump_type == "ASHP":
        # Linear COP curve with temperature dependency
        cop = ASHP_COP_INTERCEPT + ASHP_COP_SLOPE * outdoor_temp_c
        # Clamp to realistic bounds
        cop = max(ASHP_COP_MIN, min(ASHP_COP_MAX, cop))
        return cop
    elif heat_pump_type == "GSHP":
        # More stable COP with slight temperature dependency
        cop = GSHP_COP_BASE + GSHP_COP_SLOPE * outdoor_temp_c
        # Clamp to realistic bounds
        cop = max(GSHP_COP_MIN, min(GSHP_COP_MAX, cop))
        return cop
    else:
        raise ValueError(
            f"Invalid heat pump type: '{heat_pump_type}'. Must be 'ASHP' or 'GSHP'"
        )


@dataclass(frozen=True)
class HeatPumpConfig:
    """Configuration for a heat pump system.

    Attributes:
        heat_pump_type: Type of heat pump - ASHP (Air Source) or GSHP (Ground Source)
        thermal_capacity_kw: Thermal capacity in kilowatts (heating output)
        annual_heat_demand_kwh: Annual heating demand in kilowatt-hours
        name: Optional identifier for the heat pump
    """

    heat_pump_type: HeatPumpType
    thermal_capacity_kw: float
    annual_heat_demand_kwh: float = 8000.0  # Typical UK home heating demand
    name: str = ""

    def __post_init__(self) -> None:
        """Validate heat pump configuration parameters."""
        # Validate heat pump type
        valid_types = ("ASHP", "GSHP")
        if self.heat_pump_type not in valid_types:
            raise ValueError(
                f"Heat pump type must be one of {valid_types}, got '{self.heat_pump_type}'"
            )

        # Validate thermal capacity
        if self.thermal_capacity_kw <= 0:
            raise ValueError(
                f"Thermal capacity must be positive, got {self.thermal_capacity_kw} kW"
            )
        if self.thermal_capacity_kw > 50:
            raise ValueError(
                f"Thermal capacity seems unrealistic for domestic use: {self.thermal_capacity_kw} kW"
            )

        # Validate annual heat demand
        if self.annual_heat_demand_kwh <= 0:
            raise ValueError(
                f"Annual heat demand must be positive, got {self.annual_heat_demand_kwh} kWh"
            )
        if self.annual_heat_demand_kwh > 50000:
            raise ValueError(
                f"Annual heat demand seems unrealistic for domestic use: {self.annual_heat_demand_kwh} kWh"
            )

    @classmethod
    def default_ashp(cls) -> "HeatPumpConfig":
        """Create a typical UK domestic air source heat pump.

        Returns:
            HeatPumpConfig with 8 kW capacity, 8000 kWh annual demand
        """
        return cls(
            heat_pump_type="ASHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0,
            name="8 kW ASHP"
        )

    @classmethod
    def default_gshp(cls) -> "HeatPumpConfig":
        """Create a typical UK domestic ground source heat pump.

        Returns:
            HeatPumpConfig with 8 kW capacity, 8000 kWh annual demand
        """
        return cls(
            heat_pump_type="GSHP",
            thermal_capacity_kw=8.0,
            annual_heat_demand_kwh=8000.0,
            name="8 kW GSHP"
        )
