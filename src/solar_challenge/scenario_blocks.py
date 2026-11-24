# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read one block of a scenario file into a value of a domain module, naming the block's path.

The component tables it reads blocks by also carry each key's fleet row and each nested block's
writer, which the fleet grammar and scenario_writer read, so a field's key is declared once.
"""

from dataclasses import MISSING, asdict, dataclass, field, fields
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Collection,
    Generic,
    Iterable,
    Mapping,
    Optional,
    Protocol,
    TypeVar,
    Union,
)

from solar_challenge.battery import BatteryConfig, has_battery
from solar_challenge.community import CommunityBillingConfig, CommunityConfig
from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.dispatch import STRATEGY_CONFIG_BY_TYPE, DispatchStrategyConfig, GridChargeConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import CHARGER_TYPES, EVConfig
from solar_challenge.finance import FinanceConfig
from solar_challenge.gridservices import EventWindow, GridServicesEventsConfig
from solar_challenge.heat_pump import HEAT_PUMP_TYPES, HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from solar_challenge.tariff import PRESET_RATES, PresetRates, TariffConfig, TariffPeriod


#: The value a fleet gives every home for a SETTING or FLAG key: a SETTING's as written or as its
#: sub-block reads it, a FLAG's as true or false.
SettingValue = Union[bool, str, GridChargeConfig, DispatchStrategyConfig, None]


def child_path(block_path: str, key: str) -> str:
    """Return the path of the *key* block inside the block at *block_path*; "" is the top level."""
    return f"{block_path}.{key}" if block_path else key


def block_label(block_path: str) -> str:
    """Name the block at *block_path* in an error message."""
    return block_path or "the top level"


def refusal(block_path: str, problem: str) -> ConfigurationError:
    """Return the refusal of the block at *block_path*, reading "<block label>: <problem>".

    The caller raises it, ``from`` the exception that caused it where there is one.
    """
    return ConfigurationError(f"{block_label(block_path)}: {problem}")


def require_mapping(block_path: str, data: object) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping."""
    if not isinstance(data, dict):
        raise refusal(block_path, f"must be a mapping, got {type(data).__name__}")
    return data


def require_list(block_path: str, data: object) -> list[Any]:
    """Return the list at *block_path*, refusing it unless it is a list."""
    if not isinstance(data, list):
        raise refusal(block_path, f"must be a list, got {type(data).__name__}")
    return data


def refuse_unrecognised_keys(
    block_path: str, data: object, recognised: Collection[str]
) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping holding only *recognised* keys."""
    mapping = require_mapping(block_path, data)
    unrecognised = sorted(repr(key) for key in mapping.keys() - recognised)
    if unrecognised:
        raise refusal(
            block_path,
            f"unrecognised keys {', '.join(unrecognised)}; "
            f"recognised keys: {', '.join(sorted(recognised))}",
        )
    return mapping


def refuse_retired_keys(block_path: str, data: object, retired: Mapping[str, str]) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping holding no key of *retired*, null or not, naming the first such key's path and why it is refused."""
    block = require_mapping(block_path, data)
    for key, why in retired.items():
        if key in block:
            raise refusal(child_path(block_path, key), why)
    return block


RETIRED_DISPATCH_STRATEGY_KEY: Mapping[str, str] = MappingProxyType({
    "dispatch_strategy": (
        "the dispatch strategy is the battery's own setting; write it in the battery block, "
        "as battery.dispatch_strategy: {strategy_type: tou_optimized}; a battery that sets none "
        "dispatches self_consumption, as greedy did"
    ),
})
"""The home's and the fleet's retired dispatch_strategy key, with why it is refused and what replaces it."""


def _read_name(block: Mapping[str, Any], *, block_path: str) -> str:
    """Return the name the block at *block_path* sets, "" when it sets none or a null one, refusing a name that is not a string by its path."""
    name = block.get("name")
    if name is None:
        return ""
    if not isinstance(name, str):
        raise refusal(child_path(block_path, "name"), f"must be a string, got {name!r}")
    return name


_Built = TypeVar("_Built")


@dataclass(frozen=True)
class BlockType(Generic[_Built]):
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
_Value = TypeVar("_Value")


