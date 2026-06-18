# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration file support for simulation scenarios.

Supports loading configurations from YAML and JSON files,
scenario definitions, and parameter sweep functionality.
"""

import json
import random
import warnings
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator, Literal, Optional, Union, cast

import pandas as pd

# Import yaml with fallback
try:
    import yaml
    YAML_AVAILABLE = True
except ImportError:
    yaml = None
    YAML_AVAILABLE = False

from solar_challenge.battery import BatteryConfig
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.ev import EVConfig
from solar_challenge.fleet import FleetConfig, FleetResults, simulate_fleet
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEG_PRESETS
from solar_challenge.tariff import TariffConfig, TariffPeriod


class ConfigurationError(Exception):
    """Raised when configuration file is invalid."""

    pass


#: Dispatch strategy names recognised by the simulation engine.
#: Used to validate fleet_distribution.dispatch_strategy in YAML configs.
_VALID_DISPATCH_STRATEGIES: frozenset[str] = frozenset({"greedy", "tou_optimized"})


# --- Distribution Types for Fleet Generation ---


@dataclass(frozen=True)
class WeightedDiscreteDistribution:
    """Weighted discrete distribution for sampling from a list of values.

    Weights are auto-normalized (e.g., [2,4,3,1] == [20,40,30,10]).

    Attributes:
        values: List of values to sample from (can include None)
        weights: Corresponding weights (must be non-negative, sum > 0)
    """

    values: tuple[Optional[float], ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(self.weights):
            raise ConfigurationError(
                "WeightedDiscreteDistribution: values and weights must have same length"
            )
        if any(w < 0 for w in self.weights):
            raise ConfigurationError(
                "WeightedDiscreteDistribution: weights cannot be negative"
            )
        if sum(self.weights) == 0:
            raise ConfigurationError(
                "WeightedDiscreteDistribution: weights cannot all be zero"
            )


@dataclass(frozen=True)
class NormalDistribution:
    """Normal (Gaussian) distribution with optional bounds.

    Attributes:
        mean: Mean of the distribution
        std: Standard deviation
        min: Optional minimum bound (values are clamped)
        max: Optional maximum bound (values are clamped)
    """

    mean: float
    std: float
    min: Optional[float] = None
    max: Optional[float] = None

    def __post_init__(self) -> None:
        if self.std < 0:
            raise ConfigurationError("NormalDistribution: std cannot be negative")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ConfigurationError("NormalDistribution: min cannot be greater than max")


@dataclass(frozen=True)
class UniformDistribution:
    """Uniform distribution between min and max.

    Attributes:
        min: Minimum value (inclusive)
        max: Maximum value (inclusive)
    """

    min: float
    max: float

    def __post_init__(self) -> None:
        if self.min > self.max:
            raise ConfigurationError("UniformDistribution: min cannot be greater than max")


@dataclass(frozen=True)
class ShuffledPoolDistribution:
    """Shuffled pool distribution for exact count assignment.

    Creates a pool of values with exact counts, shuffles once, and assigns
    sequentially. This matches the behavior of pre-generating distributions
    then shuffling (like bristol-phase1).

    Attributes:
        values: List of values (can include None)
        counts: Number of each value in the pool (must sum to n_homes)
    """

    values: tuple[Optional[float], ...]
    counts: tuple[int, ...]

    def __post_init__(self) -> None:
        if len(self.values) != len(self.counts):
            raise ConfigurationError(
                "ShuffledPoolDistribution: values and counts must have same length"
            )
        if any(c < 0 for c in self.counts):
            raise ConfigurationError(
                "ShuffledPoolDistribution: counts cannot be negative"
            )
        if sum(self.counts) == 0:
            raise ConfigurationError(
                "ShuffledPoolDistribution: counts cannot all be zero"
            )

    def create_pool(self) -> list[Optional[float]]:
        """Create the expanded pool of values."""
        pool: list[Optional[float]] = []
        for value, count in zip(self.values, self.counts):
            pool.extend([value] * count)
        return pool


@dataclass(frozen=True)
class SweepSpec:
    """Sweep specification for parameter exploration.

    Attributes:
        min: Minimum value
        max: Maximum value
        steps: Number of steps
        mode: "geometric" or "linear" (default: geometric)
    """

    min: float
    max: float
    steps: int
    mode: str = "geometric"

    def __post_init__(self) -> None:
        if self.min <= 0 and self.mode == "geometric":
            raise ConfigurationError(
                "SweepSpec: geometric mode requires min > 0"
            )
        if self.max <= self.min:
            raise ConfigurationError(
                "SweepSpec: max must be greater than min"
            )
        if self.steps < 2:
            raise ConfigurationError(
                "SweepSpec: steps must be at least 2"
            )
        if self.mode not in ("geometric", "linear"):
            raise ConfigurationError(
                f"SweepSpec: mode must be 'geometric' or 'linear', got '{self.mode}'"
            )

    def get_values(self) -> list[float]:
        """Generate the sweep values."""
        if self.mode == "geometric":
            ratio = (self.max / self.min) ** (1 / (self.steps - 1))
            return [self.min * (ratio ** i) for i in range(self.steps)]
        else:
            step = (self.max - self.min) / (self.steps - 1)
            return [self.min + step * i for i in range(self.steps)]


@dataclass(frozen=True)
class ProportionalDistribution:
    """Distribution proportional to another sampled field.

    Used for making one parameter proportional to another, e.g.,
    battery capacity = multiplier * PV capacity.

    Attributes:
        source: Source field path (e.g., "pv.capacity_kw")
        multiplier: Multiplication factor (float or SweepSpec)
        offset: Additive offset (default 0.0)
    """

    source: str
    multiplier: Union[float, SweepSpec] = 1.0
    offset: float = 0.0


# Type alias for distribution specifications
DistributionSpec = Union[
    WeightedDiscreteDistribution,
    NormalDistribution,
    UniformDistribution,
    ShuffledPoolDistribution,
    ProportionalDistribution,
    float,
    None,
]


@dataclass
class PVDistributionConfig:
    """Distribution configuration for PV parameters.

    Attributes:
        capacity_kw: Distribution for PV capacity (required)
        azimuth: Distribution for azimuth angle (default: 180)
        tilt: Distribution for tilt angle (default: 35)
        module_efficiency: Distribution for module efficiency (default: 0.20)
        inverter_efficiency: Distribution for inverter efficiency (default: 0.96)
        system_age_years: Distribution for system age in years (default: 0.0)
        degradation_rate_per_year: Distribution for annual degradation rate (default: 0.005)
    """

    capacity_kw: DistributionSpec
    azimuth: DistributionSpec = 180.0
    tilt: DistributionSpec = 35.0
    module_efficiency: DistributionSpec = 0.20
    inverter_efficiency: DistributionSpec = 0.96
    system_age_years: DistributionSpec = 0.0
    degradation_rate_per_year: DistributionSpec = 0.005


@dataclass
class BatteryDistributionConfig:
    """Distribution configuration for battery parameters.

    Values can include None to represent homes without batteries.

    Attributes:
        capacity_kwh: Distribution for battery capacity (can include None)
        max_charge_kw: Distribution for max charge rate (default: 2.5)
        max_discharge_kw: Distribution for max discharge rate (default: 2.5)
    """

    capacity_kwh: DistributionSpec
    max_charge_kw: DistributionSpec = 2.5
    max_discharge_kw: DistributionSpec = 2.5


@dataclass
class LoadDistributionConfig:
    """Distribution configuration for load parameters.

    Attributes:
        annual_consumption_kwh: Distribution for annual consumption (optional)
        household_occupants: Distribution for occupants (default: 3)
        use_stochastic: Whether to use stochastic load profiles (default: True)
    """

    annual_consumption_kwh: DistributionSpec = None
    household_occupants: DistributionSpec = 3
    use_stochastic: bool = True


@dataclass
class HeatPumpDistributionConfig:
    """Distribution configuration for heat pump parameters.

    Values can include None to represent homes without heat pumps.

    Attributes:
        heat_pump_type: Heat pump type ('ASHP' or 'GSHP'), distribution spec, or None for no heat pump
        thermal_capacity_kw: Distribution for thermal capacity (default: 8.0)
        annual_heat_demand_kwh: Distribution for annual heating demand (default: 8000.0)
    """

    heat_pump_type: Union[str, DistributionSpec, None] = None
    thermal_capacity_kw: DistributionSpec = 8.0
    annual_heat_demand_kwh: DistributionSpec = 8000.0


@dataclass
class EVDistributionConfig:
    """Distribution configuration for EV charging parameters.

    Values can include None to represent homes without EVs.

    Attributes:
        charger_type: Distribution for EV charger type (can include None)
        arrival_hour: Distribution for EV arrival hour (0-23), or fixed value
        departure_hour: Distribution for EV departure hour (0-23), default 7am
        required_charge_kwh: Distribution for daily charging requirement, default 35kWh
        smart_charging_mode: Smart charging mode (none, solar, off_peak), default "none"
    """

    charger_type: DistributionSpec
    arrival_hour: DistributionSpec = 18.0
    departure_hour: DistributionSpec = 7.0
    required_charge_kwh: DistributionSpec = 35.0
    smart_charging_mode: str = "none"


@dataclass
class DispatchStrategyConfig:
    """Configuration for battery dispatch strategy.

    Attributes:
        strategy_type: Type of dispatch strategy (self_consumption, tou_optimized, peak_shaving)
        peak_hours: List of (start_hour, end_hour) tuples for TOU strategy (optional)
        import_limit_kw: Grid import limit in kW for peak-shaving strategy (optional)
    """

    strategy_type: str
    peak_hours: Optional[list[tuple[int, int]]] = None
    import_limit_kw: Optional[float] = None

    def __post_init__(self) -> None:
        """Validate dispatch strategy configuration."""
        valid_strategies = ("self_consumption", "tou_optimized", "peak_shaving")
        if self.strategy_type not in valid_strategies:
            raise ConfigurationError(
                f"Invalid strategy_type '{self.strategy_type}'. "
                f"Must be one of: {', '.join(valid_strategies)}"
            )

        # Validate TOU strategy parameters
        if self.strategy_type == "tou_optimized":
            if not self.peak_hours:
                raise ConfigurationError(
                    "tou_optimized strategy requires 'peak_hours' parameter"
                )
            for start_hour, end_hour in self.peak_hours:
                if not (0 <= start_hour < 24 and 0 <= end_hour <= 24):
                    raise ConfigurationError(
                        f"Invalid peak hours ({start_hour}, {end_hour}). "
                        "Hours must be in range [0, 24)"
                    )
                if start_hour >= end_hour:
                    raise ConfigurationError(
                        f"Invalid peak hours ({start_hour}, {end_hour}). "
                        "start_hour must be less than end_hour"
                    )

        # Validate peak-shaving strategy parameters
        if self.strategy_type == "peak_shaving":
            if self.import_limit_kw is None:
                raise ConfigurationError(
                    "peak_shaving strategy requires 'import_limit_kw' parameter"
                )
            if self.import_limit_kw <= 0:
                raise ConfigurationError(
                    f"import_limit_kw must be positive, got {self.import_limit_kw}"
                )


@dataclass(frozen=True)
class GridChargeConfig:
    """Configuration for grid-charging (battery arbitrage) mode.

    Attributes:
        target_soc_fraction: Target state-of-charge to reach via grid charging,
            expressed as a fraction of usable capacity (0 < x <= 1). Defaults to 0.9.
    """

    target_soc_fraction: float = 0.9

    def __post_init__(self) -> None:
        """Validate grid-charge configuration."""
        if not (0 < self.target_soc_fraction <= 1):
            raise ConfigurationError(
                f"target_soc_fraction must be in (0, 1], got {self.target_soc_fraction}"
            )


@dataclass
class FleetDistributionConfig:
    """Configuration for generating a fleet from distributions.

    Attributes:
        n_homes: Number of homes to generate
        pv: PV distribution configuration
        load: Load distribution configuration
        battery: Battery distribution configuration (optional)
        heat_pump: Heat pump distribution configuration (optional)
        ev: EV distribution configuration (optional)
        seed: Random seed for reproducibility (optional)
        random_order: Order of random operations ("default" or "bristol_legacy")
            - "default": Shuffle pools first, then sample normal distributions per home
            - "bristol_legacy": Sample all normal distributions first, then shuffle pools
              (matches exact behavior of create_bristol_phase1_scenario)
    """

    n_homes: int
    pv: PVDistributionConfig
    load: LoadDistributionConfig
    battery: Optional[BatteryDistributionConfig] = None
    heat_pump: Optional[HeatPumpDistributionConfig] = None
    ev: Optional[EVDistributionConfig] = None
    seed: Optional[int] = None
    random_order: str = "default"

    def __post_init__(self) -> None:
        if self.n_homes < 1:
            raise ConfigurationError("FleetDistributionConfig: n_homes must be at least 1")
        if self.random_order not in ("default", "bristol_legacy"):
            raise ConfigurationError(
                f"FleetDistributionConfig: random_order must be 'default' or 'bristol_legacy', "
                f"got '{self.random_order}'"
            )


@dataclass
class SimulationPeriod:
    """Defines the time period for a simulation.

    Attributes:
        start_date: Start date as string (YYYY-MM-DD) or Timestamp
        end_date: End date as string (YYYY-MM-DD) or Timestamp
    """

    start_date: Union[str, pd.Timestamp]
    end_date: Union[str, pd.Timestamp]

    def get_start_timestamp(self, timezone: str = "Europe/London") -> pd.Timestamp:
        """Get start date as Timestamp."""
        if isinstance(self.start_date, pd.Timestamp):
            return self.start_date
        ts = pd.Timestamp(self.start_date)
        if ts.tz is None:
            ts = ts.tz_localize(timezone)
        return ts

    def get_end_timestamp(self, timezone: str = "Europe/London") -> pd.Timestamp:
        """Get end date as Timestamp."""
        if isinstance(self.end_date, pd.Timestamp):
            return self.end_date
        ts = pd.Timestamp(self.end_date)
        if ts.tz is None:
            ts = ts.tz_localize(timezone)
        return ts


@dataclass
class OutputConfig:
    """Configuration for simulation output.

    Attributes:
        csv_path: Path to save CSV results (optional)
        include_minute_data: Include 1-minute resolution data in output
        include_summary: Include summary statistics
        aggregation: Aggregation level for output (minute, daily, monthly, annual)
    """

    csv_path: Optional[str] = None
    include_minute_data: bool = True
    include_summary: bool = True
    aggregation: str = "minute"


@dataclass(frozen=True)
class FinanceConfig:
    """Financial parameters for community PV/battery project appraisal.

    Holds investor-spreadsheet defaults (§3.1 of the financial-layer PRD)
    used to compute project NPV, payback period, and per-home savings.
    All monetary values are in nominal GBP or pence; rates are fractional.

    Attributes:
        standing_charge_pence_per_day: Retail grid standing charge (required).
        vat_rate: VAT fraction applied to retail electricity (default 0.05).
        retail_baseline_rate_pence_per_kwh: Grid import unit rate before project
            (default 23.0 p/kWh).
        self_consumption_override: Optional fixed self-consumption fraction
            (0, 1]; if None the simulator uses the modelled value.
        pv_cost_per_kwp_gbp: PV hardware + install cost per kWp (default 1000.0).
        roof_fit_cost_gbp: Fixed per-home roof-fitting cost (default 1000.0).
        battery_cost_per_kwh_gbp: Battery hardware cost per kWh (default 250.0).
        inverter_cost_per_kw_gbp: Inverter capex cost per kW of effective (AC) inverter
            capacity (default 0.0; 0 permitted).
        grant_gbp: Total grant received by the project (default 250000.0; 0 allowed).
        equity_fraction: Fraction of project cost financed by equity (default 0.75).
        loan_term_years: Loan repayment term in years (default 15).
        loan_rate: Annual loan interest rate as a fraction (default 0.07).
        opex_per_home_per_year_gbp: Annual operating cost per home (default 131.0).
        asset_life_years: Useful life of the asset in years (default 25).
        own_use_rate_pence_per_kwh: CBS transfer price for self-consumed CBS-owned solar
            (default 15.0 p/kWh; 0 permitted).
        retained_cash_floor_per_home_per_year_gbp: Board-set minimum retained CBS
            surplus per home per year in GBP (default 27.0; 0 permitted).
        grid_services_income_per_kw_per_year_gbp: Exogenous DFS/DNO grid-services income
            per kW of installed battery discharge power per year, net of aggregator share
            (default 0.0; W1 cross-PRD seam — W1-delta fills the value cross-batch).
        grid_services_model: Grid-services pricing model selector.  ``"flat"`` uses
            the legacy flat per-kW rate (``grid_services_income_per_kw_per_year_gbp``);
            ``"capacity_at_events"`` uses the structured events-based model configured
            via ``grid_services_events``.  Default ``"flat"`` leaves all existing
            behaviour bit-unchanged.
        grid_services_events: Optional :class:`~solar_challenge.gridservices.GridServicesEventsConfig`
            used when ``grid_services_model == "capacity_at_events"``.  May be ``None``
            even for that model (α only validates the selector field; γ/δ consume it).
    """

    standing_charge_pence_per_day: float
    vat_rate: float = 0.05
    retail_baseline_rate_pence_per_kwh: float = 23.0
    self_consumption_override: Optional[float] = None
    pv_cost_per_kwp_gbp: float = 1000.0
    roof_fit_cost_gbp: float = 1000.0
    battery_cost_per_kwh_gbp: float = 250.0
    inverter_cost_per_kw_gbp: float = 0.0
    grant_gbp: float = 250000.0
    equity_fraction: float = 0.75
    loan_term_years: int = 15
    loan_rate: float = 0.07
    opex_per_home_per_year_gbp: float = 131.0
    asset_life_years: int = 25
    own_use_rate_pence_per_kwh: float = 15.0
    retained_cash_floor_per_home_per_year_gbp: float = 27.0
    grid_services_income_per_kw_per_year_gbp: float = 0.0
    grid_services_model: str = "flat"
    grid_services_events: Optional[GridServicesEventsConfig] = None

    def __post_init__(self) -> None:
        """Validate financial parameters, raising ConfigurationError on violation."""
        if not (0.0 <= self.vat_rate <= 1.0):
            raise ConfigurationError(
                f"vat_rate must be in [0, 1], got {self.vat_rate}"
            )
        if not (0.0 <= self.equity_fraction <= 1.0):
            raise ConfigurationError(
                f"equity_fraction must be in [0, 1], got {self.equity_fraction}"
            )
        if self.self_consumption_override is not None:
            if not (0.0 < self.self_consumption_override <= 1.0):
                raise ConfigurationError(
                    "self_consumption_override must be in (0, 1] when set, "
                    f"got {self.self_consumption_override}"
                )
        if self.loan_term_years <= 0:
            raise ConfigurationError(
                f"loan_term_years must be > 0, got {self.loan_term_years}"
            )
        if self.loan_rate < 0.0:
            raise ConfigurationError(
                f"loan_rate must be >= 0, got {self.loan_rate}"
            )
        if self.asset_life_years < self.loan_term_years:
            raise ConfigurationError(
                f"asset_life_years ({self.asset_life_years}) must be >= "
                f"loan_term_years ({self.loan_term_years})"
            )
        # Cost/rate fields must be strictly positive
        _positive_fields = {
            "standing_charge_pence_per_day": self.standing_charge_pence_per_day,
            "retail_baseline_rate_pence_per_kwh": self.retail_baseline_rate_pence_per_kwh,
            "pv_cost_per_kwp_gbp": self.pv_cost_per_kwp_gbp,
            "roof_fit_cost_gbp": self.roof_fit_cost_gbp,
            "battery_cost_per_kwh_gbp": self.battery_cost_per_kwh_gbp,
            "opex_per_home_per_year_gbp": self.opex_per_home_per_year_gbp,
        }
        for field_name, value in _positive_fields.items():
            if value <= 0.0:
                raise ConfigurationError(
                    f"{field_name} must be > 0, got {value}"
                )
        # Grant may be zero but not negative
        if self.grant_gbp < 0.0:
            raise ConfigurationError(
                f"grant_gbp must be >= 0, got {self.grant_gbp}"
            )
        # Inverter cost may be zero (opt-in default) but not negative
        if self.inverter_cost_per_kw_gbp < 0.0:
            raise ConfigurationError(
                f"inverter_cost_per_kw_gbp must be >= 0, got {self.inverter_cost_per_kw_gbp}"
            )
        # Cost-recovery fields: zero allowed, negative rejected
        if self.own_use_rate_pence_per_kwh < 0.0:
            raise ConfigurationError(
                f"own_use_rate_pence_per_kwh must be >= 0, got {self.own_use_rate_pence_per_kwh}"
            )
        if self.retained_cash_floor_per_home_per_year_gbp < 0.0:
            raise ConfigurationError(
                "retained_cash_floor_per_home_per_year_gbp must be >= 0, "
                f"got {self.retained_cash_floor_per_home_per_year_gbp}"
            )
        if self.grid_services_income_per_kw_per_year_gbp < 0.0:
            raise ConfigurationError(
                "grid_services_income_per_kw_per_year_gbp must be >= 0, "
                f"got {self.grid_services_income_per_kw_per_year_gbp}"
            )
        _VALID_GS_MODELS = frozenset({"flat", "capacity_at_events"})
        if self.grid_services_model not in _VALID_GS_MODELS:
            raise ConfigurationError(
                f"grid_services_model must be one of {sorted(_VALID_GS_MODELS)}, "
                f"got '{self.grid_services_model}'"
            )


@dataclass
class ScenarioConfig:
    """Configuration for a simulation scenario.

    Attributes:
        name: Scenario identifier
        description: Human-readable description
        location: Geographic location (defaults to Bristol)
        period: Simulation period
        homes: List of home configurations (for fleet simulation)
        home: Single home configuration (for single-home simulation)
        output: Output preferences
        seg_tariff_pence_per_kwh: Smart Export Guarantee rate in pence/kWh (optional)
        tariff_config: Tariff configuration (None for no cost tracking)
        finance: Financial appraisal parameters (None for no financial analysis)
    """

    name: str
    period: SimulationPeriod
    description: str = ""
    location: Optional[Location] = None
    homes: list[HomeConfig] = field(default_factory=list)
    home: Optional[HomeConfig] = None
    output: Optional[OutputConfig] = None
    seg_tariff_pence_per_kwh: Optional[float] = None
    tariff_config: Optional[TariffConfig] = None
    finance: Optional[FinanceConfig] = None

    def __post_init__(self) -> None:
        """Validate scenario configuration."""
        if not self.homes and self.home is None:
            raise ConfigurationError(
                f"Scenario '{self.name}' must define either 'home' or 'homes'"
            )
        if self.homes and self.home is not None:
            raise ConfigurationError(
                f"Scenario '{self.name}' cannot define both 'home' and 'homes'"
            )

    @property
    def is_fleet(self) -> bool:
        """Whether this is a fleet simulation."""
        return len(self.homes) > 1 or (len(self.homes) == 1 and self.home is None)

    def get_location(self) -> Location:
        """Get location, defaulting to Bristol."""
        return self.location if self.location is not None else Location.bristol()


@dataclass
class ParameterSweepConfig:
    """Configuration for parameter sweep analysis.

    Attributes:
        parameter_name: Name of parameter to sweep (e.g., "battery_capacity_kwh")
        values: Explicit list of values to test
        min_value: Minimum value for range generation
        max_value: Maximum value for range generation
        step: Step size for range generation
        n_steps: Number of steps (alternative to step)
    """

    parameter_name: str
    values: Optional[list[float]] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    step: Optional[float] = None
    n_steps: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate sweep configuration."""
        if self.values is not None:
            if len(self.values) == 0:
                raise ConfigurationError("Parameter sweep values list cannot be empty")
            return

        if self.min_value is None or self.max_value is None:
            raise ConfigurationError(
                "Parameter sweep requires either 'values' list or 'min_value' and 'max_value'"
            )
        if self.min_value >= self.max_value:
            raise ConfigurationError(
                f"min_value ({self.min_value}) must be less than max_value ({self.max_value})"
            )
        if self.step is None and self.n_steps is None:
            raise ConfigurationError(
                "Parameter sweep requires either 'step' or 'n_steps'"
            )

    def get_values(self) -> list[float]:
        """Get list of parameter values to sweep."""
        if self.values is not None:
            return self.values

        if self.min_value is None or self.max_value is None:
            raise ConfigurationError("Range parameters not configured")

        if self.step is not None:
            values: list[float] = []
            current = self.min_value
            while current <= self.max_value:
                values.append(current)
                current += self.step
            return values
        elif self.n_steps is not None:
            step = (self.max_value - self.min_value) / self.n_steps
            return [self.min_value + i * step for i in range(self.n_steps + 1)]
        else:
            return [self.min_value, self.max_value]


