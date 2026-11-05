# SPDX-License-Identifier: AGPL-3.0-or-later
"""Configuration file support for simulation scenarios.

Supports loading configurations from YAML and JSON files and
scenario definitions.
"""

import json
import math
import random
import re
from dataclasses import MISSING, asdict, dataclass, field, fields, replace
from enum import Enum
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

from solar_challenge.battery import BatteryConfig, has_battery
from solar_challenge.boolean_fields import as_boolean
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.dispatch import STRATEGY_CONFIG_BY_TYPE, DispatchStrategyConfig, GridChargeConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import CHARGER_TYPES, EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.fleet import FleetConfig
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.heat_pump import HEAT_PUMP_TYPES, HeatPumpConfig
from solar_challenge.home import HOME_DISPATCH_STRATEGIES, HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import as_finite_float
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from solar_challenge.tariff import TariffConfig, TariffPeriod


# --- Distribution Types for Fleet Generation ---


#: An outcome a weighted_discrete or shuffled_pool lists: a number, one of a CHOICE field's choices, or null.
SpecValue = Union[float, str, None]


@dataclass(frozen=True)
class WeightedDiscreteDistribution:
    """Weighted discrete distribution for sampling from a list of values.

    Weights are auto-normalized (e.g., [2,4,3,1] == [20,40,30,10]).

    Attributes:
        values: List of values to sample from (can include None)
        weights: Corresponding weights (must be non-negative, sum > 0)
    """

    values: tuple[SpecValue, ...]
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

    def draw(self, rng: random.Random) -> SpecValue:
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

    values: tuple[SpecValue, ...]
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

    def create_pool(self) -> list[SpecValue]:
        """Create the expanded pool of values."""
        pool: list[SpecValue] = []
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


# Type alias for distribution specifications; a bare string is one of a CHOICE field's choices.
DistributionSpec = Union[
    WeightedDiscreteDistribution,
    NormalDistribution,
    UniformDistribution,
    ShuffledPoolDistribution,
    ProportionalDistribution,
    float,
    str,
    None,
]

#: The value a fleet gives every home for a SETTING or FLAG key: a SETTING's as written or as its
#: sub-block reads it, a FLAG's as true or false.
SettingValue = Union[bool, str, GridChargeConfig, DispatchStrategyConfig, None]


@dataclass(frozen=True)
class ComponentDistribution:
    """How a fleet gives each home one component: the specs it draws and the settings it gives every home.

    *draws* maps each key a home draws to its spec, and *settings* each SETTING or FLAG key to the
    value every home is given. A key in neither takes its dataclass's default. Both are held as
    read-only copies; a ComponentDistribution pickles and deep-copies, but dataclasses.asdict
    of one raises TypeError.
    """

    draws: Mapping[str, DistributionSpec]
    settings: Mapping[str, SettingValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "draws", MappingProxyType(dict(self.draws)))
        object.__setattr__(self, "settings", MappingProxyType(dict(self.settings)))

    def __reduce__(
        self,
    ) -> tuple[type["ComponentDistribution"], tuple[dict[str, DistributionSpec], dict[str, SettingValue]]]:
        """Rebuild through the constructor from dicts of the draws and settings, since a mappingproxy does not pickle."""
        return (type(self), (dict(self.draws), dict(self.settings)))


@dataclass
class FleetDistributionConfig:
    """Configuration for generating a fleet from distributions.

    Attributes:
        n_homes: Number of homes to generate
        pv: How each home draws its PV
        load: How each home draws its load; an empty one draws nothing, so every load takes
            LoadConfig's defaults
        battery: How each home draws its battery; None is no battery for any home
        heat_pump: How each home draws its heat pump; None is no heat pump for any home
        ev: How each home draws its EV; None is no EV for any home
        seed: Random seed for reproducibility (optional)
        random_order: One of _RANDOM_ORDERS' keys, naming what is drawn ahead of the first
            home and in which order ("bristol_legacy" reproduces
            create_bristol_phase1_scenario's sequence)
        dispatch_strategy: Dispatch strategy of every home ("greedy" or "tou_optimized");
            None means greedy.  A battery given a dispatch_strategy setting dispatches with
            that instead.
    """

    n_homes: int
    pv: ComponentDistribution
    load: ComponentDistribution = field(default_factory=lambda: ComponentDistribution({}))
    battery: Optional[ComponentDistribution] = None
    heat_pump: Optional[ComponentDistribution] = None
    ev: Optional[ComponentDistribution] = None
    seed: Optional[int] = None
    random_order: str = "default"
    dispatch_strategy: Optional[str] = None

    def __post_init__(self) -> None:
        """Refuse a fleet no home of which could be drawn, as each check's helper states."""
        if self.n_homes < 1:
            raise ConfigurationError("FleetDistributionConfig: n_homes must be at least 1")
        if not isinstance(self.random_order, str) or self.random_order not in _RANDOM_ORDERS:
            raise ConfigurationError(
                f"FleetDistributionConfig: random_order must be "
                f"{' or '.join(repr(order) for order in _RANDOM_ORDERS)}, got '{self.random_order}'"
            )
        if self.dispatch_strategy is not None and self.dispatch_strategy not in HOME_DISPATCH_STRATEGIES:
            raise ConfigurationError(
                f"FleetDistributionConfig: dispatch_strategy must be "
                f"{' or '.join(repr(name) for name in HOME_DISPATCH_STRATEGIES)} or None, got {self.dispatch_strategy!r}"
            )
        _refuse_pools_not_sized_to_the_fleet(self)
        _refuse_fixed_presences_their_rules_refuse(self)
        _refuse_rounded_counts_with_no_whole_number(self)


