# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration file support for simulation scenarios.

Supports loading configurations from YAML and JSON files,
scenario definitions, and parameter sweep functionality.
"""

import json
import math
import random
import re
import warnings
from dataclasses import MISSING, asdict, dataclass, field, fields, replace
from pathlib import Path
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Collection,
    Generic,
    Iterable,
    Iterator,
    Mapping,
    Optional,
    Protocol,
    TypeVar,
    Union,
)

import pandas as pd
import yaml

from solar_challenge.battery import BatteryConfig, has_battery, require_valid_capacity_setting
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.dispatch import STRATEGY_CONFIG_BY_TYPE, DispatchStrategyConfig, GridChargeConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVChargerType, EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig, FleetResults, simulate_fleet
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.heat_pump import HEAT_PUMP_TYPES, HeatPumpConfig
from solar_challenge.home import HomeConfig, SimulationResults, simulate_home
from solar_challenge.load import LoadConfig, household_occupant_count
from solar_challenge.location import Location
from solar_challenge.number_fields import as_finite_float
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from solar_challenge.tariff import TariffConfig, TariffPeriod
from solar_challenge.weather import default_weather


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

    def draw(self, rng: random.Random) -> Optional[float]:
        """Draw one of the values from *rng*, each with its weight's share of the chance."""
        return rng.choices(list(self.values), weights=list(self.weights), k=1)[0]


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

    def draw(self, rng: random.Random) -> float:
        """Draw a value from *rng*'s normal distribution of mean and std, clamped to whichever of min and max is set."""
        value = rng.gauss(self.mean, self.std)
        if self.min is not None:
            value = max(self.min, value)
        if self.max is not None:
            value = min(self.max, value)
        return value


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

    def draw(self, rng: random.Random) -> float:
        """Draw a value from *rng* uniformly between min and max."""
        return rng.uniform(self.min, self.max)