@dataclass
class SweepResult:
    """Result from a single parameter sweep iteration.

    Attributes:
        parameter_value: The parameter value used
        results: Simulation results (SimulationResults or FleetResults)
    """

    parameter_value: float
    results: Union[SimulationResults, FleetResults]


def _parse_location(data: dict[str, Any]) -> Location:
    """Parse location from config data."""
    return Location(
        latitude=data.get("latitude", 51.45),
        longitude=data.get("longitude", -2.58),
        timezone=data.get("timezone", "Europe/London"),
        altitude=data.get("altitude", 11.0),
        name=data.get("name", ""),
    )


def _parse_pv_config(data: dict[str, Any]) -> PVConfig:
    """Parse PV configuration from config data."""
    return PVConfig(
        capacity_kw=data.get("capacity_kw", 4.0),
        azimuth=data.get("azimuth", 180.0),
        tilt=data.get("tilt", 35.0),
        name=data.get("name", ""),
        module_efficiency=data.get("module_efficiency", 0.20),
        temperature_coefficient=data.get("temperature_coefficient", -0.004),
        inverter_efficiency=data.get("inverter_efficiency", 0.96),
        inverter_capacity_kw=data.get("inverter_capacity_kw"),
        system_age_years=data.get("system_age_years", 0.0),
        degradation_rate_per_year=data.get("degradation_rate_per_year", 0.005),
    )


