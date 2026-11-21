# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read one block of a scenario file into a value of a domain module, naming the block's path."""

import math
from dataclasses import MISSING, asdict, dataclass, fields
from enum import Enum
from types import MappingProxyType
from typing import (
    Any,
    Callable,
    Collection,
    Generic,
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
from solar_challenge.home import HomeConfig, refuse_unknown_home_dispatch_strategy
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff, resolve_seg_tariff
from solar_challenge.tariff import TariffConfig, TariffPeriod


#: The value a fleet gives every home for a SETTING or FLAG key: a SETTING's as written or as its
#: sub-block reads it, a FLAG's as true or false.
SettingValue = Union[bool, str, GridChargeConfig, DispatchStrategyConfig, None]


def child_path(block_path: str, key: str) -> str:
    """Return the path of the *key* block inside the block at *block_path*; "" is the top level."""
    return f"{block_path}.{key}" if block_path else key


def block_label(block_path: str) -> str:
    """Name the block at *block_path* in an error message."""
    return block_path or "the top level"


def require_mapping(block_path: str, data: object) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping."""
    if not isinstance(data, dict):
        raise ConfigurationError(
            f"{block_label(block_path)} must be a mapping, got {type(data).__name__}"
        )
    return data


def refuse_unrecognised_keys(
    block_path: str, data: object, recognised: Collection[str]
) -> dict[Any, Any]:
    """Return the block at *block_path*, refusing it unless it is a mapping holding only *recognised* keys."""
    mapping = require_mapping(block_path, data)
    unrecognised = sorted(repr(key) for key in mapping.keys() - recognised)
    if unrecognised:
        raise ConfigurationError(
            f"Unrecognised keys in {block_label(block_path)}: {', '.join(unrecognised)}; "
            f"recognised keys: {', '.join(sorted(recognised))}"
        )
    return mapping


def _read_name(block: Mapping[str, Any], *, block_path: str) -> str:
    """Return the name the block at *block_path* sets, "" when it sets none or a null one, refusing a name that is not a string by its path."""
    name = block.get("name")
    if name is None:
        return ""
    if not isinstance(name, str):
        raise ConfigurationError.must_be(child_path(block_path, "name"), "a string", got=name)
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
        for key, value in refuse_unrecognised_keys(block_path, data, block.keys).items()
        if value is not None
    }


def refuse_missing_keys(block_path: str, missing_keys: Collection[str]) -> None:
    """Refuse the block at *block_path* if it leaves out any of *missing_keys*, keys it needs, naming each by its path."""
    if missing_keys:
        missing = ", ".join(child_path(block_path, key) for key in missing_keys)
        raise ConfigurationError(f"Missing required keys in {block_label(block_path)}: {missing}")


def _built_from(config_type: type[_Built], values: Mapping[str, Any], block_path: str) -> _Built:
    """The config *config_type* builds from *values*, the block at *block_path*'s.

    Raises:
        ConfigurationError: naming the block, for a value of a type *config_type* cannot use,
            which building it refuses with a TypeError.
    """
    try:
        return config_type(**values)
    except TypeError as refusal:
        raise ConfigurationError(f"{block_label(block_path)}: {refusal}") from refusal


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
    refuse_missing_keys(
        block_path,
        [key for key in block.keys if key not in set_keys and block.value_when_omitted(key) is MISSING],
    )
    sub_block_configs = {
        key: sub_block.read(set_keys[key], block_path=child_path(block_path, key))
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


def float_or_none(value: Any) -> Optional[float]:
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

    A block that is absent or sets no key, its null keys read as absent, is Bristol. Otherwise it
    must set latitude and longitude: a block that leaves either out is refused, naming it by its
    path. An omitted timezone or altitude takes Bristol's, and an omitted name stays empty.
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


def parse_grid_charge_config(
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
    return GridChargeConfig(**refuse_unrecognised_keys(block_path, data, _GRID_CHARGING_BLOCK_KEYS))


def _grid_charging_block(grid_charging: GridChargeConfig) -> dict[str, Any]:
    """The grid_charging: block parse_grid_charge_config reads back as *grid_charging*."""
    return {"target_soc_fraction": grid_charging.target_soc_fraction}


_PER_DIRECTION_EFFICIENCY_KEYS: tuple[str, ...] = ("charge_efficiency", "discharge_efficiency")
"""The battery: block's per-direction efficiency keys, in BATTERY_BLOCK's order, which a block setting efficiency, the round trip, may not set."""


def _refuse_both_efficiency_forms(block_path: str, set_keys: Mapping[str, Any]) -> None:
    """Refuse the battery: block at *block_path* if *set_keys*, the keys it sets, hold a per-direction efficiency beside efficiency, naming the block and each key."""
    per_direction = [key for key in _PER_DIRECTION_EFFICIENCY_KEYS if key in set_keys]
    if per_direction:
        raise ConfigurationError(
            f"{block_label(block_path)} sets both forms of a battery's efficiency: efficiency and "
            f"{' and '.join(per_direction)}; set efficiency, the round trip, or charge_efficiency "
            "and discharge_efficiency, not both"
        )


def _parse_battery_config(
    data: Optional[dict[str, Any]], *, block_path: str
) -> Optional[BatteryConfig]:
    """Parse a battery: block into a BatteryConfig by BATTERY_BLOCK, its efficiency the round trip BatteryConfig.with_round_trip reads; a null block is no battery.

    Raises:
        ConfigurationError: as _read_component_block refuses a block; for one setting
            efficiency beside charge_efficiency or discharge_efficiency, naming the block and
            each key; or as with_round_trip refuses the efficiency it sets, naming that key by
            its path.
    """
    if data is None:
        return None
    set_keys = _set_keys(BATTERY_BLOCK, data, block_path)
    round_trip = set_keys.get("efficiency")
    if round_trip is None:
        return _built_component(BATTERY_BLOCK, set_keys, block_path)
    _refuse_both_efficiency_forms(block_path, set_keys)
    other_keys = {key: value for key, value in set_keys.items() if key != "efficiency"}
    battery = _built_component(BATTERY_BLOCK, other_keys, block_path)
    try:
        return battery.with_round_trip(round_trip)
    except ConfigurationError as refusal:
        raise ConfigurationError(f"{child_path(block_path, 'efficiency')}: {refusal}") from refusal


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
            f"Invalid {child_path(block_path, 'strategy_type')} {tag!r}; "
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
    block = require_mapping(block_path, data)
    variant = _strategy_variant(block, block_path)
    variant_fields = [each for each in fields(variant) if each.init]
    set_keys = refuse_unrecognised_keys(
        block_path,
        {key: value for key, value in block.items() if value is not None or key not in _KEYS_A_STRATEGY_READS},
        {"strategy_type", *(each.name for each in variant_fields)},
    )
    refuse_missing_keys(
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

_PRESET_TARIFF_RATE_KEYS: frozenset[str] = frozenset({"off_peak_rate", "peak_rate"})


def _build_flat_rate_tariff(data: dict[str, Any], block_path: str) -> TariffConfig:
    """Build the flat_rate tariff a block names, refusing it unless it gives a rate."""
    rate = data.get("rate_per_kwh")
    if rate is None:
        raise ConfigurationError("flat_rate tariff requires 'rate_per_kwh' field")
    return TariffConfig.flat_rate(
        rate_per_kwh=float(rate),
        name=_read_name(data, block_path=block_path)
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
    period = refuse_unrecognised_keys(block_path, data, _TARIFF_PERIOD_KEYS)
    for key in ("start_time", "end_time", "rate_per_kwh"):
        if key not in period:
            raise ConfigurationError(f"Tariff period requires '{key}' field")
    return TariffPeriod(
        start_time=period["start_time"],
        end_time=period["end_time"],
        rate_per_kwh=float(period["rate_per_kwh"]),
        name=_read_name(period, block_path=block_path)
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
            _parse_tariff_period(period, block_path=child_path(block_path, f"periods[{index}]"))
            for index, period in enumerate(periods_data)
        ),
        name=_read_name(data, block_path=block_path)
    )


_TARIFF_TYPES: Mapping[str, BlockType[TariffConfig]] = MappingProxyType({
    "flat_rate": BlockType(
        frozenset({"type", "rate_per_kwh", "name"}),
        _build_flat_rate_tariff,
    ),
    "economy_7": BlockType(
        frozenset({
            "type", "off_peak_rate", "peak_rate", "off_peak_start", "off_peak_end",
        }),
        _build_economy_7_tariff,
    ),
    "economy_10": BlockType(
        frozenset({
            "type", "off_peak_rate", "peak_rate", "night_start", "night_end", "afternoon_start",
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
            type does not read
    """
    if data is None:
        return None
    require_mapping(block_path, data)

    tariff_type = data.get("type")
    if tariff_type is None:
        raise ConfigurationError("Tariff configuration requires 'type' field")
    block_type = _TARIFF_TYPES.get(tariff_type) if isinstance(tariff_type, str) else None
    if block_type is None:
        raise ConfigurationError(
            f"Unknown tariff type '{tariff_type}'. "
            f"Supported types: {', '.join(_TARIFF_TYPES)}"
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
    *_HOME_SCALAR_KEYS, "dispatch_strategy", "pv", "battery", "load", "tariff", "heat_pump", "ev",
})


