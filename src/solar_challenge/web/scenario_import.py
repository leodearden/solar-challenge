# SPDX-License-Identifier: AGPL-3.0-or-later
"""The readers a dashboard page composes into its import of a fleet scenario as its form.

The fleet page (fleet_scenario.py) and the scenario builder (builder_form.py) each read a
scenario with these readers, declaring what their own form holds as the reads they give
read_blocks, and each typed block it holds, a tariff or a dispatch strategy, as the
HeldType of each type it offers.  Each reader that refuses names the setting and the
*page* it refuses it for.
docs/web-ui-design.md, *Scenario import policy*, says what loads, what is named not
loaded and what is refused.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Any

import yaml

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import ComponentDistribution, FleetDistributionConfig
from solar_challenge.scenario_blocks import child_path
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits
from solar_challenge.web.simulation_params import read_iso_date


@dataclass(frozen=True)
class ImportedForm:
    """A fleet scenario read as a dashboard page's form.

    Attributes:
        form: The form the scenario describes: the body the page posts.
        not_loaded: The path of each setting of the scenario the form has no control for,
            in document order; the form leaves them out.
    """

    form: Mapping[str, Any]
    not_loaded: tuple[str, ...]


#: A scenario block read as its part of a page's form, and the path of each setting in it
#: the form does not hold.
BlockRead = tuple[dict[str, Any], tuple[str, ...]]

#: Reads a setting a page's form holds from its value in a scenario and its path there.
SettingReader = Callable[[Any, str], Any]

#: Reads a page's form's battery from a fleet_distribution block, its path and the grammar's
#: reading of its battery block, None for a fleet without a battery.
BatteryReader = Callable[[Mapping[str, Any], str, ComponentDistribution | None], BlockRead]


def scenario_yaml_document(yaml_text: str) -> object:
    """The document the scenario YAML *yaml_text* holds, as yaml.safe_load reads it.

    Raises:
        ConfigurationError: For text that does not parse as YAML, "Invalid YAML: " and the parser's error.
    """
    try:
        return yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML: {exc}") from exc


def fleet_scenario_document(document: object, page: str) -> dict[str, Any]:
    """*document*, which must be a scenario with a fleet_distribution block, the fleet the *page* loads.

    Raises:
        ConfigurationError: For a document that is not a mapping or has no fleet_distribution block,
            or a fleet_distribution block that is not a mapping.
    """
    if not isinstance(document, dict):
        raise ConfigurationError(f"A fleet scenario must be a mapping, got {type(document).__name__}")
    if "fleet_distribution" not in document:
        raise ConfigurationError(
            f"The scenario has no fleet_distribution block, the fleet the {page} loads"
        )
    fleet = document["fleet_distribution"]
    if not isinstance(fleet, dict):
        raise ConfigurationError(f"fleet_distribution must be a mapping, got {type(fleet).__name__}")
    return document


def read_period(period: object, page: str) -> tuple[date, date] | None:
    """The first and last days of the scenario's *period*, as the *page*'s date fields hold them; None when it is absent or null.

    Only the two days are read: bounding the window they span is the page's own rule.

    Raises:
        ConfigurationError: For a period that is not a mapping, or a date that is not a day,
            naming it as period.start_date or period.end_date.
    """
    if period is None:
        return None
    if not isinstance(period, Mapping):
        raise ConfigurationError(f"period must be a mapping, got {type(period).__name__}")
    return (
        read_day(period.get("start_date"), "period.start_date", page),
        read_day(period.get("end_date"), "period.end_date", page),
    )


def read_day(value: object, path: str, page: str) -> date:
    """*value*, a date as YAML reads one or an ISO 8601 date string, as the day it names.

    A YAML timestamp is its day when it is that day's midnight with no time zone.

    Raises:
        ConfigurationError: For a timestamp with a time of day or a time zone, which the
            *page*'s date fields cannot hold, or, from read_iso_date, any other value that is
            not an ISO 8601 date string, a missing one read as None included, naming *path*.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.time() != time.min:
            raise ConfigurationError(
                f"{path} must be a day, got {value!r}: the {page}'s date fields hold "
                "no time of day or time zone"
            )
        return value.date()
    if isinstance(value, date):
        return value
    return read_iso_date(value, path)