@dataclass(frozen=True)
class ShuffledPoolDistribution:
    """Shuffled pool distribution for exact count assignment.

    Creates a pool of values with exact counts, shuffles once, and assigns
    sequentially. This matches the behavior of pre-generating distributions
    then shuffling (like bristol-phase1).

    Attributes:
        values: List of values (can include None)
        counts: Number of each value in the pool.  In a fleet distribution they total
            n_homes, one value per home, and FleetDistributionConfig refuses any other total;
            a parameter only some homes draw leaves the other homes' values undrawn.
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
        module_efficiency: Distribution for module efficiency (default: None, which leaves
            each home's module its own)
        inverter_efficiency: Distribution for inverter efficiency (default: 0.96)
        system_age_years: Distribution for system age in years (default: 0.0)
        degradation_rate_per_year: Distribution for annual degradation rate (default: 0.005)
    """

    capacity_kw: DistributionSpec
    azimuth: DistributionSpec = 180.0
    tilt: DistributionSpec = 35.0
    module_efficiency: DistributionSpec = None
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
        grid_charging: Grid-charging configuration of every home with a battery (optional)
        dispatch_strategy: Dispatch strategy of every home with a battery (optional), set
            on its BatteryConfig.  Its tou_optimized dispatches by its own peak_hours, so it
            needs no tariff.  It is not FleetDistributionConfig.dispatch_strategy, the
            HomeConfig.dispatch_strategy string whose tou_optimized dispatches by the
            scenario's tariff; a battery given a strategy here dispatches with it instead.
    """

    capacity_kwh: DistributionSpec
    max_charge_kw: DistributionSpec = 2.5
    max_discharge_kw: DistributionSpec = 2.5
    grid_charging: Optional[GridChargeConfig] = None
    dispatch_strategy: Optional[DispatchStrategyConfig] = None

    def __post_init__(self) -> None:
        """Refuse a fixed capacity_kwh that is not a valid battery capacity setting; samples are checked as drawn."""
        if isinstance(self.capacity_kwh, (int, float)):
            require_valid_capacity_setting(self.capacity_kwh, "battery.capacity_kwh")


@dataclass
class LoadDistributionConfig:
    """Distribution configuration for load parameters.

    Attributes:
        annual_consumption_kwh: Distribution for annual consumption (optional)
        household_occupants: Distribution for occupants (default: 3), drawn with
            _DistributionSampler.sample_count and held to
            load.household_occupant_count. A null draw takes LoadConfig's default.
            A normal or uniform with no whole number from its min to its max is
            refused on construction, and again as drawn.
        use_stochastic: Whether to use stochastic load profiles (default: True)
    """

    annual_consumption_kwh: DistributionSpec = None
    household_occupants: DistributionSpec = 3
    use_stochastic: bool = True

    def __post_init__(self) -> None:
        """Refuse a normal or uniform household_occupants with no whole number from its min to its max; draws are checked as drawn."""
        if isinstance(self.household_occupants, (NormalDistribution, UniformDistribution)):
            _count_bounds(self.household_occupants, "load.household_occupants")


@dataclass
class HeatPumpDistributionConfig:
    """Distribution configuration for heat pump parameters.

    Values can include None to represent homes without heat pumps.

    Attributes:
        heat_pump_type: One of heat_pump.HEAT_PUMP_TYPES, a distribution spec over them, or None for no heat pump
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
        charger_type: null, or a weighted_discrete or shuffled_pool of EVChargerType values
            and nulls (a null is a home without an EV); parse_fleet_distribution_config
            refuses any other
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
        random_order: One of _RANDOM_ORDERS' keys, naming what is drawn ahead of the first
            home and in which order ("bristol_legacy" reproduces
            create_bristol_phase1_scenario's sequence)
        dispatch_strategy: Dispatch strategy of every home ("greedy" or "tou_optimized");
            None means greedy.  A battery given BatteryDistributionConfig.dispatch_strategy
            dispatches with that instead.
    """

    n_homes: int
    pv: PVDistributionConfig
    load: LoadDistributionConfig
    battery: Optional[BatteryDistributionConfig] = None
    heat_pump: Optional[HeatPumpDistributionConfig] = None
    ev: Optional[EVDistributionConfig] = None
    seed: Optional[int] = None
    random_order: str = "default"
    dispatch_strategy: Optional[str] = None

    def __post_init__(self) -> None:
        if self.n_homes < 1:
            raise ConfigurationError("FleetDistributionConfig: n_homes must be at least 1")
        if not isinstance(self.random_order, str) or self.random_order not in _RANDOM_ORDERS:
            raise ConfigurationError(
                f"FleetDistributionConfig: random_order must be "
                f"{' or '.join(repr(order) for order in _RANDOM_ORDERS)}, got '{self.random_order}'"
            )
        _refuse_pools_not_sized_to_the_fleet(self)


#: The fleet's components, as FleetDistributionConfig names them. Their order is the default
#: shuffle order: every random order shuffles the pools it does not shuffle first component
#: by component in this order, field order within a component. It is not the order in which
#: a home draws them.
_FLEET_COMPONENTS: tuple[str, ...] = ("pv", "load", "battery", "heat_pump", "ev")


@dataclass(frozen=True)
class _RandomOrder:
    """What a fleet's random order draws for every home before the first home is built.

    First each pre_sampled setting's values, then the pools of the shuffled_first settings
    in that order, then every other pool in the default shuffle order: component by
    component in _FLEET_COMPONENTS, field order within a component.

    Attributes:
        pre_sampled: Paths of the settings whose weighted discrete, normal or uniform
            values are all drawn ahead, e.g. 'load.annual_consumption_kwh'
        shuffled_first: Paths of the settings whose pools are shuffled before any other pool
    """

    pre_sampled: tuple[str, ...] = ()
    shuffled_first: tuple[str, ...] = ()


#: create_bristol_phase1_scenario's random call order, which review/briefing.yaml's
#: reproducibility rule says to keep.
_BRISTOL_LEGACY_ORDER = _RandomOrder(
    pre_sampled=("load.annual_consumption_kwh",),
    shuffled_first=("pv.capacity_kw", "battery.capacity_kwh", "heat_pump.heat_pump_type", "ev.charger_type"),
)

_RANDOM_ORDERS: Mapping[str, _RandomOrder] = MappingProxyType({
    "default": _RandomOrder(),
    "bristol_legacy": _BRISTOL_LEGACY_ORDER,
})


def _component_settings(config: FleetDistributionConfig) -> Iterator[tuple[str, object]]:
    """Each setting of *config*'s components with its path, e.g. ('pv.tilt', spec), component by component in _FLEET_COMPONENTS."""
    for name in _FLEET_COMPONENTS:
        component = getattr(config, name)
        if component is None:
            continue
        for parameter in fields(component):
            yield f"{name}.{parameter.name}", getattr(component, parameter.name)


def _shuffled_pools(
    config: FleetDistributionConfig,
) -> Iterator[tuple[str, ShuffledPoolDistribution]]:
    """Each shuffled pool among *config*'s component parameters, with its path, e.g. ('pv.capacity_kw', pool)."""
    for path, setting in _component_settings(config):
        if isinstance(setting, ShuffledPoolDistribution):
            yield path, setting


def _refuse_pools_not_sized_to_the_fleet(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a shuffled pool's counts do not total its n_homes: a pool holds one value per home."""
    for path, pool in _shuffled_pools(config):
        total = sum(pool.counts)
        if total != config.n_homes:
            raise ConfigurationError(
                f"FleetDistributionConfig: shuffled_pool counts for '{path}' must total n_homes "
                f"({config.n_homes}), got {total}"
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


def _child_path(block_path: str, key: str) -> str:
    """Return the path of the *key* block inside the block at *block_path*; "" is the top level."""
    return f"{block_path}.{key}" if block_path else key


def _block_label(block_path: str) -> str:
    """Name the block at *block_path* in an error message."""
    return block_path or "the top level"


def _require_mapping(block_path: str, data: object) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping."""
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"{_block_label(block_path)} must be a mapping, got {type(data).__name__}"
        )
    return data


def _refuse_unrecognised_keys(
    block_path: str, data: object, recognised: Collection[str]
) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping holding only *recognised* keys."""
    mapping = _require_mapping(block_path, data)
    unrecognised = sorted(repr(key) for key in mapping.keys() - recognised)
    if unrecognised:
        raise ConfigurationError(
            f"Unrecognised keys in {_block_label(block_path)}: {', '.join(unrecognised)}; "
            f"recognised keys: {', '.join(sorted(recognised))}"
        )
    return mapping


_Built = TypeVar("_Built")


@dataclass(frozen=True)
class _BlockType(Generic[_Built]):
    """One type a block names in its ``type:`` key.

    *recognised_keys* is every key a block of the type recognises, ``type`` among them. *build*
    reads a block holding only those keys, and receives the block's path in its file.
    """

    recognised_keys: frozenset[str]
    build: Callable[[dict[str, Any], str], _Built]


class _SubBlockReader(Protocol):
    """Reads a nested block's value, given its path in its file, as the config the block describes."""

    def __call__(self, data: Any, *, block_path: str) -> object: ...


@dataclass(frozen=True)
class SubBlock:
    """A key whose value is a nested block, with its grammar's reader and writer.

    *read* reads the key's non-null value at its block path; *write* writes the field's non-None
    value as the block *read* reads back as it.
    """

    read: _SubBlockReader
    write: Callable[[Any], dict[str, Any]]


_Component = TypeVar("_Component", bound=DataclassInstance)


@dataclass(frozen=True)
class ComponentBlock(Generic[_Component]):
    """A component's block in the scenario grammar, stated against the dataclass it builds.

    *config_type* is the dataclass. *keys* are the block's keys, the fields it carries, in field
    order; *outside_grammar* maps each other field to the reason no key carries it. *sub_blocks*
    holds the keys whose value is a nested block, and *when_omitted* the value an omitted key
    reads as, for each key where that is not the dataclass's declared default.
    tests/unit/config/test_component_blocks.py holds every table to its dataclass's fields (T1).
    """

    config_type: type[_Component]
    keys: tuple[str, ...]
    outside_grammar: Mapping[str, str]
    sub_blocks: Mapping[str, SubBlock]
    when_omitted: Mapping[str, object]

    def value_when_omitted(self, name: str) -> object:
        """The value field *name* is built with when a block does not set it, as no block sets a field outside the grammar.

        That is the table's when-omitted value, else the dataclass's declared default or its
        default factory's value, else MISSING, which no value equals.
        """
        if name in self.when_omitted:
            return self.when_omitted[name]
        declared = {each.name: each for each in fields(self.config_type)}[name]
        if declared.default_factory is not MISSING:
            return declared.default_factory()
        return declared.default


def _set_keys(block: ComponentBlock[Any], data: object, block_path: str) -> dict[str, Any]:
    """The keys the block at *block_path* sets, its null ones dropped, once every key it holds is one of *block*'s."""
    return {
        key: value
        for key, value in _refuse_unrecognised_keys(block_path, data, block.keys).items()
        if value is not None
    }


def _refuse_missing_keys(block_path: str, missing_keys: Collection[str]) -> None:
    """Refuse the block at *block_path* if it leaves out any of *missing_keys*, keys it needs, naming each by its path."""
    if missing_keys:
        missing = ", ".join(_child_path(block_path, key) for key in missing_keys)
        raise ConfigurationError(f"Missing required keys in {_block_label(block_path)}: {missing}")


def _built_from(config_type: type[_Built], values: Mapping[str, Any], block_path: str) -> _Built:
    """The config *config_type* builds from *values*, the block at *block_path*'s.

    Raises:
        ConfigurationError: naming the block, for a value of a type *config_type* cannot use,
            which building it refuses with a TypeError.
    """
    try:
        return config_type(**values)
    except TypeError as refusal:
        raise ConfigurationError(f"{_block_label(block_path)}: {refusal}") from refusal


def _built_component(
    block: ComponentBlock[_Component], set_keys: Mapping[str, Any], block_path: str
) -> _Component:
    """The config the block at *block_path* describes, built from the keys it sets.

    Each sub-block it sets is read first, in the table's order; then the dataclass is built once
    from the set values, as written, over the table's when-omitted values.

    Raises:
        ConfigurationError: naming by its path each key the block leaves out that has neither a
            declared default nor a when-omitted value; or naming the block, for a value of a
            type its dataclass cannot use, which building it refuses with a TypeError.
    """
    _refuse_missing_keys(
        block_path,
        [key for key in block.keys if key not in set_keys and block.value_when_omitted(key) is MISSING],
    )
    sub_block_configs = {
        key: sub_block.read(set_keys[key], block_path=_child_path(block_path, key))
        for key, sub_block in block.sub_blocks.items()
        if key in set_keys
    }
    return _built_from(block.config_type, {**block.when_omitted, **set_keys, **sub_block_configs}, block_path)


def _read_component_block(
    block: ComponentBlock[_Component], data: object, *, block_path: str
) -> _Component:
    """The config the component block at *block_path* describes, read by *block*'s table.

    A key outside the table's keys is refused, null or not; a null key reads as absent; an
    omitted key takes the table's when-omitted value, else the dataclass's declared default; a
    key with neither is refused by its path; and a value of a type the dataclass cannot use is
    refused naming the block.
    """
    return _built_component(block, _set_keys(block, data, block_path), block_path)


def _float_or_none(value: Any) -> Optional[float]:
    """Coerce *value* to a float, keeping a null as None."""
    return None if value is None else float(value)


def _number(value: Any) -> float:
    """Coerce *value* to a float as float() does, refusing a boolean, which float() would read as 1.0 or 0.0."""
    if isinstance(value, bool):
        raise TypeError(f"{value!r} is a boolean, not a number")
    return float(value)


def _number_or_none(value: Any) -> Optional[float]:
    """Coerce *value* as :func:`_number` does, keeping a null as None."""
    return None if value is None else _number(value)


def parse_location_block(
    data: Optional[dict[str, Any]], *, block_path: str = "location"
) -> Location:
    """Parse a ``location:`` block into a Location, as LOCATION_BLOCK reads it.

    A block that is absent or sets no key, its null keys read as absent, is Bristol. Otherwise each
    key it leaves out takes Bristol's value, but an omitted name stays empty.
    """
    if data is None:
        return Location.bristol()
    set_keys = _set_keys(LOCATION_BLOCK, data, block_path)
    if not set_keys:
        return Location.bristol()
    return _built_component(LOCATION_BLOCK, set_keys, block_path)


def _parse_pv_config(data: dict[str, Any], *, block_path: str) -> PVConfig:
    """Parse a pv: block into a PVConfig, as _read_component_block reads PV_BLOCK."""
    return _read_component_block(PV_BLOCK, data, block_path=block_path)


_GRID_CHARGING_BLOCK_KEYS: frozenset[str] = frozenset({"target_soc_fraction"})


def _parse_grid_charge_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[GridChargeConfig]:
    """Parse grid-charging configuration from a dict or None.

    An omitted ``target_soc_fraction`` takes GridChargeConfig's declared default.

    Args:
        data: grid_charging mapping (e.g. ``{'target_soc_fraction': 0.9}``) or None.
        block_path: The block's path in its file, named in error messages.

    Returns:
        GridChargeConfig if data is a non-None mapping, else None.

    Raises:
        ConfigurationError: If data is present but not a mapping, or carries a key
            other than ``target_soc_fraction``.
    """
    if data is None:
        return None
    return GridChargeConfig(**_refuse_unrecognised_keys(block_path, data, _GRID_CHARGING_BLOCK_KEYS))


def _grid_charging_block(grid_charging: GridChargeConfig) -> dict[str, Any]:
    """The grid_charging: block _parse_grid_charge_config reads back as *grid_charging*."""
    return {"target_soc_fraction": grid_charging.target_soc_fraction}


def _parse_battery_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[BatteryConfig]:
    """Parse a battery: block into a BatteryConfig, as _read_component_block reads BATTERY_BLOCK; a null block is no battery."""
    if data is None:
        return None
    return _read_component_block(BATTERY_BLOCK, data, block_path=block_path)


def _parse_load_config(data: dict[str, Any], *, block_path: str) -> LoadConfig:
    """Parse a load: block into a LoadConfig, as _read_component_block reads LOAD_BLOCK."""
    return _read_component_block(LOAD_BLOCK, data, block_path=block_path)


_KEYS_A_STRATEGY_READS: frozenset[str] = frozenset(
    each.name for variant in STRATEGY_CONFIG_BY_TYPE.values() for each in fields(variant) if each.init
)
"""Each key a dispatch_strategy: block reads beside strategy_type, for one strategy or another."""


def _tuples(value: Any) -> Any:
    """*value* with each list in it, at any depth, read as a tuple."""
    if isinstance(value, (list, tuple)):
        return tuple(_tuples(item) for item in value)
    return value


def _lists(value: Any) -> Any:
    """*value* with each tuple in it, at any depth, written as a list, which _tuples reads back as it."""
    if isinstance(value, (list, tuple)):
        return [_lists(item) for item in value]
    return value


def _strategy_variant(block: Mapping[str, Any], block_path: str) -> type[DispatchStrategyConfig]:
    """The variant of DispatchStrategyConfig the strategy_type of the dispatch_strategy: block at *block_path* names.

    Raises:
        ConfigurationError: for a strategy_type that is missing or names no variant, naming its
            path, its value and the variants' tags.
    """
    tag = block.get("strategy_type")
    variant = STRATEGY_CONFIG_BY_TYPE.get(tag) if isinstance(tag, str) else None
    if variant is None:
        raise ConfigurationError(
            f"Invalid {_child_path(block_path, 'strategy_type')} {tag!r}; "
            f"valid values: {sorted(STRATEGY_CONFIG_BY_TYPE)}"
        )
    return variant


def parse_dispatch_strategy_config(
    data: Optional[dict[str, Any]], *, block_path: str = "dispatch_strategy"
) -> Optional[DispatchStrategyConfig]:
    """Parse a dispatch_strategy: block into the variant of DispatchStrategyConfig its strategy_type names; a null block is no strategy.

    The block's other keys are the variant's fields, each list in them read as a tuple. A null
    key that some strategy reads reads as absent, so a block written before the strategies were
    variants, every key present and those its strategy does not read null, reads as its variant.

    Raises:
        ConfigurationError: for a block that is not a mapping; a strategy_type that is missing
            or names no variant, naming its path, its value and the variants' tags; a key the
            variant does not read, unless it is null and another strategy reads it; a key the
            variant needs, left out or null, naming its path; a value of a type the variant
            cannot use, naming the block; and a value the variant refuses, as it refuses it.
    """
    if data is None:
        return None
    block = _require_mapping(block_path, data)
    variant = _strategy_variant(block, block_path)
    variant_fields = [each for each in fields(variant) if each.init]
    set_keys = _refuse_unrecognised_keys(
        block_path,
        {key: value for key, value in block.items() if value is not None or key not in _KEYS_A_STRATEGY_READS},
        {"strategy_type", *(each.name for each in variant_fields)},
    )
    _refuse_missing_keys(
        block_path,
        [
            each.name
            for each in variant_fields
            if each.name not in set_keys and each.default is MISSING and each.default_factory is MISSING
        ],
    )
    values = {each.name: _tuples(set_keys[each.name]) for each in variant_fields if each.name in set_keys}
    return _built_from(variant, values, block_path)


def _dispatch_strategy_block(strategy: DispatchStrategyConfig) -> dict[str, Any]:
    """The dispatch_strategy: block parse_dispatch_strategy_config reads back as *strategy*: its tag, then its fields."""
    return {
        "strategy_type": strategy.strategy_type,
        **{each.name: _lists(getattr(strategy, each.name)) for each in fields(strategy) if each.init},
    }


PV_BLOCK: ComponentBlock[PVConfig] = ComponentBlock(
    config_type=PVConfig,
    keys=(
        "capacity_kw", "azimuth", "tilt", "name", "module_efficiency", "temperature_coefficient",
        "inverter_efficiency", "inverter_capacity_kw", "system_age_years",
        "degradation_rate_per_year", "system_losses",
    ),
    outside_grammar=MappingProxyType({
        "custom_module_params": "custom pvlib module parameters have no YAML form",
        "custom_inverter_params": "custom pvlib inverter parameters have no YAML form",
    }),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({"capacity_kw": 4.0}),
)

BATTERY_BLOCK: ComponentBlock[BatteryConfig] = ComponentBlock(
    config_type=BatteryConfig,
    keys=(
        "capacity_kwh", "max_charge_kw", "max_discharge_kw", "name", "dispatch_strategy",
        "grid_charging", "min_soc_fraction", "max_soc_fraction", "charge_efficiency",
        "discharge_efficiency", "efficiency", "system_age_years", "calendar_fade_rate_per_year",
        "cycle_fade_per_equivalent_full_cycle", "soh_floor", "soh",
    ),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({
        "dispatch_strategy": SubBlock(parse_dispatch_strategy_config, _dispatch_strategy_block),
        "grid_charging": SubBlock(_parse_grid_charge_config, _grid_charging_block),
    }),
    when_omitted=MappingProxyType({"capacity_kwh": 5.0}),
)

LOAD_BLOCK: ComponentBlock[LoadConfig] = ComponentBlock(
    config_type=LoadConfig,
    keys=("annual_consumption_kwh", "household_occupants", "name", "use_stochastic", "seed"),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({}),
)

HEAT_PUMP_BLOCK: ComponentBlock[HeatPumpConfig] = ComponentBlock(
    config_type=HeatPumpConfig,
    keys=("heat_pump_type", "thermal_capacity_kw", "annual_heat_demand_kwh", "name"),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({}),
)

EV_BLOCK: ComponentBlock[EVConfig] = ComponentBlock(
    config_type=EVConfig,
    keys=(
        "charger_type", "arrival_hour", "departure_hour", "required_charge_kwh",
        "smart_charging_mode", "name",
    ),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({}),
)

LOCATION_BLOCK: ComponentBlock[Location] = ComponentBlock(
    config_type=Location,
    keys=("latitude", "longitude", "timezone", "altitude", "name"),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType(
        {key: value for key, value in asdict(Location.bristol()).items() if key != "name"}
    ),
)


_TARIFF_PERIOD_KEYS: frozenset[str] = frozenset({"start_time", "end_time", "rate_per_kwh", "name"})

_PRESET_TARIFF_RATE_KEYS: frozenset[str] = frozenset({"off_peak_rate", "peak_rate"})


def _build_flat_rate_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the flat_rate tariff a block names, refusing it unless it gives a rate."""
    rate = data.get("rate_per_kwh")
    if rate is None:
        raise ConfigurationError("flat_rate tariff requires 'rate_per_kwh' field")
    return TariffConfig.flat_rate(
        rate_per_kwh=float(rate),
        name=data.get("name", "")
    )


def _preset_tariff_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Return the keyword overrides a preset tariff block sets, its rates read as floats.

    Reads a block that parse_tariff_config has already confined to its type's keys.
    """
    return {
        key: float(value) if key in _PRESET_TARIFF_RATE_KEYS else value
        for key, value in data.items()
        if key != "type"
    }


def _build_economy_7_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the Economy 7 tariff a block names, with the overrides it sets."""
    return TariffConfig.economy_7(**_preset_tariff_overrides(data))


def _build_economy_10_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the Economy 10 tariff a block names, with the overrides it sets."""
    return TariffConfig.economy_10(**_preset_tariff_overrides(data))


def _parse_tariff_period(data: object, *, block_path: str) -> TariffPeriod:
    """Parse one period of a custom tariff block, refusing it unless it gives a start, an end and a rate."""
    period = _refuse_unrecognised_keys(block_path, data, _TARIFF_PERIOD_KEYS)
    for key in ("start_time", "end_time", "rate_per_kwh"):
        if key not in period:
            raise ConfigurationError(f"Tariff period requires '{key}' field")
    return TariffPeriod(
        start_time=period["start_time"],
        end_time=period["end_time"],
        rate_per_kwh=float(period["rate_per_kwh"]),
        name=period.get("name", "")
    )


def _build_custom_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the custom tariff a block names from its periods, refusing it unless it gives some."""
    if "periods" not in data:
        raise ConfigurationError("custom tariff requires 'periods' field")

    periods_data = data["periods"]
    if not periods_data:
        raise ConfigurationError("custom tariff must have at least one period")

    return TariffConfig(
        periods=tuple(
            _parse_tariff_period(period, block_path=_child_path(block_path, f"periods[{index}]"))
            for index, period in enumerate(periods_data)
        ),
        name=data.get("name", "")
    )


_TARIFF_TYPES: Mapping[str, _BlockType[TariffConfig]] = MappingProxyType({
    "flat_rate": _BlockType(
        frozenset({"type", "rate_per_kwh", "name"}),
        _build_flat_rate_tariff,
    ),
    "economy_7": _BlockType(
        frozenset({
            "type", "off_peak_rate", "peak_rate", "off_peak_start", "off_peak_end",
        }),
        _build_economy_7_tariff,
    ),
    "economy_10": _BlockType(
        frozenset({
            "type", "off_peak_rate", "peak_rate", "night_start", "night_end", "afternoon_start",
            "afternoon_end", "evening_start", "evening_end",
        }),
        _build_economy_10_tariff,
    ),
    "custom": _BlockType(
        frozenset({"type", "periods", "name"}),
        _build_custom_tariff,
    ),
})


def parse_tariff_config(
    data: Optional[dict[str, Any]], *, block_path: str = "tariff"
) -> Optional[TariffConfig]:
    """Parse tariff configuration from config data.

    Supports preset tariffs (flat_rate, economy_7, economy_10) and custom
    tariff definitions with explicit periods.

    Args:
        data: Tariff configuration dictionary or None
        block_path: The block's path in its file, named in error messages

    Returns:
        TariffConfig object or None if data is None

    Raises:
        ConfigurationError: If tariff specification is invalid, including a
            block or custom period that is not a mapping or carries a key its
            type does not read
    """
    if data is None:
        return None
    _require_mapping(block_path, data)

    tariff_type = data.get("type")
    if tariff_type is None:
        raise ConfigurationError("Tariff configuration requires 'type' field")
    block_type = _TARIFF_TYPES.get(tariff_type) if isinstance(tariff_type, str) else None
    if block_type is None:
        raise ConfigurationError(
            f"Unknown tariff type '{tariff_type}'. "
            f"Supported types: {', '.join(_TARIFF_TYPES)}"
        )
    _refuse_unrecognised_keys(block_path, data, block_type.recognised_keys)
    return block_type.build(data, block_path)


def _parse_heat_pump_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[HeatPumpConfig]:
    """Parse a heat_pump: block into a HeatPumpConfig, as _read_component_block reads HEAT_PUMP_BLOCK; a null block is no heat pump."""
    if data is None:
        return None
    return _read_component_block(HEAT_PUMP_BLOCK, data, block_path=block_path)


def _parse_ev_config(data: Optional[dict[str, Any]], *, block_path: str) -> Optional[EVConfig]:
    """Parse an ev: block into an EVConfig, as _read_component_block reads EV_BLOCK; a null block is no EV."""
    if data is None:
        return None
    return _read_component_block(EV_BLOCK, data, block_path=block_path)


_HOME_SCALAR_KEYS: tuple[str, ...] = ("name", "dispatch_strategy")

#: The home scalars whose null parse_home_block hands on to HomeConfig rather than reading it as
#: absent: a null dispatch_strategy is held as None until task 787's reader reads it.
_HOME_SCALARS_HANDING_ON_NULL: frozenset[str] = frozenset({"dispatch_strategy"})

_HOME_BLOCK_KEYS: frozenset[str] = frozenset({
    *_HOME_SCALAR_KEYS, "pv", "battery", "load", "tariff", "heat_pump", "ev",
})


def parse_home_block(
    data: dict[str, Any], location: Location, *, block_path: str = "home"
) -> HomeConfig:
    """Parse a ``home:`` block, or one ``homes:`` entry, into a HomeConfig at *location*.

    A key the block omits takes HomeConfig's declared default, and so does a null scalar other than
    those _HOME_SCALARS_HANDING_ON_NULL names, which are handed on. An omitted pv or load block
    reads as an empty one.
    """
    home = _refuse_unrecognised_keys(block_path, data, _HOME_BLOCK_KEYS)
    return HomeConfig(
        pv_config=_parse_pv_config(home.get("pv", {}), block_path=_child_path(block_path, "pv")),
        battery_config=_parse_battery_config(
            home.get("battery"), block_path=_child_path(block_path, "battery")
        ),
        load_config=_parse_load_config(
            home.get("load", {}), block_path=_child_path(block_path, "load")
        ),
        location=location,
        tariff_config=parse_tariff_config(
            home.get("tariff"), block_path=_child_path(block_path, "tariff")
        ),
        heat_pump_config=_parse_heat_pump_config(
            home.get("heat_pump"), block_path=_child_path(block_path, "heat_pump")
        ),
        ev_config=_parse_ev_config(home.get("ev"), block_path=_child_path(block_path, "ev")),
        **{
            key: home[key]
            for key in _HOME_SCALAR_KEYS
            if key in home and (home[key] is not None or key in _HOME_SCALARS_HANDING_ON_NULL)
        },
    )


_PERIOD_BLOCK_KEYS: frozenset[str] = frozenset({"start_date", "end_date"})


def _parse_period(data: dict[str, Any], *, block_path: str) -> SimulationPeriod:
    """Parse simulation period from config data."""
    _refuse_unrecognised_keys(block_path, data, _PERIOD_BLOCK_KEYS)
    if "start_date" not in data or "end_date" not in data:
        raise ConfigurationError("Simulation period requires 'start_date' and 'end_date'")
    return SimulationPeriod(
        start_date=data["start_date"],
        end_date=data["end_date"],
    )


_OUTPUT_BLOCK_KEYS: frozenset[str] = frozenset({
    "csv_path", "include_minute_data", "include_summary", "aggregation",
})


def _parse_output_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[OutputConfig]:
    """Parse output configuration from config data."""
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _OUTPUT_BLOCK_KEYS)
    return OutputConfig(
        csv_path=data.get("csv_path"),
        include_minute_data=data.get("include_minute_data", True),
        include_summary=data.get("include_summary", True),
        aggregation=data.get("aggregation", "minute"),
    )


# --- Distribution Parsing and Sampling ---


_SWEEP_SPEC_KEYS: frozenset[str] = frozenset({"type", "min", "max", "steps", "mode"})


def _build_weighted_discrete_spec(
    data: dict[str, Any], block_path: str
) -> WeightedDiscreteDistribution:
    """Build the weighted_discrete distribution a spec names, refusing it unless it gives values and weights."""
    if "values" not in data or "weights" not in data:
        raise ConfigurationError(
            f"weighted_discrete distribution for '{block_path}' requires 'values' and 'weights'"
        )
    return WeightedDiscreteDistribution(
        values=tuple(data["values"]),
        weights=tuple(float(w) for w in data["weights"]),
    )


def _build_normal_spec(data: dict[str, Any], block_path: str) -> NormalDistribution:
    """Build the normal distribution a spec names, refusing it unless it gives a mean and a std."""
    if "mean" not in data or "std" not in data:
        raise ConfigurationError(
            f"normal distribution for '{block_path}' requires 'mean' and 'std'"
        )
    return NormalDistribution(
        mean=float(data["mean"]),
        std=float(data["std"]),
        min=_float_or_none(data.get("min")),
        max=_float_or_none(data.get("max")),
    )


def _build_uniform_spec(data: dict[str, Any], block_path: str) -> UniformDistribution:
    """Build the uniform distribution a spec names, refusing it unless it gives a min and a max."""
    if "min" not in data or "max" not in data:
        raise ConfigurationError(
            f"uniform distribution for '{block_path}' requires 'min' and 'max'"
        )
    return UniformDistribution(min=float(data["min"]), max=float(data["max"]))


def _build_fixed_spec(data: dict[str, Any], block_path: str) -> Optional[float]:
    """Build the fixed value a spec names, refusing it unless it gives a value."""
    if "value" not in data:
        raise ConfigurationError(
            f"fixed distribution for '{block_path}' requires 'value'"
        )
    return _float_or_none(data["value"])


def _build_shuffled_pool_spec(
    data: dict[str, Any], block_path: str
) -> ShuffledPoolDistribution:
    """Build the shuffled_pool distribution a spec names, refusing it unless it gives values and counts."""
    if "values" not in data or "counts" not in data:
        raise ConfigurationError(
            f"shuffled_pool distribution for '{block_path}' requires 'values' and 'counts'"
        )
    return ShuffledPoolDistribution(
        values=tuple(data["values"]),
        counts=tuple(int(c) for c in data["counts"]),
    )


def _parse_proportional_to_multiplier(data: Any, block_path: str) -> Union[float, SweepSpec]:
    """Parse the multiplier of the spec at *block_path*: a number, or a sweep given as a mapping."""
    if not isinstance(data, dict):
        return float(data)
    if data.get("type") != "sweep":
        raise ConfigurationError(
            f"proportional_to multiplier dict for '{block_path}' must have type='sweep'"
        )
    _refuse_unrecognised_keys(_child_path(block_path, "multiplier"), data, _SWEEP_SPEC_KEYS)
    return SweepSpec(
        min=float(data["min"]),
        max=float(data["max"]),
        steps=int(data["steps"]),
        mode=data.get("mode", "geometric"),
    )


def _build_proportional_to_spec(
    data: dict[str, Any], block_path: str
) -> ProportionalDistribution:
    """Build the proportional_to distribution a spec names, refusing it unless it gives a source."""
    if "source" not in data:
        raise ConfigurationError(
            f"proportional_to distribution for '{block_path}' requires 'source'"
        )
    return ProportionalDistribution(
        source=data["source"],
        multiplier=_parse_proportional_to_multiplier(data.get("multiplier", 1.0), block_path),
        offset=float(data.get("offset", 0.0)),
    )


_DISTRIBUTION_SPEC_TYPES: Mapping[str, _BlockType[DistributionSpec]] = MappingProxyType({
    "weighted_discrete": _BlockType(
        frozenset({"type", "values", "weights"}),
        _build_weighted_discrete_spec,
    ),
    "normal": _BlockType(
        frozenset({"type", "mean", "std", "min", "max"}),
        _build_normal_spec,
    ),
    "uniform": _BlockType(
        frozenset({"type", "min", "max"}),
        _build_uniform_spec,
    ),
    "fixed": _BlockType(
        frozenset({"type", "value"}),
        _build_fixed_spec,
    ),
    "shuffled_pool": _BlockType(
        frozenset({"type", "values", "counts"}),
        _build_shuffled_pool_spec,
    ),
    "proportional_to": _BlockType(
        frozenset({"type", "source", "multiplier", "offset"}),
        _build_proportional_to_spec,
    ),
})


def _parse_distribution_spec(data: Any, param_name: str) -> DistributionSpec:
    """Parse a distribution specification from config data.

    Args:
        data: Raw data (scalar, None, or distribution dict)
        param_name: The parameter's path in its file, named in error messages

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
    block_type = _DISTRIBUTION_SPEC_TYPES.get(dist_type) if isinstance(dist_type, str) else None
    if block_type is None:
        raise ConfigurationError(
            f"Unknown distribution type '{dist_type}' for '{param_name}'. "
            f"Supported: {', '.join(_DISTRIBUTION_SPEC_TYPES)}"
        )
    _refuse_unrecognised_keys(param_name, data, block_type.recognised_keys)
    return block_type.build(data, param_name)


_PV_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "capacity_kw", "azimuth", "tilt", "module_efficiency", "inverter_efficiency",
    "system_age_years", "degradation_rate_per_year",
})


def _parse_pv_distribution_config(
    data: dict[str, Any], *, block_path: str
) -> PVDistributionConfig:
    """Parse PV distribution configuration from config data."""
    _refuse_unrecognised_keys(block_path, data, _PV_DISTRIBUTION_BLOCK_KEYS)
    if "capacity_kw" not in data:
        raise ConfigurationError("PV distribution config requires 'capacity_kw'")

    return PVDistributionConfig(
        capacity_kw=_parse_distribution_spec(
            data["capacity_kw"], _child_path(block_path, "capacity_kw")
        ),
        azimuth=_parse_distribution_spec(
            data.get("azimuth", 180.0), _child_path(block_path, "azimuth")
        ),
        tilt=_parse_distribution_spec(data.get("tilt", 35.0), _child_path(block_path, "tilt")),
        module_efficiency=_parse_distribution_spec(
            data.get("module_efficiency"), _child_path(block_path, "module_efficiency")
        ),
        inverter_efficiency=_parse_distribution_spec(
            data.get("inverter_efficiency", 0.96), _child_path(block_path, "inverter_efficiency")
        ),
        system_age_years=_parse_distribution_spec(
            data.get("system_age_years", 0.0), _child_path(block_path, "system_age_years")
        ),
        degradation_rate_per_year=_parse_distribution_spec(
            data.get("degradation_rate_per_year", 0.005),
            _child_path(block_path, "degradation_rate_per_year"),
        ),
    )


_BATTERY_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "capacity_kwh", "max_charge_kw", "max_discharge_kw", "grid_charging", "dispatch_strategy",
})


