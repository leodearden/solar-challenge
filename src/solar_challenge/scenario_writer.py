# SPDX-License-Identifier: AGPL-3.0-or-later
"""Write configs as the scenario YAML documents config.py's loaders read.

Each block written here is the inverse of the config.py parser that reads it:
parse_location_block, parse_home_block and its block parsers, parse_tariff_config's
custom type, and parse_seg_rate.  location: and each component block carry every
key of config.py's table for that component, in field order, an unset value as
null, which the reader reads as absent.  A field the grammar has no key for is
refused unless it is at its default.  A battery with a round-trip efficiency omits
the pair it derives.
"""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import MISSING, Field, fields
from typing import Any, Optional

import yaml

from solar_challenge.config import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    LOCATION_BLOCK,
    PV_BLOCK,
    ComponentBlock,
)
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig

_PAIR_DERIVED_FROM_EFFICIENCY: tuple[str, ...] = ("charge_efficiency", "discharge_efficiency")
"""The per-direction efficiencies BatteryConfig derives from a round-trip efficiency, until S28 retires it."""


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
        "battery": (
            None
            if battery is None
            else _component_block(
                BATTERY_BLOCK,
                battery,
                omit=_PAIR_DERIVED_FROM_EFFICIENCY if battery.efficiency is not None else (),
            )
        ),
        "load": _component_block(LOAD_BLOCK, home.load_config),
        "tariff": None if home.tariff_config is None else _tariff_block(home.tariff_config),
        "dispatch_strategy": home.dispatch_strategy,
        "heat_pump": (
            None
            if home.heat_pump_config is None
            else _component_block(HEAT_PUMP_BLOCK, home.heat_pump_config)
        ),
        "ev": None if home.ev_config is None else _component_block(EV_BLOCK, home.ev_config),
    }


def _component_block(
    block: ComponentBlock[Any], config: object, *, omit: Collection[str] = ()
) -> dict[str, Any]:
    """The block config.py's reader of *block*'s table reads back as *config*.

    It holds each of the table's keys not in *omit*, in the table's order: a sub-block key's
    value written by its sub-block's writer, and None as null.

    Raises:
        ValueError: from _refuse_fields_without_a_key, before anything is written.
    """
    _refuse_fields_without_a_key(block, config)
    values = {key: getattr(config, key) for key in block.keys if key not in omit}
    return {
        key: value if value is None or key not in block.sub_blocks else block.sub_blocks[key].write(value)
        for key, value in values.items()
    }


def _refuse_fields_without_a_key(block: ComponentBlock[Any], config: object) -> None:
    """Refuse *config* if it sets a field *block*'s grammar has no key for away from its declared default.

    Raises:
        ValueError: naming each such field with the reason no key carries it.
    """
    unwritable = [
        f"{each.name} ({block.outside_grammar[each.name]})"
        for each in fields(block.config_type)
        if each.name in block.outside_grammar and getattr(config, each.name) != _declared_default(each)
    ]
    if unwritable:
        raise ValueError(
            f"{block.config_type.__name__} {' and '.join(unwritable)} cannot be written as scenario YAML"
        )


def _declared_default(declared: Field[Any]) -> object:
    """*declared*'s default, or its default factory's value; MISSING, which no value equals, when it has neither."""
    if declared.default_factory is not MISSING:
        return declared.default_factory()
    return declared.default


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
