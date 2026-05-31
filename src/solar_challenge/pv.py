# SPDX-License-Identifier: AGPL-3.0-or-later
"""PV system configuration and modelling."""

import warnings
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

import pandas as pd
import pvlib
from pvlib.location import Location as PVLibLocation
from pvlib.modelchain import ModelChain
from pvlib.pvsystem import Array, FixedMount, PVSystem

if TYPE_CHECKING:
    from solar_challenge.location import Location


@dataclass(frozen=True)
class PVConfig:
    """Configuration for a photovoltaic system.

    Attributes:
        capacity_kw: Rated DC capacity in kilowatts
        azimuth: Panel orientation in degrees (0=North, 90=East, 180=South, 270=West)
        tilt: Panel tilt angle from horizontal in degrees (0=flat, 90=vertical)
        name: Optional identifier for the system

        # Panel parameters (PV-004)
        module_efficiency: Panel efficiency as fraction (default 0.20 = 20%)
        temperature_coefficient: Power temp coefficient per °C (default -0.004 = -0.4%/°C)
        custom_module_params: Optional custom pvlib module parameters dict

        # Inverter parameters (PV-005)
        inverter_efficiency: Inverter efficiency as fraction (default 0.96 = 96%)
        inverter_capacity_kw: AC capacity in kW (default = DC capacity)
        custom_inverter_params: Optional custom pvlib inverter parameters dict
    """

    capacity_kw: float
    azimuth: float = 180.0  # South-facing default (UK optimal)
    tilt: float = 35.0  # Optimal for UK latitude
    name: str = ""

    # Panel parameters (PV-004)
    module_efficiency: float = 0.20  # 20% efficiency
    temperature_coefficient: float = -0.004  # -0.4%/°C
    custom_module_params: Optional[dict[str, float]] = None

    # Inverter parameters (PV-005)
    inverter_efficiency: float = 0.96  # 96% efficiency
    inverter_capacity_kw: Optional[float] = None  # Defaults to DC capacity
    custom_inverter_params: Optional[dict[str, float]] = None

    def __post_init__(self) -> None:
        """Validate PV configuration parameters."""
        if self.capacity_kw <= 0:
            raise ValueError(f"Capacity must be positive, got {self.capacity_kw} kW")
        if not 0 <= self.azimuth <= 360:
            raise ValueError(f"Azimuth must be 0-360 degrees, got {self.azimuth}")
        if not 0 <= self.tilt <= 90:
            raise ValueError(f"Tilt must be 0-90 degrees, got {self.tilt}")
        if not 0 < self.module_efficiency <= 1:
            raise ValueError(
                f"Module efficiency must be (0, 1], got {self.module_efficiency}"
            )
        if not -1 < self.temperature_coefficient < 0:
            raise ValueError(
                f"Temperature coefficient must be (-1, 0), got {self.temperature_coefficient}"
            )
        if not 0 < self.inverter_efficiency <= 1:
            raise ValueError(
                f"Inverter efficiency must be (0, 1], got {self.inverter_efficiency}"
            )
        if self.inverter_capacity_kw is not None and self.inverter_capacity_kw <= 0:
            raise ValueError(
                f"Inverter capacity must be positive, got {self.inverter_capacity_kw} kW"
            )

    @property
    def effective_inverter_capacity_kw(self) -> float:
        """Get effective inverter capacity (defaults to DC capacity)."""
        return self.inverter_capacity_kw if self.inverter_capacity_kw is not None else self.capacity_kw

    @classmethod
    def default_4kw(cls) -> "PVConfig":
        """Create a typical UK domestic 4 kW system.

        Returns:
            PVConfig with 4 kW, south-facing, 35° tilt
        """
        return cls(
            capacity_kw=4.0,
            azimuth=180.0,
            tilt=35.0,
            name="4 kW domestic system"
        )


