# SPDX-License-Identifier: AGPL-3.0-or-later
"""Each table of config.py's scenario grammar, a component block table, held to its dataclass."""

import dataclasses
from typing import Any

import pytest

from solar_challenge.config import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    LOCATION_BLOCK,
    PV_BLOCK,
    ComponentBlock,
    DispatchStrategyConfig,
    GridChargeConfig,
)
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
    follow field order; and every sub-block and when-omitted entry is one of the keys.
    """
    field_names = [field.name for field in dataclasses.fields(block.config_type)]
    keys = set(block.keys)
    outside = set(block.outside_grammar)
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


def test_system_losses_is_a_pv_key() -> None:
    """T2: a pv: block carries PVConfig.system_losses."""
    assert "system_losses" in PV_BLOCK.keys


@pytest.mark.parametrize(
    ("key", "value"),
    [
        pytest.param(
            "dispatch_strategy",
            DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 19)]),
            id="dispatch_strategy-tou_optimized",
        ),
        pytest.param(
            "dispatch_strategy",
            DispatchStrategyConfig("peak_shaving", import_limit_kw=3.0),
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