#: The default shuffle order: every random order shuffles the pools it does not shuffle first
#: component by component in this order, each component's keys in its table's fleet order. It
#: is not the order in which a home draws them, which is _generated_home's.
_DEFAULT_SHUFFLE_ORDER: tuple[str, ...] = ("pv", "load", "battery", "heat_pump", "ev")


@dataclass(frozen=True)
class _RandomOrder:
    """What a fleet's random order draws for every home before the first home is built.

    First each pre_sampled setting's values, then the pools of the shuffled_first settings
    in that order, then every other pool in the default shuffle order: component by
    component in _DEFAULT_SHUFFLE_ORDER, each component's keys in its table's fleet order.

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


def _component_draws(config: FleetDistributionConfig) -> Iterator[tuple[str, "FleetField", DistributionSpec]]:
    """Each spec *config*'s components draw, with its path and its fleet row, e.g. ('pv.tilt', row, spec).

    Components come in _DEFAULT_SHUFFLE_ORDER and each component's keys in its table's fleet
    order, never in the order its draws mapping lists them.
    """
    components = _fleet_components(config)
    for name in _DEFAULT_SHUFFLE_ORDER:
        block, component = components[name]
        if component is None:
            continue
        for key, row in block.fleet.items():
            if key in component.draws:
                yield f"{name}.{key}", row, component.draws[key]


def _shuffled_pools(
    config: FleetDistributionConfig,
) -> Iterator[tuple[str, ShuffledPoolDistribution]]:
    """Each shuffled pool among *config*'s component parameters, with its path, e.g. ('pv.capacity_kw', pool)."""
    for path, _, spec in _component_draws(config):
        if isinstance(spec, ShuffledPoolDistribution):
            yield path, spec