def _parse_battery_distribution_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[BatteryDistributionConfig]:
    """Parse battery distribution configuration from config data."""
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _BATTERY_DISTRIBUTION_BLOCK_KEYS)

    if "capacity_kwh" not in data:
        raise ConfigurationError("Battery distribution config requires 'capacity_kwh'")

    return BatteryDistributionConfig(
        capacity_kwh=_parse_distribution_spec(
            data["capacity_kwh"], _child_path(block_path, "capacity_kwh")
        ),
        max_charge_kw=_parse_distribution_spec(
            data.get("max_charge_kw", 2.5), _child_path(block_path, "max_charge_kw")
        ),
        max_discharge_kw=_parse_distribution_spec(
            data.get("max_discharge_kw", 2.5), _child_path(block_path, "max_discharge_kw")
        ),
        grid_charging=_parse_grid_charge_config(
            data.get("grid_charging"), block_path=_child_path(block_path, "grid_charging")
        ),
        dispatch_strategy=parse_dispatch_strategy_config(
            data.get("dispatch_strategy"), block_path=_child_path(block_path, "dispatch_strategy")
        ),
    )


_HEAT_PUMP_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "heat_pump_type", "thermal_capacity_kw", "annual_heat_demand_kwh",
})


def _parse_heat_pump_distribution_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[HeatPumpDistributionConfig]:
    """Parse heat pump distribution configuration from config data."""
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _HEAT_PUMP_DISTRIBUTION_BLOCK_KEYS)

    # Parse heat_pump_type - can be string, distribution, or None
    heat_pump_type_raw = data.get("heat_pump_type")
    heat_pump_type: Union[str, DistributionSpec, None]
    if heat_pump_type_raw is None:
        heat_pump_type = None
    elif isinstance(heat_pump_type_raw, str):
        # Direct string value
        heat_pump_type = heat_pump_type_raw
    elif isinstance(heat_pump_type_raw, dict):
        # Distribution spec
        heat_pump_type = _parse_distribution_spec(
            heat_pump_type_raw, _child_path(block_path, "heat_pump_type")
        )
    else:
        raise ConfigurationError(
            f"Invalid heat_pump_type: expected string, dict, or null, got {type(heat_pump_type_raw).__name__}"
        )

    return HeatPumpDistributionConfig(
        heat_pump_type=heat_pump_type,
        thermal_capacity_kw=_parse_distribution_spec(
            data.get("thermal_capacity_kw", 8.0), _child_path(block_path, "thermal_capacity_kw")
        ),
        annual_heat_demand_kwh=_parse_distribution_spec(
            data.get("annual_heat_demand_kwh", 8000.0),
            _child_path(block_path, "annual_heat_demand_kwh"),
        ),
    )