def _get_cec_module() -> dict[str, float]:
    """Get a representative CEC module for simulation.

    Returns a ~400W module representative of modern panels.
    """
    # Use Canadian Solar CS6K-400MS as representative modern module
    # Parameters for a ~400W module with ~20% efficiency
    module_params = pvlib.pvsystem.retrieve_sam("CECMod")

    # Find a suitable module around 400W
    # Canadian_Solar_Inc__CS6K_400MS or similar
    target_modules = [
        col for col in module_params.columns
        if "Canadian_Solar" in col and "400" in col
    ]

    if target_modules:
        return dict(module_params[target_modules[0]])

    # Fallback: find any module around 380-420W
    for col in module_params.columns:
        params = module_params[col]
        if 380 < params.get("STC", 0) < 420:
            return dict(params)

    # Last resort: use first available module
    return dict(module_params.iloc[:, 0])


def create_simple_module_params(
    efficiency: float = 0.20,
    temperature_coefficient: float = -0.004,
    module_power_w: float = 400.0,
) -> dict[str, float]:
    """Create simplified module parameters from basic specifications.

    Uses the PVWatts model which only requires efficiency and temp coefficient.
    This allows users to specify custom panel characteristics without
    needing the full CEC parameter set.

    Args:
        efficiency: Module efficiency as fraction (e.g., 0.20 for 20%)
        temperature_coefficient: Power temperature coefficient per °C
            (e.g., -0.004 for -0.4%/°C)
        module_power_w: Nominal module power in watts (for reference)

    Returns:
        Dict of module parameters compatible with pvlib PVWatts model

    Example:
        >>> params = create_simple_module_params(efficiency=0.22, temperature_coefficient=-0.003)
        >>> params['pdc0']  # Nominal power at STC
        1000.0
    """
    # PVWatts model parameters
    # pdc0 is the nominal DC power at STC (1000 W/m² irradiance)
    # gamma_pdc is the temperature coefficient (negative)
    return {
        "pdc0": 1000.0,  # Normalized to 1 kW for easy scaling
        "gamma_pdc": temperature_coefficient,
        # Store efficiency for reference (used in array sizing)
        "efficiency": efficiency,
        "STC": module_power_w,  # For compatibility with existing code
    }


def create_simple_inverter_params(
    efficiency: float = 0.96,
    capacity_w: float = 4000.0,
) -> dict[str, float]:
    """Create simplified inverter parameters from basic specifications.

    Uses a simple efficiency model. When DC power exceeds inverter
    capacity, output is clipped to the rated capacity.

    Args:
        efficiency: Inverter efficiency as fraction (e.g., 0.96 for 96%)
        capacity_w: AC power capacity in watts

    Returns:
        Dict of inverter parameters for a simple efficiency model

    Example:
        >>> params = create_simple_inverter_params(efficiency=0.97, capacity_w=5000)
        >>> params['Paco']
        5000.0
    """
    # Simple inverter model: efficiency-based with capacity limit
    # Paco is the AC power output rating (used for clipping)
    return {
        "Paco": capacity_w,  # AC power capacity (watts)
        "Pdco": capacity_w / efficiency,  # DC power at which Paco is reached
        "Vdco": 400.0,  # Nominal DC voltage (typical)
        "Pso": 0.0,  # Self-consumption (watts)
        "C0": -0.0,  # Coefficient for Paco formula
        "C1": 0.0,  # Coefficient for Pso formula
        "C2": 0.0,  # Coefficient for Co formula
        "C3": 0.0,  # Coefficient for C1 formula
        "Pnt": 0.0,  # Night tare loss (watts)
        "efficiency": efficiency,  # Store for reference
    }


def _get_cec_inverter(capacity_kw: float) -> dict[str, float]:
    """Get a CEC inverter sized for the given system capacity.

    Args:
        capacity_kw: Target AC capacity in kW

    Returns:
        Inverter parameters from CEC database
    """
    inverter_params = pvlib.pvsystem.retrieve_sam("CECInverter")
    target_watts = capacity_kw * 1000

    # Find inverter closest to target capacity
    best_match = None
    best_diff = float("inf")

    for col in inverter_params.columns:
        params = inverter_params[col]
        paco = params.get("Paco", 0)  # AC power output rating
        if paco > 0:
            diff = abs(paco - target_watts)
            if diff < best_diff:
                best_diff = diff
                best_match = col

    if best_match:
        return dict(inverter_params[best_match])

    # Fallback: return first inverter
    return dict(inverter_params.iloc[:, 0])


