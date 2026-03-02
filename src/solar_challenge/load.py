"""Load profile generation for domestic energy consumption."""

import random
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from solar_challenge.ev import EVConfig


# Try to import richardsonpy for stochastic load profiles
# Use Any type since module may not be available
_richardsonpy_module: Any = None
try:
    import richardsonpy as _rpy  # type: ignore[import-untyped]
    _richardsonpy_module = _rpy
except ImportError:
    pass
RICHARDSONPY_AVAILABLE: bool = _richardsonpy_module is not None


# Ofgem Typical Domestic Consumption Values (TDCV) by household size
# Values in kWh/year for electricity (excluding electric heating)
OFGEM_TDCV_BY_OCCUPANTS: dict[int, float] = {
    1: 1800.0,   # Single occupant
    2: 2700.0,   # 2 people
    3: 3200.0,   # 3 people (close to "medium" TDCV of 2900)
    4: 3900.0,   # 4 people
    5: 4500.0,   # 5+ people (extrapolated)
}


@dataclass(frozen=True)
class LoadConfig:
    """Configuration for household load profile.

    Attributes:
        annual_consumption_kwh: Target annual electricity consumption in kWh.
            If not specified and household_occupants is set, derived from Ofgem TDCV.
        household_occupants: Number of household occupants (1-5+).
            Affects consumption and profile shape.
        name: Optional identifier for the load profile
        use_stochastic: Use richardsonpy stochastic model if available
        seed: Random seed for stochastic load generation (for reproducibility)
    """

    annual_consumption_kwh: Optional[float] = None
    household_occupants: int = 3  # Default UK average household size
    name: str = ""
    use_stochastic: bool = True  # Prefer stochastic model if available
    seed: Optional[int] = None  # Seed for reproducible stochastic profiles

    def __post_init__(self) -> None:
        """Validate load configuration parameters."""
        # Validate household_occupants
        if self.household_occupants < 1:
            raise ValueError(
                f"Household occupants must be at least 1, got {self.household_occupants}"
            )
        if self.household_occupants > 10:
            raise ValueError(
                f"Household occupants seems unrealistic: {self.household_occupants}"
            )

        # Validate annual_consumption if provided
        if self.annual_consumption_kwh is not None and self.annual_consumption_kwh <= 0:
            raise ValueError(
                f"Annual consumption must be positive, got {self.annual_consumption_kwh} kWh"
            )

    def get_annual_consumption(self) -> float:
        """Get annual consumption, deriving from occupants if not explicitly set.

        Returns:
            Annual consumption in kWh
        """
        if self.annual_consumption_kwh is not None:
            return self.annual_consumption_kwh

        # Derive from Ofgem TDCV based on household size
        occupants = min(self.household_occupants, 5)  # Cap at 5 for lookup
        base_consumption = OFGEM_TDCV_BY_OCCUPANTS[occupants]

        # For households larger than 5, add 400 kWh per additional person
        if self.household_occupants > 5:
            extra_people = self.household_occupants - 5
            base_consumption += extra_people * 400.0

        return base_consumption


# Elexon Profile Class 1 (Domestic Unrestricted) typical shape
# Simplified as 48 half-hourly values representing relative demand
# Values normalized so sum = 1.0 for one day
# Based on typical UK domestic unrestricted profile shape
ELEXON_PROFILE_CLASS_1: list[float] = [
    # 00:00-05:30 (overnight low)
    0.012, 0.011, 0.010, 0.010, 0.009, 0.009, 0.009, 0.009, 0.010, 0.010, 0.012, 0.014,
    # 06:00-11:30 (morning rise and plateau)
    0.018, 0.024, 0.030, 0.034, 0.036, 0.035, 0.032, 0.030, 0.028, 0.026, 0.024, 0.023,
    # 12:00-17:30 (afternoon)
    0.022, 0.021, 0.021, 0.021, 0.022, 0.024, 0.028, 0.032, 0.036, 0.040, 0.044, 0.046,
    # 18:00-23:30 (evening peak and decline)
    0.046, 0.044, 0.040, 0.036, 0.032, 0.028, 0.024, 0.020, 0.017, 0.015, 0.014, 0.013,
]


# Seasonal scaling factors (higher in winter, lower in summer)
# Based on UK domestic consumption patterns
SEASONAL_FACTORS: dict[int, float] = {
    1: 1.25,   # January
    2: 1.20,   # February
    3: 1.10,   # March
    4: 0.95,   # April
    5: 0.85,   # May
    6: 0.80,   # June
    7: 0.75,   # July
    8: 0.75,   # August
    9: 0.85,   # September
    10: 0.95,  # October
    11: 1.10,  # November
    12: 1.20,  # December
}


def _normalize_profile(profile: list[float]) -> "np.ndarray[tuple[int], np.dtype[np.float64]]":
    """Normalize profile so it sums to 1.0."""
    arr: np.ndarray[tuple[int], np.dtype[np.float64]] = np.array(profile, dtype=np.float64)
    result: np.ndarray[tuple[int], np.dtype[np.float64]] = arr / arr.sum()
    return result