def read_dispatch_strategy_key(block: Mapping[str, Any], *, block_path: str) -> Optional[str]:
    """The dispatch_strategy the block at *block_path* sets: None when it is absent or null, else one of HOME_DISPATCH_STRATEGIES.

    Raises:
        ConfigurationError: It is set to another value, as refuse_unknown_home_dispatch_strategy
            refuses it, naming its key's path.
    """
    value = block.get("dispatch_strategy")
    if value is None:
        return None
    return refuse_unknown_home_dispatch_strategy(value, field=child_path(block_path, "dispatch_strategy"))


def parse_home_block(
    data: dict[str, Any], location: Location, *, block_path: str = "home"
) -> HomeConfig:
    """Parse a ``home:`` block, or one ``homes:`` entry, into a HomeConfig at *location*.

    A key the block omits takes HomeConfig's declared default, and so does a null scalar. An
    omitted pv or load block reads as an empty one.
    """
    home = refuse_unrecognised_keys(block_path, data, HOME_BLOCK_KEYS)
    return HomeConfig(
        pv_config=_parse_pv_config(home.get("pv", {}), block_path=child_path(block_path, "pv")),
        battery_config=_parse_battery_config(
            home.get("battery"), block_path=child_path(block_path, "battery")
        ),
        load_config=_parse_load_config(
            home.get("load", {}), block_path=child_path(block_path, "load")
        ),
        location=location,
        tariff_config=parse_tariff_config(
            home.get("tariff"), block_path=child_path(block_path, "tariff")
        ),
        heat_pump_config=_parse_heat_pump_config(
            home.get("heat_pump"), block_path=child_path(block_path, "heat_pump")
        ),
        ev_config=_parse_ev_config(home.get("ev"), block_path=child_path(block_path, "ev")),
        **{key: home[key] for key in _HOME_SCALAR_KEYS if home.get(key) is not None},
        **dispatch_strategy_argument(read_dispatch_strategy_key(home, block_path=block_path)),
    )