_LOAD_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "annual_consumption_kwh", "household_occupants", "use_stochastic",
})


def _parse_load_distribution_config(
    data: dict[str, Any], *, block_path: str
) -> LoadDistributionConfig:
    """Parse load distribution configuration from config data."""
    _refuse_unrecognised_keys(block_path, data, _LOAD_DISTRIBUTION_BLOCK_KEYS)
    return LoadDistributionConfig(
        annual_consumption_kwh=_parse_distribution_spec(
            data.get("annual_consumption_kwh"), _child_path(block_path, "annual_consumption_kwh")
        ),
        household_occupants=_parse_distribution_spec(
            data.get("household_occupants", 3), _child_path(block_path, "household_occupants")
        ),
        use_stochastic=data.get("use_stochastic", True),
    )


_EV_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "charger_type", "arrival_hour", "departure_hour", "required_charge_kwh",
    "smart_charging_mode",
})


def _parse_charger_type_spec(data: Any, key_path: str) -> DistributionSpec:
    """Read an ev block's charger_type: null, or a weighted_discrete or shuffled_pool of charger types and nulls.

    Any other spec, a bare charger type among them, is refused naming *key_path*, and so is
    a listed value that names no EVChargerType; a null is a home without an EV.
    """
    spec = _parse_distribution_spec(data, key_path) if isinstance(data, dict) else data
    if spec is None:
        return None
    if not isinstance(spec, (WeightedDiscreteDistribution, ShuffledPoolDistribution)):
        raise ConfigurationError(
            f"Invalid {key_path} {data!r}; valid specs: null, or a weighted_discrete or "
            "shuffled_pool of charger types and nulls"
        )
    for value in spec.values:
        if value is not None:
            _require_charger_type(value, key_path)
    return spec