def _refuse_pools_not_sized_to_the_fleet(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a shuffled pool's counts do not total its n_homes: a pool holds one value per home."""
    for path, pool in _shuffled_pools(config):
        total = sum(pool.counts)
        if total != config.n_homes:
            raise ConfigurationError(
                f"FleetDistributionConfig: shuffled_pool counts for '{path}' must total n_homes "
                f"({config.n_homes}), got {total}"
            )


def _refuse_fixed_presences_their_rules_refuse(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a presence field's fixed value is one its table's presence rule refuses, e.g. a negative battery capacity; draws are checked as drawn."""
    for name, (block, component) in _fleet_components(config).items():
        if component is None or block.presence is None:
            continue
        spec = component.draws.get(block.presence)
        if isinstance(spec, (int, float, str)):
            block.asks_for_component(spec, f"{name}.{block.presence}")


def _refuse_rounded_counts_with_no_whole_number(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a normal or uniform count that _converted_count rounds has no whole number from its min to its max, as _count_bounds states; draws are checked as drawn."""
    for path, row, spec in _component_draws(config):
        if (
            row.kind is FieldKind.COUNT
            and path not in _TRUNCATED_COUNTS
            and isinstance(spec, (NormalDistribution, UniformDistribution))
        ):
            _count_bounds(spec, path)


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
class ScenarioConfig:
    """Configuration for a simulation scenario.

    Attributes:
        name: Scenario identifier
        description: Human-readable description
        location: Geographic location (defaults to Bristol)
        period: Simulation period
        homes: Home configurations (for fleet simulation); a list is held as a tuple
        home: Single home configuration (for single-home simulation)
        output: Output preferences
        seg_tariff_pence_per_kwh: Smart Export Guarantee rate in pence/kWh (optional), read
            as SEGTariff reads its rate; a home whose own seg_tariff sets another rate is refused
        tariff_config: Refused when set: no simulation reads it, so a home's
            tariff is its HomeConfig.tariff_config
        finance: Financial appraisal parameters (None for no financial analysis)
    """

    name: str
    period: SimulationPeriod
    description: str = ""
    location: Optional[Location] = None
    homes: tuple[HomeConfig, ...] = ()
    home: Optional[HomeConfig] = None
    output: Optional[OutputConfig] = None
    seg_tariff_pence_per_kwh: Optional[float] = None
    tariff_config: Optional[TariffConfig] = None
    finance: Optional[FinanceConfig] = None

    def __post_init__(self) -> None:
        """Validate scenario configuration."""
        object.__setattr__(self, "homes", tuple(self.homes))
        if not self.homes and self.home is None:
            raise ConfigurationError(
                f"Scenario '{self.name}' must define either 'home' or 'homes'"
            )
        if self.homes and self.home is not None:
            raise ConfigurationError(
                f"Scenario '{self.name}' cannot define both 'home' and 'homes'"
            )
        self._read_the_seg_rate()
        self._refuse_a_home_seg_rate_other_than_the_scenarios()
        if self.tariff_config is not None:
            raise ConfigurationError(
                f"Scenario '{self.name}' sets tariff_config, which no simulation reads: "
                "give each home its tariff as HomeConfig.tariff_config"
            )

    @property
    def is_fleet(self) -> bool:
        """Whether this is a fleet simulation."""
        return len(self.homes) > 1 or (len(self.homes) == 1 and self.home is None)

    def get_location(self) -> Location:
        """Get location, defaulting to Bristol."""
        return self.location if self.location is not None else Location.bristol()

    def simulated_homes(self) -> tuple[HomeConfig, ...]:
        """The homes this scenario simulates, in order; one with no SEG tariff of its own exports at the scenario's rate."""
        tariff = self._seg_tariff()
        if tariff is None:
            return self._stored_homes()
        return tuple(
            home if home.seg_tariff is not None else replace(home, seg_tariff=tariff)
            for home in self._stored_homes()
        )

    def map_homes(self, transform: Callable[[HomeConfig], HomeConfig]) -> "ScenarioConfig":
        """This scenario in the same form, *transform* applied to each stored home, and checked as construction checks."""
        if self.home is not None:
            return replace(self, home=transform(self.home))
        return replace(self, homes=tuple(transform(home) for home in self.homes))

    def _stored_homes(self) -> tuple[HomeConfig, ...]:
        """The homes as stored: (home,) in the single-home form, else homes, in order."""
        return (self.home,) if self.home is not None else self.homes

    def _seg_tariff(self) -> Optional[SEGTariff]:
        """The tariff a home with none of its own exports at: the scenario's rate, unnamed; None when the scenario sets no rate."""
        if self.seg_tariff_pence_per_kwh is None:
            return None
        return SEGTariff(name="", rate_pence_per_kwh=self.seg_tariff_pence_per_kwh)

    def _read_the_seg_rate(self) -> None:
        """Hold seg_tariff_pence_per_kwh as the float SEGTariff reads, raising ConfigurationError, naming the scenario and the rate, for one SEGTariff refuses."""
        try:
            tariff = self._seg_tariff()
        except ConfigurationError as exc:
            raise ConfigurationError(
                f"Scenario '{self.name}' sets seg_tariff_pence_per_kwh="
                f"{self.seg_tariff_pence_per_kwh!r}, which SEGTariff refuses: {exc}"
            ) from exc
        if tariff is not None:
            object.__setattr__(self, "seg_tariff_pence_per_kwh", tariff.rate_pence_per_kwh)

    def _refuse_a_home_seg_rate_other_than_the_scenarios(self) -> None:
        """Raise ConfigurationError naming the first home, by its path 'home' or 'homes[i]', whose own SEG rate is not math.isclose to the scenario's."""
        rate = self.seg_tariff_pence_per_kwh
        if rate is None:
            return
        for index, home in enumerate(self._stored_homes()):
            if home.seg_tariff is None or math.isclose(home.seg_tariff.rate_pence_per_kwh, rate):
                continue
            path = "home" if self.home is not None else f"homes[{index}]"
            named = f"{path} ({home.name!r})" if home.name else path
            raise ConfigurationError(
                f"Inconsistent SEG rate: {named} has its own seg_tariff at "
                f"{home.seg_tariff.rate_pence_per_kwh}p/kWh but scenario '{self.name}' sets "
                f"seg_tariff_pence_per_kwh={rate}p/kWh. Set only one, or use matching rates."
            )


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

    def __call__(self, data: Any, *, block_path: str) -> SettingValue: ...


@dataclass(frozen=True)
class SubBlock:
    """A key whose value is a nested block, with its grammar's reader and writer.

    *read* reads the key's non-null value at its block path; *write* writes the field's non-None
    value as the block *read* reads back as it.
    """

    read: _SubBlockReader
    write: Callable[[Any], dict[str, Any]]


class FieldKind(Enum):
    """The ways a fleet_distribution: block can give each home a value for one key of a component."""

    NUMBER = "number"
    """A float: fixed, null, weighted_discrete, normal, uniform, shuffled_pool or proportional_to."""

    COUNT = "count"
    """A whole number: drawn as a NUMBER is, then converted by the sampler's one count conversion."""

    CHOICE = "choice"
    """One of its FleetField's choices: fixed, null, or a weighted_discrete or shuffled_pool of them."""

    SETTING = "setting"
    """Not drawn: one value, as written (a string or a sub-block), given to every home."""

    FLAG = "flag"
    """Not drawn: true or false, read as boolean_fields.as_boolean reads it, given to every home."""


#: The kinds a fleet gives every home as one value, never drawn.
_GIVEN_EVERY_HOME: frozenset[FieldKind] = frozenset({FieldKind.SETTING, FieldKind.FLAG})


@dataclass(frozen=True)
class FleetField:
    """One key's row in a component's fleet grammar.

    *kind* is how a fleet_distribution: block gives each home the key's value. *choices* are the
    values a CHOICE field may take; a field of any other kind has none. *required* means the
    block must give the key.
    """

    kind: FieldKind
    choices: tuple[str, ...] = ()
    required: bool = False

    def __post_init__(self) -> None:
        """Refuse a CHOICE field without choices, and a field of any other kind with some."""
        if (self.kind is FieldKind.CHOICE) != bool(self.choices):
            needs = "must list its choices" if self.kind is FieldKind.CHOICE else "takes no choices"
            raise ConfigurationError(f"FleetField: a {self.kind.name} field {needs}, got {self.choices!r}")


def _any_draw_asks_for_it(drawn: object, path: str) -> bool:
    """The presence rule of a component that any non-null draw of its presence field asks for."""
    return True


_Component = TypeVar("_Component", bound=DataclassInstance)


@dataclass(frozen=True)
class ComponentBlock(Generic[_Component]):
    """A component's block in the scenario grammar, stated against the dataclass it builds.

    *config_type* is the dataclass. *keys* are the block's keys, the fields it carries, in field
    order; *outside_grammar* maps each other field to the reason no key carries it. *sub_blocks*
    holds the keys whose value is a nested block, and *when_omitted* the value an omitted key
    reads as, for each key where that is not the dataclass's declared default.

    *fleet* holds the keys a fleet_distribution: block gives each home, each with its FleetField,
    in key order, which is the order a home draws them; *not_in_fleet* maps each other key to the
    reason the fleet grammar does not carry it. *presence* is the fleet field whose null draw
    means the home has no such component, and *asks_for_component* says whether its non-null
    draw, at its path, asks for one.
    tests/unit/config/test_component_blocks.py holds every table to its dataclass's fields (T1).
    """

    config_type: type[_Component]
    keys: tuple[str, ...]
    outside_grammar: Mapping[str, str]
    sub_blocks: Mapping[str, SubBlock]
    when_omitted: Mapping[str, object]
    fleet: Mapping[str, FleetField]
    not_in_fleet: Mapping[str, str]
    presence: Optional[str] = None
    asks_for_component: Callable[[object, str], bool] = _any_draw_asks_for_it

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


_NUMBER_FIELD = FleetField(FieldKind.NUMBER)
_COUNT_FIELD = FleetField(FieldKind.COUNT)
_SETTING_FIELD = FleetField(FieldKind.SETTING)

_UNNAMED_IN_A_FLEET = "the generator names each home, and leaves its components unnamed"

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
    fleet=MappingProxyType({
        "capacity_kw": FleetField(FieldKind.NUMBER, required=True),
        **dict.fromkeys(
            (
                "azimuth", "tilt", "module_efficiency", "temperature_coefficient", "inverter_efficiency",
                "inverter_capacity_kw", "system_age_years", "degradation_rate_per_year", "system_losses",
            ),
            _NUMBER_FIELD,
        ),
    }),
    not_in_fleet=MappingProxyType({"name": _UNNAMED_IN_A_FLEET}),
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
    fleet=MappingProxyType({
        "capacity_kwh": FleetField(FieldKind.NUMBER, required=True),
        "max_charge_kw": _NUMBER_FIELD,
        "max_discharge_kw": _NUMBER_FIELD,
        "dispatch_strategy": _SETTING_FIELD,
        "grid_charging": _SETTING_FIELD,
        **dict.fromkeys(
            (
                "min_soc_fraction", "max_soc_fraction", "charge_efficiency", "discharge_efficiency",
                "efficiency", "system_age_years", "calendar_fade_rate_per_year",
                "cycle_fade_per_equivalent_full_cycle", "soh_floor", "soh",
            ),
            _NUMBER_FIELD,
        ),
    }),
    not_in_fleet=MappingProxyType({"name": _UNNAMED_IN_A_FLEET}),
    presence="capacity_kwh",
    asks_for_component=has_battery,
)

LOAD_BLOCK: ComponentBlock[LoadConfig] = ComponentBlock(
    config_type=LoadConfig,
    keys=("annual_consumption_kwh", "household_occupants", "name", "use_stochastic", "seed"),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({}),
    fleet=MappingProxyType({
        "annual_consumption_kwh": _NUMBER_FIELD,
        "household_occupants": _COUNT_FIELD,
        "use_stochastic": FleetField(FieldKind.FLAG),
    }),
    not_in_fleet=MappingProxyType({
        "name": _UNNAMED_IN_A_FLEET,
        "seed": "the generator gives each home the fleet's seed plus the home's index",
    }),
)

HEAT_PUMP_BLOCK: ComponentBlock[HeatPumpConfig] = ComponentBlock(
    config_type=HeatPumpConfig,
    keys=("heat_pump_type", "thermal_capacity_kw", "annual_heat_demand_kwh", "name"),
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType({}),
    fleet=MappingProxyType({
        "heat_pump_type": FleetField(FieldKind.CHOICE, choices=HEAT_PUMP_TYPES),
        "thermal_capacity_kw": _NUMBER_FIELD,
        "annual_heat_demand_kwh": _NUMBER_FIELD,
    }),
    not_in_fleet=MappingProxyType({"name": _UNNAMED_IN_A_FLEET}),
    presence="heat_pump_type",
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
    fleet=MappingProxyType({
        "charger_type": FleetField(FieldKind.CHOICE, choices=CHARGER_TYPES, required=True),
        "arrival_hour": _COUNT_FIELD,
        "departure_hour": _COUNT_FIELD,
        "required_charge_kwh": _NUMBER_FIELD,
        "smart_charging_mode": _SETTING_FIELD,
    }),
    not_in_fleet=MappingProxyType({"name": _UNNAMED_IN_A_FLEET}),
    presence="charger_type",
)

_LOCATION_KEYS = ("latitude", "longitude", "timezone", "altitude", "name")

LOCATION_BLOCK: ComponentBlock[Location] = ComponentBlock(
    config_type=Location,
    keys=_LOCATION_KEYS,
    outside_grammar=MappingProxyType({}),
    sub_blocks=MappingProxyType({}),
    when_omitted=MappingProxyType(
        {key: value for key, value in asdict(Location.bristol()).items() if key != "name"}
    ),
    fleet=MappingProxyType({}),
    not_in_fleet=MappingProxyType(
        dict.fromkeys(_LOCATION_KEYS, "a fleet's homes share the location: block of its file")
    ),
)


def _fleet_components(
    config: FleetDistributionConfig,
) -> Mapping[str, tuple[ComponentBlock[Any], Optional[ComponentDistribution]]]:
    """Each component of *config* by name, with its table and its distribution, None for a component the fleet gives no home."""
    return {
        "pv": (PV_BLOCK, config.pv),
        "battery": (BATTERY_BLOCK, config.battery),
        "load": (LOAD_BLOCK, config.load),
        "heat_pump": (HEAT_PUMP_BLOCK, config.heat_pump),
        "ev": (EV_BLOCK, config.ev),
    }


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


_HOME_SCALAR_KEYS: tuple[str, ...] = ("name",)

_HOME_BLOCK_KEYS: frozenset[str] = frozenset({
    *_HOME_SCALAR_KEYS, "dispatch_strategy", "pv", "battery", "load", "tariff", "heat_pump", "ev",
})


def _read_dispatch_strategy_key(block: Mapping[str, Any], *, block_path: str) -> Optional[str]:
    """The dispatch_strategy the block at *block_path* sets: None when it is absent or null, else one of HOME_DISPATCH_STRATEGIES.

    Raises:
        ConfigurationError: It is set to another value, naming its key's path, the value and the
            valid values.
    """
    value = block.get("dispatch_strategy")
    if value is None:
        return None
    if not isinstance(value, str) or value not in HOME_DISPATCH_STRATEGIES:
        raise ConfigurationError(
            f"Invalid {_child_path(block_path, 'dispatch_strategy')} {value!r}; "
            f"valid values: {sorted(HOME_DISPATCH_STRATEGIES)}"
        )
    return value


def parse_home_block(
    data: dict[str, Any], location: Location, *, block_path: str = "home"
) -> HomeConfig:
    """Parse a ``home:`` block, or one ``homes:`` entry, into a HomeConfig at *location*.

    A key the block omits takes HomeConfig's declared default, and so does a null scalar. An
    omitted pv or load block reads as an empty one.
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
        **{key: home[key] for key in _HOME_SCALAR_KEYS if home.get(key) is not None},
        **_dispatch_strategy_argument(_read_dispatch_strategy_key(home, block_path=block_path)),
    )


def _dispatch_strategy_argument(dispatch_strategy: Optional[str]) -> dict[str, Any]:
    """HomeConfig's dispatch_strategy argument for *dispatch_strategy*: none when it is None, so the field takes its default."""
    return {} if dispatch_strategy is None else {"dispatch_strategy": dispatch_strategy}


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


def _parse_choice_spec(data: object, choices: tuple[str, ...], key_path: str) -> DistributionSpec:
    """Read a CHOICE key's spec: null, one of *choices* given bare, or a weighted_discrete or shuffled_pool of them and nulls.

    Any other spec is refused naming *key_path*, the spec as written and *choices*; so is a
    value, bare or listed, that is not one of *choices*, even one no home would draw.
    """
    spec = _parse_distribution_spec(data, key_path) if isinstance(data, dict) else data
    if spec is None:
        return None
    if isinstance(spec, str):
        listed: tuple[SpecValue, ...] = (spec,)
    elif isinstance(spec, (WeightedDiscreteDistribution, ShuffledPoolDistribution)):
        listed = spec.values
    else:
        raise ConfigurationError(
            f"Invalid {key_path} {data!r}; valid specs: null, one of {list(choices)}, "
            "or a weighted_discrete or shuffled_pool of them and nulls"
        )
    for value in listed:
        if value is not None and value not in choices:
            raise ConfigurationError(
                f"Invalid {key_path} value {value!r}; valid values: null or one of {list(choices)}"
            )
    return spec


def _read_setting(block: ComponentBlock[Any], key: str, value: Any, key_path: str) -> SettingValue:
    """The value every home is given for *block*'s *key*, a SETTING or FLAG, read from *value*, not null, at *key_path*.

    A FLAG is read as true or false, naming *key_path*. A SETTING is read by its sub-block's
    reader when the key has a sub-block, and is otherwise the value as written.
    """
    if block.fleet[key].kind is FieldKind.FLAG:
        return as_boolean(value, key_path)
    sub_block = block.sub_blocks.get(key)
    return value if sub_block is None else sub_block.read(value, block_path=key_path)


def _parse_component_distribution(
    block: ComponentBlock[Any], data: object, *, block_path: str
) -> ComponentDistribution:
    """Read a fleet_distribution: component block by *block*'s fleet rows.

    A key outside the rows is refused, and so is a required key left out, naming its path. A
    SETTING key is read as written, or by its sub-block's reader, and a FLAG key as true or
    false, naming its path; a null one of either reads as absent. Any other key is a spec, kept
    even when null: a CHOICE's as _parse_choice_spec reads it, any other's as
    _parse_distribution_spec does.
    """
    mapping = _refuse_unrecognised_keys(block_path, data, block.fleet)
    _refuse_missing_keys(block_path, [key for key, row in block.fleet.items() if row.required and key not in mapping])
    draws: dict[str, DistributionSpec] = {}
    settings: dict[str, SettingValue] = {}
    for key, row in block.fleet.items():
        if key not in mapping:
            continue
        value, key_path = mapping[key], _child_path(block_path, key)
        if row.kind is FieldKind.CHOICE:
            draws[key] = _parse_choice_spec(value, row.choices, key_path)
        elif row.kind not in _GIVEN_EVERY_HOME:
            draws[key] = _parse_distribution_spec(value, key_path)
        elif value is not None:
            settings[key] = _read_setting(block, key, value, key_path)
    return ComponentDistribution(draws, settings)


def _parse_optional_component_distribution(
    block: ComponentBlock[Any], data: object, *, block_path: str
) -> Optional[ComponentDistribution]:
    """Read a component block as _parse_component_distribution does; a null block is no such component for any home."""
    return None if data is None else _parse_component_distribution(block, data, block_path=block_path)


_FLEET_DISTRIBUTION_BLOCK_KEYS: frozenset[str] = frozenset({
    "n_homes", "pv", "load", "battery", "heat_pump", "ev", "seed", "random_order",
    "dispatch_strategy",
})


def parse_fleet_distribution_config(
    data: dict[str, Any], *, block_path: str = "fleet_distribution"
) -> FleetDistributionConfig:
    """Parse a fleet_distribution: block, each component block read by its table's fleet rows."""
    _refuse_unrecognised_keys(block_path, data, _FLEET_DISTRIBUTION_BLOCK_KEYS)
    if "n_homes" not in data:
        raise ConfigurationError("Fleet distribution config requires 'n_homes'")
    if "pv" not in data:
        raise ConfigurationError("Fleet distribution config requires 'pv' section")

    return FleetDistributionConfig(
        n_homes=int(data["n_homes"]),
        pv=_parse_component_distribution(PV_BLOCK, data["pv"], block_path=_child_path(block_path, "pv")),
        load=_parse_component_distribution(
            LOAD_BLOCK, data.get("load", {}), block_path=_child_path(block_path, "load")
        ),
        battery=_parse_optional_component_distribution(
            BATTERY_BLOCK, data.get("battery"), block_path=_child_path(block_path, "battery")
        ),
        heat_pump=_parse_optional_component_distribution(
            HEAT_PUMP_BLOCK, data.get("heat_pump"), block_path=_child_path(block_path, "heat_pump")
        ),
        ev=_parse_optional_component_distribution(
            EV_BLOCK, data.get("ev"), block_path=_child_path(block_path, "ev")
        ),
        seed=data.get("seed"),
        random_order=data.get("random_order", "default"),
        dispatch_strategy=_read_dispatch_strategy_key(data, block_path=block_path),
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
    return float(min(max(_nearest_whole_number(draw), least), greatest))


def _nearest_whole_number(value: float) -> float:
    """Return the whole number nearest *value*, a half rounding up, as a float."""
    whole = math.floor(value)
    return float(whole + 1 if value - whole >= 0.5 else whole)


#: The COUNT fields _converted_count truncates, as the generator did before it drew each field
#: by its kind; every other count is rounded. Task 868 rounds these too and deletes the set
#: (docs/prds/component-defaults-one-home.md §6 decisions 8 and 9).
_TRUNCATED_COUNTS: frozenset[str] = frozenset({"ev.arrival_hour", "ev.departure_hour"})


def _refuse_unless_finite(value: SpecValue, path: str) -> None:
    """Refuse *value*, a count of the field at *path* to convert, if it is an infinity or a NaN, naming *path* and the value."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError(f"{path} must be a finite number, got {value!r}")


def _converted_count(value: SpecValue, spec: DistributionSpec, path: str) -> SpecValue:
    """Return the count of the COUNT field at *path* for *value*, drawn from *spec*; this is the sampler's one count conversion.

    A count in _TRUNCATED_COUNTS is truncated to an int. For any other, a draw from a normal or
    uniform distribution gives the whole number nearest it among those from the spec's min to
    its max, as _nearest_count states, and a proportional_to's value the whole number nearest
    it, a half rounding up either way. The whole number is returned as a float, so a refusal of
    the count names it as drawn, 1e+300 rather than the 301-digit int it equals. A fixed value
    is returned as the spec gives it, and any other value as drawn.

    Raises:
        ConfigurationError: If a count it truncates, or a proportional_to's value, is an
            infinity or a NaN, naming *path* and the value; or as _nearest_count does, for a
            normal or uniform distribution with no whole number from its min to its max.
    """
    if path in _TRUNCATED_COUNTS:
        _refuse_unless_finite(value, path)
        return None if value is None else int(value)
    if isinstance(spec, (int, float)):
        return spec
    if isinstance(value, (int, float)) and isinstance(spec, (NormalDistribution, UniformDistribution)):
        return _nearest_count(value, spec, path)
    if isinstance(value, (int, float)) and isinstance(spec, ProportionalDistribution):
        _refuse_unless_finite(value, path)
        return _nearest_whole_number(value)
    return value


def _proportional_value(
    spec: ProportionalDistribution, path: str, drawn: Mapping[str, SpecValue]
) -> Optional[float]:
    """The value *spec*, the spec of the field at *path*, gives: its multiplier times the value *drawn* holds for its source, plus its offset; a null source gives null.

    A home draws no field of a component it has none of, past the presence field, so a source
    there is refused for each home without that component, and not for the others.

    Raises:
        ConfigurationError: If *drawn*, the home's draws so far by path, holds no value for the
            source, or holds a choice, naming *path* and the source; or if the multiplier is a
            SweepSpec, which expand_sweep_configs replaces before any home is drawn.
    """
    if spec.source not in drawn:
        raise ConfigurationError(f"{path} is proportional_to {spec.source}, which no earlier field of the home drew")
    source = drawn[spec.source]
    if source is None:
        return None
    if isinstance(source, str):
        raise ConfigurationError(f"{path} is proportional_to {spec.source}, which drew {source!r}, not a number")
    if isinstance(spec.multiplier, SweepSpec):
        raise ConfigurationError(
            "Cannot sample ProportionalDistribution with SweepSpec multiplier directly. "
            "Use expand_sweep_configs() to expand sweep values first."
        )
    return source * spec.multiplier + spec.offset


class _DistributionSampler:
    """Draws a fleet's settings home by home, from one RNG seeded with the fleet's seed.

    Before the first home it draws ahead what the fleet's random order says, each
    setting's values under the setting's path. A setting drawn ahead hands out its
    values in order, one per home; any other setting is drawn afresh from its spec.
    """

    def __init__(self, config: FleetDistributionConfig) -> None:
        self._rng = random.Random(config.seed)
        self._drawn_ahead: dict[str, list[SpecValue]] = {}
        self._handed_out: dict[str, int] = {}
        order = _RANDOM_ORDERS[config.random_order]
        specs = {path: spec for path, _, spec in _component_draws(config)}
        for setting in order.pre_sampled:
            spec = specs.get(setting)
            if isinstance(spec, (WeightedDiscreteDistribution, NormalDistribution, UniformDistribution)):
                self._drawn_ahead[setting] = [spec.draw(self._rng) for _ in range(config.n_homes)]
        pools = dict(_shuffled_pools(config))
        shuffled_first = [setting for setting in order.shuffled_first if setting in pools]
        for setting in shuffled_first + [setting for setting in pools if setting not in shuffled_first]:
            values = pools[setting].create_pool()
            self._rng.shuffle(values)
            self._drawn_ahead[setting] = values

    def draw(
        self, row: FleetField, spec: DistributionSpec, path: str, drawn: Mapping[str, SpecValue]
    ) -> SpecValue:
        """Draw the next home's value of the field at *path*, whose fleet row is *row*, from *spec*.

        A proportional_to gives what _proportional_value computes from *drawn*, the home's
        draws so far by path, and any other spec what sample draws; a COUNT's value is then
        converted by _converted_count.

        Raises:
            ConfigurationError: As _proportional_value, sample or _converted_count refuse the draw.
        """
        value: SpecValue
        if isinstance(spec, ProportionalDistribution):
            value = _proportional_value(spec, path, drawn)
        else:
            value = self.sample(spec, path)
        return _converted_count(value, spec, path) if row.kind is FieldKind.COUNT else value

    def sample(self, spec: DistributionSpec, setting: str) -> SpecValue:
        """Draw the next home's value of *setting* from *spec*.

        A setting drawn ahead hands out its next value. Any other is drawn afresh: None
        gives None, a bare choice gives itself, a fixed number gives itself as a float, and
        a weighted discrete, normal or uniform spec draws from the RNG.

        Args:
            spec: The setting's distribution specification
            setting: The setting's path in the fleet distribution, e.g. 'pv.tilt'

        Raises:
            ConfigurationError: If *setting* was drawn ahead and every value of it is
                handed out, or if *spec* cannot be drawn afresh, as a proportional_to
                or a pool not drawn ahead for *setting* cannot, naming *setting*; or if
                *spec* is a normal or uniform distribution and the value it draws is not
                a finite number, naming *setting* and the draw. A normal's draw is
                checked after its min and max clamp it.
        """
        value = self._next_value(spec, setting)
        if (
            isinstance(spec, (NormalDistribution, UniformDistribution))
            and isinstance(value, float)
            and not math.isfinite(value)
        ):
            raise ConfigurationError(
                f"{setting} must draw samples that are finite numbers, got a sample of {value!r}"
            )
        return value

    def _next_value(self, spec: DistributionSpec, setting: str) -> SpecValue:
        if setting in self._drawn_ahead:
            return self._next_value_drawn_ahead(setting)
        if spec is None or isinstance(spec, str):
            return spec
        if isinstance(spec, (int, float)):
            return float(spec)
        if isinstance(spec, (WeightedDiscreteDistribution, NormalDistribution, UniformDistribution)):
            return spec.draw(self._rng)
        raise ConfigurationError(f"{setting} cannot be drawn from {spec!r}")

    def _next_value_drawn_ahead(self, setting: str) -> SpecValue:
        values = self._drawn_ahead[setting]
        handed_out = self._handed_out.get(setting, 0)
        if handed_out == len(values):
            raise ConfigurationError(
                f"{setting} has no value left to draw: its {len(values)} values, one per home, are all drawn"
            )
        self._handed_out[setting] = handed_out + 1
        return values[handed_out]


_NOTHING_GIVEN: Mapping[str, object] = MappingProxyType({})


def _drawn_component(
    name: str,
    block: ComponentBlock[_Component],
    component: Optional[ComponentDistribution],
    sampler: _DistributionSampler,
    drawn: dict[str, SpecValue],
    home_number: int,
    *,
    given: Mapping[str, object] = _NOTHING_GIVEN,
) -> Optional[_Component]:
    """Draw home *home_number*'s *name* component by *block*'s fleet rows, and build it; None when the home has none.

    Each row *component* draws is drawn in the table's order, and recorded in *drawn* under its
    path; SETTING and FLAG rows, and rows it does not draw, are skipped. The home has no such
    component when the presence field is not drawn, draws null, or draws a value the table's
    presence rule says asks for none. The dataclass is built from the non-null draws, the
    settings and *given*, so each field drawn null or not drawn takes its default.

    Raises:
        ConfigurationError: As sampler.draw refuses a draw, naming its path; as the table's
            presence rule refuses the presence field's draw, e.g. has_battery a negative or
            non-finite battery capacity; if a required field is not drawn, naming its path, or
            draws null, naming its path and the home; or, naming the component and the home, as
            the dataclass refuses what it is built from.
    """
    if component is None:
        return None
    values: dict[str, object] = {}
    for key, row in block.fleet.items():
        if row.kind in _GIVEN_EVERY_HOME:
            continue
        path = f"{name}.{key}"
        value: SpecValue = None
        if key in component.draws:
            value = drawn[path] = sampler.draw(row, component.draws[key], path, drawn)
        if key == block.presence and (value is None or not block.asks_for_component(value, path)):
            return None
        if value is not None:
            values[key] = value
        elif row.required:
            got = f"home {home_number} drew null" if key in component.draws else "the fleet does not draw it"
            raise ConfigurationError(f"fleet_distribution.{path} is required, but {got}")
    try:
        return block.config_type(**values, **component.settings, **given)
    except (ValueError, TypeError) as refusal:
        raise ConfigurationError(f"fleet_distribution.{name}, home {home_number}: {refusal}") from refusal


def _drawn_component_every_home_has(
    name: str,
    block: ComponentBlock[_Component],
    component: ComponentDistribution,
    sampler: _DistributionSampler,
    drawn: dict[str, SpecValue],
    home_number: int,
    *,
    given: Mapping[str, object] = _NOTHING_GIVEN,
) -> _Component:
    """Draw and build home *home_number*'s *name* component as _drawn_component does, for a component every home has.

    Every home has a PV and a load: HomeConfig's pv_config and load_config are not Optional.

    Raises:
        ConfigurationError: As _drawn_component does; or if the home is given no *name*
            component, naming the component and the home.
    """
    built = _drawn_component(name, block, component, sampler, drawn, home_number, given=given)
    if built is None:
        raise ConfigurationError(f"fleet_distribution.{name} gave home {home_number} no {name}, which every home needs")
    return built


def _generated_home(
    config: FleetDistributionConfig,
    sampler: _DistributionSampler,
    index: int,
    location: Location,
    fleet_tariff: Optional[TariffConfig],
) -> HomeConfig:
    """The fleet's home at *index*: it draws its PV, battery, load, heat pump and EV in that order (T3), each by its table's fleet rows.

    Each load is given the fleet's seed plus the home's index, when the fleet has a seed.
    """
    home_number = index + 1
    drawn: dict[str, SpecValue] = {}
    pv = _drawn_component_every_home_has("pv", PV_BLOCK, config.pv, sampler, drawn, home_number)
    battery = _drawn_component("battery", BATTERY_BLOCK, config.battery, sampler, drawn, home_number)
    load = _drawn_component_every_home_has(
        "load",
        LOAD_BLOCK,
        config.load,
        sampler,
        drawn,
        home_number,
        given={} if config.seed is None else {"seed": config.seed + index},
    )
    heat_pump = _drawn_component("heat_pump", HEAT_PUMP_BLOCK, config.heat_pump, sampler, drawn, home_number)
    ev = _drawn_component("ev", EV_BLOCK, config.ev, sampler, drawn, home_number)
    return HomeConfig(
        pv_config=pv,
        battery_config=battery,
        load_config=load,
        heat_pump_config=heat_pump,
        ev_config=ev,
        location=location,
        name=f"Home {home_number}",
        tariff_config=fleet_tariff,
        dispatch_strategy=config.dispatch_strategy or "greedy",
    )


def generate_homes_from_distribution(
    config: FleetDistributionConfig,
    location: Location,
    *,
    fleet_tariff: Optional[TariffConfig] = None,
) -> list[HomeConfig]:
    """Generate a list of homes by sampling from distributions.

    Each home draws its components in _generated_home's order, each component's keys in its
    table's fleet order, through one sampler (_DistributionSampler).

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
            naming the pool; as the sampler refuses a draw, naming its setting (a
            proportional_to whose source the home has not drawn, such as a field of a
            component the home has none of, a normal or uniform draw that is not a
            finite number, a count with no whole number from its spec's min to its max,
            an EV hour or a proportional_to's count that is an infinity or a NaN); if a
            required field is not drawn, naming its path, or draws null, naming its
            path and the home; if a presence rule refuses a draw, as
            battery.has_battery refuses a negative or non-finite battery capacity; if
            the fleet gives a home no PV or no load, which every home needs, naming the
            component and the home; or as a component's dataclass refuses what it is
            built from, naming the component and the home.
    """
    _refuse_pools_not_sized_to_the_fleet(config)
    sampler = _DistributionSampler(config)
    return [_generated_home(config, sampler, index, location, fleet_tariff) for index in range(config.n_homes)]


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
        homes=tuple(homes),
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
        cap_spec = config.battery.draws.get("capacity_kwh")
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

    cap_spec = config.battery.draws.get("capacity_kwh")
    if not isinstance(cap_spec, ProportionalDistribution):
        return config

    swept_draws = {**config.battery.draws, "capacity_kwh": replace(cap_spec, multiplier=value)}
    return replace(config, battery=replace(config.battery, draws=swept_draws))


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
    fleet_distribution: and tariff: in that order.
    """
    location = parse_location_block(document.get("location"))
    distribution = parse_fleet_distribution_config(document["fleet_distribution"])
    tariff = parse_tariff_config(document.get("tariff"))
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
