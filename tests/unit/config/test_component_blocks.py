# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each table of config.py's scenario grammar, a component block table, held to its dataclass."""

import dataclasses
import re
from typing import Any, Callable, Optional

import pytest

from solar_challenge.battery import BatteryConfig, has_battery
from solar_challenge.config import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    LOCATION_BLOCK,
    PV_BLOCK,
    ComponentBlock,
    FieldKind,
    FleetField,
    parse_home_block,
    parse_location_block,
)
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.ev import CHARGER_TYPES, EVConfig
from solar_challenge.heat_pump import HEAT_PUMP_TYPES, HeatPumpConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig

_TABLES: tuple[ComponentBlock[Any], ...] = (
    PV_BLOCK, BATTERY_BLOCK, LOAD_BLOCK, HEAT_PUMP_BLOCK, EV_BLOCK, LOCATION_BLOCK,
)

_BRISTOL = Location.bristol()


def _table_id(block: ComponentBlock[Any]) -> str:
    """Name *block* by the dataclass it builds."""
    return block.config_type.__name__


def _placement_faults(block: ComponentBlock[Any]) -> list[str]:
    """Each way *block* fails to place its dataclass's fields, naming the field; empty when it places every one.

    Every field is either one of the block's keys or outside its grammar, never both; the keys
    follow field order; and every sub-block and when-omitted entry is one of the keys. Every key
    is either drawn by the fleet or outside it, never both; the fleet keys follow key order; the
    presence field is the first of them, since a home draws nothing of a component before
    learning whether it has one; and a sub-block the fleet carries is a SETTING.
    """
    field_names = [field.name for field in dataclasses.fields(block.config_type)]
    keys = set(block.keys)
    outside = set(block.outside_grammar)
    fleet = set(block.fleet)
    not_in_fleet = set(block.not_in_fleet)
    return [
        *(f"{name} is both a key and outside the grammar" for name in field_names if name in keys & outside),
        *(f"{name} is neither a key nor outside the grammar" for name in field_names if name not in keys | outside),
        *(f"{name} is placed but is not a field" for name in sorted((keys | outside) - set(field_names))),
        *(
            [f"keys {list(block.keys)} do not follow field order {field_names}"]
            if list(block.keys) != [name for name in field_names if name in keys]
            else []
        ),
        *(f"sub-block {key} is not a key" for key in block.sub_blocks if key not in keys),
        *(f"when_omitted {key} is not a key" for key in block.when_omitted if key not in keys),
        *(f"{key} is both drawn by the fleet and outside it" for key in block.keys if key in fleet & not_in_fleet),
        *(
            f"{key} is a key but neither drawn by the fleet nor outside it"
            for key in block.keys
            if key not in fleet | not_in_fleet
        ),
        *(f"{key} is placed in the fleet but is not a key" for key in sorted((fleet | not_in_fleet) - keys)),
        *(
            [f"fleet keys {list(block.fleet)} do not follow key order {list(block.keys)}"]
            if list(block.fleet) != [key for key in block.keys if key in fleet]
            else []
        ),
        *(
            [f"presence {block.presence} is not the first fleet key of {list(block.fleet)}"]
            if block.presence is not None and list(block.fleet)[:1] != [block.presence]
            else []
        ),
        *(
            f"sub-block {key} is not a SETTING in the fleet"
            for key in block.sub_blocks
            if key in block.fleet and block.fleet[key].kind is not FieldKind.SETTING
        ),
    ]


@pytest.mark.parametrize("block", _TABLES, ids=_table_id)
def test_each_table_places_every_field_of_its_dataclass_once_in_field_order(
    block: ComponentBlock[Any],
) -> None:
    """T1: a table's keys and the fields outside its grammar are its dataclass's fields, disjoint, the keys in field order."""
    assert _placement_faults(block) == []


def test_a_field_added_to_the_dataclass_fails_until_its_table_places_it() -> None:
    """T1 is not a tautology: PV_BLOCK's table over a PVConfig widened by one field reports that field."""
    widened = dataclasses.make_dataclass(
        "WidenedPVConfig", [("bifacial_gain", float, 0.0)], bases=(PVConfig,), frozen=True
    )

    faults = _placement_faults(dataclasses.replace(PV_BLOCK, config_type=widened))

    assert faults == ["bifacial_gain is neither a key nor outside the grammar"]