@dataclass(frozen=True)
class ReaderOnlyKey(Generic[_Component]):
    """A key of a component's block that no field holds: the block's reader applies it to the component it builds.

    *apply* gives the component with the key's value applied, setting the fields *sets* names;
    a block may set the key or those fields, not both. *subject* and *form* name, in the
    refusal of a block setting both, what the key and the fields are two forms of and the
    key's form of it. tests/unit/config/test_component_blocks.py holds each one to be a key of
    its block and no field of the dataclass (T1).
    """

    sets: tuple[str, ...]
    apply: Callable[[_Component, Any], _Component]
    subject: str
    form: str


@dataclass(frozen=True)
class ComponentBlock(Generic[_Component]):
    """A component's block in the scenario grammar, stated against the dataclass it builds.

    *config_type* is the dataclass. *keys* are the block's keys: the fields it carries, in field
    order, and its reader-only keys; *outside_grammar* maps each other field to the reason no key
    carries it. *sub_blocks*
    holds the keys whose value is a nested block, and *when_omitted* the value an omitted key
    reads as, for each key where that is not the dataclass's declared default.

    *fleet* holds the keys a fleet_distribution: block gives each home, each with its FleetField,
    in key order, which is the order a home draws them; *not_in_fleet* maps each other key to the
    reason the fleet grammar does not carry it. *presence* is the fleet field whose null draw
    means the home has no such component, and *asks_for_component* says whether its non-null
    draw, at its path, asks for one.

    *reader_only* holds the keys no field holds, each with its ReaderOnlyKey: every builder
    of the component builds it from the other keys, then applies each reader-only key set
    non-null, and refuses a block setting one beside a field it sets; a writer writes none.
    tests/unit/config/test_component_blocks.py holds every table to its dataclass's fields,
    its reader-only keys among its keys and none of them a field (T1).
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
    reader_only: Mapping[str, ReaderOnlyKey[_Component]] = field(default_factory=lambda: MappingProxyType({}))

    def refuse_both_forms(self, keys: Collection[str], block_path: str) -> None:
        """Refuse the block at *block_path* if *keys*, the keys it sets, hold a reader-only key beside a field it sets, naming the block and each key."""
        for key, reader_only in self.reader_only.items():
            present = [name for name in reader_only.sets if name in keys]
            if key in keys and present:
                raise refusal(
                    block_path,
                    f"sets both forms of {reader_only.subject}: {key} and {' and '.join(present)}; "
                    f"set {key}, {reader_only.form}, or {' and '.join(reader_only.sets)}, not both",
                )

    def without_reader_only_keys(self, values: Mapping[str, _Value]) -> dict[str, _Value]:
        """*values*, by key, without the reader-only keys: the values the dataclass is built from."""
        return {key: value for key, value in values.items() if key not in self.reader_only}

    def with_reader_only_keys(self, component: _Component, values: Mapping[str, object], block_path: str) -> _Component:
        """*component* with each reader-only key *values* sets non-null applied, in key order.

        Raises:
            ConfigurationError: As a key's apply refuses its value, naming the key by its path
                under *block_path*, the block's; "" names the key alone.
        """
        for key in self.keys:
            value = values.get(key)
            if key in self.reader_only and value is not None:
                component = constructed(child_path(block_path, key), self.reader_only[key].apply, component, value)
        return component

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
        for key, value in refuse_unrecognised_keys(block_path, data, block.keys).items()
        if value is not None
    }


def refuse_missing_keys(block_path: str, missing_keys: Collection[str]) -> None:
    """Refuse the block at *block_path* if it leaves out any of *missing_keys*, keys it needs, naming each in the order given."""
    if missing_keys:
        raise refusal(block_path, f"requires {', '.join(repr(key) for key in missing_keys)}")


def require_keys(block_path: str, block: Mapping[str, Any], keys: Iterable[str]) -> None:
    """Refuse the block at *block_path* unless it sets each of *keys*, a null key reading as absent, naming each it leaves out in the order given."""
    refuse_missing_keys(block_path, [key for key in keys if block.get(key) is None])


def require_held_keys(block_path: str, block: Mapping[str, Any], keys: Iterable[str]) -> None:
    """Refuse the block at *block_path* unless it holds each of *keys*, null or not, naming each it leaves out in the order given.

    It is require_keys for a block whose null is a value: a fleet's null spec, or a null the
    block's type refuses as it refuses any value.
    """
    refuse_missing_keys(block_path, [key for key in keys if key not in block])


def _required_keys(config_type: type[DataclassInstance]) -> tuple[str, ...]:
    """The keys a block building *config_type* must set: its init fields with neither a default nor a default factory, in field order."""
    return tuple(
        each.name
        for each in fields(config_type)
        if each.init and each.default is MISSING and each.default_factory is MISSING
    )


def constructed(block_path: str, cls: Callable[..., _Built], /, *args: Any, **values: Any) -> _Built:
    """cls(*args, **values), its refusal, a ConfigurationError or a TypeError, re-raised as "<block label>: <message>" from the original."""
    try:
        return cls(*args, **values)
    except (ConfigurationError, TypeError) as exc:
        raise refusal(block_path, str(exc)) from exc


def _built_component(
    block: ComponentBlock[_Component], set_keys: Mapping[str, Any], block_path: str
) -> _Component:
    """The config the block at *block_path* describes, built from the keys it sets.

    Each sub-block it sets is read first, in the table's order; then the dataclass is built once
    from the set values of its fields, as written, over the table's when-omitted values; then
    each reader-only key it sets is applied.

    Raises:
        ConfigurationError: for a block setting a reader-only key beside a field it sets, as
            refuse_both_forms refuses it; naming the block and each key it leaves out that has
            neither a declared default nor a when-omitted value; as its dataclass refuses the
            values, prefixed by the block's path; or as a reader-only key's apply refuses its
            value, prefixed by the key's path.
    """
    block.refuse_both_forms(set_keys, block_path)
    require_keys(
        block_path,
        set_keys,
        [key for key in block.keys if key not in block.reader_only and block.value_when_omitted(key) is MISSING],
    )
    sub_block_configs = {
        key: sub_block.read(set_keys[key], block_path=child_path(block_path, key))
        for key, sub_block in block.sub_blocks.items()
        if key in set_keys
    }
    field_values = block.without_reader_only_keys(set_keys)
    built = constructed(block_path, block.config_type, **{**block.when_omitted, **field_values, **sub_block_configs})
    return block.with_reader_only_keys(built, set_keys, block_path)


def _read_component_block(
    block: ComponentBlock[_Component], data: object, *, block_path: str
) -> _Component:
    """The config the component block at *block_path* describes, read by *block*'s table.

    A key outside the table's keys is refused, null or not; a null key reads as absent; an
    omitted key takes the table's when-omitted value, else the dataclass's declared default; a
    block leaving out a key with neither is refused, naming the block and each key it leaves out;
    and a value the dataclass refuses is refused as it refuses it, prefixed by the block's path.
    """
    return _built_component(block, _set_keys(block, data, block_path), block_path)


def parse_location_block(
    data: Optional[dict[str, Any]], *, block_path: str = "location"
) -> Location:
    """Parse a ``location:`` block into a Location, as LOCATION_BLOCK reads it.

    A block that is absent or sets no key, its null keys read as absent, is Bristol. Otherwise it
    must set latitude and longitude: a block that leaves either out is refused, naming the block
    and each it leaves out. An omitted timezone or altitude takes Bristol's, and an omitted name
    stays empty.
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