def create_pv_system(config: PVConfig) -> PVSystem:
    """Create a pvlib PVSystem from configuration.

    Creates a PVSystem with an Array configured using CEC module and inverter
    databases for realistic modelling parameters, or custom parameters if provided.

    Args:
        config: PV system configuration with capacity, azimuth, tilt, and
            optional custom module/inverter parameters

    Returns:
        pvlib PVSystem ready for use in ModelChain simulation

    Example:
        >>> config = PVConfig(capacity_kw=4.0, azimuth=180, tilt=35)
        >>> system = create_pv_system(config)
        >>> system.arrays[0].mount.surface_tilt
        35.0
    """
    # Get module parameters (custom or CEC database)
    if config.custom_module_params is not None:
        module_params = config.custom_module_params
    else:
        # Get CEC module and optionally modify with config's efficiency/temp coeff
        module_params = _get_cec_module()
        # Update temperature coefficient if different from typical CEC value
        if config.temperature_coefficient != -0.004:
            module_params["gamma_pdc"] = config.temperature_coefficient

    # Get inverter parameters (custom or CEC database)
    inverter_capacity_kw = config.effective_inverter_capacity_kw
    if config.custom_inverter_params is not None:
        inverter_params = config.custom_inverter_params
    else:
        # Get CEC inverter sized for configured capacity
        inverter_params = _get_cec_inverter(inverter_capacity_kw)
        # Apply efficiency scaling if different from typical
        if config.inverter_efficiency != 0.96:
            # Scale Paco based on efficiency difference
            if "Paco" in inverter_params:
                # Adjust Pdco to achieve target efficiency
                inverter_params["Pdco"] = inverter_params["Paco"] / config.inverter_efficiency

    # Calculate number of modules needed for target capacity
    module_power = module_params.get("STC", 400)  # Watts at STC
    target_power = config.capacity_kw * 1000  # Convert to watts
    modules_per_string = max(1, round(target_power / module_power))

    # Create mount with configuration's orientation
    mount = FixedMount(
        surface_tilt=config.tilt,
        surface_azimuth=config.azimuth
    )

    # Create array with module parameters
    array = Array(
        mount=mount,
        module_parameters=module_params,
        modules_per_string=modules_per_string,
        strings=1,
        temperature_model_parameters=pvlib.temperature.TEMPERATURE_MODEL_PARAMETERS[
            "sapm"
        ]["open_rack_glass_glass"],
    )

    # Create PVSystem with array and inverter
    system = PVSystem(
        arrays=[array],
        inverter_parameters=inverter_params,
    )

    return system


def create_model_chain(
    config: PVConfig,
    location: "Location",
) -> ModelChain:
    """Create a pvlib ModelChain for AC power simulation.

    Args:
        config: PV system configuration
        location: Geographic location for solar position calculations

    Returns:
        ModelChain ready to run simulations with weather data
    """
    pv_system = create_pv_system(config)

    # Convert our Location to pvlib Location
    pvlib_location = PVLibLocation(
        latitude=location.latitude,
        longitude=location.longitude,
        tz=location.timezone,
        altitude=location.altitude,
        name=location.name,
    )

    # Create ModelChain with appropriate models
    model_chain = ModelChain(
        system=pv_system,
        location=pvlib_location,
        aoi_model="physical",
        spectral_model="no_loss",
    )

    return model_chain