def test_a_key_added_to_the_table_fails_until_its_fleet_rows_place_it() -> None:
    """T1's fleet half is not a tautology: PV_BLOCK's table over a widened PVConfig, the new field one of its keys, reports that the fleet does not place it."""
    widened = dataclasses.make_dataclass(
        "WidenedPVConfig", [("bifacial_gain", float, 0.0)], bases=(PVConfig,), frozen=True
    )

    faults = _placement_faults(
        dataclasses.replace(PV_BLOCK, config_type=widened, keys=(*PV_BLOCK.keys, "bifacial_gain"))
    )

    assert faults == ["bifacial_gain is a key but neither drawn by the fleet nor outside it"]


@pytest.mark.parametrize(
    ("block", "fault"),
    [
        pytest.param(
            dataclasses.replace(BATTERY_BLOCK, presence="max_charge_kw"),
            f"presence max_charge_kw is not the first fleet key of {list(BATTERY_BLOCK.fleet)}",
            id="presence-after-another-fleet-key",
        ),
        pytest.param(
            dataclasses.replace(
                BATTERY_BLOCK, fleet={**BATTERY_BLOCK.fleet, "grid_charging": FleetField(FieldKind.NUMBER)}
            ),
            "sub-block grid_charging is not a SETTING in the fleet",
            id="sub-block-drawn",
        ),
    ],
)
def test_a_presence_or_sub_block_the_fleet_misplaces_is_reported(block: ComponentBlock[Any], fault: str) -> None:
    """T1 reports a presence field a home would draw after another fleet field, and a sub-block the fleet would draw."""
    assert _placement_faults(block) == [fault]


def test_a_field_declaring_a_default_factory_is_built_with_the_factorys_value() -> None:
    """value_when_omitted gives such a field the value constructing the dataclass without it gives, as it does a declared default."""
    widened = dataclasses.make_dataclass(
        "WidenedPVConfig",
        [("bifacial_gains", tuple[float, ...], dataclasses.field(default_factory=lambda: (0.1,)))],
        bases=(PVConfig,),
        frozen=True,
    )

    omitted = dataclasses.replace(PV_BLOCK, config_type=widened).value_when_omitted("bifacial_gains")

    assert omitted == widened(capacity_kw=4.0).bifacial_gains


@pytest.mark.parametrize(
    ("block", "outside_grammar", "sub_blocks", "when_omitted"),
    [
        pytest.param(
            PV_BLOCK,
            {"custom_module_params", "custom_inverter_params"},
            (),
            {"capacity_kw": 4.0},
            id="PVConfig",
        ),
        pytest.param(
            BATTERY_BLOCK, set(), ("dispatch_strategy", "grid_charging"), {"capacity_kwh": 5.0},
            id="BatteryConfig",
        ),
        pytest.param(LOAD_BLOCK, set(), (), {}, id="LoadConfig"),
        pytest.param(HEAT_PUMP_BLOCK, set(), (), {}, id="HeatPumpConfig"),
        pytest.param(EV_BLOCK, set(), (), {}, id="EVConfig"),
        pytest.param(
            LOCATION_BLOCK,
            set(),
            (),
            {
                "latitude": _BRISTOL.latitude,
                "longitude": _BRISTOL.longitude,
                "timezone": _BRISTOL.timezone,
                "altitude": _BRISTOL.altitude,
            },
            id="Location",
        ),
    ],
)
def test_each_table_holds_its_rows(
    block: ComponentBlock[Any],
    outside_grammar: set[str],
    sub_blocks: tuple[str, ...],
    when_omitted: dict[str, object],
) -> None:
    """T2: every field but those outside the grammar, each with its reason, is a key; then the sub-blocks in order and the when-omitted values."""
    field_names = {field.name for field in dataclasses.fields(block.config_type)}

    assert set(block.outside_grammar) == outside_grammar
    assert all(reason.strip() for reason in block.outside_grammar.values())
    assert set(block.keys) == field_names - outside_grammar
    assert tuple(block.sub_blocks) == sub_blocks
    assert dict(block.when_omitted) == when_omitted


_NUMBER = FleetField(FieldKind.NUMBER)
_COUNT = FleetField(FieldKind.COUNT)
_SETTING = FleetField(FieldKind.SETTING)