def _require_charger_type(value: object, key_path: str) -> None:
    """Refuse *value*, listed at *key_path*, unless it names an EVChargerType."""
    try:
        EVChargerType(value)
    except ValueError as exc:
        raise ConfigurationError(
            f"Invalid {key_path} value {value!r}; valid values: null or one of "
            f"{[charger.value for charger in EVChargerType]}"
        ) from exc


def _parse_ev_distribution_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[EVDistributionConfig]:
    """Parse EV distribution configuration from config data."""
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _EV_DISTRIBUTION_BLOCK_KEYS)

    if "charger_type" not in data:
        raise ConfigurationError("EV distribution config requires 'charger_type'")

    return EVDistributionConfig(
        charger_type=_parse_charger_type_spec(
            data["charger_type"], _child_path(block_path, "charger_type")
        ),
        arrival_hour=_parse_distribution_spec(
            data.get("arrival_hour", 18.0), _child_path(block_path, "arrival_hour")
        ),
        departure_hour=_parse_distribution_spec(
            data.get("departure_hour", 7.0), _child_path(block_path, "departure_hour")
        ),
        required_charge_kwh=_parse_distribution_spec(
            data.get("required_charge_kwh", 35.0), _child_path(block_path, "required_charge_kwh")
        ),
        smart_charging_mode=data.get("smart_charging_mode", "none"),
    )


_FLEET_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "n_homes", "pv", "load", "battery", "heat_pump", "ev", "seed", "random_order",
    "dispatch_strategy",
})


def _parse_fleet_dispatch_strategy(data: object, *, key_path: str) -> Optional[str]:
    """Read a fleet's dispatch strategy: absent, or one of _VALID_DISPATCH_STRATEGIES."""
    if data is None:
        return None
    if not isinstance(data, str) or data not in _VALID_DISPATCH_STRATEGIES:
        raise ConfigurationError(
            f"Invalid {key_path} {data!r}; valid values: {sorted(_VALID_DISPATCH_STRATEGIES)}"
        )
    return data


def parse_fleet_distribution_config(
    data: dict[str, Any], *, block_path: str = "fleet_distribution"
) -> FleetDistributionConfig:
    """Parse fleet distribution configuration from config data."""
    _refuse_unrecognised_keys(block_path, data, _FLEET_DISTRIBUTION_BLOCK_KEYS)
    if "n_homes" not in data:
        raise ConfigurationError("Fleet distribution config requires 'n_homes'")
    if "pv" not in data:
        raise ConfigurationError("Fleet distribution config requires 'pv' section")

    return FleetDistributionConfig(
        n_homes=int(data["n_homes"]),
        pv=_parse_pv_distribution_config(data["pv"], block_path=_child_path(block_path, "pv")),
        load=_parse_load_distribution_config(
            data.get("load", {}), block_path=_child_path(block_path, "load")
        ),
        battery=_parse_battery_distribution_config(
            data.get("battery"), block_path=_child_path(block_path, "battery")
        ),
        heat_pump=_parse_heat_pump_distribution_config(
            data.get("heat_pump"), block_path=_child_path(block_path, "heat_pump")
        ),
        ev=_parse_ev_distribution_config(data.get("ev"), block_path=_child_path(block_path, "ev")),
        seed=data.get("seed"),
        random_order=data.get("random_order", "default"),
        dispatch_strategy=_parse_fleet_dispatch_strategy(
            data.get("dispatch_strategy"), key_path=_child_path(block_path, "dispatch_strategy")
        ),
    )


def _count_bounds(
    spec: Union[NormalDistribution, UniformDistribution], setting: str
) -> tuple[float, float]:
    """Return the least and greatest whole numbers from *spec*'s min to its max.

    A min or max that *spec* leaves unset, or that is not finite, bounds nothing:
    the least is then -inf and the greatest inf.

    Raises:
        ConfigurationError: If no whole number lies from *spec*'s min to its max,
            naming *setting*, the min and the max.
    """
    least: float = math.ceil(spec.min) if spec.min is not None and math.isfinite(spec.min) else -math.inf
    greatest: float = math.floor(spec.max) if spec.max is not None and math.isfinite(spec.max) else math.inf
    if least > greatest:
        raise ConfigurationError(
            f"{setting} is a count, so a whole number must lie from its min to its max, "
            f"got a min of {spec.min!r} and a max of {spec.max!r}"
        )
    return least, greatest


def _nearest_count(
    draw: float, spec: Union[NormalDistribution, UniformDistribution], setting: str
) -> float:
    """Return the whole number nearest *draw* among those from *spec*'s min to its max, as a float.

    A half rounds up. _count_bounds says which whole numbers *spec* allows.

    Raises:
        ConfigurationError: As _count_bounds, if no whole number lies from *spec*'s
            min to its max.
    """
    least, greatest = _count_bounds(spec, setting)
    whole = math.floor(draw)
    nearest = whole + 1 if draw - whole >= 0.5 else whole
    return float(min(max(nearest, least), greatest))