def _parse_grid_charge_config(data: Optional[dict[str, Any]]) -> Optional[GridChargeConfig]:
    """Parse grid-charging configuration from a dict or None.

    Args:
        data: grid_charging mapping (e.g. ``{'target_soc_fraction': 0.9}``) or None.

    Returns:
        GridChargeConfig if data is a non-None mapping, else None.

    Raises:
        ConfigurationError: If data is present but not a mapping.
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"grid_charging must be a mapping, got {type(data).__name__}"
        )
    return GridChargeConfig(target_soc_fraction=data.get("target_soc_fraction", 0.9))


def _parse_battery_config(data: Optional[dict[str, Any]]) -> Optional[BatteryConfig]:
    """Parse battery configuration from config data."""
    if data is None:
        return None

    # Parse dispatch strategy if present
    dispatch_strategy = None
    if "dispatch_strategy" in data:
        dispatch_strategy = _parse_dispatch_strategy_config(data["dispatch_strategy"])

    # Parse grid-charging config if present
    grid_charging = _parse_grid_charge_config(data.get("grid_charging"))

    return BatteryConfig(
        capacity_kwh=data.get("capacity_kwh", 5.0),
        max_charge_kw=data.get("max_charge_kw", 2.5),
        max_discharge_kw=data.get("max_discharge_kw", 2.5),
        name=data.get("name", ""),
        dispatch_strategy=dispatch_strategy,
        grid_charging=grid_charging,
        min_soc_fraction=data.get("min_soc_fraction", 0.1),
        max_soc_fraction=data.get("max_soc_fraction", 0.9),
        charge_efficiency=data.get("charge_efficiency", 0.975),
        discharge_efficiency=data.get("discharge_efficiency", 0.975),
        efficiency=data.get("efficiency"),
        system_age_years=data.get("system_age_years", 0.0),
        calendar_fade_rate_per_year=data.get("calendar_fade_rate_per_year", 0.02),
        cycle_fade_per_equivalent_full_cycle=data.get(
            "cycle_fade_per_equivalent_full_cycle", 5e-5
        ),
        soh_floor=data.get("soh_floor", 0.5),
        soh=data.get("soh"),
    )


def _parse_load_config(data: dict[str, Any]) -> LoadConfig:
    """Parse load configuration from config data."""
    return LoadConfig(
        annual_consumption_kwh=data.get("annual_consumption_kwh"),
        household_occupants=data.get("household_occupants", 3),
        name=data.get("name", ""),
        use_stochastic=data.get("use_stochastic", True),
        seed=data.get("seed"),
    )


def _parse_dispatch_strategy_config(
    data: Optional[dict[str, Any]]
) -> Optional[DispatchStrategyConfig]:
    """Parse dispatch strategy configuration from config data."""
    if data is None:
        return None

    strategy_type = data.get("strategy_type")
    if not strategy_type:
        raise ConfigurationError("Dispatch strategy config requires 'strategy_type'")

    # Parse peak_hours if present (convert from list of lists to list of tuples)
    peak_hours = None
    if "peak_hours" in data:
        peak_hours_raw = data["peak_hours"]
        if peak_hours_raw is not None:
            peak_hours = [tuple(hours) for hours in peak_hours_raw]

    return DispatchStrategyConfig(
        strategy_type=strategy_type,
        peak_hours=peak_hours,
        import_limit_kw=data.get("import_limit_kw"),
    )


def _parse_tariff_config(data: Optional[dict[str, Any]]) -> Optional[TariffConfig]:
    """Parse tariff configuration from config data.

    Supports preset tariffs (flat_rate, economy_7, economy_10) and custom
    tariff definitions with explicit periods.

    Args:
        data: Tariff configuration dictionary or None

    Returns:
        TariffConfig object or None if data is None

    Raises:
        ConfigurationError: If tariff specification is invalid
    """
    if data is None:
        return None

    tariff_type = data.get("type")
    if tariff_type is None:
        raise ConfigurationError("Tariff configuration requires 'type' field")

    if tariff_type == "flat_rate":
        rate = data.get("rate_per_kwh")
        if rate is None:
            raise ConfigurationError("flat_rate tariff requires 'rate_per_kwh' field")
        return TariffConfig.flat_rate(
            rate_per_kwh=float(rate),
            name=data.get("name", "")
        )

    elif tariff_type == "economy_7":
        kwargs: dict[str, Any] = {}
        if "off_peak_rate" in data:
            kwargs["off_peak_rate"] = float(data["off_peak_rate"])
        if "peak_rate" in data:
            kwargs["peak_rate"] = float(data["peak_rate"])
        if "off_peak_start" in data:
            kwargs["off_peak_start"] = data["off_peak_start"]
        if "off_peak_end" in data:
            kwargs["off_peak_end"] = data["off_peak_end"]
        return TariffConfig.economy_7(**kwargs)

    elif tariff_type == "economy_10":
        kwargs = {}
        if "off_peak_rate" in data:
            kwargs["off_peak_rate"] = float(data["off_peak_rate"])
        if "peak_rate" in data:
            kwargs["peak_rate"] = float(data["peak_rate"])
        if "night_start" in data:
            kwargs["night_start"] = data["night_start"]
        if "night_end" in data:
            kwargs["night_end"] = data["night_end"]
        if "afternoon_start" in data:
            kwargs["afternoon_start"] = data["afternoon_start"]
        if "afternoon_end" in data:
            kwargs["afternoon_end"] = data["afternoon_end"]
        if "evening_start" in data:
            kwargs["evening_start"] = data["evening_start"]
        if "evening_end" in data:
            kwargs["evening_end"] = data["evening_end"]
        return TariffConfig.economy_10(**kwargs)

    elif tariff_type == "custom":
        if "periods" not in data:
            raise ConfigurationError("custom tariff requires 'periods' field")

        periods_data = data["periods"]
        if not periods_data:
            raise ConfigurationError("custom tariff must have at least one period")

        periods = []
        for period_data in periods_data:
            if "start_time" not in period_data:
                raise ConfigurationError("Tariff period requires 'start_time' field")
            if "end_time" not in period_data:
                raise ConfigurationError("Tariff period requires 'end_time' field")
            if "rate_per_kwh" not in period_data:
                raise ConfigurationError("Tariff period requires 'rate_per_kwh' field")

            periods.append(
                TariffPeriod(
                    start_time=period_data["start_time"],
                    end_time=period_data["end_time"],
                    rate_per_kwh=float(period_data["rate_per_kwh"]),
                    name=period_data.get("name", "")
                )
            )

        return TariffConfig(
            periods=tuple(periods),
            name=data.get("name", "")
        )

    else:
        raise ConfigurationError(
            f"Unknown tariff type '{tariff_type}'. "
            "Supported types: flat_rate, economy_7, economy_10, custom"
        )


def _parse_heat_pump_config(data: Optional[dict[str, Any]]) -> Optional[HeatPumpConfig]:
    """Parse heat pump configuration from config data.

    Args:
        data: Dict with heat_pump_type, thermal_capacity_kw, and optional fields,
              or None.

    Returns:
        HeatPumpConfig or None if data is None.

    Raises:
        ConfigurationError: If a required field is missing.
    """
    if data is None:
        return None
    if "heat_pump_type" not in data:
        raise ConfigurationError(
            "heat_pump configuration requires 'heat_pump_type' field"
        )
    if "thermal_capacity_kw" not in data:
        raise ConfigurationError(
            "heat_pump configuration requires 'thermal_capacity_kw' field"
        )
    return HeatPumpConfig(
        heat_pump_type=data["heat_pump_type"],
        thermal_capacity_kw=float(data["thermal_capacity_kw"]),
        annual_heat_demand_kwh=float(data.get("annual_heat_demand_kwh", 8000.0)),
        name=data.get("name", ""),
    )


def _parse_ev_config(data: Optional[dict[str, Any]]) -> Optional[EVConfig]:
    """Parse EV configuration from config data.

    Args:
        data: Dict with charger_type, arrival_hour, and optional fields, or None.

    Returns:
        EVConfig or None if data is None.

    Raises:
        ConfigurationError: If a required field is missing.
    """
    if data is None:
        return None
    if "charger_type" not in data:
        raise ConfigurationError(
            "ev configuration requires 'charger_type' field"
        )
    if "arrival_hour" not in data:
        raise ConfigurationError(
            "ev configuration requires 'arrival_hour' field"
        )
    return EVConfig(
        charger_type=str(data["charger_type"]),
        arrival_hour=int(data["arrival_hour"]),
        departure_hour=int(data.get("departure_hour", 7)),
        required_charge_kwh=float(data.get("required_charge_kwh", 35.0)),
        smart_charging_mode=str(data.get("smart_charging_mode", "none")),
        name=str(data.get("name", "")),
    )


def _parse_home_config(data: dict[str, Any], location: Location) -> HomeConfig:
    """Parse home configuration from config data."""
    pv_data = data.get("pv", {})
    battery_data = data.get("battery")
    load_data = data.get("load", {})
    tariff_data = data.get("tariff")
    dispatch_strategy = data.get("dispatch_strategy", "greedy")

    return HomeConfig(
        pv_config=_parse_pv_config(pv_data),
        battery_config=_parse_battery_config(battery_data),
        load_config=_parse_load_config(load_data),
        location=location,
        name=data.get("name", ""),
        tariff_config=_parse_tariff_config(tariff_data),
        dispatch_strategy=dispatch_strategy,
        heat_pump_config=_parse_heat_pump_config(data.get("heat_pump")),
        ev_config=_parse_ev_config(data.get("ev")),
    )


def _parse_period(data: dict[str, Any]) -> SimulationPeriod:
    """Parse simulation period from config data."""
    if "start_date" not in data or "end_date" not in data:
        raise ConfigurationError("Simulation period requires 'start_date' and 'end_date'")
    return SimulationPeriod(
        start_date=data["start_date"],
        end_date=data["end_date"],
    )


def _parse_output_config(data: Optional[dict[str, Any]]) -> Optional[OutputConfig]:
    """Parse output configuration from config data."""
    if data is None:
        return None
    return OutputConfig(
        csv_path=data.get("csv_path"),
        include_minute_data=data.get("include_minute_data", True),
        include_summary=data.get("include_summary", True),
        aggregation=data.get("aggregation", "minute"),
    )


# --- Distribution Parsing and Sampling ---


def _parse_distribution_spec(data: Any, param_name: str) -> DistributionSpec:
    """Parse a distribution specification from config data.

    Args:
        data: Raw data (scalar, None, or distribution dict)
        param_name: Parameter name for error messages

    Returns:
        DistributionSpec (distribution object, scalar, or None)

    Raises:
        ConfigurationError: If distribution specification is invalid
    """
    # Handle None and scalars
    if data is None:
        return None
    if isinstance(data, (int, float)):
        return float(data)

    # Must be a dict with type key
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"Invalid distribution spec for '{param_name}': expected number, null, or dict"
        )

    dist_type = data.get("type")
    if dist_type is None:
        raise ConfigurationError(
            f"Distribution for '{param_name}' requires 'type' field"
        )

    if dist_type == "weighted_discrete":
        if "values" not in data or "weights" not in data:
            raise ConfigurationError(
                f"weighted_discrete distribution for '{param_name}' requires 'values' and 'weights'"
            )
        values = tuple(v if v is not None else None for v in data["values"])
        weights = tuple(float(w) for w in data["weights"])
        return WeightedDiscreteDistribution(values=values, weights=weights)

    elif dist_type == "normal":
        if "mean" not in data or "std" not in data:
            raise ConfigurationError(
                f"normal distribution for '{param_name}' requires 'mean' and 'std'"
            )
        return NormalDistribution(
            mean=float(data["mean"]),
            std=float(data["std"]),
            min=float(data["min"]) if data.get("min") is not None else None,
            max=float(data["max"]) if data.get("max") is not None else None,
        )

    elif dist_type == "uniform":
        if "min" not in data or "max" not in data:
            raise ConfigurationError(
                f"uniform distribution for '{param_name}' requires 'min' and 'max'"
            )
        return UniformDistribution(min=float(data["min"]), max=float(data["max"]))

    elif dist_type == "fixed":
        if "value" not in data:
            raise ConfigurationError(
                f"fixed distribution for '{param_name}' requires 'value'"
            )
        value = data["value"]
        if value is None:
            return None
        return float(value)

    elif dist_type == "shuffled_pool":
        if "values" not in data or "counts" not in data:
            raise ConfigurationError(
                f"shuffled_pool distribution for '{param_name}' requires 'values' and 'counts'"
            )
        values = tuple(v if v is not None else None for v in data["values"])
        counts = tuple(int(c) for c in data["counts"])
        return ShuffledPoolDistribution(values=values, counts=counts)

    elif dist_type == "proportional_to":
        if "source" not in data:
            raise ConfigurationError(
                f"proportional_to distribution for '{param_name}' requires 'source'"
            )
        multiplier_data = data.get("multiplier", 1.0)
        multiplier: Union[float, SweepSpec]
        if isinstance(multiplier_data, dict):
            # Parse sweep spec for multiplier
            if multiplier_data.get("type") != "sweep":
                raise ConfigurationError(
                    f"proportional_to multiplier dict for '{param_name}' must have type='sweep'"
                )
            multiplier = SweepSpec(
                min=float(multiplier_data["min"]),
                max=float(multiplier_data["max"]),
                steps=int(multiplier_data["steps"]),
                mode=multiplier_data.get("mode", "geometric"),
            )
        else:
            multiplier = float(multiplier_data)
        return ProportionalDistribution(
            source=data["source"],
            multiplier=multiplier,
            offset=float(data.get("offset", 0.0)),
        )

    else:
        raise ConfigurationError(
            f"Unknown distribution type '{dist_type}' for '{param_name}'. "
            "Supported: weighted_discrete, normal, uniform, fixed, shuffled_pool, proportional_to"
        )


def _sample_from_distribution(spec: DistributionSpec, rng: random.Random) -> Optional[float]:
    """Sample a single value from a distribution specification.

    Args:
        spec: Distribution specification
        rng: Random number generator

    Returns:
        Sampled value (float or None)
    """
    if spec is None:
        return None
    if isinstance(spec, (int, float)):
        return float(spec)

    if isinstance(spec, WeightedDiscreteDistribution):
        return rng.choices(list(spec.values), weights=list(spec.weights), k=1)[0]

    if isinstance(spec, NormalDistribution):
        value = rng.gauss(spec.mean, spec.std)
        if spec.min is not None:
            value = max(spec.min, value)
        if spec.max is not None:
            value = min(spec.max, value)
        return value

    if isinstance(spec, UniformDistribution):
        return rng.uniform(spec.min, spec.max)

    # Should not reach here
    raise ConfigurationError(f"Unknown distribution type: {type(spec)}")


def _parse_pv_distribution_config(data: dict[str, Any]) -> PVDistributionConfig:
    """Parse PV distribution configuration from config data."""
    if "capacity_kw" not in data:
        raise ConfigurationError("PV distribution config requires 'capacity_kw'")

    return PVDistributionConfig(
        capacity_kw=_parse_distribution_spec(data["capacity_kw"], "pv.capacity_kw"),
        azimuth=_parse_distribution_spec(data.get("azimuth", 180.0), "pv.azimuth"),
        tilt=_parse_distribution_spec(data.get("tilt", 35.0), "pv.tilt"),
        module_efficiency=_parse_distribution_spec(
            data.get("module_efficiency", 0.20), "pv.module_efficiency"
        ),
        inverter_efficiency=_parse_distribution_spec(
            data.get("inverter_efficiency", 0.96), "pv.inverter_efficiency"
        ),
        system_age_years=_parse_distribution_spec(
            data.get("system_age_years", 0.0), "pv.system_age_years"
        ),
        degradation_rate_per_year=_parse_distribution_spec(
            data.get("degradation_rate_per_year", 0.005), "pv.degradation_rate_per_year"
        ),
    )


def _parse_battery_distribution_config(
    data: Optional[dict[str, Any]],
) -> Optional[BatteryDistributionConfig]:
    """Parse battery distribution configuration from config data."""
    if data is None:
        return None

    if "capacity_kwh" not in data:
        raise ConfigurationError("Battery distribution config requires 'capacity_kwh'")

    return BatteryDistributionConfig(
        capacity_kwh=_parse_distribution_spec(data["capacity_kwh"], "battery.capacity_kwh"),
        max_charge_kw=_parse_distribution_spec(
            data.get("max_charge_kw", 2.5), "battery.max_charge_kw"
        ),
        max_discharge_kw=_parse_distribution_spec(
            data.get("max_discharge_kw", 2.5), "battery.max_discharge_kw"
        ),
    )


def _parse_heat_pump_distribution_config(
    data: Optional[dict[str, Any]],
) -> Optional[HeatPumpDistributionConfig]:
    """Parse heat pump distribution configuration from config data."""
    if data is None:
        return None

    # Parse heat_pump_type - can be string, distribution, or None
    heat_pump_type_raw = data.get("heat_pump_type")
    heat_pump_type: Union[str, DistributionSpec, None]
    if heat_pump_type_raw is None:
        heat_pump_type = None
    elif isinstance(heat_pump_type_raw, str):
        # Direct string value (e.g., "ASHP" or "GSHP")
        heat_pump_type = heat_pump_type_raw
    elif isinstance(heat_pump_type_raw, dict):
        # Distribution spec
        heat_pump_type = _parse_distribution_spec(
            heat_pump_type_raw, "heat_pump.heat_pump_type"
        )
    else:
        raise ConfigurationError(
            f"Invalid heat_pump_type: expected string, dict, or null, got {type(heat_pump_type_raw).__name__}"
        )

    return HeatPumpDistributionConfig(
        heat_pump_type=heat_pump_type,
        thermal_capacity_kw=_parse_distribution_spec(
            data.get("thermal_capacity_kw", 8.0), "heat_pump.thermal_capacity_kw"
        ),
        annual_heat_demand_kwh=_parse_distribution_spec(
            data.get("annual_heat_demand_kwh", 8000.0), "heat_pump.annual_heat_demand_kwh"
        ),
    )


def _parse_load_distribution_config(data: dict[str, Any]) -> LoadDistributionConfig:
    """Parse load distribution configuration from config data."""
    return LoadDistributionConfig(
        annual_consumption_kwh=_parse_distribution_spec(
            data.get("annual_consumption_kwh"), "load.annual_consumption_kwh"
        ),
        household_occupants=_parse_distribution_spec(
            data.get("household_occupants", 3), "load.household_occupants"
        ),
        use_stochastic=data.get("use_stochastic", True),
    )


def _parse_ev_distribution_config(
    data: Optional[dict[str, Any]],
) -> Optional[EVDistributionConfig]:
    """Parse EV distribution configuration from config data."""
    if data is None:
        return None

    if "charger_type" not in data:
        raise ConfigurationError("EV distribution config requires 'charger_type'")

    return EVDistributionConfig(
        charger_type=_parse_distribution_spec(data["charger_type"], "ev.charger_type"),
        arrival_hour=_parse_distribution_spec(
            data.get("arrival_hour", 18.0), "ev.arrival_hour"
        ),
        departure_hour=_parse_distribution_spec(
            data.get("departure_hour", 7.0), "ev.departure_hour"
        ),
        required_charge_kwh=_parse_distribution_spec(
            data.get("required_charge_kwh", 35.0), "ev.required_charge_kwh"
        ),
        smart_charging_mode=data.get("smart_charging_mode", "none"),
    )


def _parse_fleet_distribution_config(data: dict[str, Any]) -> FleetDistributionConfig:
    """Parse fleet distribution configuration from config data."""
    if "n_homes" not in data:
        raise ConfigurationError("Fleet distribution config requires 'n_homes'")
    if "pv" not in data:
        raise ConfigurationError("Fleet distribution config requires 'pv' section")

    return FleetDistributionConfig(
        n_homes=int(data["n_homes"]),
        pv=_parse_pv_distribution_config(data["pv"]),
        load=_parse_load_distribution_config(data.get("load", {})),
        battery=_parse_battery_distribution_config(data.get("battery")),
        heat_pump=_parse_heat_pump_distribution_config(data.get("heat_pump")),
        ev=_parse_ev_distribution_config(data.get("ev")),
        seed=data.get("seed"),
        random_order=data.get("random_order", "default"),
    )


class _DistributionSampler:
    """Helper class to handle sampling from distributions with pool support.

    For ShuffledPoolDistribution, creates and shuffles the pool once,
    then yields values sequentially. For other distributions, samples
    each time (or uses pre-sampled values if pre_sample was called).
    """

    def __init__(self, rng: random.Random) -> None:
        self._rng = rng
        self._pools: dict[int, list[Optional[float]]] = {}
        self._pool_indices: dict[int, int] = {}
        self._presampled: dict[int, list[Optional[float]]] = {}
        self._presample_indices: dict[int, int] = {}

    def pre_sample(self, spec: DistributionSpec, n: int) -> None:
        """Pre-sample n values from the distribution (for legacy mode)."""
        if spec is None or isinstance(spec, (int, float)):
            return  # Fixed values don't need pre-sampling
        if isinstance(spec, ShuffledPoolDistribution):
            return  # Shuffled pools are handled separately
        spec_id = id(spec)
        if spec_id not in self._presampled:
            samples = [_sample_from_distribution(spec, self._rng) for _ in range(n)]
            self._presampled[spec_id] = samples
            self._presample_indices[spec_id] = 0

    def prepare(self, spec: DistributionSpec) -> None:
        """Prepare a distribution for sampling (creates pool if needed)."""
        if isinstance(spec, ShuffledPoolDistribution):
            spec_id = id(spec)
            if spec_id not in self._pools:
                pool = spec.create_pool()
                self._rng.shuffle(pool)
                self._pools[spec_id] = pool
                self._pool_indices[spec_id] = 0

    def sample(self, spec: DistributionSpec) -> Optional[float]:
        """Sample a value from the distribution."""
        spec_id = id(spec)

        # Check for pre-sampled values first
        if spec_id in self._presampled:
            idx = self._presample_indices[spec_id]
            value = self._presampled[spec_id][idx]
            self._presample_indices[spec_id] = idx + 1
            return value

        # Check for shuffled pool
        if isinstance(spec, ShuffledPoolDistribution):
            pool = self._pools[spec_id]
            idx = self._pool_indices[spec_id]
            value = pool[idx]
            self._pool_indices[spec_id] = idx + 1
            return value

        return _sample_from_distribution(spec, self._rng)

    def sample_with_context(
        self, spec: DistributionSpec, context: dict[str, Optional[float]]
    ) -> Optional[float]:
        """Sample with support for ProportionalDistribution.

        For ProportionalDistribution, looks up the source value from context
        and applies multiplier and offset. For other distributions, delegates
        to the regular sample method.

        Args:
            spec: Distribution specification
            context: Dict mapping field paths to sampled values

        Returns:
            Sampled value (float or None)
        """
        if isinstance(spec, ProportionalDistribution):
            source_val = context.get(spec.source)
            if source_val is None:
                return None
            multiplier = spec.multiplier
            if isinstance(multiplier, SweepSpec):
                raise ConfigurationError(
                    "Cannot sample ProportionalDistribution with SweepSpec multiplier directly. "
                    "Use expand_sweep_configs() to expand sweep values first."
                )
            return source_val * multiplier + spec.offset
        return self.sample(spec)


def generate_homes_from_distribution(
    config: FleetDistributionConfig,
    location: Location,
    *,
    fleet_tariff: Optional[TariffConfig] = None,
    fleet_grid_charging: Optional[GridChargeConfig] = None,
    fleet_dispatch_strategy: Optional[str] = None,
) -> list[HomeConfig]:
    """Generate a list of homes by sampling from distributions.

    Args:
        config: Fleet distribution configuration
        location: Location for all homes
        fleet_tariff: Optional TariffConfig to apply to every home. When None
            (default) homes are generated with tariff_config=None, preserving
            bit-identical behaviour for callers that do not pass this kwarg.
        fleet_grid_charging: Optional GridChargeConfig to apply to every home
            that has a battery. When None (default) the battery's grid_charging
            remains None, preserving bit-identical behaviour. Note: if a home's
            sampled battery capacity is non-positive (or battery is absent), no
            BatteryConfig is created and fleet_grid_charging is silently dropped
            for that home — this is expected behaviour (no battery → no grid
            charging), not an error.
        fleet_dispatch_strategy: Optional dispatch strategy string to apply to
            every home. When None (default) or empty, homes use "greedy",
            preserving bit-identical behaviour for existing callers.

    Returns:
        List of HomeConfig objects
    """
    rng = random.Random(config.seed)
    sampler = _DistributionSampler(rng)
    homes: list[HomeConfig] = []

    # Collect all distribution specs
    all_specs: list[DistributionSpec] = [
        config.pv.capacity_kw,
        config.pv.azimuth,
        config.pv.tilt,
        config.pv.module_efficiency,
        config.pv.inverter_efficiency,
        config.pv.system_age_years,
        config.pv.degradation_rate_per_year,
        config.load.annual_consumption_kwh,
        config.load.household_occupants,
    ]
    if config.battery is not None:
        all_specs.extend([
            config.battery.capacity_kwh,
            config.battery.max_charge_kw,
            config.battery.max_discharge_kw,
        ])
    if config.heat_pump is not None:
        all_specs.extend([
            config.heat_pump.thermal_capacity_kw,
            config.heat_pump.annual_heat_demand_kwh,
        ])
    if config.ev is not None:
        all_specs.extend([
            config.ev.charger_type,
            config.ev.arrival_hour,
            config.ev.departure_hour,
            config.ev.required_charge_kwh,
        ])

    if config.random_order == "bristol_legacy":
        # Bristol legacy order: pre-sample all normal distributions first,
        # then shuffle pools. This matches the exact random call order of
        # create_bristol_phase1_scenario().
        # Order: consumption (normal) -> pv shuffle -> battery shuffle -> ev shuffle
        sampler.pre_sample(config.load.annual_consumption_kwh, config.n_homes)
        sampler.prepare(config.pv.capacity_kw)
        if config.battery is not None:
            sampler.prepare(config.battery.capacity_kwh)
        if config.heat_pump is not None and not isinstance(config.heat_pump.heat_pump_type, str):
            # Only prepare if heat_pump_type is a distribution (not a direct string value)
            sampler.prepare(config.heat_pump.heat_pump_type)
        if config.ev is not None:
            sampler.prepare(config.ev.charger_type)
        # Other specs don't need special handling (fixed values)
    else:
        # Default order: prepare all shuffled pools upfront
        for spec in all_specs:
            sampler.prepare(spec)

    for i in range(config.n_homes):
        # Sample PV parameters
        pv_capacity = sampler.sample(config.pv.capacity_kw)
        if pv_capacity is None or pv_capacity <= 0:
            raise ConfigurationError(f"PV capacity must be positive, got {pv_capacity}")

        pv_azimuth = sampler.sample(config.pv.azimuth)
        pv_tilt = sampler.sample(config.pv.tilt)
        pv_module_eff = sampler.sample(config.pv.module_efficiency)
        pv_inverter_eff = sampler.sample(config.pv.inverter_efficiency)
        pv_age = sampler.sample(config.pv.system_age_years)
        pv_degradation = sampler.sample(config.pv.degradation_rate_per_year)

        pv_config = PVConfig(
            capacity_kw=pv_capacity,
            azimuth=pv_azimuth if pv_azimuth is not None else 180.0,
            tilt=pv_tilt if pv_tilt is not None else 35.0,
            module_efficiency=pv_module_eff if pv_module_eff is not None else 0.20,
            inverter_efficiency=pv_inverter_eff if pv_inverter_eff is not None else 0.96,
            system_age_years=pv_age if pv_age is not None else 0.0,
            degradation_rate_per_year=pv_degradation if pv_degradation is not None else 0.005,
        )

        # Build context for proportional distributions
        context: dict[str, Optional[float]] = {"pv.capacity_kw": pv_capacity}

        # Sample battery parameters (may be None)
        battery_config: Optional[BatteryConfig] = None
        if config.battery is not None:
            battery_capacity = sampler.sample_with_context(
                config.battery.capacity_kwh, context
            )
            if battery_capacity is not None and battery_capacity > 0:
                charge_kw = sampler.sample_with_context(
                    config.battery.max_charge_kw, context
                )
                discharge_kw = sampler.sample_with_context(
                    config.battery.max_discharge_kw, context
                )
                battery_config = BatteryConfig(
                    capacity_kwh=battery_capacity,
                    max_charge_kw=charge_kw if charge_kw is not None else 2.5,
                    max_discharge_kw=discharge_kw if discharge_kw is not None else 2.5,
                    grid_charging=fleet_grid_charging,
                )

        # Sample load parameters
        annual_consumption = sampler.sample(config.load.annual_consumption_kwh)
        household_occupants = sampler.sample(config.load.household_occupants)

        # Derive per-home seed for reproducible stochastic load profiles
        home_seed: Optional[int] = None
        if config.seed is not None:
            home_seed = config.seed + i

        load_config = LoadConfig(
            annual_consumption_kwh=annual_consumption,
            household_occupants=int(household_occupants) if household_occupants else 3,
            use_stochastic=config.load.use_stochastic,
            seed=home_seed,
        )

        # Sample heat pump parameters (may be None)
        heat_pump_config: Optional[HeatPumpConfig] = None
        if config.heat_pump is not None:
            # Handle heat_pump_type: can be string, distribution, or None
            heat_pump_type: Optional[str]
            if isinstance(config.heat_pump.heat_pump_type, str):
                heat_pump_type = config.heat_pump.heat_pump_type
            elif isinstance(config.heat_pump.heat_pump_type, WeightedDiscreteDistribution):
                # Sample from distribution (values can include None)
                # Note: WeightedDiscreteDistribution is typed for floats but used with strings here
                heat_pump_type = sampler.sample(config.heat_pump.heat_pump_type)  # type: ignore[assignment]
            else:
                heat_pump_type = None

            if heat_pump_type is not None:
                # Runtime validation - ensure heat_pump_type is valid
                if heat_pump_type not in ('ASHP', 'GSHP'):
                    raise ConfigurationError(
                        f"Invalid heat pump type sampled: '{heat_pump_type}'. "
                        f"Must be 'ASHP' or 'GSHP'"
                    )

                # Type narrowing - mypy now knows it's Literal['ASHP', 'GSHP']
                heat_pump_type_literal = cast(Literal['ASHP', 'GSHP'], heat_pump_type)

                thermal_capacity = sampler.sample_with_context(
                    config.heat_pump.thermal_capacity_kw, context
                )
                annual_heat_demand = sampler.sample_with_context(
                    config.heat_pump.annual_heat_demand_kwh, context
                )
                heat_pump_config = HeatPumpConfig(
                    heat_pump_type=heat_pump_type_literal,
                    thermal_capacity_kw=thermal_capacity if thermal_capacity is not None else 8.0,
                    annual_heat_demand_kwh=annual_heat_demand if annual_heat_demand is not None else 8000.0,
                )

        # Sample EV parameters (may be None)
        ev_config: Optional[EVConfig] = None
        if config.ev is not None:
            charger_type = sampler.sample(config.ev.charger_type)
            if charger_type is not None:
                arrival_hour_val = sampler.sample(config.ev.arrival_hour)
                departure_hour_val = sampler.sample(config.ev.departure_hour)
                required_charge_val = sampler.sample(config.ev.required_charge_kwh)

                ev_config = EVConfig(
                    charger_type=str(charger_type),
                    arrival_hour=int(arrival_hour_val) if arrival_hour_val is not None else 18,
                    departure_hour=int(departure_hour_val) if departure_hour_val is not None else 7,
                    required_charge_kwh=required_charge_val if required_charge_val is not None else 35.0,
                    smart_charging_mode=config.ev.smart_charging_mode,
                )

        homes.append(
            HomeConfig(
                pv_config=pv_config,
                battery_config=battery_config,
                load_config=load_config,
                heat_pump_config=heat_pump_config,
                ev_config=ev_config,
                location=location,
                name=f"Home {i + 1}",
                tariff_config=fleet_tariff,
                dispatch_strategy=fleet_dispatch_strategy or "greedy",
            )
        )

    return homes


def _parse_seg_config(data: Optional[dict[str, Any]]) -> Optional[float]:
    """Parse SEG (Smart Export Guarantee) configuration from config data.

    Args:
        data: SEG config dict with 'rate_pence_per_kwh', or None

    Returns:
        SEG tariff rate in pence per kWh, or None if not configured
    """
    if data is None:
        return None
    rate = data.get("rate_pence_per_kwh")
    if rate is None:
        return None
    return float(rate)


def _parse_finance_config(data: Optional[dict[str, Any]]) -> Optional[FinanceConfig]:
    """Parse finance configuration from config data.

    Args:
        data: Finance configuration dictionary or None

    Returns:
        FinanceConfig object or None if data is None

    Raises:
        ConfigurationError: If any field value is out of its allowed range
            (propagated from FinanceConfig.__post_init__)
    """
    if data is None:
        return None
    if "standing_charge_pence_per_day" not in data:
        raise ConfigurationError(
            "finance.standing_charge_pence_per_day is required"
        )

    # Parse optional nested grid_services_events block BEFORE the try/except so
    # ConfigurationError raised by GridServicesEventsConfig.__post_init__ propagates
    # without being swallowed by the (ValueError, TypeError) 'non-numeric' wrapper.
    grid_services_model: str = str(data.get("grid_services_model", "flat"))
    grid_services_events_obj: Optional[GridServicesEventsConfig] = None
    gs_events_raw = data.get("grid_services_events")
    if gs_events_raw is not None:
        gs_data = gs_events_raw
        # Parse event_windows list-of-dicts -> tuple[EventWindow, ...]
        # mirroring _parse_tariff_config 'custom' branch.
        ew_raw_list = gs_data.get("event_windows", [])
        if not isinstance(ew_raw_list, list):
            raise ConfigurationError(
                "grid_services_events.event_windows must be a list of window dicts"
            )
        parsed_windows: list[EventWindow] = []
        for i, ew_dict in enumerate(ew_raw_list):
            for req_key in ("months", "weekdays", "hours", "events_per_year", "event_hours"):
                if req_key not in ew_dict:
                    raise ConfigurationError(
                        f"grid_services_events.event_windows[{i}] requires '{req_key}' field"
                    )
            parsed_windows.append(
                EventWindow(
                    months=tuple(int(m) for m in ew_dict["months"]),
                    weekdays=tuple(int(d) for d in ew_dict["weekdays"]),
                    hours=tuple(int(h) for h in ew_dict["hours"]),
                    events_per_year=int(ew_dict["events_per_year"]),
                    event_hours=float(ew_dict["event_hours"]),
                )
            )
        # Build optional override float fields
        avail_raw = gs_data.get("availability_gbp_per_kw_per_event")
        util_raw = gs_data.get("utilisation_gbp_per_mwh")
        # GridServicesEventsConfig.__post_init__ validates; ConfigurationError propagates.
        grid_services_events_obj = GridServicesEventsConfig(
            band=gs_data.get("band", "central"),
            event_windows=tuple(parsed_windows),
            aggregator_share=float(gs_data.get("aggregator_share", 0.25)),
            utilisation_factor=float(gs_data.get("utilisation_factor", 0.6)),
            availability_gbp_per_kw_per_event=(
                float(avail_raw) if avail_raw is not None else None
            ),
            utilisation_gbp_per_mwh=(
                float(util_raw) if util_raw is not None else None
            ),
        )

    try:
        sc_raw = data.get("self_consumption_override")
        return FinanceConfig(
            standing_charge_pence_per_day=float(data["standing_charge_pence_per_day"]),
            vat_rate=float(data.get("vat_rate", 0.05)),
            retail_baseline_rate_pence_per_kwh=float(
                data.get("retail_baseline_rate_pence_per_kwh", 23.0)
            ),
            self_consumption_override=float(sc_raw) if sc_raw is not None else None,
            pv_cost_per_kwp_gbp=float(data.get("pv_cost_per_kwp_gbp", 1000.0)),
            roof_fit_cost_gbp=float(data.get("roof_fit_cost_gbp", 1000.0)),
            battery_cost_per_kwh_gbp=float(data.get("battery_cost_per_kwh_gbp", 250.0)),
            inverter_cost_per_kw_gbp=float(data.get("inverter_cost_per_kw_gbp", 0.0)),
            grant_gbp=float(data.get("grant_gbp", 250000.0)),
            equity_fraction=float(data.get("equity_fraction", 0.75)),
            loan_term_years=int(data.get("loan_term_years", 15)),
            loan_rate=float(data.get("loan_rate", 0.07)),
            opex_per_home_per_year_gbp=float(
                data.get("opex_per_home_per_year_gbp", 131.0)
            ),
            asset_life_years=int(data.get("asset_life_years", 25)),
            own_use_rate_pence_per_kwh=float(
                data.get("own_use_rate_pence_per_kwh", 15.0)
            ),
            retained_cash_floor_per_home_per_year_gbp=float(
                data.get("retained_cash_floor_per_home_per_year_gbp", 27.0)
            ),
            grid_services_income_per_kw_per_year_gbp=float(
                data.get("grid_services_income_per_kw_per_year_gbp", 0.0)
            ),
            grid_services_model=grid_services_model,
            grid_services_events=grid_services_events_obj,
        )
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(
            f"finance block contains a non-numeric value: {exc}"
        ) from exc


def _parse_scenario(data: dict[str, Any]) -> ScenarioConfig:
    """Parse a scenario from config data."""
    if "name" not in data:
        raise ConfigurationError("Scenario must have a 'name' field")
    if "period" not in data:
        raise ConfigurationError(f"Scenario '{data['name']}' must have a 'period' field")

    location_data = data.get("location")
    location = _parse_location(location_data) if location_data else Location.bristol()

    homes: list[HomeConfig] = []
    home: Optional[HomeConfig] = None

    if "homes" in data:
        for home_data in data["homes"]:
            homes.append(_parse_home_config(home_data, location))
    elif "home" in data:
        home = _parse_home_config(data["home"], location)
    else:
        raise ConfigurationError(
            f"Scenario '{data['name']}' must define either 'home' or 'homes'"
        )

    return ScenarioConfig(
        name=data["name"],
        description=data.get("description", ""),
        location=location,
        period=_parse_period(data["period"]),
        homes=homes,
        home=home,
        output=_parse_output_config(data.get("output")),
        seg_tariff_pence_per_kwh=_parse_seg_config(data.get("seg")),
        tariff_config=_parse_tariff_config(data.get("tariff_config")),
        finance=_parse_finance_config(data.get("finance")),
    )


import re

# Pattern for variable substitution: ${VAR} or ${VAR:default}
_VAR_PATTERN = re.compile(r"\$\{([^}:]+)(?::([^}]*))?\}")


def _substitute_variables(data: Any, variables: dict[str, float]) -> Any:
    """Recursively substitute ${VAR} or ${VAR:default} patterns in data.

    Args:
        data: Data structure to process (dict, list, or scalar)
        variables: Dict mapping variable names to values

    Returns:
        Data with variables substituted
    """
    if isinstance(data, str):
        match = _VAR_PATTERN.fullmatch(data)
        if match:
            var_name = match.group(1)
            default_str = match.group(2)
            if var_name in variables:
                return variables[var_name]
            elif default_str is not None:
                return float(default_str)
            else:
                raise ConfigurationError(
                    f"Variable '{var_name}' not provided and has no default"
                )
        return data
    elif isinstance(data, dict):
        return {k: _substitute_variables(v, variables) for k, v in data.items()}
    elif isinstance(data, list):
        return [_substitute_variables(item, variables) for item in data]
    else:
        return data


def substitute_config_variables(
    config: dict[str, Any], variables: Optional[dict[str, float]] = None
) -> dict[str, Any]:
    """Substitute variables in a configuration dictionary.

    Variables are specified as ${VAR} or ${VAR:default} in YAML values.

    Args:
        config: Configuration dictionary
        variables: Dict mapping variable names to values (default: empty)

    Returns:
        Configuration with variables substituted
    """
    return _substitute_variables(config, variables or {})  # type: ignore[no-any-return]


def detect_sweep_spec(config: FleetDistributionConfig) -> Optional[SweepSpec]:
    """Find SweepSpec in config (e.g., in battery.capacity_kwh.multiplier).

    Currently only checks battery.capacity_kwh for ProportionalDistribution
    with a SweepSpec multiplier.

    Args:
        config: Fleet distribution configuration

    Returns:
        SweepSpec if found, None otherwise
    """
    if config.battery is not None:
        cap_spec = config.battery.capacity_kwh
        if isinstance(cap_spec, ProportionalDistribution):
            if isinstance(cap_spec.multiplier, SweepSpec):
                return cap_spec.multiplier
    return None


def _replace_sweep_with_value(
    config: FleetDistributionConfig, value: float
) -> FleetDistributionConfig:
    """Create a copy of config with sweep multiplier replaced by a fixed value.

    Args:
        config: Original configuration with SweepSpec
        value: Value to use instead of sweep

    Returns:
        New FleetDistributionConfig with fixed multiplier
    """
    if config.battery is None:
        return config

    cap_spec = config.battery.capacity_kwh
    if not isinstance(cap_spec, ProportionalDistribution):
        return config

    new_cap_spec = ProportionalDistribution(
        source=cap_spec.source,
        multiplier=value,
        offset=cap_spec.offset,
    )
    new_battery = BatteryDistributionConfig(
        capacity_kwh=new_cap_spec,
        max_charge_kw=config.battery.max_charge_kw,
        max_discharge_kw=config.battery.max_discharge_kw,
    )
    return FleetDistributionConfig(
        n_homes=config.n_homes,
        pv=config.pv,
        load=config.load,
        battery=new_battery,
        heat_pump=config.heat_pump,
        ev=config.ev,
        seed=config.seed,
        random_order=config.random_order,
    )


def expand_sweep_configs(
    config: FleetDistributionConfig,
) -> Iterator[tuple[float, FleetDistributionConfig]]:
    """Expand a config with SweepSpec into individual configs.

    Args:
        config: Fleet distribution configuration (may contain SweepSpec)

    Yields:
        (sweep_value, config) pairs for each sweep point

    Raises:
        ConfigurationError: If no sweep spec found
    """
    sweep = detect_sweep_spec(config)
    if sweep is None:
        raise ConfigurationError(
            "No sweep specification found in config. "
            "Use proportional_to with type: sweep in multiplier."
        )

    for value in sweep.get_values():
        yield value, _replace_sweep_with_value(config, value)


def load_config_yaml(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from a YAML file.

    Args:
        path: Path to YAML configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or parsed
    """
    if not YAML_AVAILABLE:
        raise ConfigurationError(
            "YAML support requires pyyaml: pip install pyyaml"
        )

    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: dict[str, Any] = yaml.safe_load(f)
        if config is None:
            raise ConfigurationError(f"Empty configuration file: {path}")
        return config
    except yaml.YAMLError as e:
        raise ConfigurationError(f"Invalid YAML in {path}: {e}") from e