@pytest.mark.parametrize(
    ("block", "rows", "other_rows", "not_in_fleet", "presence"),
    [
        pytest.param(
            PV_BLOCK, {"capacity_kw": FleetField(FieldKind.NUMBER, required=True)}, _NUMBER, {"name"}, None,
            id="PVConfig",
        ),
        pytest.param(
            BATTERY_BLOCK,
            {
                "capacity_kwh": FleetField(FieldKind.NUMBER, required=True),
                "dispatch_strategy": _SETTING,
                "grid_charging": _SETTING,
            },
            _NUMBER,
            {"name"},
            "capacity_kwh",
            id="BatteryConfig",
        ),
        pytest.param(
            LOAD_BLOCK,
            {"annual_consumption_kwh": _NUMBER, "household_occupants": _COUNT, "use_stochastic": _SETTING},
            None,
            {"name", "seed"},
            None,
            id="LoadConfig",
        ),
        pytest.param(
            HEAT_PUMP_BLOCK,
            {"heat_pump_type": FleetField(FieldKind.CHOICE, choices=HEAT_PUMP_TYPES)},
            _NUMBER,
            {"name"},
            "heat_pump_type",
            id="HeatPumpConfig",
        ),
        pytest.param(
            EV_BLOCK,
            {
                "charger_type": FleetField(FieldKind.CHOICE, choices=CHARGER_TYPES, required=True),
                "arrival_hour": _COUNT,
                "departure_hour": _COUNT,
                "smart_charging_mode": _SETTING,
            },
            _NUMBER,
            {"name"},
            "charger_type",
            id="EVConfig",
        ),
        pytest.param(LOCATION_BLOCK, {}, None, set(LOCATION_BLOCK.keys), None, id="Location"),
    ],
)
def test_each_table_holds_its_fleet_rows(
    block: ComponentBlock[Any],
    rows: dict[str, FleetField],
    other_rows: Optional[FleetField],
    not_in_fleet: set[str],
    presence: Optional[str],
) -> None:
    """T2: each key outside the fleet has its reason, and every other key is drawn with its row, *rows*' or else *other_rows*; then the presence field."""
    assert set(block.not_in_fleet) == not_in_fleet
    assert all(reason.strip() for reason in block.not_in_fleet.values())
    assert dict(block.fleet) == {key: rows.get(key, other_rows) for key in block.keys if key not in not_in_fleet}
    assert block.presence == presence


def test_a_battery_is_present_as_has_battery_says() -> None:
    """The battery's presence rule is battery.has_battery, so a 0 capacity is no battery here as it is in a home: block."""
    assert BATTERY_BLOCK.asks_for_component is has_battery


@pytest.mark.parametrize(
    ("kind", "choices"),
    [
        pytest.param(FieldKind.CHOICE, (), id="a-choice-listing-none"),
        pytest.param(FieldKind.NUMBER, ("a",), id="a-number-listing-one"),
    ],
)
def test_choices_belong_to_a_choice_field_alone(kind: FieldKind, choices: tuple[str, ...]) -> None:
    """A CHOICE field lists the values it may take, and a field of any other kind lists none."""
    with pytest.raises(ConfigurationError) as exc_info:
        FleetField(kind, choices=choices)

    assert kind.name in str(exc_info.value)
    assert repr(choices) in str(exc_info.value)


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param(
            "dispatch_strategy", SelfConsumptionStrategyConfig(), id="dispatch_strategy-self_consumption"
        ),
        pytest.param(
            "dispatch_strategy",
            TOUOptimizedStrategyConfig(peak_hours=((16, 19), (20, 22))),
            id="dispatch_strategy-tou_optimized",
        ),
        pytest.param(
            "dispatch_strategy",
            PeakShavingStrategyConfig(import_limit_kw=3.0),
            id="dispatch_strategy-peak_shaving",
        ),
        pytest.param(
            "grid_charging", GridChargeConfig(target_soc_fraction=0.8), id="grid_charging"
        ),
    ],
)
def test_each_battery_sub_block_reads_back_what_it_writes(key: str, value: object) -> None:
    """A sub-block's reader and writer are inverse: the block written for a config reads back as an equal one."""
    sub_block = BATTERY_BLOCK.sub_blocks[key]

    assert sub_block.read(sub_block.write(value), block_path=f"home.battery.{key}") == value


@pytest.mark.parametrize(
    ("strategy", "keys"),
    [
        pytest.param(SelfConsumptionStrategyConfig(), ["strategy_type"], id="self_consumption"),
        pytest.param(
            TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
            ["strategy_type", "peak_hours"],
            id="tou_optimized",
        ),
        pytest.param(
            PeakShavingStrategyConfig(import_limit_kw=3.0),
            ["strategy_type", "import_limit_kw"],
            id="peak_shaving",
        ),
    ],
)
def test_a_written_dispatch_strategy_block_holds_its_tag_and_only_its_strategys_keys(
    strategy: object, keys: list[str]
) -> None:
    """The writer writes no key of another strategy, null or not."""
    assert list(BATTERY_BLOCK.sub_blocks["dispatch_strategy"].write(strategy)) == keys


