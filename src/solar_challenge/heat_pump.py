# SPDX-License-Identifier: AGPL-3.0-or-later
"""Heat pump configuration and modelling."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from types import MappingProxyType
from typing import Literal, get_args

import pandas as pd

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval, as_finite_float, read_field
from solar_challenge.timebase import SimulationWindow


@dataclass(frozen=True)
class CopCurve:
    """A heat pump's COP (heat out over electricity in) at each outdoor temperature.

    The COP follows the line intercept + slope × outdoor °C (intercept is the COP at 0 °C,
    slope its change per °C), held between minimum and maximum.
    """

    intercept: float
    slope: float
    minimum: float
    maximum: float

    def __post_init__(self) -> None:
        """Refuse bounds that are not 0 < minimum <= maximum: electrical load is heat over COP, so a COP stays above zero."""
        if not 0 < self.minimum <= self.maximum:
            raise ValueError(
                "A COP curve's bounds must satisfy 0 < minimum <= maximum, "
                f"got minimum={self.minimum}, maximum={self.maximum}"
            )

    def cops(self, outdoor_temp_c: pd.Series) -> pd.Series:
        """The COP at each row's outdoor temperature in °C, on outdoor_temp_c's index."""
        return (self.intercept + self.slope * outdoor_temp_c).clip(lower=self.minimum, upper=self.maximum)

    def cop(self, outdoor_temp_c: float) -> float:
        """The COP at an outdoor temperature of outdoor_temp_c °C: cops at that one temperature."""
        return float(self.cops(pd.Series([outdoor_temp_c])).iloc[0])


HeatPumpType = Literal["ASHP", "GSHP"]  # air source, ground source
HEAT_PUMP_TYPES: tuple[HeatPumpType, ...] = get_args(HeatPumpType)
COP_CURVES: Mapping[HeatPumpType, CopCurve] = MappingProxyType({
    "ASHP": CopCurve(intercept=2.5, slope=0.1, minimum=1.8, maximum=4.5),
    "GSHP": CopCurve(intercept=3.8, slope=0.02, minimum=3.2, maximum=4.8),
})


def _refuse_unknown_heat_pump_type(heat_pump_type: object) -> None:
    """Raise ConfigurationError, naming HEAT_PUMP_TYPES, unless heat_pump_type is one of them."""
    if heat_pump_type not in HEAT_PUMP_TYPES:
        raise ConfigurationError(f"Heat pump type must be one of {HEAT_PUMP_TYPES}, got {heat_pump_type!r}")


# Base temperature for heating degree day calculations
# UK standard base temperature for domestic heating demand
BASE_TEMPERATURE_C: float = 15.5


def reference_year_lengths(rows_per_day: int) -> range:
    """The row counts of one reference year, the year a heat pump's annual heat demand is shared out over.

    That is 365 to 366 days (366 in a leap year) of rows, at rows_per_day rows a day.
    """
    return range(365 * rows_per_day, 366 * rows_per_day + 1)


def _reference_year_window(annual_temperature_c: pd.Series) -> SimulationWindow:
    """The window annual_temperature_c's index describes, returned only once the series is one year of its own rows.

    Raises:
        ValueError: If SimulationWindow.of_index refuses the index.
        ValueError: If the window's cadence does not divide one day, naming it.
        ValueError: If the row count is outside reference_year_lengths at that cadence,
            naming the count, the cadence and the year's row counts.
    """
    window = SimulationWindow.of_index(annual_temperature_c.index)
    rows_per_day, leftover = divmod(timedelta(days=1), window.cadence)
    if leftover:
        raise ValueError(
            f"annual_temperature_c's rows are {window.cadence} apart, which does not divide one day, "
            "so no whole number of them makes a year: pass one year of temperature at a spacing "
            "that divides one day, such as the minute-interpolated TMY."
        )
    year_lengths = reference_year_lengths(rows_per_day)
    if len(annual_temperature_c) not in year_lengths:
        raise ValueError(
            f"annual_temperature_c has {len(annual_temperature_c):,} rows, not one year of rows "
            f"{window.cadence} apart ({year_lengths.start:,} to {year_lengths[-1]:,}): "
            "annual_heat_demand_kwh is shared out over one year's heating degree-hours, "
            "so pass one whole year of temperature, such as the minute-interpolated TMY."
        )
    return window


def heating_degree_deficit_c(
    temperature_c: pd.Series,
    base_temp_c: float = BASE_TEMPERATURE_C
) -> pd.Series:
    """Each row's temperature deficit below the heating base temperature, in °C.

    When outdoor temperature falls below the base temperature, heating is required,
    and the deficit is the temperature gap that must be made up.

    The deficit is per row, whatever the row's length: a caller multiplies it by
    the window's step_hours to get heating degree-hours, which divided by 24 are
    heating degree days (HDD), commonly used for UK heating demand calculations.

    Args:
        temperature_c: Time series of outdoor temperature in degrees Celsius
        base_temp_c: Base temperature threshold for heating (default 15.5°C for UK)

    Returns:
        Series of deficits in °C, same length as input.
        Zero when temperature is at or above base, positive when heating needed.
    """
    # Calculate temperature deficit below base temperature
    # Negative values (temp above base) become zero (no heating needed)
    deficit_c = base_temp_c - temperature_c
    deficit_c = deficit_c.clip(lower=0.0)
    return deficit_c


def calculate_cop(heat_pump_type: HeatPumpType, outdoor_temp_c: float) -> float:
    """The Coefficient of Performance (COP) of heat_pump_type at outdoor_temp_c: its COP_CURVES curve's cop there.

    Args:
        heat_pump_type: One of HEAT_PUMP_TYPES
        outdoor_temp_c: Outdoor air temperature in degrees Celsius

    Returns:
        Coefficient of Performance (dimensionless, typically 2-5)

    Raises:
        ConfigurationError: If heat_pump_type is not one of HEAT_PUMP_TYPES, naming them
    """
    _refuse_unknown_heat_pump_type(heat_pump_type)
    return COP_CURVES[heat_pump_type].cop(outdoor_temp_c)


@dataclass(frozen=True)
class HeatPumpConfig:
    """Configuration for a heat pump system.

    Attributes:
        heat_pump_type: One of HEAT_PUMP_TYPES
        thermal_capacity_kw: Thermal capacity in kilowatts (heating output), default 8 kW
        annual_heat_demand_kwh: Annual heating demand in kilowatt-hours
        name: Optional identifier for the heat pump
    """

    heat_pump_type: HeatPumpType
    thermal_capacity_kw: float = 8.0
    annual_heat_demand_kwh: float = 8000.0  # Typical UK home heating demand
    name: str = ""

    def __post_init__(self) -> None:
        """Read each number setting, then refuse a type outside HEAT_PUMP_TYPES."""
        read_field(self, "thermal_capacity_kw", as_finite_float, Interval(0, 50, low_open=True))
        read_field(self, "annual_heat_demand_kwh", as_finite_float, Interval(0, 50000, low_open=True))
        _refuse_unknown_heat_pump_type(self.heat_pump_type)

    @classmethod
    def default_ashp(cls) -> "HeatPumpConfig":
        """Create a typical UK domestic air source heat pump.

        Returns:
            HeatPumpConfig with the declared default capacity and annual demand
        """
        return cls(heat_pump_type="ASHP", name=f"{cls.thermal_capacity_kw:g} kW ASHP")

    @classmethod
    def default_gshp(cls) -> "HeatPumpConfig":
        """Create a typical UK domestic ground source heat pump.

        Returns:
            HeatPumpConfig with the declared default capacity and annual demand
        """
        return cls(heat_pump_type="GSHP", name=f"{cls.thermal_capacity_kw:g} kW GSHP")


def generate_heat_pump_load(
    config: HeatPumpConfig,
    temperature_c: pd.Series,
    *,
    annual_temperature_c: pd.Series,
) -> pd.Series:
    """Generate a heat pump's electrical load, in kW, over the rows of temperature_c.

    config.annual_heat_demand_kwh is shared out over the heating degree-hours
    of annual_temperature_c, a reference year of its own rows at any spacing
    that divides one day, such as the minute-interpolated TMY. Each row of
    temperature_c gets heat in proportion to its own heating degree-hours, so
    temperature_c may be at any cadence: a row's load in kW does not depend on
    how long the row lasts.
    So a window's load does not depend on the window's length, and a run over
    exactly the reference year delivers the whole annual demand wherever the
    capacity cap does not bind. Each row's heat is capped at
    config.thermal_capacity_kw, and its electrical load is that heat divided by
    the COP at the row's outdoor temperature. A reference year with no
    heating degree-hours has no heat to share out, so the load is zero.

    Args:
        config: Heat pump configuration (type, capacity, annual demand)
        temperature_c: Outdoor temperature in degrees Celsius, at any cadence,
            over the rows to generate the load for.
            Must have a DatetimeIndex with timezone info.
        annual_temperature_c: One year of outdoor temperature in degrees
            Celsius, on an evenly spaced DatetimeIndex whose spacing divides
            one day: 365 to 366 days of its rows.

    Returns:
        Series of electrical power demand in kW, named heat_pump_load_kw, with
        same index as temperature_c. Values are non-negative and capped at
        thermal_capacity_kw / COP.

    Raises:
        ValueError: If temperature_c doesn't have a DatetimeIndex
        ValueError: If temperature_c index is not timezone-aware
        ValueError: If SimulationWindow.of_index refuses annual_temperature_c's
            index, as it does one that is not a DatetimeIndex or not evenly spaced
        ValueError: If annual_temperature_c's spacing does not divide one day,
            or it is not 365 to 366 days of its rows

    Example:
        >>> config = HeatPumpConfig(heat_pump_type="ASHP", thermal_capacity_kw=8.0)
        >>> year = pd.Series(
        ...     10.0,
        ...     index=pd.date_range('2023-01-01', periods=525_600, freq='1min', tz='UTC'),
        ... )
        >>> load = generate_heat_pump_load(config, year.loc['2023-01-15'], annual_temperature_c=year)
        >>> len(load)
        1440
        >>> heat_delivered_kwh = SimulationWindow.of_index(load.index).energy_kwh(load) * calculate_cop("ASHP", 10.0)
        >>> round(heat_delivered_kwh, 2)  # one day's share of 8000 kWh: 8000 / 365
        21.92
    """
    # Validate input
    if not isinstance(temperature_c.index, pd.DatetimeIndex):
        raise ValueError("Temperature series must have a DatetimeIndex")
    if temperature_c.index.tz is None:
        raise ValueError("Temperature series index must be timezone-aware")

    reference_year = _reference_year_window(annual_temperature_c)

    annual_degree_rows = heating_degree_deficit_c(annual_temperature_c).sum()
    if annual_degree_rows == 0:
        electrical_load_kw = pd.Series(0.0, index=temperature_c.index)
    else:
        heat_kw_per_degree = config.annual_heat_demand_kwh / annual_degree_rows / reference_year.step_hours
        thermal_demand_kw = (
            heating_degree_deficit_c(temperature_c) * heat_kw_per_degree
        ).clip(upper=config.thermal_capacity_kw)

        cop_series = COP_CURVES[config.heat_pump_type].cops(temperature_c)

        # Calculate electrical load (thermal output / COP)
        electrical_load_kw = thermal_demand_kw / cop_series

    return electrical_load_kw.rename("heat_pump_load_kw")