def load_config_json(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from a JSON file.

    Args:
        path: Path to JSON configuration file

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or parsed
    """
    path = Path(path)
    if not path.exists():
        raise ConfigurationError(f"Configuration file not found: {path}")

    try:
        with open(path, encoding="utf-8") as f:
            config: dict[str, Any] = json.load(f)
        return config
    except json.JSONDecodeError as e:
        raise ConfigurationError(f"Invalid JSON in {path}: {e}") from e


def load_config(path: Union[str, Path]) -> dict[str, Any]:
    """Load configuration from YAML or JSON file.

    Auto-detects format by file extension.

    Args:
        path: Path to configuration file (.yaml, .yml, or .json)

    Returns:
        Parsed configuration dictionary

    Raises:
        ConfigurationError: If file cannot be read or format unknown
    """
    path = Path(path)
    suffix = path.suffix.lower()

    if suffix in (".yaml", ".yml"):
        return load_config_yaml(path)
    elif suffix == ".json":
        return load_config_json(path)
    else:
        raise ConfigurationError(
            f"Unknown configuration file format: {suffix}. "
            "Supported formats: .yaml, .yml, .json"
        )


def load_scenarios(path: Union[str, Path]) -> list[ScenarioConfig]:
    """Load scenarios from a configuration file.

    Args:
        path: Path to configuration file

    Returns:
        List of ScenarioConfig objects

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)

    if "scenarios" in config:
        return [_parse_scenario(s) for s in config["scenarios"]]
    elif "scenario" in config:
        return [_parse_scenario(config["scenario"])]
    else:
        # Try to parse the entire config as a single scenario
        return [_parse_scenario(config)]