_GRID_CHARGING_BLOCK_KEYS: frozenset[str] = frozenset({"target_soc_fraction", "forecast"})


def parse_grid_charge_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[GridChargeConfig]:
    """Parse grid-charging configuration from a dict or None.

    An omitted ``target_soc_fraction`` or ``forecast`` takes GridChargeConfig's declared
    default, so a block that names no forecast is PV-blind.

    Args:
        data: grid_charging mapping (e.g. ``{'target_soc_fraction': 0.9, 'forecast':
            'trailing_14_days'}``) or None.
        block_path: The block's path in its file, named in error messages.

    Returns:
        GridChargeConfig if data is a non-None mapping, else None.

    Raises:
        ConfigurationError: If data is present but not a mapping, or carries a key
            other than ``target_soc_fraction`` and ``forecast``; or as GridChargeConfig
            refuses its target or its forecast, prefixed by the block's path.
    """
    if data is None:
        return None
    return constructed(
        block_path, GridChargeConfig, **refuse_unrecognised_keys(block_path, data, _GRID_CHARGING_BLOCK_KEYS)
    )


def _grid_charging_block(grid_charging: GridChargeConfig) -> dict[str, Any]:
    """The grid_charging: block parse_grid_charge_config reads back as *grid_charging*."""
    return {"target_soc_fraction": grid_charging.target_soc_fraction, "forecast": grid_charging.forecast}


