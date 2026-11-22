# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet_distribution: grammar and the homes it generates, sweep points included.

It reads each component's keys by that component's table in solar_challenge.scenario_blocks.
"""

import math
import random
from dataclasses import dataclass, field, fields, is_dataclass, replace
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Collection,
    Iterator,
    Mapping,
    Optional,
    TypeVar,
    Union,
)

from solar_challenge.battery import BatteryConfig
from solar_challenge.boolean_fields import as_boolean
from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import EVConfig
from solar_challenge.fleet import fleet_home_seed
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig, refuse_unknown_home_dispatch_strategy
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import (
    NON_NEGATIVE,
    Interval,
    as_finite_float,
    as_finite_floats,
    as_finite_real,
    as_list_elements,
    as_whole_number,
    as_whole_numbers,
    read_field,
)
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_blocks import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    PV_BLOCK,
    ComponentBlock,
    FieldKind,
    FleetField,
    SettingValue,
    child_path,
    constructed,
    dispatch_strategy_argument,
    read_dispatch_strategy_key,
    refuse_missing_keys,
    refuse_unrecognised_keys,
)
from solar_challenge.tariff import TariffConfig


# --- Distribution Types for Fleet Generation ---


#: An outcome a weighted_discrete or shuffled_pool lists: a number, one of a CHOICE field's choices, or null.
SpecValue = Union[float, str, None]


@dataclass(frozen=True)
class WeightedDiscreteDistribution:
    """Weighted discrete distribution for sampling from a list of values.

    Weights are auto-normalized (e.g., [2,4,3,1] == [20,40,30,10]).

    Attributes:
        values: The values to sample from, held as given, none read as a number; the home's
            type reads each (can include None)
        weights: Corresponding weights, read as finite floats of at least 0 (sum > 0)
    """

    values: tuple[SpecValue, ...]
    weights: tuple[float, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", as_list_elements(self.values, "values"))
        read_field(self, "weights", as_finite_floats, NON_NEGATIVE)
        if len(self.values) != len(self.weights):
            raise ConfigurationError(
                "WeightedDiscreteDistribution: values and weights must have same length"
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

    Each number is read as a finite float.

    Attributes:
        mean: Mean of the distribution
        std: Standard deviation, at least 0
        min: Optional least value; a draw below it is clamped to it
        max: Optional greatest value; a draw above it is clamped to it
    """

    mean: float
    std: float
    min: Optional[float] = None
    max: Optional[float] = None

    def __post_init__(self) -> None:
        read_field(self, "mean", as_finite_float)
        read_field(self, "std", as_finite_float, NON_NEGATIVE)
        read_field(self, "min", as_finite_float, optional=True)
        read_field(self, "max", as_finite_float, optional=True)
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
        min: Minimum value (inclusive), read as a finite float
        max: Maximum value (inclusive), read as a finite float
    """

    min: float
    max: float

    def __post_init__(self) -> None:
        read_field(self, "min", as_finite_float)
        read_field(self, "max", as_finite_float)
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
        values: The values, held as given, none read as a number; the home's type reads each
            (can include None)
        counts: Number of each value in the pool, read as whole numbers of at least 0.  In a
            fleet distribution they total n_homes, one value per home, and
            FleetDistributionConfig refuses any other total; a parameter only some homes draw
            leaves the other homes' values undrawn.
    """

    values: tuple[SpecValue, ...]
    counts: tuple[int, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "values", as_list_elements(self.values, "values"))
        read_field(self, "counts", as_whole_numbers, NON_NEGATIVE)
        if len(self.values) != len(self.counts):
            raise ConfigurationError(
                "ShuffledPoolDistribution: values and counts must have same length"
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
        min: Minimum value, read as a finite float
        max: Maximum value, read as a finite float
        steps: Number of steps, read as a whole number of at least 2
        mode: "geometric" or "linear" (default: geometric)
    """

    min: float
    max: float
    steps: int
    mode: str = "geometric"

    def __post_init__(self) -> None:
        read_field(self, "min", as_finite_float)
        read_field(self, "max", as_finite_float)
        read_field(self, "steps", as_whole_number, Interval(2, math.inf))
        if self.min <= 0 and self.mode == "geometric":
            raise ConfigurationError(
                "SweepSpec: geometric mode requires min > 0"
            )
        if self.max <= self.min:
            raise ConfigurationError(
                "SweepSpec: max must be greater than min"
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
        multiplier: Multiplication factor: a SweepSpec, or a number read as a finite float
        offset: Additive offset, read as a finite float (default 0.0)
    """

    source: str
    multiplier: Union[float, SweepSpec] = 1.0
    offset: float = 0.0

    def __post_init__(self) -> None:
        if not isinstance(self.multiplier, SweepSpec):
            read_field(self, "multiplier", as_finite_float)
        read_field(self, "offset", as_finite_float)


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


#: The path of a fleet's block in its file, under which every refusal of a fleet names its keys.
_FLEET_DISTRIBUTION_PATH = "fleet_distribution"


@dataclass(frozen=True)
class FleetDistributionConfig:
    """Configuration for generating a fleet from distributions.

    It is frozen: a changed fleet is a new one, made with dataclasses.replace, which checks it
    as construction does.

    Attributes:
        n_homes: Number of homes to generate, read as a whole number of at least 1
        pv: How each home draws its PV
        load: How each home draws its load; an empty one draws nothing, so every load takes
            LoadConfig's defaults
        battery: How each home draws its battery; None is no battery for any home
        heat_pump: How each home draws its heat pump; None is no heat pump for any home
        ev: How each home draws its EV; None is no EV for any home
        seed: Random seed for reproducibility (optional), read as a whole number
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
        """Read n_homes and seed, then refuse a fleet no home of which could be drawn, as each check's helper states.

        Past n_homes, seed, random_order and dispatch_strategy it refuses, in this order: a component
        key outside its table's fleet rows, or held in the wrong one of its draws and settings
        (F1); a required key a component does not draw (F5); a spec its key's kind does not
        draw, or one listing a value the kind does not admit (F2, F3); a proportional_to whose
        source is not a number or count field drawn earlier for every home that draws it (F4);
        a shuffled pool whose counts do not total n_homes (F6); a fixed presence value its
        table's presence rule refuses; and a rounded count with no whole number from its min
        to its max.
        """
        read_field(self, "n_homes", as_whole_number, Interval(1, math.inf))
        read_field(self, "seed", as_whole_number, optional=True)
        if not isinstance(self.random_order, str) or self.random_order not in _RANDOM_ORDERS:
            raise ConfigurationError(
                f"FleetDistributionConfig: random_order must be "
                f"{' or '.join(repr(order) for order in _RANDOM_ORDERS)}, got '{self.random_order}'"
            )
        if self.dispatch_strategy is not None:
            refuse_unknown_home_dispatch_strategy(
                self.dispatch_strategy, field="FleetDistributionConfig.dispatch_strategy"
            )
        _refuse_keys_held_where_no_row_puts_them(self)
        _refuse_required_keys_not_drawn(self)
        _refuse_specs_their_kinds_cannot_draw(self)
        _refuse_proportional_sources_not_drawn_earlier(_fleet_components(self), _FLEET_DISTRIBUTION_PATH)
        _refuse_pools_not_sized_to_the_fleet(self)
        _refuse_fixed_presences_their_rules_refuse(self)
        _refuse_rounded_counts_with_no_whole_number(self)


#: The default shuffle order: every random order shuffles the pools it does not shuffle first
#: component by component in this order, each component's keys in its table's fleet order. It
#: is not the order in which a home draws them, which is _HOME_DRAW_ORDER.
_DEFAULT_SHUFFLE_ORDER: tuple[str, ...] = ("pv", "load", "battery", "heat_pump", "ev")

#: The order in which each home draws its components (T3), each component's keys in its table's
#: fleet order.
_HOME_DRAW_ORDER: tuple[str, ...] = ("pv", "battery", "load", "heat_pump", "ev")

#: The components every home has: HomeConfig's pv_config and load_config are not Optional.
_EVERY_HOME_HAS: frozenset[str] = frozenset({"pv", "load"})


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


def _refuse_keys_held_where_no_row_puts_them(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a component holds a key outside its table's fleet rows, as the parser refuses one, or holds a SETTING or FLAG key in its draws, or a key of a drawn kind in its settings, naming the key's path and kind."""
    for name, (block, component) in _fleet_components(config).items():
        if component is None:
            continue
        block_path = child_path(_FLEET_DISTRIBUTION_PATH, name)
        refuse_unrecognised_keys(block_path, {**component.draws, **component.settings}, block.fleet)
        for key, row in block.fleet.items():
            if key in (component.draws if row.kind in _GIVEN_EVERY_HOME else component.settings):
                raise _held_in_the_wrong_place(child_path(block_path, key), row)


def _refuse_required_keys_not_drawn(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a component does not draw a key its table's fleet rows require, as the parser refuses a block leaving it out; a null draw is drawn."""
    for name, (block, component) in _fleet_components(config).items():
        if component is not None:
            _refuse_required_fleet_keys_left_out(block, component.draws, child_path(_FLEET_DISTRIBUTION_PATH, name))


def _refuse_specs_their_kinds_cannot_draw(config: FleetDistributionConfig) -> None:
    """Refuse *config* when a key is drawn from a spec its row's kind does not draw, or one listing a value the kind does not admit, as _refuse_a_spec_its_row_cannot_draw states."""
    for path, row, spec in _component_draws(config):
        _refuse_a_spec_its_row_cannot_draw(row, spec, child_path(_FLEET_DISTRIBUTION_PATH, path), written=spec)


def _refuse_proportional_sources_not_drawn_earlier(
    components: Mapping[str, tuple["ComponentBlock[Any]", Optional[ComponentDistribution]]], block_path: str
) -> None:
    """Refuse the fleet at *block_path* whose *components*, by name, hold a proportional_to whose source is not a number or count field drawn earlier for every home that draws the dependent, naming the dependent's path under *block_path*, its source and those it may name, in draw order.

    Those are the number and count fields the components every home has draw before the
    dependent's component in _HOME_DRAW_ORDER, and those the dependent's own component draws
    before it in its table's fleet order. A field of another component every home need not have
    is never one, even when every home of this fleet has it, so whether a fleet is refused does
    not depend on what it draws.
    """
    drawn_for_every_home: list[str] = []
    for name in _HOME_DRAW_ORDER:
        block, component = components[name]
        if component is None:
            continue
        drawn_earlier = list(drawn_for_every_home)
        for key, row in block.fleet.items():
            if key not in component.draws:
                continue
            path, spec = f"{name}.{key}", component.draws[key]
            if isinstance(spec, ProportionalDistribution) and spec.source not in drawn_earlier:
                raise ConfigurationError(
                    f"Invalid {child_path(block_path, path)} source {spec.source!r}; "
                    "valid sources: a number or count field drawn earlier for every home that draws it, "
                    f"one of {drawn_earlier!r}"
                )
            if row.kind in _NUMBER_KINDS:
                drawn_earlier.append(path)
        if name in _EVERY_HOME_HAS:
            drawn_for_every_home = drawn_earlier


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
        if row.kind is FieldKind.COUNT and isinstance(spec, (NormalDistribution, UniformDistribution)):
            _count_bounds(spec, path)


#: The kinds a fleet gives every home as one value, never drawn.
_GIVEN_EVERY_HOME: frozenset[FieldKind] = frozenset({FieldKind.SETTING, FieldKind.FLAG})

#: The kinds whose draws are numbers: a count is drawn as a number is, then converted.
_NUMBER_KINDS: frozenset[FieldKind] = frozenset({FieldKind.NUMBER, FieldKind.COUNT})


@dataclass(frozen=True)
class DrawnKindRule:
    """What a fleet may give a key of one drawn kind: the specs the kind draws, and the values a spec of it may list.

    *spec_types* are the types of the specs the kind draws, beside null. *admits* says whether a
    value a spec lists, or a bare spec, is one the kind admits for a key of the row given; null
    always is. *describe_specs* and *describe_values* return the prose a refusal naming a key of
    the row uses for the specs the kind draws and the values it admits, e.g. 'null or a number'.
    """

    spec_types: tuple[type[DistributionSpec], ...]
    admits: Callable[[SpecValue, FleetField], bool]
    describe_specs: Callable[[FleetField], str]
    describe_values: Callable[[FleetField], str]


#: A number or count field's rule. A value it lists is no string; the home's type reads it as a number.
_NUMBER_KIND_RULE = DrawnKindRule(
    spec_types=(
        int, float, WeightedDiscreteDistribution, NormalDistribution, UniformDistribution,
        ShuffledPoolDistribution, ProportionalDistribution,
    ),
    admits=lambda value, row: not isinstance(value, str),
    describe_specs=lambda row: (
        "null, a number, or a weighted_discrete, normal, uniform, shuffled_pool or proportional_to of numbers"
    ),
    describe_values=lambda row: "null or a number",
)

_CHOICE_KIND_RULE = DrawnKindRule(
    spec_types=(str, WeightedDiscreteDistribution, ShuffledPoolDistribution),
    admits=lambda value, row: value in row.choices,
    describe_specs=lambda row: (
        f"null, one of {list(row.choices)}, or a weighted_discrete or shuffled_pool of them and nulls"
    ),
    describe_values=lambda row: f"null or one of {list(row.choices)}",
)

#: The kind rules: what a fleet may give a key of each drawn kind. A number and a count draw alike;
#: a SETTING or FLAG key is given every home, never drawn, so no rule names it.
DRAWN_KIND_RULES: Mapping[FieldKind, DrawnKindRule] = MappingProxyType({
    **dict.fromkeys(_NUMBER_KINDS, _NUMBER_KIND_RULE),
    FieldKind.CHOICE: _CHOICE_KIND_RULE,
})


def _listed_values(spec: DistributionSpec) -> tuple[SpecValue, ...]:
    """The values *spec* lists: a weighted_discrete's or shuffled_pool's values; a normal, uniform or proportional_to lists none, and any other spec lists itself."""
    if isinstance(spec, (WeightedDiscreteDistribution, ShuffledPoolDistribution)):
        return spec.values
    if isinstance(spec, (NormalDistribution, UniformDistribution, ProportionalDistribution)):
        return ()
    return (spec,)


def _held_in_the_wrong_place(path: str, row: FleetField) -> ConfigurationError:
    """The refusal of the key at *path*, whose fleet row is *row*, held in the wrong one of a ComponentDistribution's draws and settings: a SETTING or FLAG key in its draws, or a key of a drawn kind in its settings."""
    held_in, not_in = ("settings", "draws") if row.kind in _GIVEN_EVERY_HOME else ("draws", "settings")
    return ConfigurationError(
        f"{path} is a {row.kind.value} key, which a ComponentDistribution holds in its {held_in}, not its {not_in}"
    )


def _refuse_a_spec_its_row_cannot_draw(row: FleetField, spec: object, path: str, written: object) -> DistributionSpec:
    """Return *spec*, the spec of the key at *path* whose fleet row is *row*, refusing it unless the row's kind is drawn and *spec* is null or a spec the kind draws, every value it lists one the kind admits.

    A key of a kind no home draws, a SETTING or FLAG, is refused whatever its spec, as
    _held_in_the_wrong_place states. A spec of a type the kind does not draw is refused naming
    *path* and *written*, the spec as its block gives it. A value it lists, or a bare spec, that
    the kind does not admit is refused naming *path* and the value, even one no home would draw.
    DRAWN_KIND_RULES holds each drawn kind's rule.
    """
    rule = DRAWN_KIND_RULES.get(row.kind)
    if rule is None:
        raise _held_in_the_wrong_place(path, row)
    if spec is None:
        return None
    if not isinstance(spec, rule.spec_types):
        raise ConfigurationError(f"Invalid {path} {written!r}; valid specs: {rule.describe_specs(row)}")
    for value in _listed_values(spec):
        if value is not None and not rule.admits(value, row):
            raise ConfigurationError(f"Invalid {path} value {value!r}; valid values: {rule.describe_values(row)}")
    return spec


def _refuse_required_fleet_keys_left_out(block: ComponentBlock[Any], given: Collection[str], block_path: str) -> None:
    """Refuse the fleet's component block at *block_path* if *given*, the keys it gives, leaves out a key *block*'s fleet rows require, naming each by its path."""
    refuse_missing_keys(block_path, [key for key, row in block.fleet.items() if row.required and key not in given])


def _components_by_name(
    *,
    pv: ComponentDistribution,
    battery: Optional[ComponentDistribution],
    load: ComponentDistribution,
    heat_pump: Optional[ComponentDistribution],
    ev: Optional[ComponentDistribution],
) -> Mapping[str, tuple[ComponentBlock[Any], Optional[ComponentDistribution]]]:
    """Each of a fleet's components by name, with its table and its distribution, None for a component the fleet gives no home."""
    return {
        "pv": (PV_BLOCK, pv),
        "battery": (BATTERY_BLOCK, battery),
        "load": (LOAD_BLOCK, load),
        "heat_pump": (HEAT_PUMP_BLOCK, heat_pump),
        "ev": (EV_BLOCK, ev),
    }


def _fleet_components(
    config: FleetDistributionConfig,
) -> Mapping[str, tuple[ComponentBlock[Any], Optional[ComponentDistribution]]]:
    """Each component of *config* by name, with its table and its distribution, as _components_by_name pairs them."""
    return _components_by_name(
        pv=config.pv, battery=config.battery, load=config.load, heat_pump=config.heat_pump, ev=config.ev
    )


# --- Distribution Parsing and Sampling ---


@dataclass(frozen=True)
class SpecParameter:
    """One scalar key of a distribution type, its caption in an editor, and whether a spec must give it."""

    key: str
    title: str
    required: bool = True


@dataclass(frozen=True)
class SpecRows:
    """A distribution type's paired lists: 'values', and the list paired with it, with its caption in an editor and its entries' kind."""

    paired_key: str
    paired_title: str
    paired_kind: FieldKind

    @property
    def keys(self) -> tuple[str, str]:
        """The two lists' keys, 'values' first."""
        return ("values", self.paired_key)


@dataclass(frozen=True)
class DistributionType:
    """One type a distribution spec names in its ``type:`` key: its title, the spec_type its build returns, and its keys beside 'type', those an editor holds as parameters and rows, then the unheld keys it has no input for."""

    name: str
    title: str
    spec_type: type[object]
    build: Callable[[dict[str, Any], str], DistributionSpec]
    parameters: tuple[SpecParameter, ...] = ()
    rows: Optional[SpecRows] = None
    unheld_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Refuse a type whose keys do not hold its spec, naming them: a spec dataclass's keys are its fields in order, and the scalar form's are one key beside 'type'."""
        if is_dataclass(self.spec_type):
            spec_fields = tuple(each.name for each in fields(self.spec_type))
            if self.spec_keys != spec_fields:
                raise ConfigurationError(
                    f"DistributionType {self.name!r}: its keys {self.spec_keys!r} must be "
                    f"{self.spec_type.__name__}'s fields in order, {spec_fields!r}"
                )
        elif len(self.spec_keys) != 1 or "type" in self.spec_keys:
            raise ConfigurationError(
                f"DistributionType {self.name!r}: the scalar form gives one key beside 'type', got {self.spec_keys!r}"
            )

    @property
    def spec_keys(self) -> tuple[str, ...]:
        """Every key a spec of the type gives beside 'type', in order: its parameters', its rows', then its unheld keys."""
        rows = self.rows.keys if self.rows is not None else ()
        return (*(parameter.key for parameter in self.parameters), *rows, *self.unheld_keys)

    @property
    def recognised_keys(self) -> frozenset[str]:
        """Every key a spec of the type recognises, 'type' among them."""
        return frozenset({"type", *self.spec_keys})

    @property
    def editable(self) -> bool:
        """Whether an editor holds every key of the type: one with unheld keys is not."""
        return not self.unheld_keys

    @property
    def is_scalar_form(self) -> bool:
        """Whether its spec is the bare number a key gives every home, which an editor offers as its own Fixed Value option."""
        return not is_dataclass(self.spec_type)

    def drawn_by(self, kind: FieldKind) -> bool:
        """Whether a field of *kind* draws a spec of the type, as DRAWN_KIND_RULES says; a kind it holds no rule for draws none."""
        rule = DRAWN_KIND_RULES.get(kind)
        return rule is not None and issubclass(self.spec_type, rule.spec_types)

    def write(self, spec: DistributionSpec) -> dict[str, Any]:
        """The mapping build reads back as *spec*: its type, then every key in spec_keys' order, a None one as null, which build reads as absent.

        A spec dataclass gives each key its field of the same name, as construction checks; the
        scalar form's spec is its one key's value.

        Raises:
            ConfigurationError: If *spec* is not of the type, naming the type and *spec*: a
                dataclass type's spec is an instance of its spec_type, the scalar form's a null
                or a number.
        """
        if self.is_scalar_form:
            of_the_type = spec is None or isinstance(spec, (int, float))
        else:
            of_the_type = isinstance(spec, self.spec_type)
        if not of_the_type:
            raise ConfigurationError(f"DistributionType {self.name!r} cannot write {spec!r}, which is no spec of its type")
        held = (spec,) if self.is_scalar_form else tuple(getattr(spec, key) for key in self.spec_keys)
        return {"type": self.name, **{key: _written_value(value) for key, value in zip(self.spec_keys, held, strict=True)}}


def _written_value(value: object) -> object:
    """*value*, a spec's field, as plain data: a tuple as a list of its elements, a SweepSpec as the mapping _parse_proportional_to_multiplier reads, anything else as it is."""
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, SweepSpec):
        return {"type": "sweep", **{each.name: getattr(value, each.name) for each in fields(value)}}
    return value


_SWEEP_SPEC_KEYS: frozenset[str] = frozenset({"type", "min", "max", "steps", "mode"})


def _build_weighted_discrete_spec(
    data: dict[str, Any], block_path: str
) -> WeightedDiscreteDistribution:
    """Build the weighted_discrete distribution a spec names, refusing it unless it gives values and weights."""
    if "values" not in data or "weights" not in data:
        raise ConfigurationError(
            f"weighted_discrete distribution for '{block_path}' requires 'values' and 'weights'"
        )
    return constructed(
        block_path, WeightedDiscreteDistribution, values=data["values"], weights=data["weights"]
    )


def _build_normal_spec(data: dict[str, Any], block_path: str) -> NormalDistribution:
    """Build the normal distribution a spec names, refusing it unless it gives a mean and a std; a min or max it leaves out is NormalDistribution's default."""
    if "mean" not in data or "std" not in data:
        raise ConfigurationError(
            f"normal distribution for '{block_path}' requires 'mean' and 'std'"
        )
    bounds = {key: data[key] for key in ("min", "max") if key in data}
    return constructed(block_path, NormalDistribution, mean=data["mean"], std=data["std"], **bounds)


def _build_uniform_spec(data: dict[str, Any], block_path: str) -> UniformDistribution:
    """Build the uniform distribution a spec names, refusing it unless it gives a min and a max."""
    if "min" not in data or "max" not in data:
        raise ConfigurationError(
            f"uniform distribution for '{block_path}' requires 'min' and 'max'"
        )
    return constructed(block_path, UniformDistribution, min=data["min"], max=data["max"])


def _build_fixed_spec(data: dict[str, Any], block_path: str) -> Optional[float]:
    """Build the fixed value the spec at *block_path*, the parameter's path, names: null, or its value read as a finite number, as the scalar it stands for is read.

    Raises:
        ConfigurationError: If the spec gives no value, or one that is not a finite number,
            text included, naming *block_path*.
    """
    if "value" not in data:
        raise ConfigurationError(
            f"fixed distribution for '{block_path}' requires 'value'"
        )
    value = data["value"]
    return None if value is None else as_finite_real(value, block_path)


def _build_shuffled_pool_spec(
    data: dict[str, Any], block_path: str
) -> ShuffledPoolDistribution:
    """Build the shuffled_pool distribution a spec names, refusing it unless it gives values and counts."""
    if "values" not in data or "counts" not in data:
        raise ConfigurationError(
            f"shuffled_pool distribution for '{block_path}' requires 'values' and 'counts'"
        )
    return constructed(block_path, ShuffledPoolDistribution, values=data["values"], counts=data["counts"])


def _parse_proportional_to_multiplier(data: Any, block_path: str) -> Union[float, SweepSpec]:
    """Parse the multiplier of the spec at *block_path*: a number, as written, for ProportionalDistribution to read, or a sweep given as a mapping, built at the multiplier's path, refusing one that leaves out its min, max or steps, naming each by its path."""
    if not isinstance(data, dict):
        return data
    if data.get("type") != "sweep":
        raise ConfigurationError(
            f"proportional_to multiplier dict for '{block_path}' must have type='sweep'"
        )
    multiplier_path = child_path(block_path, "multiplier")
    refuse_unrecognised_keys(multiplier_path, data, _SWEEP_SPEC_KEYS)
    refuse_missing_keys(multiplier_path, [key for key in ("min", "max", "steps") if key not in data])
    return constructed(multiplier_path, SweepSpec, **{key: value for key, value in data.items() if key != "type"})


def _build_proportional_to_spec(
    data: dict[str, Any], block_path: str
) -> ProportionalDistribution:
    """Build the proportional_to distribution a spec names, refusing it unless it gives a source; a multiplier or offset it leaves out is ProportionalDistribution's default."""
    if "source" not in data:
        raise ConfigurationError(
            f"proportional_to distribution for '{block_path}' requires 'source'"
        )
    given: dict[str, object] = {key: data[key] for key in ("offset",) if key in data}
    if "multiplier" in data:
        given["multiplier"] = _parse_proportional_to_multiplier(data["multiplier"], block_path)
    return constructed(block_path, ProportionalDistribution, source=data["source"], **given)


#: The per-type table of the distribution grammar, by name, in the order a refusal lists them,
#: which the parser, the editor and the writers read.
DISTRIBUTION_TYPES: Mapping[str, DistributionType] = MappingProxyType({
    distribution_type.name: distribution_type
    for distribution_type in (
        DistributionType(
            "weighted_discrete",
            "Weighted Discrete",
            WeightedDiscreteDistribution,
            _build_weighted_discrete_spec,
            rows=SpecRows("weights", "Weight", FieldKind.NUMBER),
        ),
        DistributionType(
            "normal",
            "Normal (Gaussian)",
            NormalDistribution,
            _build_normal_spec,
            parameters=(
                SpecParameter("mean", "Mean"),
                SpecParameter("std", "Std Dev"),
                SpecParameter("min", "Min (clamp)", required=False),
                SpecParameter("max", "Max (clamp)", required=False),
            ),
        ),
        DistributionType(
            "uniform",
            "Uniform",
            UniformDistribution,
            _build_uniform_spec,
            parameters=(SpecParameter("min", "Min"), SpecParameter("max", "Max")),
        ),
        DistributionType(
            "fixed", "Fixed Value", float, _build_fixed_spec, parameters=(SpecParameter("value", "Value"),)
        ),
        DistributionType(
            "shuffled_pool",
            "Shuffled Pool",
            ShuffledPoolDistribution,
            _build_shuffled_pool_spec,
            rows=SpecRows("counts", "Count", FieldKind.COUNT),
        ),
        DistributionType(
            "proportional_to",
            "Proportional To",
            ProportionalDistribution,
            _build_proportional_to_spec,
            unheld_keys=("source", "multiplier", "offset"),
        ),
    )
})


def write_distribution_spec(spec: DistributionSpec) -> object:
    """Write *spec* as the value the grammar reads back as it, the inverse of its reading of a drawn key.

    A null, a number or a choice, the scalar forms, is written as it is; any other spec as the
    write of the DISTRIBUTION_TYPES record whose spec_type it is an instance of.

    Raises:
        ConfigurationError: If no record writes *spec*, naming it and the table's types.
    """
    if spec is None or isinstance(spec, (int, float, str)):
        return spec
    for distribution_type in DISTRIBUTION_TYPES.values():
        if isinstance(spec, distribution_type.spec_type):
            return distribution_type.write(spec)
    raise ConfigurationError(
        f"Cannot write {spec!r}; valid specs: null, a number, a choice, or a spec of {', '.join(DISTRIBUTION_TYPES)}"
    )


def editor_types(kind: FieldKind) -> tuple[DistributionType, ...]:
    """The editable types a field of *kind* draws, in table order; none for a kind no home draws.

    The scalar form is left out: it is the editor's own Fixed Value option, titled by its record.
    """
    return tuple(
        distribution_type
        for distribution_type in DISTRIBUTION_TYPES.values()
        if distribution_type.drawn_by(kind) and distribution_type.editable and not distribution_type.is_scalar_form
    )


def _parse_distribution_spec(data: Any, param_name: str) -> DistributionSpec:
    """Parse a distribution specification from config data.

    Args:
        data: Raw data: null, a distribution mapping, or any other value, read as the number
            every home is given
        param_name: The parameter's path in its file, named in error messages

    Returns:
        DistributionSpec (distribution object, a finite float, or None)

    Raises:
        ConfigurationError: If distribution specification is invalid; a value that is
            neither null nor a mapping and is not a finite number, text included, is
            refused naming *param_name* and the value
    """
    if data is None:
        return None
    if not isinstance(data, dict):
        return as_finite_real(data, param_name)

    dist_type = data.get("type")
    if dist_type is None:
        raise ConfigurationError(
            f"Distribution for '{param_name}' requires 'type' field"
        )
    distribution_type = DISTRIBUTION_TYPES.get(dist_type) if isinstance(dist_type, str) else None
    if distribution_type is None:
        raise ConfigurationError(
            f"Unknown distribution type '{dist_type}' for '{param_name}'. "
            f"Supported: {', '.join(DISTRIBUTION_TYPES)}"
        )
    refuse_unrecognised_keys(param_name, data, distribution_type.recognised_keys)
    return distribution_type.build(data, param_name)


def _parse_drawn_spec(row: FleetField, data: object, key_path: str) -> DistributionSpec:
    """Read the spec of the drawn key at *key_path*, whose fleet row is *row*, as _refuse_a_spec_its_row_cannot_draw admits it.

    A CHOICE's value is the spec as written when _is_a_choice_spec_as_written says so; any other
    value is read as _parse_distribution_spec reads it. A spec the row's kind does not draw is
    refused naming *key_path* and the spec as written.
    """
    spec = data if _is_a_choice_spec_as_written(row, data) else _parse_distribution_spec(data, key_path)
    return _refuse_a_spec_its_row_cannot_draw(row, spec, key_path, written=data)


def _is_a_choice_spec_as_written(row: FleetField, data: object) -> bool:
    """Whether *data*, given the key whose fleet row is *row*, is a CHOICE's spec as written, never read as a distribution.

    It is when it is no mapping, or a mapping naming a type of DISTRIBUTION_TYPES that the row's
    kind does not draw, as its drawn_by says, a type of numbers, so the CHOICE refuses it as a spec
    it does not draw before a number in it is read, a fixed one's value included.
    """
    if row.kind is not FieldKind.CHOICE:
        return False
    if not isinstance(data, dict):
        return True
    named = data.get("type")
    named_type = DISTRIBUTION_TYPES.get(named) if isinstance(named, str) else None
    return named_type is not None and not named_type.drawn_by(row.kind)


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
    even when null, as _parse_drawn_spec reads it.
    """
    mapping = refuse_unrecognised_keys(block_path, data, block.fleet)
    _refuse_required_fleet_keys_left_out(block, mapping, block_path)
    draws: dict[str, DistributionSpec] = {}
    settings: dict[str, SettingValue] = {}
    for key, row in block.fleet.items():
        if key not in mapping:
            continue
        value, key_path = mapping[key], child_path(block_path, key)
        if row.kind not in _GIVEN_EVERY_HOME:
            draws[key] = _parse_drawn_spec(row, value, key_path)
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
    data: dict[str, Any], *, block_path: str = _FLEET_DISTRIBUTION_PATH
) -> FleetDistributionConfig:
    """Parse the fleet_distribution: block at *block_path*, each component block read by its table's fleet rows.

    The refusals of a key outside its component's rows, a required key left out, a spec its
    key's kind does not draw and a proportional_to source not drawn earlier for every home that
    draws the dependent name the key under *block_path*.
    """
    refuse_unrecognised_keys(block_path, data, _FLEET_DISTRIBUTION_BLOCK_KEYS)
    if "n_homes" not in data:
        raise ConfigurationError("Fleet distribution config requires 'n_homes'")
    if "pv" not in data:
        raise ConfigurationError("Fleet distribution config requires 'pv' section")

    pv = _parse_component_distribution(PV_BLOCK, data["pv"], block_path=child_path(block_path, "pv"))
    load = _parse_component_distribution(LOAD_BLOCK, data.get("load", {}), block_path=child_path(block_path, "load"))
    battery = _parse_optional_component_distribution(
        BATTERY_BLOCK, data.get("battery"), block_path=child_path(block_path, "battery")
    )
    heat_pump = _parse_optional_component_distribution(
        HEAT_PUMP_BLOCK, data.get("heat_pump"), block_path=child_path(block_path, "heat_pump")
    )
    ev = _parse_optional_component_distribution(EV_BLOCK, data.get("ev"), block_path=child_path(block_path, "ev"))
    _refuse_proportional_sources_not_drawn_earlier(
        _components_by_name(pv=pv, battery=battery, load=load, heat_pump=heat_pump, ev=ev), block_path
    )
    return constructed(
        block_path,
        FleetDistributionConfig,
        n_homes=data["n_homes"],
        pv=pv,
        load=load,
        battery=battery,
        heat_pump=heat_pump,
        ev=ev,
        seed=data.get("seed"),
        random_order=data.get("random_order", "default"),
        dispatch_strategy=read_dispatch_strategy_key(data, block_path=block_path),
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


def _refuse_unless_finite(value: SpecValue, path: str) -> None:
    """Refuse *value*, a proportional_to's computed count of the field at *path*, if it is an infinity or a NaN, to which no whole number is nearest, naming *path* and the value; a multiplier overflow makes an infinity."""
    if isinstance(value, float) and not math.isfinite(value):
        raise ConfigurationError.must_be(path, "a finite number", got=value)


def _converted_count(value: SpecValue, spec: DistributionSpec, path: str) -> SpecValue:
    """Return the count of the COUNT field at *path*, an occupant count or an EV hour alike, for *value*, drawn from *spec*; this is the sampler's one count conversion.

    A draw from a normal or uniform distribution gives the whole number nearest it among those
    from the spec's min to its max, as _nearest_count states, and a proportional_to's value the
    whole number nearest it, a half rounding up either way. The whole number is returned as a
    float, so a refusal of the count names it as drawn, 1e+300 rather than the 301-digit int it
    equals. A fixed value is returned as the spec gives it, and a listed outcome as drawn, for
    the component's type to read, so a fractional one is refused there.

    Raises:
        ConfigurationError: If a proportional_to's value is an infinity or a NaN, naming *path*
            and the value; or as _nearest_count does, for a normal or uniform distribution with
            no whole number from its min to its max.
    """
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

    FleetDistributionConfig refuses, as it is built, a source that is not a number or count
    field drawn earlier for every home that draws *path*; these refusals check that rule again
    where the source is used.

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
        gives None, a bare choice or number gives itself as given, for the home's type to
        read, and a weighted discrete, normal or uniform spec draws from the RNG.

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
        if spec is None or isinstance(spec, (str, int, float)):
            return spec
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


_Component = TypeVar("_Component", bound=DataclassInstance)


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
            raise ConfigurationError(f"{child_path(_FLEET_DISTRIBUTION_PATH, path)} is required, but {got}")
    try:
        return block.config_type(**values, **component.settings, **given)
    except (ValueError, TypeError) as refusal:
        raise ConfigurationError(
            f"{child_path(_FLEET_DISTRIBUTION_PATH, name)}, home {home_number}: {refusal}"
        ) from refusal


def _drawn_component_every_home_has(
    name: str,
    block: ComponentBlock[_Component],
    component: Optional[ComponentDistribution],
    sampler: _DistributionSampler,
    drawn: dict[str, SpecValue],
    home_number: int,
    *,
    given: Mapping[str, object] = _NOTHING_GIVEN,
) -> _Component:
    """Draw and build home *home_number*'s *name* component as _drawn_component does, for a component in _EVERY_HOME_HAS.

    Raises:
        ConfigurationError: As _drawn_component does; or if the home is given no *name*
            component, naming the component and the home.
    """
    built = _drawn_component(name, block, component, sampler, drawn, home_number, given=given)
    if built is None:
        raise ConfigurationError(
            f"{child_path(_FLEET_DISTRIBUTION_PATH, name)} gave home {home_number} no {name}, which every home needs"
        )
    return built


_Built = TypeVar("_Built")


def _checked_component(built: Mapping[str, object], name: str, config_type: type[_Built]) -> _Built:
    """The home's *name* component in *built*, checked to be a *config_type*.

    Raises:
        TypeError: If *built* holds another type under *name*, naming the component and both types.
    """
    component = built[name]
    if not isinstance(component, config_type):
        raise TypeError(
            f"home component {name!r} was built as {type(component).__name__}, not {config_type.__name__}"
        )
    return component


def _checked_component_or_none(
    built: Mapping[str, object], name: str, config_type: type[_Built]
) -> Optional[_Built]:
    """The home's *name* component in *built* as _checked_component checks it; None when the home has none.

    Raises:
        TypeError: As _checked_component does.
    """
    if built[name] is None:
        return None
    return _checked_component(built, name, config_type)


def _generated_home(
    config: FleetDistributionConfig,
    sampler: _DistributionSampler,
    index: int,
    location: Location,
    fleet_tariff: Optional[TariffConfig],
) -> HomeConfig:
    """The fleet's home at *index*: it draws its components in _HOME_DRAW_ORDER (T3), each by its table's fleet rows.

    A component in _EVERY_HOME_HAS is drawn as _drawn_component_every_home_has draws it, any
    other as _drawn_component does. Each load's seed is fleet.fleet_home_seed of the fleet's
    seed and the home's index. Each component goes into HomeConfig only after it is checked to
    be its own field's type.
    """
    home_number = index + 1
    drawn: dict[str, SpecValue] = {}
    components = _fleet_components(config)
    given = {"load": {"seed": fleet_home_seed(config.seed, index)}}
    built: dict[str, object] = {}
    for name in _HOME_DRAW_ORDER:
        block, component = components[name]
        draw = _drawn_component_every_home_has if name in _EVERY_HOME_HAS else _drawn_component
        built[name] = draw(name, block, component, sampler, drawn, home_number, given=given.get(name, _NOTHING_GIVEN))
    return HomeConfig(
        pv_config=_checked_component(built, "pv", PVConfig),
        battery_config=_checked_component_or_none(built, "battery", BatteryConfig),
        load_config=_checked_component(built, "load", LoadConfig),
        heat_pump_config=_checked_component_or_none(built, "heat_pump", HeatPumpConfig),
        ev_config=_checked_component_or_none(built, "ev", EVConfig),
        location=location,
        name=f"Home {home_number}",
        tariff_config=fleet_tariff,
        **dispatch_strategy_argument(config.dispatch_strategy),
    )


def generate_homes_from_distribution(
    config: FleetDistributionConfig,
    location: Location,
    *,
    fleet_tariff: Optional[TariffConfig] = None,
) -> list[HomeConfig]:
    """Generate a list of homes by sampling from distributions.

    Each home draws its components in _HOME_DRAW_ORDER, each component's keys in its table's
    fleet order, through one sampler (_DistributionSampler).

    Args:
        config: Fleet distribution configuration
        location: Location for all homes
        fleet_tariff: Optional TariffConfig to apply to every home. When None
            (default) homes are generated with tariff_config=None, preserving
            bit-identical behaviour for callers that do not pass this kwarg.

    Returns:
        List of HomeConfig objects

    Raises:
        ConfigurationError: As the sampler refuses a draw, naming its setting (a normal or
            uniform draw that is not a finite number, a count with no whole number from its
            spec's min to its max, a proportional_to's count that is an infinity or a
            NaN); if a required field draws null, naming its path and the
            home; if a presence rule refuses a draw, as battery.has_battery refuses a
            negative or non-finite battery capacity; if the fleet gives a home no PV or no
            load, which every home needs, naming the component and the home; as a
            component's dataclass refuses what it is built from, naming the component and
            the home; or as HomeConfig refuses a home whose battery's dispatch would ignore
            a setting (tou_optimized with no fleet_tariff, or a grid_charging its dispatch
            would ignore), in HomeConfig's words, which name neither the home nor the
            fleet_distribution block.
            Where it uses them, it checks again what FleetDistributionConfig
            refuses as it is built: that each shuffled pool's counts total config.n_homes,
            that each required field is drawn and that each proportional_to's source is a
            number the home drew earlier.
    """
    _refuse_pools_not_sized_to_the_fleet(config)
    sampler = _DistributionSampler(config)
    return [_generated_home(config, sampler, index, location, fleet_tariff) for index in range(config.n_homes)]


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