def load_home_config(path: Union[str, Path]) -> HomeConfig:
    """Load a single home configuration from file.

    Args:
        path: Path to configuration file

    Returns:
        HomeConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)

    # Check for home section or parse entire config as home
    home_data = config.get("home", config)
    location_data = config.get("location")
    location = _parse_location(location_data) if location_data else Location.bristol()

    return _parse_home_config(home_data, location)


def load_fleet_config(path: Union[str, Path]) -> FleetConfig:
    """Load a fleet configuration from file.

    Supports two formats:
    - Explicit homes list: `homes: [...]`
    - Distribution-based generation: `fleet_distribution: {...}`

    Args:
        path: Path to configuration file

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)

    location_data = config.get("location")
    location = _parse_location(location_data) if location_data else Location.bristol()

    # Check for fleet_distribution (new format)
    if "fleet_distribution" in config:
        dist_config = _parse_fleet_distribution_config(config["fleet_distribution"])
        # Thread scenario-level tariff and fleet battery grid_charging (Seam 1, §9.1).
        # _parse_tariff_config returns None when the key is absent → calibration-safe.
        fleet_tariff = _parse_tariff_config(config.get("tariff"))
        # grid_charging lives under fleet_distribution.battery.grid_charging
        battery_data = config["fleet_distribution"].get("battery")
        fleet_grid_charging = (
            _parse_grid_charge_config(battery_data.get("grid_charging"))
            if isinstance(battery_data, dict)
            else None
        )
        # dispatch_strategy lives directly under fleet_distribution (raw-dict read,
        # mirroring the fleet_grid_charging seam above — not added to FleetDistributionConfig).
        fleet_dispatch_strategy = config["fleet_distribution"].get("dispatch_strategy")
        if fleet_dispatch_strategy and fleet_dispatch_strategy not in _VALID_DISPATCH_STRATEGIES:
            raise ConfigurationError(
                f"Invalid fleet_distribution.dispatch_strategy "
                f"{fleet_dispatch_strategy!r}; valid values: "
                f"{sorted(_VALID_DISPATCH_STRATEGIES)}"
            )
        if fleet_dispatch_strategy == "tou_optimized" and fleet_tariff is None:
            warnings.warn(
                "fleet_distribution.dispatch_strategy is 'tou_optimized' but no tariff "
                "is configured; homes will fall back to self-consumption dispatch at "
                "simulation time. Add a top-level 'tariff:' key to the fleet YAML to "
                "enable Economy-7 grid-charging.",
                UserWarning,
                stacklevel=2,
            )
        homes = generate_homes_from_distribution(
            dist_config,
            location,
            fleet_tariff=fleet_tariff,
            fleet_grid_charging=fleet_grid_charging,
            fleet_dispatch_strategy=fleet_dispatch_strategy,
        )
    elif "homes" in config:
        # Explicit homes list (original format)
        homes_data = config["homes"]
        if not homes_data:
            raise ConfigurationError("Fleet 'homes' list cannot be empty")
        homes = [_parse_home_config(h, location) for h in homes_data]
    else:
        raise ConfigurationError(
            "Fleet configuration requires either 'homes' list or 'fleet_distribution'"
        )

    return FleetConfig(homes=homes, name=config.get("name", ""))


