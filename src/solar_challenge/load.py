"""Load profile generation for domestic energy consumption."""

import random
from dataclasses import dataclass
from typing import Any, Optional, TYPE_CHECKING

import numpy as np
import pandas as pd

if TYPE_CHECKING:
    from solar_challenge.ev import EVConfig


# richardsonpy is a hard (non-optional) dependency since task #13.
# RICHARDSONPY_AVAILABLE is kept for backward compatibility but is always True
# after richardsonpy was promoted from the optional [stochastic] extra to
# [project].dependencies.  The Elexon profile remains as a *defensive* fallback
# for any richardsonpy runtime error — it is no longer the silent default when
# the extra is absent.
_richardsonpy_module: Any = None
try:
    import richardsonpy as _rpy
    _richardsonpy_module = _rpy
except ImportError:  # pragma: no cover — only hit in broken install environments
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
        use_stochastic: Use the windowed richardsonpy stochastic model (default True).
            richardsonpy is a hard dependency so this path is always available.
            Set False to force the deterministic Elexon Profile Class 1 shape.
        seed: Random seed for stochastic load generation (for reproducibility)
    """

    annual_consumption_kwh: Optional[float] = None
    household_occupants: int = 3  # Default UK average household size
    name: str = ""
    # use_stochastic: richardsonpy is a hard dep so True uses the windowed
    # stochastic path by default; False forces the deterministic Elexon path.
    use_stochastic: bool = True
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


def _simulate_stochastic_day(
    wrapper: Any,
    occupancy_day: "np.ndarray[tuple[int], np.dtype[np.int64]]",
    irradiance_day: "np.ndarray[tuple[int], np.dtype[np.float64]]",
    day_of_year: int,
    is_weekend: bool,
) -> "np.ndarray[tuple[int], np.dtype[np.float64]]":
    """Simulate one day of stochastic electric load via richardsonpy's per-day API.

    Calls ElectricityProfile.power_sim exactly once, returning the 1440-element
    (1-minute resolution) total-power array in Watts.

    Args:
        wrapper: richardsonpy ElectricityProfile instance
        occupancy_day: 144-element occupancy array (10-min resolution)
        irradiance_day: 1440-element irradiance array (1-min resolution, W/m²)
        day_of_year: 1-based day of year — used to determine the month for
            appliance activity statistics inside power_sim
        is_weekend: True if Saturday or Sunday

    Returns:
        1440-element array of total electric power in Watts
    """
    total_power, _light, _app = wrapper.power_sim(
        irradiation=irradiance_day,
        weekend=is_weekend,
        day=day_of_year,
        occupancy=occupancy_day,
    )
    return total_power  # type: ignore[no-any-return]


def _try_richardsonpy_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str,
) -> Optional[pd.Series]:
    """Generate a windowed stochastic load profile using richardsonpy's per-day API.

    Bypasses richardsonpy's full-year ElectricLoad (which always simulates 365
    days due to its irradiance-length assertion) and drives ElectricityProfile.
    power_sim directly.  Exactly one day is simulated per requested window day:
    a 1-day request runs 1 simulation cycle, a 7-day request runs 7 — not 365.

    Normalization is performed by scaling the raw stochastic shape to the same
    seasonal daily energy target used by the Elexon path:
    target_window_kwh = Σ_days (annual/365 × SEASONAL_FACTORS[month]).

    richardsonpy is now a hard dependency, so RICHARDSONPY_AVAILABLE is always
    True.  The Elexon path remains as a defensive fallback in case richardsonpy
    raises a runtime error (any exception → return None → Elexon fallback).

    Args:
        config: Load configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string

    Returns:
        Load profile Series if successful, None otherwise (triggers Elexon fallback)
    """
    try:
        import os
        from richardsonpy.classes.occupancy import Occupancy
        from richardsonpy.classes.appliance import Appliances
        from richardsonpy.classes.lighting import load_lighting_profile
        from richardsonpy.classes.stochastic_el_load_wrapper import ElectricityProfile
        import richardsonpy.classes.electric_load as _el_mod

        # Resolve paths to richardsonpy's bundled default input CSV files
        _src_path = os.path.dirname(os.path.dirname(_el_mod.__file__))
        _path_app = os.path.join(_src_path, "inputs", "Appliances.csv")
        _path_light = os.path.join(_src_path, "inputs", "LightBulbs.csv")

        # Set random seed for reproducibility if provided.
        # richardsonpy uses both numpy.random and Python's random module.
        if config.seed is not None:
            np.random.seed(config.seed)
            random.seed(config.seed)

        # Normalise dates (strip any intra-day time component)
        start_norm = start_date.normalize()
        end_norm = end_date.normalize()
        if start_norm.tz is None:
            start_norm = start_norm.tz_localize(timezone)
        if end_norm.tz is None:
            end_norm = end_norm.tz_localize(timezone)

        # Use calendar-date arithmetic, not timedelta.days, so that a DST
        # transition (spring-forward: only 23 h in the day → timedelta.days==0
        # for that span) does not cause an off-by-one.  E.g. Mar 30–Apr 1
        # across the UK spring-forward: abs delta = 47 h → timedelta.days=1
        # → int+1=2 (wrong); date subtraction gives 2 + 1 = 3 (correct).
        window_days = (end_norm.date() - start_norm.date()).days + 1

        # richardsonpy initial_day:  1=Monday … 5=Friday, 6=Saturday, 7=Sunday
        # pandas dayofweek:           0=Monday … 4=Friday, 5=Saturday, 6=Sunday
        start_weekday = int(start_norm.dayofweek) + 1  # convert to 1-7

        # Build windowed occupancy for ONLY the requested window (not 365 days)
        occupants = min(config.household_occupants, 5)  # richardsonpy cap is 5
        occ = Occupancy(
            number_occupants=occupants,
            initial_day=start_weekday,
            nb_days=window_days,
        )

        # Appliances calibrated to 91% of annual demand (lighting uses ~9%)
        # — consistent with ElectricLoad.calc_stoch_el_profile's split
        appliances_demand = 0.91 * config.get_annual_consumption()
        appliances = Appliances(_path_app, annual_consumption=appliances_demand)
        lights = load_lighting_profile(filename=_path_light, index=0)
        wrapper = ElectricityProfile(appliances, lights)

        # Simulate each day in the requested window — exactly one power_sim call
        # per window day.  Loop count == window_days (the key windowing invariant).
        _timesteps_per_day = 144  # occupancy at 10-min resolution: 86400/600

        all_days_power: list[np.ndarray] = []

        for i in range(window_days):  # exactly window_days iterations
            current_date = start_norm + pd.Timedelta(days=i)
            is_weekend = int(current_date.dayofweek) >= 5
            day_of_year = int(current_date.dayofyear)

            # 1-minute diurnal irradiance for lighting model (W/m²)
            # Simple sinusoidal daylight pattern: 6 am–8 pm, peak at 1 pm
            _hour = np.arange(1440) / 60.0
            irradiance_day: np.ndarray = np.where(
                (_hour >= 6.0) & (_hour <= 20.0),
                100.0 * np.maximum(0.0, np.sin((_hour - 6.0) * np.pi / 14.0)),
                0.0,
            )

            # 10-min occupancy for this day (144 values)
            occupancy_day = occ.occupancy[
                _timesteps_per_day * i : _timesteps_per_day * (i + 1)
            ]

            day_power_w = _simulate_stochastic_day(
                wrapper=wrapper,
                occupancy_day=occupancy_day,
                irradiance_day=irradiance_day,
                day_of_year=day_of_year,
                is_weekend=is_weekend,
            )
            all_days_power.append(day_power_w)

        # Concatenate all days and convert W → kW
        power_kw: np.ndarray = np.concatenate(all_days_power) / 1000.0

        # Build 1-minute DatetimeIndex for the requested window.
        # Reuse the Elexon DST trim/pad pattern so index length is consistent.
        minute_index = pd.date_range(
            start=start_norm,
            end=end_norm + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
            freq="1min",
            tz=timezone,
        )

        # Trim or extend to match index length (handles DST transitions)
        if len(power_kw) > len(minute_index):
            power_kw = power_kw[: len(minute_index)]
        elif len(power_kw) < len(minute_index):
            avg = power_kw[-1440:].mean() if len(power_kw) >= 1440 else power_kw.mean()
            padding = np.full(len(minute_index) - len(power_kw), avg)
            power_kw = np.concatenate([power_kw, padding])

        profile = pd.Series(power_kw, index=minute_index, name="demand_kw")

        # Scale to the seasonal daily energy target so stochastic energy is
        # consistent with the Elexon path.  target = Σ annual/365 × SEASONAL_FACTORS[month].
        # Do NOT use ElectricLoad's do_normalization — on a 1-day window it
        # would force the full annual demand (~3400 kWh) into a single day.
        annual_kwh = config.get_annual_consumption()
        target_window_kwh = sum(
            annual_kwh / 365.0
            * SEASONAL_FACTORS.get(
                int((start_norm + pd.Timedelta(days=j)).month), 1.0
            )
            for j in range(window_days)
        )
        raw_kwh = calculate_annual_consumption(profile)
        if raw_kwh > 0.0:
            profile = profile * (target_window_kwh / raw_kwh)

        profile.name = "demand_kw"
        return profile

    except Exception:
        # Defensive fallback: any richardsonpy runtime error → Elexon profile
        return None


def generate_load_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
    ev_config: "Optional[EVConfig]" = None,
) -> pd.Series:
    """Generate domestic load profile.

    Uses the windowed richardsonpy stochastic model when config.use_stochastic
    is True (the default).  richardsonpy is a hard dependency so this path is
    always available.  Falls back to the deterministic Elexon Profile Class 1
    shape only when use_stochastic=False, or defensively if richardsonpy raises
    a runtime error.

    Creates a 1-minute resolution load profile for the specified date range,
    scaled to match the configured annual consumption using seasonal factors.

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