def _parse_battery_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[BatteryConfig]:
    """Parse a battery: block into a BatteryConfig, as _read_component_block reads BATTERY_BLOCK; a null block is no battery.

    Its efficiency is the round trip BatteryConfig.with_round_trip splits, a reader-only key.
    """
    return None if data is None else _read_component_block(BATTERY_BLOCK, data, block_path=block_path)


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
        ConfigurationError: for a strategy_type that is missing or null, naming the block; for
            one that names no variant, naming its path, its value and the variants' tags.
    """
    require_keys(block_path, block, ["strategy_type"])
    tag = block["strategy_type"]
    variant = STRATEGY_CONFIG_BY_TYPE.get(tag) if isinstance(tag, str) else None
    if variant is None:
        raise refusal(
            child_path(block_path, "strategy_type"),
            f"invalid value {tag!r}; valid values: {sorted(STRATEGY_CONFIG_BY_TYPE)}",
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
        ConfigurationError: for a block that is not a mapping; a strategy_type that is missing,
            naming the block, or names no variant, naming its path, its value and the variants' tags; a key the
            variant does not read, unless it is null and another strategy reads it; a key the
            variant needs, left out or null, naming the block and the key; and a value the variant refuses,
            as it refuses it, prefixed by the block's path.
    """
    if data is None:
        return None
    block = require_mapping(block_path, data)
    variant = _strategy_variant(block, block_path)
    variant_fields = [each for each in fields(variant) if each.init]
    set_keys = refuse_unrecognised_keys(
        block_path,
        {key: value for key, value in block.items() if value is not None or key not in _KEYS_A_STRATEGY_READS},
        {"strategy_type", *(each.name for each in variant_fields)},
    )
    require_keys(block_path, set_keys, _required_keys(variant))
    values = {each.name: _tuples(set_keys[each.name]) for each in variant_fields if each.name in set_keys}
    build_variant: Callable[..., DispatchStrategyConfig] = variant
    return constructed(block_path, build_variant, **values)


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
        "grid_charging": SubBlock(parse_grid_charge_config, _grid_charging_block),
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
    reader_only=MappingProxyType({
        "efficiency": ReaderOnlyKey(
            sets=("charge_efficiency", "discharge_efficiency"),
            apply=BatteryConfig.with_round_trip,
            subject="a battery's efficiency",
            form="the round trip",
        ),
    }),
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
        "seed": "the generator gives each home fleet.fleet_home_seed(fleet seed, index)",
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
        {
            key: value
            for key, value in asdict(Location.bristol()).items()
            if key in ("timezone", "altitude")
        }
    ),
    fleet=MappingProxyType({}),
    not_in_fleet=MappingProxyType(
        dict.fromkeys(_LOCATION_KEYS, "a fleet's homes share the location: block of its file")
    ),
)


_TARIFF_PERIOD_KEYS: frozenset[str] = frozenset({"start_time", "end_time", "rate_per_kwh", "name"})

_PRESET_TARIFF_RATE_KEYS: frozenset[str] = frozenset(each.name for each in fields(PresetRates))


def _build_flat_rate_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the flat_rate tariff a block names, refusing it unless it gives a rate."""
    require_keys(block_path, data, ["rate_per_kwh"])
    return constructed(
        block_path,
        TariffConfig.flat_rate,
        rate_per_kwh=data["rate_per_kwh"],
        name=_read_name(data, block_path=block_path),
    )


def _preset_tariff(
    data: dict[str, Any],
    block_path: str,
    factory: Callable[..., TariffConfig],
    preset_rates: PresetRates,
) -> TariffConfig:
    """The tariff *factory* builds for the preset block at *block_path*: its rates as PresetRates reads them over *preset_rates*, its times as written.

    Reads a block that parse_tariff_config has already confined to its type's keys, so a rate
    PresetRates refuses is named by the key the block sets.
    """
    rates = constructed(
        block_path,
        PresetRates,
        **{**asdict(preset_rates), **{key: data[key] for key in _PRESET_TARIFF_RATE_KEYS if key in data}},
    )
    times = {key: value for key, value in data.items() if key != "type" and key not in _PRESET_TARIFF_RATE_KEYS}
    return constructed(block_path, factory, **asdict(rates), **times)


def _build_economy_7_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the Economy 7 tariff a block names, with the overrides it sets."""
    return _preset_tariff(data, block_path, TariffConfig.economy_7, PRESET_RATES["economy_7"])