def run_parameter_sweep(
    base_scenario: ScenarioConfig,
    sweep_config: ParameterSweepConfig,
) -> Iterator[SweepResult]:
    """Run a parameter sweep over a scenario.

    Yields results for each parameter value in the sweep.

    Args:
        base_scenario: Base scenario configuration
        sweep_config: Parameter sweep configuration

    Yields:
        SweepResult for each parameter value

    Raises:
        ConfigurationError: If parameter cannot be swept
    """
    values = sweep_config.get_values()
    param_name = sweep_config.parameter_name
    location = base_scenario.get_location()

    for value in values:
        # Create modified scenario for this parameter value
        if base_scenario.home is not None:
            # Single home simulation
            home = _apply_parameter_to_home(base_scenario.home, param_name, value, location)
            start = base_scenario.period.get_start_timestamp(location.timezone)
            end = base_scenario.period.get_end_timestamp(location.timezone)
            home_results = simulate_home(home, start, end)
            yield SweepResult(parameter_value=value, results=home_results)
        else:
            # Fleet simulation
            homes = [
                _apply_parameter_to_home(h, param_name, value, location)
                for h in base_scenario.homes
            ]
            fleet = FleetConfig(homes=homes, name=base_scenario.name)
            start = base_scenario.period.get_start_timestamp(location.timezone)
            end = base_scenario.period.get_end_timestamp(location.timezone)
            fleet_results = simulate_fleet(fleet, start, end)
            yield SweepResult(parameter_value=value, results=fleet_results)


