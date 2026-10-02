# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heat pump configuration and modelling."""

from dataclasses import dataclass
from typing import Literal, Optional

import pandas as pd


# Valid heat pump types
HeatPumpType = Literal["ASHP", "GSHP"]


# Base temperature for heating degree day calculations
# UK standard base temperature for domestic heating demand
BASE_TEMPERATURE_C: float = 15.5


def reference_year_lengths(rows_per_day: int) -> range:
    """The row counts of one reference year, the year a heat pump's annual heat demand is shared out over.

    That is 365 to 366 days (366 in a leap year) of rows, at rows_per_day rows a day.
    """
    return range(365 * rows_per_day, 366 * rows_per_day + 1)


_YEAR_LENGTHS_IN_MINUTES = reference_year_lengths(rows_per_day=24 * 60)


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


def calculate_heating_degree_minutes(
    temperature_c: pd.Series,
    base_temp_c: float = BASE_TEMPERATURE_C
) -> pd.Series:
    """Calculate heating degree minutes from temperature data.

    Heating degree minutes quantify heating demand at each timestep.
    When outdoor temperature falls below the base temperature, heating is required.
    The degree minutes value represents the temperature deficit that must be made up.

    This is the minute-resolution equivalent of heating degree days (HDD),
    commonly used for UK heating demand calculations.

    Args:
        temperature_c: Time series of outdoor temperature in degrees Celsius
        base_temp_c: Base temperature threshold for heating (default 15.5°C for UK)

    Returns:
        Series of heating degree minutes (°C-minutes), same length as input.
        Zero when temperature is at or above base, positive when heating needed.
    """
    # Calculate temperature deficit below base temperature
    # Negative values (temp above base) become zero (no heating needed)
    degree_minutes = base_temp_c - temperature_c
    degree_minutes = degree_minutes.clip(lower=0.0)
    return degree_minutes


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


def generate_heat_pump_load(
    config: HeatPumpConfig,
    temperature_c: pd.Series,
    *,
    annual_temperature_c: pd.Series,
) -> pd.Series:
    """Generate a heat pump's electrical load, in kW, over the minutes of temperature_c.

    config.annual_heat_demand_kwh is shared out over the heating degree-minutes
    of annual_temperature_c, a reference year such as the TMY: each minute of
    temperature_c gets heat in proportion to its own heating degree-minutes.
    So a window's load does not depend on the window's length, and a run over
    exactly the reference year delivers the whole annual demand wherever the
    capacity cap does not bind. Each minute's heat is capped at
    config.thermal_capacity_kw, and its electrical load is that heat divided by
    the COP at the minute's outdoor temperature. A reference year with no
    heating degree-minutes has no heat to share out, so the load is zero.

    Args:
        config: Heat pump configuration (type, capacity, annual demand)
        temperature_c: Outdoor temperature in degrees Celsius at 1-minute
            resolution, over the minutes to generate the load for.
            Must have a DatetimeIndex with timezone info.
        annual_temperature_c: One year of outdoor temperature in degrees
            Celsius at 1-minute resolution, 365 to 366 days of rows.
            Only its values are read.

    Returns:
        Series of electrical power demand in kW, named heat_pump_load_kw, with
        same index as temperature_c. Values are non-negative and capped at
        thermal_capacity_kw / COP.

    Raises:
        ValueError: If temperature_c doesn't have a DatetimeIndex
        ValueError: If temperature_c index is not timezone-aware
        ValueError: If annual_temperature_c is not one year of minutes, 365 to
            366 days of rows

    Example:
        >>> config = HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=8.0)
        >>> year = pd.Series(
        ...     10.0,
        ...     index=pd.date_range('2023-01-01', periods=525_600, freq='1min', tz='UTC'),
        ... )
        >>> load = generate_heat_pump_load(config, year.loc['2023-01-15'], annual_temperature_c=year)
        >>> len(load)
        1440
        >>> heat_delivered_kwh = float(load.sum()) / 60 * calculate_cop("ASHP", 10.0)
        >>> round(heat_delivered_kwh, 2)  # one day's share of 8000 kWh: 8000 / 365
        21.92
    """
    # Validate input
    if not isinstance(temperature_c.index, pd.DatetimeIndex):
        raise ValueError("Temperature series must have a DatetimeIndex")
    if temperature_c.index.tz is None:
        raise ValueError("Temperature series index must be timezone-aware")
    if len(annual_temperature_c) not in _YEAR_LENGTHS_IN_MINUTES:
        raise ValueError(
            f"annual_temperature_c has {len(annual_temperature_c):,} rows, not one year of minutes "
            f"({_YEAR_LENGTHS_IN_MINUTES.start:,} to {_YEAR_LENGTHS_IN_MINUTES[-1]:,}): "
            f"annual_heat_demand_kwh={config.annual_heat_demand_kwh:g} is shared out over one year's "
            "heating degree-minutes, so pass a whole year of 1-minute temperature, such as the "
            "minute-interpolated TMY."
        )

    annual_degree_minutes = calculate_heating_degree_minutes(annual_temperature_c).sum()
    if annual_degree_minutes == 0:
        electrical_load_kw = pd.Series(0.0, index=temperature_c.index)
    else:
        heat_kw_per_degree_minute = config.annual_heat_demand_kwh * 60.0 / annual_degree_minutes
        thermal_demand_kw = (
            calculate_heating_degree_minutes(temperature_c) * heat_kw_per_degree_minute
        ).clip(upper=config.thermal_capacity_kw)

        # Calculate COP for each timestep
        cop_series = temperature_c.apply(
            lambda temp: calculate_cop(config.heat_pump_type, temp)
        )

        # Calculate electrical load (thermal output / COP)
        # Avoid division by zero (though COP should never be zero with our bounds)
        electrical_load_kw = thermal_demand_kw / cop_series

    return electrical_load_kw.rename("heat_pump_load_kw")