def _home_component(home_key: str, attribute: str) -> Callable[[dict[str, Any]], object]:
    """A reader of a block as parse_home_block reads a home's *home_key* block, giving HomeConfig's *attribute*."""

    def read(block: dict[str, Any]) -> object:
        return getattr(parse_home_block({home_key: block}, Location.bristol()), attribute)

    return read


_PUBLIC_READINGS: tuple[
    tuple[ComponentBlock[Any], Callable[[dict[str, Any]], object], dict[str, Any]], ...
] = (
    (PV_BLOCK, _home_component("pv", "pv_config"), {"capacity_kw": 5.0}),
    (BATTERY_BLOCK, _home_component("battery", "battery_config"), {"capacity_kwh": 9.0}),
    (LOAD_BLOCK, _home_component("load", "load_config"), {"annual_consumption_kwh": 3000.0}),
    (HEAT_PUMP_BLOCK, _home_component("heat_pump", "heat_pump_config"), {"heat_pump_type": "GSHP"}),
    (EV_BLOCK, _home_component("ev", "ev_config"), {"charger_type": "3.6kW"}),
    (LOCATION_BLOCK, parse_location_block, {"name": "Clifton"}),
)
"""Each table, the public reader of its blocks, and a block of it setting one key."""

_REQUIRED_KEY_PATHS: dict[tuple[type, str], str] = {
    (HeatPumpConfig, "heat_pump_type"): "home.heat_pump.heat_pump_type",
    (EVConfig, "charger_type"): "home.ev.charger_type",
}
"""The keys a block may not leave out, each by its path in a home: block."""

_EVERY_TABLE_KEY = [
    (block, read, base, key) for block, read, base in _PUBLIC_READINGS for key in block.keys
]


@pytest.mark.parametrize(
    ("read", "base", "key"),
    [
        pytest.param(read, base, key, id=f"{block.config_type.__name__}-{key}")
        for block, read, base, key in _EVERY_TABLE_KEY
        if (block.config_type, key) not in _REQUIRED_KEY_PATHS
    ],
)
def test_a_null_key_reads_as_absent(
    read: Callable[[dict[str, Any]], object], base: dict[str, Any], key: str
) -> None:
    """R1: a block whose key is null reads as the same block without the key."""
    without_the_key = {name: value for name, value in base.items() if name != key}

    assert read({**base, key: None}) == read(without_the_key)


@pytest.mark.parametrize(
    ("read", "data", "path"),
    [
        pytest.param(
            read,
            {**base, key: None},
            _REQUIRED_KEY_PATHS[block.config_type, key],
            id=f"{block.config_type.__name__}-{key}",
        )
        for block, read, base, key in _EVERY_TABLE_KEY
        if (block.config_type, key) in _REQUIRED_KEY_PATHS
    ],
)
def test_a_null_required_key_is_refused_naming_its_path(
    read: Callable[[dict[str, Any]], object], data: dict[str, Any], path: str
) -> None:
    """R1: a null required key reads as absent, so its block is refused, naming the key by its path."""
    with pytest.raises(ConfigurationError, match=re.escape(path)):
        read(data)


_WORDS_FOR_NUMBERS: dict[type, dict[str, str]] = {
    PVConfig: {"azimuth": "south"},
    BatteryConfig: {"capacity_kwh": "ten"},
    LoadConfig: {"annual_consumption_kwh": "lots"},
    HeatPumpConfig: {"thermal_capacity_kw": "eight"},
    EVConfig: {"arrival_hour": "evening"},
    Location: {"latitude": "north"},
}
"""For each table's dataclass, one of its numbers given as a word."""


@pytest.mark.parametrize(
    ("read", "data"),
    [
        pytest.param(read, {**base, **_WORDS_FOR_NUMBERS[block.config_type]}, id=_table_id(block))
        for block, read, base in _PUBLIC_READINGS
    ],
)
def test_a_word_for_a_number_is_refused_as_a_configuration_error(
    read: Callable[[dict[str, Any]], object], data: dict[str, Any]
) -> None:
    """R1 hands a block's values to its dataclass as written: a word where it takes a number is refused as the grammar refuses a scenario, not with a raw TypeError."""
    with pytest.raises(ConfigurationError):
        read(data)