def not_loaded(
    block: Mapping[str, Any], path: str, held: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """The path of each setting in the *path* block that the page's form does not hold, in the block's order.

    *held* maps each key of the block the form holds to the paths of the settings within it
    that the form does not hold.
    """
    return tuple(
        unheld
        for key in block
        for unheld in held.get(key, (child_path(path, key),))
    )


def read_blocks(block: Mapping[str, Any], path: str, reads: Mapping[str, BlockRead]) -> BlockRead:
    """The *path* block as the page's form holds it, from the *reads* of its keys the form holds."""
    form = {setting: value for read_form, _ in reads.values() for setting, value in read_form.items()}
    held = {key: unheld for key, (_, unheld) in reads.items()}
    return form, not_loaded(block, path, held)


def read_as_given(key: str, value: object) -> BlockRead:
    """The form's *key*: the scenario's *value* as given, which read_fleet_scenario accepted; none when it is absent or null."""
    if value is None:
        return {}, ()
    return {key: value}, ()


def required(page: str) -> SettingReader:
    """A reader of a setting the *page* always sets: the scenario's value as given.

    The reader raises ConfigurationError when the scenario leaves the setting out, naming
    its path and the page.
    """

    def read_required(value: Any, path: str) -> Any:
        if value is None:
            raise ConfigurationError(f"{path} must be set: the {page} always sets it")
        return value

    return read_required


@dataclass(frozen=True)
class HeldType:
    """A type a page's form holds for a typed block, a tariff or a dispatch strategy, with the reader of each setting it holds for it.

    Attributes:
        type: The type, as the block's type key names it.
        settings: The reader of each setting of that type the form holds, by the setting's
            key in the block, in the order the form holds them.
    """

    type: str
    settings: Mapping[str, SettingReader]


def read_typed_block(
    block: Mapping[str, Any],
    path: str,
    type_key: str,
    held: Sequence[HeldType],
    page: str,
) -> BlockRead:
    """The *path* block, whose *type_key* names its type, as the *page*'s form holds it: its type and each setting the form holds for that type, read by that setting's reader.

    Raises:
        ConfigurationError: For a type none of *held* is, naming the block's *type_key*, the
            page and the types it holds, or from a setting's reader.
    """
    block_type = block[type_key]
    held_type = next((each for each in held if each.type == block_type), None)
    if held_type is None:
        raise ConfigurationError(
            f"{child_path(path, type_key)} must be one the {page} holds "
            f"({', '.join(each.type for each in held)}), got {block_type!r}"
        )
    form = {
        type_key: block_type,
        **{key: read(block.get(key), child_path(path, key)) for key, read in held_type.settings.items()},
    }
    held_keys = (type_key, *held_type.settings)
    return form, not_loaded(block, path, dict.fromkeys(held_keys, ()))


def read_seg(seg: Any, held: frozenset[str], page: str) -> BlockRead:
    """The *page*'s SEG: the scenario's seg block as given, none when it is absent or null.

    read_fleet_scenario accepted it, so it names exactly one preset or rate; *held* is the
    seg keys the page's form holds.

    Raises:
        ConfigurationError: For a key the page does not hold, naming it and the page: the
            form loaded without it would pay another export rate.
    """
    if seg is None:
        return {}, ()
    for key, value in seg.items():
        if key not in held:
            holds = ", ".join(child_path("seg", each) for each in sorted(held))
            raise ConfigurationError(
                f"{child_path('seg', key)} must not be set: the {page} holds the SEG only as "
                f"{holds}, got {value!r}"
            )
    return {"seg": dict(seg)}, ()


def read_fleet_distribution(
    fleet: Mapping[str, Any], parsed: FleetDistributionConfig, read_battery: BatteryReader
) -> BlockRead:
    """The form's fleet size, seed and distributions: the scenario's fleet_distribution block *fleet*, as the grammar read it, *parsed*, a seed it leaves out none; its battery as the page's *read_battery* reads it.

    Raises:
        ConfigurationError: From read_component or *read_battery*, for a field the form cannot hold.
    """
    path = "fleet_distribution"
    return read_blocks(
        fleet,
        path,
        {
            "n_homes": ({"n_homes": parsed.n_homes}, ()),
            "seed": ({} if parsed.seed is None else {"seed": parsed.seed}, ()),
            "pv": read_component(fleet, path, FLEET_COMPONENTS["pv"], parsed.pv),
            "battery": read_battery(fleet, path, parsed.battery),
            "load": read_component(fleet, path, FLEET_COMPONENTS["load"], parsed.load),
        },
    )


def read_component(
    fleet: Mapping[str, Any], path: str, limits: ComponentLimits, read: ComponentDistribution
) -> BlockRead:
    """The form's *limits* component block of the *path* fleet: its field as its editor loads *read*, the grammar's reading of the block.

    Raises:
        ConfigurationError: From ComponentLimits.editor_spec, for a field the editor cannot hold.
    """
    block_path = child_path(path, limits.key)
    form = {limits.key: {limits.grammar_key: editor_field(limits, read, block_path)}}
    return form, not_loaded(fleet.get(limits.key) or {}, block_path, {limits.grammar_key: ()})


def editor_field(limits: ComponentLimits, read: ComponentDistribution, block_path: str) -> object:
    """The *limits* component's field as its editor loads it from *read*, the grammar's reading of the *block_path* block: its draw, null when the block draws none, the editor's blank Fixed Value."""
    field_path = child_path(block_path, limits.grammar_key)
    return limits.editor_spec(read.draws.get(limits.grammar_key), field_path)
