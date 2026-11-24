# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write configs as the scenario YAML documents config.py's loaders read.

Each block written here is the inverse of the scenario_blocks.py reader that reads
it: parse_location_block, parse_home_block and its block parsers,
parse_tariff_config's custom type, and parse_seg_rate.  location: and each
component block carry every key of scenario_blocks.py's table for that component,
in field order, an unset value as null, which the reader reads as absent, and an enum
member as its value, the string the reader parses back into it.  A field
the grammar has no key for is refused unless it is at its default.  A reader-only
key is never written: a battery block is written without efficiency, the round
trip, as the charge_efficiency and discharge_efficiency it holds.
"""

from collections.abc import Mapping, Sequence
from enum import Enum
from typing import Any, Optional, TypeVar

import yaml

from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.scenario_blocks import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    LOCATION_BLOCK,
    PV_BLOCK,
    ComponentBlock,
)
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig

_Component = TypeVar("_Component", bound=DataclassInstance)

def scenario_yaml(document: Mapping[str, Any]) -> str:
    """The YAML text of a scenario *document*, its keys in the order written."""
    text: str = yaml.safe_dump(
        dict(document), default_flow_style=False, sort_keys=False, allow_unicode=True
    )
    return text


def location_block(location: Location) -> dict[str, Any]:
    """The location: block parse_location_block reads back as *location*."""
    return _component_block(LOCATION_BLOCK, location)


def home_scenario(home: HomeConfig, *, name: str) -> dict[str, Any]:
    """The scenario *name* that `home run` reads back as *home*, its SEG tariff unnamed."""
    return {
        "name": name,
        "location": location_block(home.location),
        "home": _home_block(home),
        "seg": _seg_block(home.seg_tariff),
    }


def fleet_scenario(homes: Sequence[HomeConfig], *, name: str) -> dict[str, Any]:
    """The scenario *name* that load_fleet_config reads back as *homes*, their SEG tariff unnamed.

    Raises:
        ValueError: for no homes, which load_fleet_config refuses too, or for homes that
            do not write the same location: and seg: blocks, which a scenario holds once
            for the whole fleet.
    """
    if not homes:
        raise ValueError("A fleet needs at least one home, as load_fleet_config requires")
    return {
        "name": name,
        "location": _fleet_wide_block(
            "location", [location_block(home.location) for home in homes]
        ),
        "seg": _fleet_wide_block("seg", [_seg_block(home.seg_tariff) for home in homes]),
        "homes": [_home_block(home) for home in homes],
    }


def _fleet_wide_block(
    key: str, home_blocks: Sequence[Optional[dict[str, Any]]]
) -> Optional[dict[str, Any]]:
    """The *key* block that every one of a fleet's *home_blocks* is.

    Raises:
        ValueError: naming *key* and the distinct blocks, when the homes write more than one.
    """
    distinct: list[Optional[dict[str, Any]]] = []
    for block in home_blocks:
        if block not in distinct:
            distinct.append(block)
    if len(distinct) > 1:
        raise ValueError(
            f"A scenario holds one {key}: block for the whole fleet, "
            f"but its homes write {len(distinct)}: {distinct}"
        )
    return distinct[0]


def _home_block(home: HomeConfig) -> dict[str, Any]:
    """The home: block parse_home_block reads back as *home*, location and SEG aside."""
    battery = home.battery_config
    return {
        "name": home.name,
        "pv": _component_block(PV_BLOCK, home.pv_config),
        "battery": None if battery is None else _component_block(BATTERY_BLOCK, battery),
        "load": _component_block(LOAD_BLOCK, home.load_config),
        "tariff": None if home.tariff_config is None else _tariff_block(home.tariff_config),
        "heat_pump": (
            None
            if home.heat_pump_config is None
            else _component_block(HEAT_PUMP_BLOCK, home.heat_pump_config)
        ),
        "ev": None if home.ev_config is None else _component_block(EV_BLOCK, home.ev_config),
    }


def _component_block(block: ComponentBlock[_Component], config: _Component) -> dict[str, Any]:
    """The block scenario_blocks.py's reader of *block*'s table reads back as *config*.

    It holds each of the table's keys but its reader-only ones, in the table's order: a
    sub-block key's value written by its sub-block's writer, an enum member as its value,
    and None as null.

    Raises:
        ValueError: from _refuse_fields_without_a_key, before anything is written.
    """
    _refuse_fields_without_a_key(block, config)
    values = {
        key: _yaml_scalar(getattr(config, key)) for key in block.keys if key not in block.reader_only
    }
    return {
        key: value if value is None or key not in block.sub_blocks else block.sub_blocks[key].write(value)
        for key, value in values.items()
    }


def _yaml_scalar(value: Any) -> Any:
    """*value*, or an enum member's value, the plain scalar that YAML carries and its reader reads back."""
    return value.value if isinstance(value, Enum) else value


def _refuse_fields_without_a_key(block: ComponentBlock[_Component], config: _Component) -> None:
    """Refuse *config* if it sets a field *block*'s grammar has no key for away from its declared default.

    Raises:
        ValueError: naming each such field with the reason no key carries it.
    """
    unwritable = [
        f"{name} ({reason})"
        for name, reason in block.outside_grammar.items()
        if getattr(config, name) != block.value_when_omitted(name)
    ]
    if unwritable:
        raise ValueError(
            f"{block.config_type.__name__} {' and '.join(unwritable)} cannot be written as scenario YAML"
        )


def _tariff_block(tariff: TariffConfig) -> dict[str, Any]:
    """The tariff: block parse_tariff_config reads back as *tariff*: its periods, as a custom tariff."""
    return {
        "type": "custom",
        "name": tariff.name,
        "periods": [
            {
                "start_time": period.start_time,
                "end_time": period.end_time,
                "rate_per_kwh": period.rate_per_kwh,
                "name": period.name,
            }
            for period in tariff.periods
        ],
    }


def _seg_block(seg_tariff: Optional[SEGTariff]) -> Optional[dict[str, Any]]:
    """The seg: block parse_seg_rate reads back as *seg_tariff*'s rate; it carries no tariff name."""
    if seg_tariff is None:
        return None
    return {"rate_pence_per_kwh": seg_tariff.rate_pence_per_kwh}