def _build_economy_10_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the Economy 10 tariff a block names, with the overrides it sets."""
    return _preset_tariff(data, block_path, TariffConfig.economy_10, PRESET_RATES["economy_10"])


def _parse_tariff_period(data: object, *, block_path: str) -> TariffPeriod:
    """Parse one period of a custom tariff block, refusing it unless it gives a start, an end and a rate, and as TariffPeriod refuses it, prefixed by its path."""
    period = refuse_unrecognised_keys(block_path, data, _TARIFF_PERIOD_KEYS)
    require_keys(block_path, period, ["start_time", "end_time", "rate_per_kwh"])
    return constructed(
        block_path,
        TariffPeriod,
        start_time=period["start_time"],
        end_time=period["end_time"],
        rate_per_kwh=period["rate_per_kwh"],
        name=_read_name(period, block_path=block_path),
    )


def _build_custom_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the custom tariff a block names from its periods, refusing it unless it gives a list of some, and as TariffConfig refuses its periods, prefixed by the block's path."""
    require_keys(block_path, data, ["periods"])

    periods_path = child_path(block_path, "periods")
    periods_data = require_list(periods_path, data["periods"])
    if not periods_data:
        raise refusal(periods_path, "must list at least one period")

    periods = tuple(
        _parse_tariff_period(period, block_path=child_path(block_path, f"periods[{index}]"))
        for index, period in enumerate(periods_data)
    )
    return constructed(block_path, TariffConfig, periods=periods, name=_read_name(data, block_path=block_path))