def _apply_parameter_to_home(
    home: HomeConfig,
    param_name: str,
    value: float,
    location: Location,
) -> HomeConfig:
    """Apply a parameter value to a home configuration.

    Args:
        home: Base home configuration
        param_name: Parameter name to modify
        value: New parameter value
        location: Location for the home

    Returns:
        Modified HomeConfig
    """
    # Map parameter names to config modifications
    pv_params = {"pv_capacity_kw", "pv_tilt", "pv_azimuth"}
    battery_params = {"battery_capacity_kwh", "battery_charge_kw", "battery_discharge_kw"}
    load_params = {"annual_consumption_kwh", "household_occupants"}

    if param_name in pv_params:
        pv_config = _modify_pv_config(home.pv_config, param_name, value)
        return HomeConfig(
            pv_config=pv_config,
            load_config=home.load_config,
            battery_config=home.battery_config,
            location=location,
            name=home.name,
            tariff_config=home.tariff_config,
            dispatch_strategy=home.dispatch_strategy,
        )
    elif param_name in battery_params:
        battery_config = _modify_battery_config(home.battery_config, param_name, value)
        return HomeConfig(
            pv_config=home.pv_config,
            load_config=home.load_config,
            battery_config=battery_config,
            location=location,
            name=home.name,
            tariff_config=home.tariff_config,
            dispatch_strategy=home.dispatch_strategy,
        )
    elif param_name in load_params:
        load_config = _modify_load_config(home.load_config, param_name, value)
        return HomeConfig(
            pv_config=home.pv_config,
            load_config=load_config,
            battery_config=home.battery_config,
            location=location,
            name=home.name,
            tariff_config=home.tariff_config,
            dispatch_strategy=home.dispatch_strategy,
        )
    else:
        raise ConfigurationError(f"Unknown parameter for sweep: {param_name}")