def _get_daily_profile_kwh(
    date: pd.Timestamp,
    annual_consumption_kwh: float,
) -> np.ndarray:
    """Get daily load profile in kWh for a specific date.

    Args:
        date: Date for the profile
        annual_consumption_kwh: Target annual consumption

    Returns:
        Array of 48 half-hourly energy values in kWh
    """
    # Base daily consumption (uniform across year)
    base_daily = annual_consumption_kwh / 365.0

    # Apply seasonal factor
    month = date.month
    seasonal_factor = SEASONAL_FACTORS.get(month, 1.0)

    # Scale base profile to get daily consumption
    daily_consumption = base_daily * seasonal_factor
    normalized_profile = _normalize_profile(ELEXON_PROFILE_CLASS_1)

    # Energy per half-hour period in kWh
    half_hourly_kwh = normalized_profile * daily_consumption

    return half_hourly_kwh


def _interpolate_half_hourly_to_minute(
    half_hourly_kwh: np.ndarray,
) -> np.ndarray:
    """Interpolate half-hourly energy to 1-minute power.

    Converts half-hourly energy (kWh) to 1-minute power (kW).
    Each half-hour's energy is divided equally across 30 minutes.

    Args:
        half_hourly_kwh: 48 half-hourly energy values in kWh

    Returns:
        1440 minute-by-minute power values in kW
    """
    # Each half-hour value becomes 30 identical minute values
    # Energy (kWh) per half hour = Power (kW) * 0.5 hours
    # So Power (kW) = Energy (kWh) / 0.5 = Energy (kWh) * 2
    minute_power = np.repeat(half_hourly_kwh * 2, 30)
    return minute_power


def _try_richardsonpy_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str,
) -> Optional[pd.Series]:
    """Try to generate profile using richardsonpy.

    Uses richardsonpy's stochastic occupancy and appliance models to generate
    realistic domestic load profiles with appliance-level variability.

    Note: richardsonpy requires full-year irradiance data for validation,
    so we always simulate 365 days and slice to the requested period.

    Args:
        config: Load configuration
        start_date: Start of simulation period
        end_date: End of simulation period
        timezone: IANA timezone string

    Returns:
        Load profile Series if successful, None otherwise
    """
    if not RICHARDSONPY_AVAILABLE or _richardsonpy_module is None:
        return None

    try:
        from richardsonpy.classes.occupancy import Occupancy  # type: ignore[import-untyped]
        from richardsonpy.classes.electric_load import ElectricLoad  # type: ignore[import-untyped]

        # Set random seed for reproducibility if provided
        # richardsonpy uses both numpy and Python's random module
        if config.seed is not None:
            np.random.seed(config.seed)
            random.seed(config.seed)

        timestep_seconds = 600  # richardsonpy uses 10-minute resolution
        timesteps_per_day = 86400 // timestep_seconds  # 144

        # richardsonpy requires full-year irradiance data (validates against 365/366 days)
        # So we always simulate a full year starting from Jan 1 and slice later
        full_year_days = 365
        n_timesteps_year = full_year_days * timesteps_per_day  # 52560

        # Determine initial_day (1-365) from start_date for seasonal alignment
        initial_day = start_date.dayofyear

        # Generate stochastic occupancy profile for full year
        occ = Occupancy(
            number_occupants=config.household_occupants,
            initial_day=1,  # Always start from day 1 for full year
            nb_days=full_year_days,
        )

        # Create synthetic radiation for lighting model (simple diurnal pattern)
        # This affects lighting load timing but not total consumption (normalized)
        q_direct = np.zeros(n_timesteps_year)
        q_diffuse = np.zeros(n_timesteps_year)

        # Simple daylight pattern: diffuse radiation during daylight hours
        for day in range(full_year_days):
            for step in range(timesteps_per_day):
                hour = (step * timestep_seconds) / 3600
                # Approximate daylight: 6am-8pm with peak at noon
                if 6 <= hour <= 20:
                    # Sinusoidal pattern peaking at 1pm (hour 13)
                    diffuse = 100 * max(0, np.sin((hour - 6) * np.pi / 14))
                    q_diffuse[day * timesteps_per_day + step] = diffuse

        # Generate stochastic electric load profile
        el = ElectricLoad(
            occ_profile=occ.occupancy,
            total_nb_occ=config.household_occupants,
            q_direct=q_direct,
            q_diffuse=q_diffuse,
            annual_demand=config.get_annual_consumption(),
            timestep=timestep_seconds,
            do_normalization=True,  # Scale to target annual consumption
        )

        # loadcurve is in Watts at 10-minute resolution for full year
        load_10min_w = el.loadcurve

        # Create 10-minute index for full year (using a reference year)
        # We'll use the year from start_date for the reference
        year = start_date.year
        full_year_start = pd.Timestamp(f"{year}-01-01", tz=timezone)
        index_10min = pd.date_range(
            start=full_year_start,
            periods=len(load_10min_w),
            freq="10min",
            tz=timezone,
        )

        # Convert to kW
        load_10min_kw = pd.Series(load_10min_w / 1000.0, index=index_10min)

        # Create 1-minute index for the requested period
        minute_index = pd.date_range(
            start=start_date,
            end=end_date + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
            freq="1min",
            tz=timezone,
        )

        # First expand full year to 1-minute resolution
        full_year_1min_index = pd.date_range(
            start=full_year_start,
            periods=len(load_10min_w) * 10,
            freq="1min",
            tz=timezone,
        )
        load_1min_full = load_10min_kw.reindex(full_year_1min_index, method="ffill")
        load_1min_full = load_1min_full.ffill().bfill()

        # Slice to requested period
        load_1min_kw = load_1min_full.reindex(minute_index)
        load_1min_kw = load_1min_kw.ffill().bfill()  # Handle any edge NaNs
        load_1min_kw.name = "demand_kw"

        return load_1min_kw

    except Exception:
        # Fall back to Elexon profile if richardsonpy fails
        return None