class _DistributionSampler:
    """Draws a fleet's settings home by home, from one RNG seeded with the fleet's seed.

    Before the first home it draws ahead what the fleet's random order says, each
    setting's values under the setting's path. A setting drawn ahead hands out its
    values in order, one per home; any other setting is drawn afresh from its spec.
    """

    def __init__(self, config: FleetDistributionConfig) -> None:
        self._rng = random.Random(config.seed)
        self._drawn_ahead: dict[str, list[Optional[float]]] = {}
        self._handed_out: dict[str, int] = {}
        order = _RANDOM_ORDERS[config.random_order]
        settings = dict(_component_settings(config))
        for setting in order.pre_sampled:
            spec = settings.get(setting)
            if isinstance(spec, (WeightedDiscreteDistribution, NormalDistribution, UniformDistribution)):
                self._drawn_ahead[setting] = [spec.draw(self._rng) for _ in range(config.n_homes)]
        pools = dict(_shuffled_pools(config))
        shuffled_first = [setting for setting in order.shuffled_first if setting in pools]
        for setting in shuffled_first + [setting for setting in pools if setting not in shuffled_first]:
            values = pools[setting].create_pool()
            self._rng.shuffle(values)
            self._drawn_ahead[setting] = values

    def sample(self, spec: DistributionSpec, setting: str) -> Optional[float]:
        """Draw the next home's value of *setting* from *spec*.

        A setting drawn ahead hands out its next value. Any other is drawn afresh: None
        gives None, a fixed number gives itself as a float, and a weighted discrete,
        normal or uniform spec draws from the RNG.

        Args:
            spec: The setting's distribution specification
            setting: The setting's path in the fleet distribution, e.g. 'pv.tilt'

        Returns:
            Sampled value (float or None)

        Raises:
            ConfigurationError: If *setting* was drawn ahead and every value of it is
                handed out, or if *spec* cannot be drawn afresh, as a proportional_to
                without its source's value or a pool not drawn ahead for *setting*
                cannot, naming *setting*; or if *spec* is a normal or uniform
                distribution and the value it draws is not a finite number, naming
                *setting* and the draw. A normal's draw is checked after its min and
                max clamp it.
        """
        value = self._next_value(spec, setting)
        if (
            isinstance(spec, (NormalDistribution, UniformDistribution))
            and value is not None
            and not math.isfinite(value)
        ):
            raise ConfigurationError(
                f"{setting} must draw samples that are finite numbers, got a sample of {value!r}"
            )
        return value

    def _next_value(self, spec: DistributionSpec, setting: str) -> Optional[float]:
        if setting in self._drawn_ahead:
            return self._next_value_drawn_ahead(setting)
        if spec is None:
            return None
        if isinstance(spec, (int, float)):
            return float(spec)
        if isinstance(spec, (WeightedDiscreteDistribution, NormalDistribution, UniformDistribution)):
            return spec.draw(self._rng)
        raise ConfigurationError(f"{setting} cannot be drawn from {spec!r}")

    def _next_value_drawn_ahead(self, setting: str) -> Optional[float]:
        values = self._drawn_ahead[setting]
        handed_out = self._handed_out.get(setting, 0)
        if handed_out == len(values):
            raise ConfigurationError(
                f"{setting} has no value left to draw: its {len(values)} values, one per home, are all drawn"
            )
        self._handed_out[setting] = handed_out + 1
        return values[handed_out]

    def sample_count(self, spec: DistributionSpec, setting: str) -> Optional[float]:
        """Sample a count of *setting* from *spec*.

        A draw from a normal or uniform distribution gives the whole number
        nearest it among those from the spec's min to its max, a half rounding
        up, as _nearest_count states. The whole number is returned as a float,
        so a refusal of the count names it as drawn, 1e+300 rather than the
        301-digit int it equals. A fixed value is returned as the spec gives
        it, and any other value as drawn.

        Args:
            spec: The setting's distribution specification
            setting: The setting's path in the fleet distribution, e.g. 'load.household_occupants'

        Raises:
            ConfigurationError: If *spec* is a normal or uniform distribution with
                no whole number from its min to its max, naming *setting*, the min
                and the max; or, as sample does, for a normal or uniform draw that
                is not a finite number.
        """
        if isinstance(spec, (int, float)):
            return spec
        value = self.sample(spec, setting)
        if value is not None and isinstance(spec, (NormalDistribution, UniformDistribution)):
            return _nearest_count(value, spec, setting)
        return value

    def sample_finite(self, spec: DistributionSpec, setting: str) -> Optional[float]:
        """Sample *setting* from *spec*, refusing an infinity or a NaN whichever spec gives it.

        Any other value is returned as sample gives it.

        Args:
            spec: The setting's distribution specification
            setting: The setting's path in the fleet distribution, e.g. 'ev.arrival_hour'

        Raises:
            ConfigurationError: As sample does; or if the value is an infinity or a
                NaN, naming *setting* and the value.
        """
        value = self.sample(spec, setting)
        if isinstance(value, float) and not math.isfinite(value):
            raise ConfigurationError(f"{setting} must be a finite number, got {value!r}")
        return value

    def sample_with_context(
        self, spec: DistributionSpec, context: dict[str, Optional[float]], setting: str
    ) -> Optional[float]:
        """Sample with support for ProportionalDistribution.

        For ProportionalDistribution, looks up the source value from context
        and applies multiplier and offset; the home's component type checks
        that computed value. For other distributions, delegates to the regular
        sample method, which checks the draw.

        Args:
            spec: Distribution specification
            context: Dict mapping field paths to sampled values
            setting: The setting's path in the fleet distribution, e.g. 'battery.capacity_kwh'

        Returns:
            Sampled value (float or None)

        Raises:
            ConfigurationError: For a ProportionalDistribution whose multiplier is a
                SweepSpec; or, as sample does, for a normal or uniform draw that is
                not a finite number.
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
        return self.sample(spec, setting)


def generate_homes_from_distribution(
    config: FleetDistributionConfig,
    location: Location,
    *,
    fleet_tariff: Optional[TariffConfig] = None,
) -> list[HomeConfig]:
    """Generate a list of homes by sampling from distributions.

    Args:
        config: Fleet distribution configuration
        location: Location for all homes
        fleet_tariff: Optional TariffConfig to apply to every home. When None
            (default) homes are generated with tariff_config=None, preserving
            bit-identical behaviour for callers that do not pass this kwarg.

    Returns:
        List of HomeConfig objects

    Raises:
        ConfigurationError: If a shuffled pool's counts do not total config.n_homes,
            naming the pool; if a setting's spec cannot be drawn for it, e.g. a
            proportional_to outside the battery and heat pump settings, naming the
            setting; if a normal or uniform draw is not a finite number, naming the
            setting and the draw; if load.household_occupants is a normal or uniform
            with no whole number from its min to its max, naming it, the min and the
            max; if a sampled PV capacity is not positive; if a sampled heat pump
            type is not one of heat_pump.HEAT_PUMP_TYPES; or if an EV hour is an
            infinity or a NaN, whichever spec gives it, naming its setting and the
            hour.
        ValueError: If a sampled battery capacity is negative or not finite,
            naming battery.capacity_kwh (a null or 0 sample is no battery), or
            if load.household_occupant_count refuses a home's household occupants.
    """
    _refuse_pools_not_sized_to_the_fleet(config)
    sampler = _DistributionSampler(config)
    homes: list[HomeConfig] = []

    for i in range(config.n_homes):
        # Sample PV parameters
        pv_capacity = sampler.sample(config.pv.capacity_kw, "pv.capacity_kw")
        if pv_capacity is None or pv_capacity <= 0:
            raise ConfigurationError(f"PV capacity must be positive, got {pv_capacity}")

        pv_azimuth = sampler.sample(config.pv.azimuth, "pv.azimuth")
        pv_tilt = sampler.sample(config.pv.tilt, "pv.tilt")
        pv_module_eff = sampler.sample(config.pv.module_efficiency, "pv.module_efficiency")
        pv_inverter_eff = sampler.sample(config.pv.inverter_efficiency, "pv.inverter_efficiency")
        pv_age = sampler.sample(config.pv.system_age_years, "pv.system_age_years")
        pv_degradation = sampler.sample(
            config.pv.degradation_rate_per_year, "pv.degradation_rate_per_year"
        )

        pv_config = PVConfig(
            capacity_kw=pv_capacity,
            azimuth=pv_azimuth if pv_azimuth is not None else 180.0,
            tilt=pv_tilt if pv_tilt is not None else 35.0,
            module_efficiency=pv_module_eff,
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
                config.battery.capacity_kwh, context, "battery.capacity_kwh"
            )
            if battery_capacity is not None and has_battery(
                battery_capacity, "battery.capacity_kwh"
            ):
                charge_kw = sampler.sample_with_context(
                    config.battery.max_charge_kw, context, "battery.max_charge_kw"
                )
                discharge_kw = sampler.sample_with_context(
                    config.battery.max_discharge_kw, context, "battery.max_discharge_kw"
                )
                battery_config = BatteryConfig(
                    capacity_kwh=battery_capacity,
                    max_charge_kw=charge_kw if charge_kw is not None else 2.5,
                    max_discharge_kw=discharge_kw if discharge_kw is not None else 2.5,
                    grid_charging=config.battery.grid_charging,
                    dispatch_strategy=config.battery.dispatch_strategy,
                )

        # Sample load parameters
        annual_consumption = sampler.sample(
            config.load.annual_consumption_kwh, "load.annual_consumption_kwh"
        )
        occupants_draw = sampler.sample_count(
            config.load.household_occupants, "load.household_occupants"
        )

        # Derive per-home seed for reproducible stochastic load profiles
        home_seed: Optional[int] = None
        if config.seed is not None:
            home_seed = config.seed + i

        load_config = LoadConfig(
            annual_consumption_kwh=annual_consumption,
            household_occupants=(
                LoadConfig.household_occupants
                if occupants_draw is None
                else household_occupant_count(occupants_draw)
            ),
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
                heat_pump_type = sampler.sample(  # type: ignore[assignment]
                    config.heat_pump.heat_pump_type, "heat_pump.heat_pump_type"
                )
            else:
                heat_pump_type = None

            if heat_pump_type is not None:
                if heat_pump_type not in HEAT_PUMP_TYPES:
                    raise ConfigurationError(
                        f"Invalid heat pump type sampled: '{heat_pump_type}'. "
                        f"Must be one of {HEAT_PUMP_TYPES}"
                    )

                thermal_capacity = sampler.sample_with_context(
                    config.heat_pump.thermal_capacity_kw, context, "heat_pump.thermal_capacity_kw"
                )
                annual_heat_demand = sampler.sample_with_context(
                    config.heat_pump.annual_heat_demand_kwh, context, "heat_pump.annual_heat_demand_kwh"
                )
                heat_pump_config = HeatPumpConfig(
                    heat_pump_type=heat_pump_type,
                    thermal_capacity_kw=thermal_capacity if thermal_capacity is not None else 8.0,
                    annual_heat_demand_kwh=annual_heat_demand if annual_heat_demand is not None else 8000.0,
                )

        # Sample EV parameters (may be None)
        ev_config: Optional[EVConfig] = None
        if config.ev is not None:
            charger_type = sampler.sample(config.ev.charger_type, "ev.charger_type")
            if charger_type is not None:
                arrival_hour_val = sampler.sample_finite(config.ev.arrival_hour, "ev.arrival_hour")
                departure_hour_val = sampler.sample_finite(
                    config.ev.departure_hour, "ev.departure_hour"
                )
                required_charge_val = sampler.sample(
                    config.ev.required_charge_kwh, "ev.required_charge_kwh"
                )

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
                dispatch_strategy=config.dispatch_strategy or "greedy",
            )
        )

    return homes


_SEG_BLOCK_KEYS: frozenset[str] = frozenset({"preset", "rate_pence_per_kwh"})


def parse_seg_rate(data: object, *, block_path: str = "seg") -> Optional[float]:
    """Read the SEG export rate in pence/kWh from a ``seg:`` block.

    The block names exactly one of a :data:`~solar_challenge.seg.SEG_PRESETS`
    ``preset`` or a ``rate_pence_per_kwh`` that :func:`_parse_seg_rate_scalar`
    accepts.  ``None`` means no SEG; any other shape raises
    :exc:`ConfigurationError` naming *block_path*.
    """
    if data is None:
        return None
    data = _refuse_unrecognised_keys(block_path, data, _SEG_BLOCK_KEYS)
    if ("preset" in data) == ("rate_pence_per_kwh" in data):
        raise ConfigurationError(
            f"'{block_path}' must specify exactly one of 'preset' or "
            f"'rate_pence_per_kwh', got {data!r}"
        )
    if "rate_pence_per_kwh" in data:
        return _parse_seg_rate_scalar(
            data["rate_pence_per_kwh"], key_path=f"{block_path}.rate_pence_per_kwh"
        )
    try:
        return resolve_seg_tariff(data["preset"]).rate_pence_per_kwh
    except (ValueError, TypeError) as exc:
        raise ConfigurationError(f"'{block_path}' block {data!r} is invalid: {exc}") from exc


def _parse_seg_rate_scalar(value: Any, *, key_path: str) -> float:
    """Read a SEG export rate in pence/kWh: a finite number that :class:`SEGTariff` accepts."""
    try:
        rate = float(value)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f"'{key_path}' must be a number, got {value!r}") from exc
    if isinstance(value, bool) or not math.isfinite(rate):
        raise ConfigurationError(f"'{key_path}' must be a finite number, got {value!r}")
    try:
        return SEGTariff(name="", rate_pence_per_kwh=rate).rate_pence_per_kwh
    except ValueError as exc:
        raise ConfigurationError(f"'{key_path}' is invalid: {exc}") from exc


# Rows follow FinanceConfig's field order, which decides the first bad value reported.
_FINANCE_SCALAR_COERCIONS: Mapping[str, Callable[[Any], Any]] = MappingProxyType({
    "standing_charge_pence_per_day": _number,
    "vat_rate": _number,
    "retail_baseline_rate_pence_per_kwh": _number,
    "self_consumption_override": _number_or_none,
    "pv_cost_per_kwp_gbp": _number,
    "roof_fit_cost_gbp": _number,
    "battery_cost_per_kwh_gbp": _number,
    "inverter_cost_per_kw_gbp": _number,
    "grant_gbp": _number,
    "equity_fraction": _number,
    "loan_term_years": _number,
    "loan_rate": _number,
    "opex_per_home_per_year_gbp": _number,
    "asset_life_years": _number,
    "own_use_rate_pence_per_kwh": _number,
    "retained_cash_floor_per_home_per_year_gbp": _number,
    "grid_services_income_per_kw_per_year_gbp": _number,
    "grid_services_model": str,
})

_FINANCE_BLOCK_KEYS: frozenset[str] = frozenset({
    *_FINANCE_SCALAR_COERCIONS, "grid_services_events",
})

# Rows follow GridServicesEventsConfig's field order, which decides the first bad value reported.
_GRID_SERVICES_EVENTS_SCALAR_COERCIONS: Mapping[str, Callable[[Any], Any]] = MappingProxyType({
    "band": str,
    "aggregator_share": _number,
    "utilisation_factor": _number,
    "availability_gbp_per_kw_per_event": _number_or_none,
    "utilisation_gbp_per_mwh": _number_or_none,
})

_GRID_SERVICES_EVENTS_BLOCK_KEYS: frozenset[str] = frozenset({
    *_GRID_SERVICES_EVENTS_SCALAR_COERCIONS, "event_windows",
})


def _int_tuple(values: Any) -> tuple[int, ...]:
    """Coerce each of *values* to an int as int() does, keeping their order."""
    return tuple(int(value) for value in values)


# Rows follow EventWindow's field order, which decides the first bad value reported.
_EVENT_WINDOW_COERCIONS: Mapping[str, Callable[[Any], Any]] = MappingProxyType({
    "months": _int_tuple,
    "weekdays": _int_tuple,
    "hours": _int_tuple,
    "events_per_year": int,
    "event_hours": _number,
})


def _parse_event_windows(data: object, *, block_path: str) -> tuple[EventWindow, ...]:
    """Parse the event_windows list at *block_path* into EventWindows."""
    if not isinstance(data, list):
        raise ConfigurationError(f"{block_path} must be a list of window dicts")
    parsed_windows: list[EventWindow] = []
    for i, ew_dict in enumerate(data):
        window_path = f"{block_path}[{i}]"
        _refuse_unrecognised_keys(window_path, ew_dict, _EVENT_WINDOW_COERCIONS)
        for req_key in _EVENT_WINDOW_COERCIONS:
            if req_key not in ew_dict:
                raise ConfigurationError(f"{window_path} requires '{req_key}' field")
        try:
            fields = {key: coerce(ew_dict[key]) for key, coerce in _EVENT_WINDOW_COERCIONS.items()}
        except (ValueError, TypeError, OverflowError) as exc:
            raise ConfigurationError(
                f"{window_path} contains a non-numeric value: {exc}"
            ) from exc
        parsed_windows.append(EventWindow(**fields))
    return tuple(parsed_windows)


def _parse_grid_services_events_config(
    data: object, *, block_path: str
) -> Optional[GridServicesEventsConfig]:
    """Parse a finance block's grid_services_events block; absent or null is no events config.

    A key the block omits takes GridServicesEventsConfig's declared default, so an omitted
    event_windows is the default schedule, DEFAULT_EVENT_WINDOWS.
    """
    if data is None:
        return None
    gs_data = _refuse_unrecognised_keys(block_path, data, _GRID_SERVICES_EVENTS_BLOCK_KEYS)
    fields: dict[str, Any] = {}
    if "event_windows" in gs_data:
        fields["event_windows"] = _parse_event_windows(
            gs_data["event_windows"], block_path=_child_path(block_path, "event_windows")
        )
    try:
        fields.update(
            (key, coerce(gs_data[key]))
            for key, coerce in _GRID_SERVICES_EVENTS_SCALAR_COERCIONS.items()
            if key in gs_data
        )
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(
            f"grid_services_events block contains a non-numeric value: {exc}"
        ) from exc
    return GridServicesEventsConfig(**fields)


def parse_finance_config(
    data: Optional[dict[str, Any]], *, block_path: str = "finance"
) -> Optional[FinanceConfig]:
    """Parse finance configuration from config data.

    A key the block omits takes FinanceConfig's declared default.

    Args:
        data: Finance configuration dictionary or None
        block_path: The block's path in its file, named in error messages

    Returns:
        FinanceConfig object or None if data is None

    Raises:
        ConfigurationError: If any field value is out of its allowed range
            (propagated from FinanceConfig.__post_init__), if a numeric value
            is a boolean or a value float() cannot read, or if the block, its
            grid_services_events block or an event window is not a mapping or
            carries a key it does not read
    """
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _FINANCE_BLOCK_KEYS)
    if "standing_charge_pence_per_day" not in data:
        raise ConfigurationError(
            "finance.standing_charge_pence_per_day is required"
        )

    grid_services_events = _parse_grid_services_events_config(
        data.get("grid_services_events"),
        block_path=_child_path(block_path, "grid_services_events"),
    )
    try:
        scalars = {
            key: coerce(data[key])
            for key, coerce in _FINANCE_SCALAR_COERCIONS.items()
            if key in data
        }
    except (ValueError, TypeError, OverflowError) as exc:
        raise ConfigurationError(f"finance block contains a non-numeric value: {exc}") from exc
    return FinanceConfig(**scalars, grid_services_events=grid_services_events)


def _parse_scenario(data: dict[str, Any], *, block_path: str) -> ScenarioConfig:
    """Parse a scenario from config data."""
    if "name" not in data:
        raise ConfigurationError("Scenario must have a 'name' field")
    if "period" not in data:
        raise ConfigurationError(f"Scenario '{data['name']}' must have a 'period' field")

    location = parse_location_block(
        data.get("location"), block_path=_child_path(block_path, "location")
    )

    homes: list[HomeConfig] = []
    home: Optional[HomeConfig] = None

    if "homes" in data:
        for index, home_data in enumerate(data["homes"]):
            homes.append(
                parse_home_block(
                    home_data, location, block_path=_child_path(block_path, f"homes[{index}]")
                )
            )
    elif "home" in data:
        home = parse_home_block(data["home"], location, block_path=_child_path(block_path, "home"))
    else:
        raise ConfigurationError(
            f"Scenario '{data['name']}' must define either 'home' or 'homes'"
        )

    return ScenarioConfig(
        name=data["name"],
        description=data.get("description", ""),
        location=location,
        period=_parse_period(data["period"], block_path=_child_path(block_path, "period")),
        homes=homes,
        home=home,
        output=_parse_output_config(
            data.get("output"), block_path=_child_path(block_path, "output")
        ),
        seg_tariff_pence_per_kwh=parse_seg_rate(
            data.get("seg"), block_path=_child_path(block_path, "seg")
        ),
        tariff_config=parse_tariff_config(
            data.get("tariff_config"), block_path=_child_path(block_path, "tariff_config")
        ),
        finance=parse_finance_config(
            data.get("finance"), block_path=_child_path(block_path, "finance")
        ),
    )


_PLACEHOLDER_PATTERN = re.compile(r"\$\{(?P<name>[^}:]+)(?::(?P<default>[^}]*))?\}")


@dataclass(frozen=True)
class _Placeholder:
    """A ${NAME} or ${NAME:default} placeholder: the whole string value at *path* in a document."""

    path: str
    name: str
    default: Optional[float]

    def value(self, variables: Mapping[str, float]) -> Optional[float]:
        """The value *variables* gives NAME, else the default, else None."""
        return variables.get(self.name, self.default)


def _read_placeholder(path: str, text: str) -> Optional[_Placeholder]:
    """The placeholder that *text*, the string value at *path*, is; None if *text* holds none.

    Raises:
        ConfigurationError: naming the key path and the variable, for a placeholder inside a
            longer string, or for a default that is not a finite number.
    """
    whole = _PLACEHOLDER_PATTERN.fullmatch(text)
    if whole is not None:
        name, default = whole["name"], whole["default"]
        default_field = f"{_block_label(path)}: the default of variable {name!r}"
        return _Placeholder(path, name, None if default is None else as_finite_float(default, default_field))
    inside = _PLACEHOLDER_PATTERN.search(text)
    if inside is not None:
        raise ConfigurationError(
            f"{_block_label(path)}: variable {inside['name']!r} is inside the longer string {text!r}; "
            "a placeholder must be the whole value"
        )
    return None


_Document = TypeVar("_Document")


@dataclass(frozen=True)
class _Substitution(Generic[_Document]):
    """A document with each placeholder that has a value replaced by it, read whole through document().

    *partial* is that document, in which a placeholder with no value stays as its text.
    *placeholders* is every placeholder the document held, in document order.
    """

    partial: _Document
    placeholders: tuple[_Placeholder, ...] = ()

    def document(self, variables: Mapping[str, float]) -> _Document:
        """*partial*, once a placeholder names each of *variables*, the variables it was substituted with, and each placeholder has a value.

        Raises:
            ConfigurationError: listing the placeholders, for a supplied variable none of them
                names; then, naming its key path and its variable, for a placeholder neither
                supplied nor defaulted.
        """
        _refuse_unmatched_variables(variables, self.placeholders)
        _refuse_placeholders_without_a_value(variables, self.placeholders)
        return self.partial


def _placeholders_of(parts: Iterable[_Substitution[Any]]) -> tuple[_Placeholder, ...]:
    """The placeholders of each of *parts*, in order."""
    return tuple(placeholder for part in parts for placeholder in part.placeholders)


def _substitute_variables(data: Any, variables: Mapping[str, float], path: str) -> _Substitution[Any]:
    """*data*, the document at *path*, with each placeholder that has a value replaced by it, and every placeholder *data* holds; *data* is left unchanged.

    A placeholder's value is the one *variables* gives its variable, else its default; a
    placeholder with neither stays as its text.
    """
    if isinstance(data, str):
        placeholder = _read_placeholder(path, data)
        if placeholder is None:
            return _Substitution(data)
        value = placeholder.value(variables)
        return _Substitution(data if value is None else value, (placeholder,))
    if isinstance(data, dict):
        return _substitute_mapping(data, variables, path)
    if isinstance(data, list):
        items = [_substitute_variables(item, variables, f"{path}[{index}]") for index, item in enumerate(data)]
        return _Substitution([each.partial for each in items], _placeholders_of(items))
    return _Substitution(data)


_Key = TypeVar("_Key")


def _substitute_mapping(
    data: Mapping[_Key, Any], variables: Mapping[str, float], path: str
) -> _Substitution[dict[_Key, Any]]:
    """*data*, the mapping at *path*, as a new dict of its keys and their values substituted, and the placeholders those hold; its keys are not read."""
    entries = {
        key: _substitute_variables(child, variables, _child_path(path, str(key)))
        for key, child in data.items()
    }
    return _Substitution(
        {key: entry.partial for key, entry in entries.items()}, _placeholders_of(entries.values())
    )


def _refuse_unmatched_variables(
    variables: Mapping[str, float], placeholders: tuple[_Placeholder, ...]
) -> None:
    """Refuse *variables* if one of them is named by none of *placeholders*, the document's, listing those."""
    unmatched = sorted(repr(name) for name in variables.keys() - {each.name for each in placeholders})
    if unmatched:
        listed = ", ".join(f"{each.name!r} at {_block_label(each.path)}" for each in placeholders)
        held = f"its placeholders: {listed}" if placeholders else "it holds no placeholders"
        raise ConfigurationError(
            f"Variables with no placeholder in the document: {', '.join(unmatched)}; {held}"
        )


