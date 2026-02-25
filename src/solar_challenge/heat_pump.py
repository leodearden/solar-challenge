"""Heat pump configuration and modelling."""

from dataclasses import dataclass
from typing import Literal, Optional


# Valid heat pump types
HeatPumpType = Literal["ASHP", "GSHP"]


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