def generate_load_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
    ev_config: "Optional[EVConfig]" = None,
) -> pd.Series:
    """Generate domestic load profile.

    Attempts to use richardsonpy for stochastic profiles if available and
    configured. Falls back to Elexon Profile Class 1 shape otherwise.

    Creates a 1-minute resolution load profile for the specified date range,
    scaled to match the configured annual consumption.

    If an EV configuration is provided, EV charging load is added to the
    household base load.

    Args:
        config: Load configuration with consumption and household parameters
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string for output index
        ev_config: Optional EV configuration for charging load

    Returns:
        Series with 1-minute DatetimeIndex and power values in kW
    """
    # Try richardsonpy first if enabled
    if config.use_stochastic:
        result = _try_richardsonpy_profile(config, start_date, end_date, timezone)
        if result is not None:
            base_load = result
        else:
            # Fall back to Elexon Profile Class 1
            base_load = _generate_elexon_profile(config, start_date, end_date, timezone)
    else:
        # Fall back to Elexon Profile Class 1
        base_load = _generate_elexon_profile(config, start_date, end_date, timezone)

    # Add EV charging if configured
    if ev_config is not None:
        from solar_challenge.ev import generate_ev_charging_profile

        ev_load = generate_ev_charging_profile(
            ev_config, start_date, end_date, timezone
        )

        # Combine household and EV load
        # Align the profiles in case of any index mismatch
        combined_load = base_load.add(ev_load, fill_value=0.0)
        combined_load.name = "demand_kw"
        return combined_load

    return base_load


def _generate_elexon_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
) -> pd.Series:
    """Generate domestic load profile using Elexon Profile Class 1 shape.

    Creates a 1-minute resolution load profile for the specified date range,
    scaled to match the configured annual consumption.

    Args:
        config: Load configuration with annual consumption target
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string for output index

    Returns:
        Series with 1-minute DatetimeIndex and power values in kW
    """
    # Get annual consumption from config (may be derived from occupants)
    annual_consumption = config.get_annual_consumption()

    # Ensure dates are timezone-aware
    if start_date.tz is None:
        start_date = start_date.tz_localize(timezone)
    if end_date.tz is None:
        end_date = end_date.tz_localize(timezone)

    # Create minute-by-minute index
    minute_index = pd.date_range(
        start=start_date,
        end=end_date + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
        freq="1min",
        tz=timezone,
    )

    # Generate profile for each day
    all_power: list[np.ndarray] = []
    current_date = start_date.normalize()

    while current_date <= end_date:
        daily_kwh = _get_daily_profile_kwh(current_date, annual_consumption)
        minute_power = _interpolate_half_hourly_to_minute(daily_kwh)
        all_power.append(minute_power)
        current_date += pd.Timedelta(days=1)

    # Concatenate all days
    power_values = np.concatenate(all_power)

    # Trim or extend to match index length (handle DST transitions)
    if len(power_values) > len(minute_index):
        power_values = power_values[: len(minute_index)]
    elif len(power_values) < len(minute_index):
        # Extend with last day's average
        avg = power_values[-1440:].mean() if len(power_values) >= 1440 else power_values.mean()
        padding = np.full(len(minute_index) - len(power_values), avg)
        power_values = np.concatenate([power_values, padding])

    return pd.Series(power_values, index=minute_index, name="demand_kw")


def calculate_annual_consumption(profile: pd.Series) -> float:
    """Calculate total annual consumption from a load profile.

    Args:
        profile: Power series in kW with 1-minute resolution

    Returns:
        Total consumption in kWh
    """
    # Power (kW) * time (1 minute = 1/60 hour) = Energy (kWh)
    return float(profile.sum() / 60.0)


def scale_profile_to_annual(
    profile: pd.Series,
    target_annual_kwh: float,
) -> pd.Series:
    """Scale a load profile to match a target annual consumption.

    Args:
        profile: Power series in kW
        target_annual_kwh: Target annual consumption in kWh

    Returns:
        Scaled power series in kW
    """
    current_annual = calculate_annual_consumption(profile)
    if current_annual == 0:
        raise ValueError("Cannot scale profile with zero consumption")

    scale_factor = target_annual_kwh / current_annual
    return profile * scale_factor