def _refuse_placeholders_without_a_value(
    variables: Mapping[str, float], placeholders: tuple[_Placeholder, ...]
) -> None:
    """Refuse the first of *placeholders* that neither *variables* nor its default gives a value, naming its key path and its variable."""
    for each in placeholders:
        if each.value(variables) is None:
            raise ConfigurationError(
                f"{_block_label(each.path)}: variable {each.name!r} is not supplied and has no default"
            )


def substitute_config_variables(
    config: dict[str, Any], variables: Optional[dict[str, float]] = None
) -> dict[str, Any]:
    """Return *config* with each placeholder in it replaced by its variable's value; *config* is left unchanged.

    A placeholder, ${NAME} or ${NAME:default}, is the whole of a string value in the document.
    It is replaced by the value *variables* gives NAME, else by its default.

    Args:
        config: Configuration dictionary
        variables: Dict mapping variable names to values (default: empty)

    Returns:
        Configuration with variables substituted

    Raises:
        ConfigurationError: naming its key path and its variable, for a placeholder inside a
            longer string or a default that is not a finite number, as the document is read, in
            document order; then, listing the document's placeholders, for a supplied variable
            none of them names; then, naming its key path and its variable, for a placeholder
            neither supplied nor defaulted.
    """
    supplied = variables or {}
    substitution = _substitute_mapping(config, supplied, "")
    return substitution.document(supplied)


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

    swept_battery = replace(config.battery, capacity_kwh=replace(cap_spec, multiplier=value))
    return replace(config, battery=swept_battery)


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
        return [
            _parse_scenario(scenario, block_path=f"scenarios[{index}]")
            for index, scenario in enumerate(config["scenarios"])
        ]
    elif "scenario" in config:
        return [_parse_scenario(config["scenario"], block_path="scenario")]
    else:
        # Try to parse the entire config as a single scenario
        return [_parse_scenario(config, block_path="")]