def dispatch_strategy_argument(dispatch_strategy: Optional[str]) -> dict[str, Any]:
    """HomeConfig's dispatch_strategy argument for *dispatch_strategy*: none when it is None, so the field takes its default."""
    return {} if dispatch_strategy is None else {"dispatch_strategy": dispatch_strategy}


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
    data = refuse_unrecognised_keys(block_path, data, _SEG_BLOCK_KEYS)
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
    "delivery_baseline": str,
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
        refuse_unrecognised_keys(window_path, ew_dict, _EVENT_WINDOW_COERCIONS)
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
    gs_data = refuse_unrecognised_keys(block_path, data, _GRID_SERVICES_EVENTS_BLOCK_KEYS)
    fields: dict[str, Any] = {}
    if "event_windows" in gs_data:
        fields["event_windows"] = _parse_event_windows(
            gs_data["event_windows"], block_path=child_path(block_path, "event_windows")
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
    refuse_unrecognised_keys(block_path, data, _FINANCE_BLOCK_KEYS)
    if "standing_charge_pence_per_day" not in data:
        raise ConfigurationError(
            "finance.standing_charge_pence_per_day is required"
        )

    grid_services_events = _parse_grid_services_events_config(
        data.get("grid_services_events"),
        block_path=child_path(block_path, "grid_services_events"),
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
    refuse_unrecognised_keys(block_path, data, _COMMUNITY_BILLING_BLOCK_KEYS)

    tariff = parse_tariff_config(data.get("tariff"), block_path=child_path(block_path, "tariff"))

    # Resolve SEG rate (three mutually-exclusive forms)
    direct_rate: Optional[float] = None
    if "seg_rate_pence_per_kwh" in data:
        direct_rate = _parse_seg_rate_scalar(
            data["seg_rate_pence_per_kwh"],
            key_path=child_path(block_path, "seg_rate_pence_per_kwh"),
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
        else parse_seg_rate(seg_block, block_path=child_path(block_path, "seg"))
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
            does not read, missing/invalid ``sharing_mode``, p2p+battery,
            community_battery-without-battery, or any nested config error.
    """
    if data is None:
        return None
    refuse_unrecognised_keys(block_path, data, _COMMUNITY_BLOCK_KEYS)

    sharing_mode = data.get("sharing_mode")
    if not sharing_mode:
        raise ConfigurationError(
            "community: block requires a 'sharing_mode' field "
            "('p2p' or 'community_battery')"
        )

    community_battery = _parse_battery_config(
        data.get("community_battery"), block_path=child_path(block_path, "community_battery")
    )
    billing = _parse_community_billing_config(
        data.get("billing"), block_path=child_path(block_path, "billing")
    )

    try:
        return CommunityConfig(
            sharing_mode=sharing_mode,
            community_battery=community_battery,
            billing=billing,
        )
    except ValueError as exc:
        raise ConfigurationError(str(exc)) from exc