def simulate_pv_output(
    config: PVConfig,
    location: "Location",
    weather_data: pd.DataFrame,
) -> pd.Series:
    """Run PV simulation and return AC power output.

    Args:
        config: PV system configuration
        location: Geographic location
        weather_data: DataFrame with ghi, dni, dhi, temp_air, wind_speed columns

    Returns:
        Series of AC power output in kW with same index as weather_data
    """
    model_chain = create_model_chain(config, location)

    # Run the simulation
    # Suppress scipy warnings from pvlib's single-diode model solver
    # (edge cases at night/low irradiance trigger harmless divide-by-zero warnings)
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered",
            category=RuntimeWarning,
            module=r"scipy\.optimize\._chandrupatla",
        )
        model_chain.run_model(weather_data)

    # Get AC power and convert from W to kW
    ac_power = model_chain.results.ac / 1000.0

    # Ensure no negative values (numerical noise)
    ac_power = ac_power.clip(lower=0.0)

    return ac_power


def calculate_degradation_factor(
    system_age_years: float,
    degradation_rate_per_year: float = 0.005,
) -> float:
    """Calculate PV degradation factor based on system age.

    PV panels degrade over time, typically losing ~0.5% of their
    rated capacity per year. This function calculates the remaining
    capacity as a fraction of original.

    Args:
        system_age_years: Age of the PV system in years (can be fractional)
        degradation_rate_per_year: Annual degradation rate as decimal
            (default 0.005 = 0.5%/year)

    Returns:
        Degradation factor as fraction of original capacity (0 to 1)
        Year 0: 1.0 (100%)
        Year 1: 0.995 (99.5%)
        Year 10: 0.95 (95%)

    Raises:
        ValueError: If system_age_years is negative or rate is invalid

    Example:
        >>> calculate_degradation_factor(0)
        1.0
        >>> calculate_degradation_factor(10, 0.005)
        0.95
    """
    if system_age_years < 0:
        raise ValueError(f"System age must be non-negative, got {system_age_years}")
    if not 0 <= degradation_rate_per_year <= 1:
        raise ValueError(
            f"Degradation rate must be 0-1, got {degradation_rate_per_year}"
        )

    # Linear degradation: factor = 1 - (age * rate)
    factor = 1.0 - (system_age_years * degradation_rate_per_year)

    # Clamp to minimum of 0 (can't have negative generation)
    return max(0.0, factor)


def apply_degradation(
    generation: pd.Series,
    system_age_years: float,
    degradation_rate_per_year: float = 0.005,
) -> pd.Series:
    """Apply degradation factor to PV generation time series.

    Args:
        generation: PV generation time series in kW
        system_age_years: Age of the PV system in years
        degradation_rate_per_year: Annual degradation rate as decimal
            (default 0.005 = 0.5%/year)

    Returns:
        Degraded generation series (same index, reduced values)

    Example:
        >>> import pandas as pd
        >>> gen = pd.Series([1.0, 2.0, 3.0])
        >>> degraded = apply_degradation(gen, system_age_years=10)
        >>> (degraded == gen * 0.95).all()
        True
    """
    factor = calculate_degradation_factor(system_age_years, degradation_rate_per_year)
    return generation * factor


def interpolate_to_minute_resolution(
    hourly_power: pd.Series,
) -> pd.Series:
    """Interpolate hourly power to 1-minute resolution preserving energy.

    Divides each hourly energy total into 60 equal 1-minute values.
    This simple approach preserves total energy while providing
    high-resolution data for battery simulation.

    Args:
        hourly_power: Power series with hourly frequency (kW)

    Returns:
        Power series with 1-minute frequency (kW)
        Same values within each hour, preserving energy totals.
    """
    # Create 1-minute index
    start = hourly_power.index[0]
    end = hourly_power.index[-1] + pd.Timedelta(hours=1) - pd.Timedelta(minutes=1)

    minute_index = pd.date_range(
        start=start,
        end=end,
        freq="1min",
        tz=hourly_power.index.tz if hasattr(hourly_power.index, "tz") else None,
    )

    # Forward-fill to expand hourly values to minutes
    # This gives same power (kW) for each minute, preserving energy
    minute_power = hourly_power.reindex(minute_index, method="ffill")

    # Handle any remaining NaN at the end
    minute_power = minute_power.ffill()

    return minute_power