_FLAT_HOME_FILE_KEYS: frozenset[str] = _HOME_BLOCK_KEYS | {"location"}


def load_home_config(path: Union[str, Path]) -> HomeConfig:
    """Load a single home configuration from file.

    The file holds a ``home:`` block, or is itself a home block beside an
    optional ``location:`` block.

    Args:
        path: Path to configuration file

    Returns:
        HomeConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    config = load_config(path)
    location = parse_location_block(config.get("location"))

    if "home" in config:
        return parse_home_block(config["home"], location)
    _refuse_unrecognised_keys("", config, _FLAT_HOME_FILE_KEYS)
    flat_home = {key: value for key, value in config.items() if key != "location"}
    return parse_home_block(flat_home, location, block_path="")


@dataclass(frozen=True)
class _FleetFileSettings:
    """What a fleet file gives every home its fleet_distribution: block generates.

    Attributes:
        location: The file's location: block, Bristol when it has none
        tariff: The file's top-level tariff: block, None when it has none
    """

    location: Location
    tariff: Optional[TariffConfig]

    def generate_homes(self, distribution: FleetDistributionConfig) -> list[HomeConfig]:
        """The homes *distribution* generates, each given the file's settings."""
        return generate_homes_from_distribution(
            distribution, self.location, fleet_tariff=self.tariff
        )


def _read_fleet_distribution_file(
    document: Mapping[str, Any],
) -> tuple[FleetDistributionConfig, _FleetFileSettings]:
    """Read the fleet_distribution: block of *document*, with what the file gives every home it generates.

    The one place that decides which top-level blocks those homes get. It reads location:,
    fleet_distribution: and tariff: in that order, and warns when the block dispatches
    tou_optimized with no tariff to dispatch by.
    """
    location = parse_location_block(document.get("location"))
    distribution = parse_fleet_distribution_config(document["fleet_distribution"])
    tariff = parse_tariff_config(document.get("tariff"))
    if distribution.dispatch_strategy == "tou_optimized" and tariff is None:
        warnings.warn(
            "fleet_distribution.dispatch_strategy is 'tou_optimized' but no tariff "
            "is configured; homes will fall back to self-consumption dispatch at "
            "simulation time. Add a top-level 'tariff:' key to the fleet YAML to "
            "enable Economy-7 grid-charging.",
            UserWarning,
            stacklevel=3,
        )
    return distribution, _FleetFileSettings(location=location, tariff=tariff)


def parse_fleet_config(document: Mapping[str, Any]) -> FleetConfig:
    """Parse a fleet file's document, already loaded or variable-substituted.

    Supports two formats:
    - Explicit homes list: `homes: [...]`
    - Distribution-based generation: `fleet_distribution: {...}`

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    if "fleet_distribution" in document:
        distribution, settings = _read_fleet_distribution_file(document)
        homes = settings.generate_homes(distribution)
    elif "homes" in document:
        location = parse_location_block(document.get("location"))
        homes_data = document["homes"]
        if not homes_data:
            raise ConfigurationError("Fleet 'homes' list cannot be empty")
        homes = [
            parse_home_block(home_data, location, block_path=f"homes[{index}]")
            for index, home_data in enumerate(homes_data)
        ]
    else:
        raise ConfigurationError(
            "Fleet configuration requires either 'homes' list or 'fleet_distribution'"
        )

    return FleetConfig(homes=homes, name=document.get("name", ""))


def load_fleet_config(path: Union[str, Path]) -> FleetConfig:
    """Load a fleet configuration from file, as parse_fleet_config parses its document.

    Args:
        path: Path to configuration file

    Returns:
        FleetConfig object

    Raises:
        ConfigurationError: If configuration is invalid
    """
    return parse_fleet_config(load_config(path))


def detect_fleet_sweep_spec(document: Mapping[str, Any]) -> Optional[SweepSpec]:
    """Find the SweepSpec of the document's YAML-defined sweep, the sweep parse_sweep_fleet_configs builds.

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        The SweepSpec detect_sweep_spec finds in its fleet_distribution: block, None when
        it has no such block or the block no sweep

    Raises:
        ConfigurationError: If its fleet_distribution: block is invalid
    """
    if "fleet_distribution" not in document:
        return None
    return detect_sweep_spec(parse_fleet_distribution_config(document["fleet_distribution"]))


def parse_sweep_fleet_configs(document: Mapping[str, Any]) -> list[tuple[float, FleetConfig]]:
    """The fleet each point of the document's YAML-defined sweep builds, with its sweep value.

    The sweep is the fleet_distribution: block's battery.capacity_kwh multiplier. Every
    point's homes get the file's top-level blocks as parse_fleet_config gives them, read
    once for the whole file.

    Args:
        document: The fleet file's configuration dictionary

    Returns:
        (sweep value, FleetConfig named after it) for each sweep point, in sweep order

    Raises:
        ConfigurationError: If the document has no fleet_distribution: block or no
            sweep, or if configuration is invalid
    """
    if "fleet_distribution" not in document:
        raise ConfigurationError("A YAML-defined sweep requires a 'fleet_distribution' block")
    distribution, settings = _read_fleet_distribution_file(document)
    return [
        (value, FleetConfig(homes=settings.generate_homes(point), name=f"multiplier={value:.4f}"))
        for value, point in expand_sweep_configs(distribution)
    ]


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
        ValueError: If the swept parameter's config refuses a value (for
            household_occupants, see load.household_occupant_count).
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
            home_results = simulate_home(home, start, end, weather=default_weather())
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
        if param_name == "battery_capacity_kwh" and has_battery(value, param_name):
            return BatteryConfig(capacity_kwh=value)
        return None

    if param_name == "battery_capacity_kwh":
        if not has_battery(value, param_name):
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
        return replace(config, household_occupants=household_occupant_count(value))
    return config


# ---------------------------------------------------------------------------
# Community config parsing
# ---------------------------------------------------------------------------


_COMMUNITY_BILLING_BLOCK_KEYS: frozenset[str] = frozenset({
    "tariff", "seg_rate_pence_per_kwh", "seg",
})


def _parse_community_billing_config(
    data: Optional[dict[str, Any]], *, block_path: str
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
        block_path: The block's path in its file, named in error messages.

    Returns:
        ``CommunityBillingConfig`` when *data* is a dict; ``None`` otherwise.

    Raises:
        ConfigurationError: For a block that is not a mapping or carries a key it
            does not read, an ambiguous SEG specification, a malformed ``seg``
            block or an invalid ``seg_rate_pence_per_kwh``.
    """
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _COMMUNITY_BILLING_BLOCK_KEYS)

    tariff = parse_tariff_config(data.get("tariff"), block_path=_child_path(block_path, "tariff"))

    # Resolve SEG rate (three mutually-exclusive forms)
    direct_rate: Optional[float] = None
    if "seg_rate_pence_per_kwh" in data:
        direct_rate = _parse_seg_rate_scalar(
            data["seg_rate_pence_per_kwh"],
            key_path=_child_path(block_path, "seg_rate_pence_per_kwh"),
        )

    seg_block = data.get("seg")

    if direct_rate is not None and seg_block is not None:
        raise ConfigurationError(
            "community billing: specify either 'seg_rate_pence_per_kwh' (scalar) "
            "or 'seg' block — not both."
        )

    seg_rate = (
        direct_rate
        if direct_rate is not None
        else parse_seg_rate(seg_block, block_path=_child_path(block_path, "seg"))
    )

    # Normalise an all-None result to None so callers can reliably test ``is None``
    # for "no billing configured" without distinguishing an empty block from an
    # absent key.
    if tariff is None and seg_rate is None:
        return None
    return CommunityBillingConfig(tariff=tariff, seg_rate_pence_per_kwh=seg_rate)


_COMMUNITY_BLOCK_KEYS: frozenset[str] = frozenset({
    "sharing_mode", "community_battery", "billing",
})


def _parse_community_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[CommunityConfig]:
    """Parse a ``community:`` YAML block into a :class:`CommunityConfig`.

    Args:
        data: Community configuration dictionary, or None.
        block_path: The block's path in its file, named in error messages.

    Returns:
        ``CommunityConfig`` when *data* is a dict; ``None`` when *data* is ``None``.

    Raises:
        ConfigurationError: For a block that is not a mapping or carries a key it
            does not read, missing/invalid ``sharing_mode``, p2p+battery,
            community_battery-without-battery, or any nested config error.
    """
    if data is None:
        return None
    _refuse_unrecognised_keys(block_path, data, _COMMUNITY_BLOCK_KEYS)

    sharing_mode = data.get("sharing_mode")
    if not sharing_mode:
        raise ConfigurationError(
            "community: block requires a 'sharing_mode' field "
            "('p2p' or 'community_battery')"
        )

    community_battery = _parse_battery_config(
        data.get("community_battery"), block_path=_child_path(block_path, "community_battery")
    )
    billing = _parse_community_billing_config(
        data.get("billing"), block_path=_child_path(block_path, "billing")
    )

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
    return _parse_community_config(data.get("community"), block_path="community")