_TARIFF_TYPES: Mapping[str, BlockType[TariffConfig]] = MappingProxyType({
    "flat_rate": BlockType(
        frozenset({"type", "rate_per_kwh", "name"}),
        _build_flat_rate_tariff,
    ),
    "economy_7": BlockType(
        frozenset({"type", *_PRESET_TARIFF_RATE_KEYS, "off_peak_start", "off_peak_end"}),
        _build_economy_7_tariff,
    ),
    "economy_10": BlockType(
        frozenset({
            "type", *_PRESET_TARIFF_RATE_KEYS, "night_start", "night_end", "afternoon_start",
            "afternoon_end", "evening_start", "evening_end",
        }),
        _build_economy_10_tariff,
    ),
    "custom": BlockType(
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
            type does not read; a value the tariff, a custom period or an
            economy preset's rates refuse is refused as they refuse it,
            prefixed by the path of the block or period
    """
    if data is None:
        return None
    require_mapping(block_path, data)

    require_keys(block_path, data, ["type"])
    tariff_type = data["type"]
    block_type = _TARIFF_TYPES.get(tariff_type) if isinstance(tariff_type, str) else None
    if block_type is None:
        raise refusal(
            child_path(block_path, "type"),
            f"unknown tariff type {tariff_type!r}; supported types: {', '.join(_TARIFF_TYPES)}",
        )
    refuse_unrecognised_keys(block_path, data, block_type.recognised_keys)
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

HOME_BLOCK_KEYS: frozenset[str] = frozenset({
    *_HOME_SCALAR_KEYS, "pv", "battery", "load", "tariff", "heat_pump", "ev",
})


def _home_tariff(
    own: Optional[TariffConfig], fleet_tariff: Optional[TariffConfig], *, block_path: str
) -> Optional[TariffConfig]:
    """The tariff of the home at *block_path*: its own, else *fleet_tariff*, refusing an own tariff that differs from *fleet_tariff* by its tariff's path."""
    if own is None:
        return fleet_tariff
    if fleet_tariff is None or own == fleet_tariff:
        return own
    raise refusal(
        child_path(block_path, "tariff"),
        "differs from the scenario's top-level tariff: block, which a home takes when it sets none; "
        "set the tariff once, or make the two equal",
    )


def parse_home_block(
    data: dict[str, Any],
    location: Location,
    *,
    block_path: str = "home",
    fleet_tariff: Optional[TariffConfig] = None,
) -> HomeConfig:
    """Parse a ``home:`` block, or one ``homes:`` entry, into a HomeConfig at *location*.

    A key the block omits takes HomeConfig's declared default, and so does a null scalar. An
    omitted pv or load block reads as an empty one. A block with no tariff of its own is built
    with *fleet_tariff*, the scenario's, before HomeConfig checks it.

    Raises:
        ConfigurationError: the block is not a mapping; it holds the retired dispatch_strategy
            key, the battery's own setting, null or not, naming the battery's key in its place
            (RETIRED_DISPATCH_STRATEGY_KEY); as each of its blocks' readers refuses that block;
            its own tariff differs from *fleet_tariff*, naming its tariff's path and the
            scenario's tariff: block; or as HomeConfig refuses the home its blocks describe,
            prefixed by the block's path.
    """
    home = refuse_unrecognised_keys(
        block_path, refuse_retired_keys(block_path, data, RETIRED_DISPATCH_STRATEGY_KEY), HOME_BLOCK_KEYS
    )
    return constructed(
        block_path,
        HomeConfig,
        pv_config=_parse_pv_config(home.get("pv", {}), block_path=child_path(block_path, "pv")),
        battery_config=_parse_battery_config(
            home.get("battery"), block_path=child_path(block_path, "battery")
        ),
        load_config=_parse_load_config(
            home.get("load", {}), block_path=child_path(block_path, "load")
        ),
        location=location,
        tariff_config=_home_tariff(
            parse_tariff_config(home.get("tariff"), block_path=child_path(block_path, "tariff")),
            fleet_tariff,
            block_path=block_path,
        ),
        heat_pump_config=_parse_heat_pump_config(
            home.get("heat_pump"), block_path=child_path(block_path, "heat_pump")
        ),
        ev_config=_parse_ev_config(home.get("ev"), block_path=child_path(block_path, "ev")),
        **{key: home[key] for key in _HOME_SCALAR_KEYS if home.get(key) is not None},
    )


_SEG_BLOCK_KEYS: frozenset[str] = frozenset({"preset", "rate_pence_per_kwh"})


def parse_seg_rate(data: object, *, block_path: str = "seg") -> Optional[float]:
    """Read the SEG export rate in pence/kWh from a ``seg:`` block.

    The block names exactly one of a :data:`~solar_challenge.seg.SEG_PRESETS`
    ``preset`` or a ``rate_pence_per_kwh`` that :func:`_parse_seg_rate_scalar`
    accepts.  ``None`` means no SEG; any other shape raises
    :exc:`ConfigurationError` naming *block_path*, and a rate SEGTariff refuses is
    refused as it refuses it, prefixed by *block_path*.
    """
    if data is None:
        return None
    data = refuse_unrecognised_keys(block_path, data, _SEG_BLOCK_KEYS)
    if ("preset" in data) == ("rate_pence_per_kwh" in data):
        raise refusal(
            block_path, f"must specify exactly one of 'preset' or 'rate_pence_per_kwh', got {data!r}"
        )
    if "rate_pence_per_kwh" in data:
        return _parse_seg_rate_scalar(data["rate_pence_per_kwh"], block_path=block_path)
    try:
        return resolve_seg_tariff(data["preset"]).rate_pence_per_kwh
    except (ValueError, TypeError) as exc:
        raise refusal(child_path(block_path, "preset"), str(exc)) from exc


def _parse_seg_rate_scalar(value: Any, *, block_path: str) -> float:
    """Read a SEG export rate in pence/kWh as :class:`SEGTariff` reads it, a refusal prefixed by *block_path*, the rate's place in its file."""
    return constructed(block_path, SEGTariff, name="", rate_pence_per_kwh=value).rate_pence_per_kwh


_FINANCE_BLOCK_KEYS: frozenset[str] = frozenset(each.name for each in fields(FinanceConfig) if each.init)

_GRID_SERVICES_EVENTS_BLOCK_KEYS: frozenset[str] = frozenset(
    each.name for each in fields(GridServicesEventsConfig) if each.init
)

_EVENT_WINDOW_KEYS: frozenset[str] = frozenset(each.name for each in fields(EventWindow) if each.init)
"""The keys an event window recognises: EventWindow's init fields."""


def _parse_event_windows(data: object, *, block_path: str) -> tuple[EventWindow, ...]:
    """Parse the event_windows list at *block_path* into EventWindows, each refused as EventWindow refuses it, prefixed by its path."""
    parsed_windows: list[EventWindow] = []
    for i, ew_dict in enumerate(require_list(block_path, data)):
        window_path = f"{block_path}[{i}]"
        window = refuse_unrecognised_keys(window_path, ew_dict, _EVENT_WINDOW_KEYS)
        require_keys(window_path, window, _required_keys(EventWindow))
        parsed_windows.append(constructed(window_path, EventWindow, **window))
    return tuple(parsed_windows)


def _parse_grid_services_events_config(
    data: object, *, block_path: str
) -> Optional[GridServicesEventsConfig]:
    """Parse a finance block's grid_services_events block; absent or null is no events config.

    A key the block omits takes GridServicesEventsConfig's declared default, so an omitted
    event_windows is the default schedule, DEFAULT_EVENT_WINDOWS. Its event windows are read
    first, then a value GridServicesEventsConfig refuses is refused as it refuses it, prefixed
    by the block's path.
    """
    if data is None:
        return None
    gs_data = refuse_unrecognised_keys(block_path, data, _GRID_SERVICES_EVENTS_BLOCK_KEYS)
    event_windows = (
        {
            "event_windows": _parse_event_windows(
                gs_data["event_windows"], block_path=child_path(block_path, "event_windows")
            )
        }
        if "event_windows" in gs_data
        else {}
    )
    return constructed(block_path, GridServicesEventsConfig, **{**gs_data, **event_windows})


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
        ConfigurationError: If the block, its grid_services_events block or an
            event window is not a mapping or carries a key it does not read, or
            leaves out a key it requires; or for a value FinanceConfig,
            GridServicesEventsConfig or an EventWindow refuses, as it refuses
            it, prefixed by its block's path
    """
    if data is None:
        return None
    refuse_unrecognised_keys(block_path, data, _FINANCE_BLOCK_KEYS)
    require_held_keys(block_path, data, ["standing_charge_pence_per_day"])

    grid_services_events = _parse_grid_services_events_config(
        data.get("grid_services_events"),
        block_path=child_path(block_path, "grid_services_events"),
    )
    return constructed(block_path, FinanceConfig, **{**data, "grid_services_events": grid_services_events})


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
            does not read, an ambiguous SEG specification or a malformed ``seg``
            block; for a ``seg_rate_pence_per_kwh``, null or not, that SEGTariff
            refuses, as it refuses it, prefixed by the key's path; or as
            CommunityBillingConfig refuses the block, prefixed by its path.
    """
    if data is None:
        return None
    refuse_unrecognised_keys(block_path, data, _COMMUNITY_BILLING_BLOCK_KEYS)

    tariff = parse_tariff_config(data.get("tariff"), block_path=child_path(block_path, "tariff"))

    # Resolve SEG rate (three mutually-exclusive forms)
    direct_rate: Optional[float] = None
    if "seg_rate_pence_per_kwh" in data:
        direct_rate = _parse_seg_rate_scalar(
            data["seg_rate_pence_per_kwh"],
            block_path=child_path(block_path, "seg_rate_pence_per_kwh"),
        )

    seg_block = data.get("seg")

    if direct_rate is not None and seg_block is not None:
        raise refusal(block_path, "sets both seg_rate_pence_per_kwh and seg; set one, not both")

    seg_rate = (
        direct_rate
        if direct_rate is not None
        else parse_seg_rate(seg_block, block_path=child_path(block_path, "seg"))
    )

    # Normalise an all-None result to None so callers can reliably test ``is None``
    # for "no billing configured" without distinguishing an empty block from an
    # absent key.
    if tariff is None and seg_rate is None:
        return None
    return constructed(block_path, CommunityBillingConfig, tariff=tariff, seg_rate_pence_per_kwh=seg_rate)


_COMMUNITY_BLOCK_KEYS: frozenset[str] = frozenset({
    "sharing_mode", "community_battery", "billing",
})


def parse_community_config(
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
            does not read, or a missing ``sharing_mode``; as a nested block's reader
            refuses that block; or as CommunityConfig refuses the block, such as an
            unknown ``sharing_mode``, p2p+battery or community_battery-without-battery,
            prefixed by its path.
    """
    if data is None:
        return None
    refuse_unrecognised_keys(block_path, data, _COMMUNITY_BLOCK_KEYS)

    sharing_mode = data.get("sharing_mode")
    if not sharing_mode:
        raise refusal(block_path, "requires 'sharing_mode': 'p2p' or 'community_battery'")

    community_battery = _parse_battery_config(
        data.get("community_battery"), block_path=child_path(block_path, "community_battery")
    )
    billing = _parse_community_billing_config(
        data.get("billing"), block_path=child_path(block_path, "billing")
    )

    return constructed(
        block_path,
        CommunityConfig,
        sharing_mode=sharing_mode,
        community_battery=community_battery,
        billing=billing,
    )