def _modify_pv_config(config: PVConfig, param_name: str, value: float) -> PVConfig:
    """Modify PV config with new parameter value."""
    if param_name == "pv_capacity_kw":
        return PVConfig(
            capacity_kw=value,
            azimuth=config.azimuth,
            tilt=config.tilt,
            name=config.name,
            module_efficiency=config.module_efficiency,
            temperature_coefficient=config.temperature_coefficient,
            inverter_efficiency=config.inverter_efficiency,
            inverter_capacity_kw=config.inverter_capacity_kw,
            system_age_years=config.system_age_years,
            degradation_rate_per_year=config.degradation_rate_per_year,
        )
    elif param_name == "pv_tilt":
        return PVConfig(
            capacity_kw=config.capacity_kw,
            azimuth=config.azimuth,
            tilt=value,
            name=config.name,
            module_efficiency=config.module_efficiency,
            temperature_coefficient=config.temperature_coefficient,
            inverter_efficiency=config.inverter_efficiency,
            inverter_capacity_kw=config.inverter_capacity_kw,
            system_age_years=config.system_age_years,
            degradation_rate_per_year=config.degradation_rate_per_year,
        )
    elif param_name == "pv_azimuth":
        return PVConfig(
            capacity_kw=config.capacity_kw,
            azimuth=value,
            tilt=config.tilt,
            name=config.name,
            module_efficiency=config.module_efficiency,
            temperature_coefficient=config.temperature_coefficient,
            inverter_efficiency=config.inverter_efficiency,
            inverter_capacity_kw=config.inverter_capacity_kw,
            system_age_years=config.system_age_years,
            degradation_rate_per_year=config.degradation_rate_per_year,
        )
    return config


def _modify_battery_config(
    config: Optional[BatteryConfig],
    param_name: str,
    value: float,
) -> Optional[BatteryConfig]:
    """Modify battery config with new parameter value."""
    if config is None:
        if param_name == "battery_capacity_kwh" and value > 0:
            return BatteryConfig(capacity_kwh=value)
        return None

    if param_name == "battery_capacity_kwh":
        if value <= 0:
            return None  # Remove battery
        return BatteryConfig(
            capacity_kwh=value,
            max_charge_kw=config.max_charge_kw,
            max_discharge_kw=config.max_discharge_kw,
            name=config.name,
        )
    elif param_name == "battery_charge_kw":
        return BatteryConfig(
            capacity_kwh=config.capacity_kwh,
            max_charge_kw=value,
            max_discharge_kw=config.max_discharge_kw,
            name=config.name,
        )
    elif param_name == "battery_discharge_kw":
        return BatteryConfig(
            capacity_kwh=config.capacity_kwh,
            max_charge_kw=config.max_charge_kw,
            max_discharge_kw=value,
            name=config.name,
        )
    return config


def _modify_load_config(config: LoadConfig, param_name: str, value: float) -> LoadConfig:
    """Modify load config with new parameter value."""
    if param_name == "annual_consumption_kwh":
        return LoadConfig(
            annual_consumption_kwh=value,
            household_occupants=config.household_occupants,
            name=config.name,
            use_stochastic=config.use_stochastic,
            seed=config.seed,
        )
    elif param_name == "household_occupants":
        return LoadConfig(
            annual_consumption_kwh=config.annual_consumption_kwh,
            household_occupants=int(value),
            name=config.name,
            use_stochastic=config.use_stochastic,
            seed=config.seed,
        )
    return config


# ---------------------------------------------------------------------------
# Community config parsing  (task γ / task #32)
# ---------------------------------------------------------------------------


def _parse_community_billing_config(
    data: Optional[dict[str, Any]]
) -> Optional[CommunityBillingConfig]:
    """Parse a ``billing:`` sub-block into a :class:`CommunityBillingConfig`.

    Resolves the SEG rate from one of three forms:

    * Direct scalar: ``seg_rate_pence_per_kwh: 4.1``
    * Preset lookup: ``seg: { preset: Octopus }``
    * Explicit rate:  ``seg: { rate_pence_per_kwh: 5.5 }``

    Supplying both the direct scalar and a nested ``seg`` block is ambiguous and
    raises :exc:`ConfigurationError`.

    Args:
        data: Billing configuration dictionary, or None.

    Returns:
        ``CommunityBillingConfig`` when *data* is a dict; ``None`` otherwise.

    Raises:
        ConfigurationError: For ambiguous SEG specification or unknown preset.
    """
    if data is None:
        return None

    tariff = _parse_tariff_config(data.get("tariff"))

    # Resolve SEG rate (three mutually-exclusive forms)
    direct_rate: Optional[float] = None
    if "seg_rate_pence_per_kwh" in data:
        direct_rate = float(data["seg_rate_pence_per_kwh"])

    seg_block = data.get("seg")

    if direct_rate is not None and seg_block is not None:
        raise ConfigurationError(
            "community billing: specify either 'seg_rate_pence_per_kwh' (scalar) "
            "or 'seg' block — not both."
        )

    seg_rate: Optional[float] = None
    if direct_rate is not None:
        seg_rate = direct_rate
    elif seg_block is not None:
        # Guard: seg must be a mapping, not a bare scalar/string
        if not isinstance(seg_block, dict):
            raise ConfigurationError(
                "community billing: 'seg' must be a mapping with 'preset' or "
                "'rate_pence_per_kwh', not a bare scalar."
            )
        if "preset" in seg_block:
            # Reject ambiguous combination of preset + explicit rate
            if "rate_pence_per_kwh" in seg_block:
                raise ConfigurationError(
                    "community billing: 'seg' block must specify either 'preset' "
                    "or 'rate_pence_per_kwh' — not both."
                )
            preset_name = seg_block["preset"]
            if preset_name not in SEG_PRESETS:
                available = ", ".join(sorted(SEG_PRESETS))
                raise ConfigurationError(
                    f"Unknown SEG preset {preset_name!r}. "
                    f"Available presets: {available}"
                )
            seg_rate = SEG_PRESETS[preset_name].rate_pence_per_kwh
        else:
            seg_rate = _parse_seg_config(seg_block)

    # Normalise an all-None result to None so callers can reliably test ``is None``
    # for "no billing configured" without distinguishing an empty block from an
    # absent key.
    if tariff is None and seg_rate is None:
        return None
    return CommunityBillingConfig(tariff=tariff, seg_rate_pence_per_kwh=seg_rate)


def _parse_community_config(
    data: Optional[dict[str, Any]]
) -> Optional[CommunityConfig]:
    """Parse a ``community:`` YAML block into a :class:`CommunityConfig`.

    Args:
        data: Community configuration dictionary, or None.

    Returns:
        ``CommunityConfig`` when *data* is a dict; ``None`` when *data* is ``None``.

    Raises:
        ConfigurationError: For missing/invalid ``sharing_mode``, p2p+battery,
            community_battery-without-battery, or any nested config error.
    """
    if data is None:
        return None

    sharing_mode = data.get("sharing_mode")
    if not sharing_mode:
        raise ConfigurationError(
            "community: block requires a 'sharing_mode' field "
            "('p2p' or 'community_battery')"
        )

    community_battery = _parse_battery_config(data.get("community_battery"))
    billing = _parse_community_billing_config(data.get("billing"))

    try:
        return CommunityConfig(
            sharing_mode=sharing_mode,
            community_battery=community_battery,
            billing=billing,
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc


def load_community_config(path: Union[str, Path]) -> Optional[CommunityConfig]:
    """Load a community configuration from a YAML or JSON file.

    Reads the file with :func:`load_config` and parses the top-level
    ``community:`` block, if present.  Returns ``None`` when the file
    contains no ``community:`` key (e.g. a plain fleet/scenario document).

    Args:
        path: Path to a ``.yaml``, ``.yml``, or ``.json`` configuration file.

    Returns:
        :class:`CommunityConfig` when a ``community:`` block is present;
        ``None`` otherwise.

    Raises:
        ConfigurationError: If the file cannot be read or the community block
            is invalid.
    """
    raw = load_config(path)
    # yaml.safe_load returns None for an empty file; coerce to a dict so that
    # .get("community") works cleanly and returns None rather than raising
    # AttributeError.
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return _parse_community_config(data.get("community"))
