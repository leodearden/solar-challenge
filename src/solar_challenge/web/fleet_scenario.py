# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's form both ways: the fleet a fleet form describes, as the simulate endpoint runs it and as a scenario document, and the fleet form a scenario describes.

A fleet form is the body fleet-simulator.js's buildPayload() posts; this module is the
fleet page's counterpart of builder_form.py.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, time
from types import MappingProxyType
from typing import Any

import pandas as pd

from solar_challenge.config import (
    generate_homes_from_distribution,
    parse_dispatch_strategy_config,
    parse_fleet_distribution_config,
    parse_location_block,
    parse_seg_rate,
    parse_tariff_config,
)
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_config import (
    apply_fleet_overlay,
    distribution_form_spec,
    form_to_fleet_distribution_config,
)
from solar_challenge.web.shared import resolve_location
from solar_challenge.web.simulation_params import parse_date_range, parse_seg_tariff

_NAMELESS_FLEET_NAME = "Fleet Distribution Simulation"


@dataclass(frozen=True)
class ParsedFleetForm:
    """The fleet a fleet form describes: the run the simulate endpoint submits, and its scenario document.

    Attributes:
        name: The fleet's name: the form's as given, or the name a nameless fleet runs as.
        homes: The fleet's homes, each with the form's tariff and SEG and, given a battery,
            its dispatch strategy.
        start_date: The first day simulated, at the fleet's location.
        end_date: The last day simulated, at the fleet's location.
        scenario: The fleet scenario document, which load_fleet_config reads back as these
            homes.
    """

    name: Any
    homes: tuple[HomeConfig, ...]
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    scenario: Mapping[str, Any]


def parse_fleet_form(form: Mapping[str, Any]) -> ParsedFleetForm:
    """The fleet the fleet *form* describes, as POST /api/simulate/fleet-from-distribution runs it, with its scenario document.

    The form's distributions are the fleet_distribution: block in config.py's grammar, from
    which the homes are generated at the form's location.  Every home gets the form's
    tariff and SEG, and every home with a battery its dispatch strategy.  The document
    writes the tariff: and seg: blocks as given, null when the form sends none, and the
    dispatch strategy in the battery block, where load_fleet_config gives it to every
    battery; a form without a battery gives it to none.

    The form's six blocks, the pv, battery and load distributions and the tariff,
    dispatch_strategy and seg overlays, share one presence rule: absent or null means none,
    which pv and load refuse as a missing distribution, and any other value must be a
    mapping its grammar reads.

    Each value is read once, as given, by the reader the loaders read it with, so the
    simulate endpoint and the export, which both read the form here, refuse it at the same
    value with the same message.

    Raises:
        ValueError, TypeError: From the form's distribution conversion, location, SEG or
            date range, or for a date that does not parse.
        ConfigurationError: For a block the loaders refuse, or homes they cannot generate.
    """
    distribution = form_to_fleet_distribution_config(dict(form))
    fleet = parse_fleet_distribution_config(distribution)
    location = _fleet_form_location(form)
    homes = _with_fleet_overlay(generate_homes_from_distribution(fleet, location), form)
    start, end = parse_date_range(form)
    name = form.get("name", _NAMELESS_FLEET_NAME)
    return ParsedFleetForm(
        name=name,
        homes=tuple(homes),
        start_date=pd.Timestamp(start, tz=location.timezone),
        end_date=pd.Timestamp(end, tz=location.timezone),
        scenario={
            "name": name,
            "period": {"start_date": start, "end_date": end},
            "location": location_block(location),
            "fleet_distribution": _with_battery_dispatch_strategy(
                distribution, form.get("dispatch_strategy")
            ),
            "tariff": form.get("tariff"),
            "seg": form.get("seg"),
        },
    )


def scenario_from_fleet_form(form: Mapping[str, Any]) -> Mapping[str, Any]:
    """The fleet scenario document the fleet *form* describes, which load_fleet_config reads back as its fleet: :func:`parse_fleet_form`'s.

    Raises:
        ValueError, TypeError, ConfigurationError: As :func:`parse_fleet_form`, for a form
            whose simulation is refused.
    """
    return parse_fleet_form(form).scenario


def _fleet_form_location(form: Mapping[str, Any]) -> Location:
    """The location of the fleet *form* describes: its 'location' as resolve_location reads it, 'bristol' when absent."""
    return resolve_location(form.get("location", "bristol"))


def _with_fleet_overlay(homes: list[HomeConfig], form: Mapping[str, Any]) -> list[HomeConfig]:
    """*homes*, each given the fleet *form*'s tariff and SEG and, with a battery, its dispatch strategy.

    Raises:
        ValueError, ConfigurationError: For a tariff, dispatch strategy or SEG the loaders
            refuse, read in that order.
    """
    tariff_config = parse_tariff_config(form.get("tariff"))
    dispatch_strategy = parse_dispatch_strategy_config(form.get("dispatch_strategy"))
    seg_tariff = parse_seg_tariff(form.get("seg"))
    return apply_fleet_overlay(
        homes,
        tariff_config=tariff_config,
        dispatch_strategy=dispatch_strategy,
        seg_tariff=seg_tariff,
    )


def _with_battery_dispatch_strategy(
    distribution: Mapping[str, Any], dispatch_strategy: Any
) -> dict[str, Any]:
    """The fleet_distribution block *distribution* with *dispatch_strategy* in its battery block; as it is without a battery or a strategy."""
    if dispatch_strategy is None or "battery" not in distribution:
        return dict(distribution)
    battery = {**distribution["battery"], "dispatch_strategy": dispatch_strategy}
    return {**distribution, "battery": battery}


@dataclass(frozen=True)
class ImportedFleetForm:
    """A fleet scenario read as the fleet page's form.

    Attributes:
        form: The fleet form the scenario describes: the body the fleet page posts.
        not_loaded: The path of each setting of the scenario the form has no control for,
            in document order; the form leaves them out.
    """

    form: Mapping[str, Any]
    not_loaded: tuple[str, ...]


def fleet_form_from_scenario(document: object) -> ImportedFleetForm:
    """The fleet form the fleet scenario *document* describes, naming the settings of it the form has no control for.

    The document must be a fleet_distribution scenario the loaders accept: their refusal of
    its fleet, location, tariff or SEG is the refusal.  The form loads exactly what it
    holds: the name, the period's dates, the fleet size and seed, the pv, battery and load
    distributions, the battery's dispatch strategy, the tariff and the SEG.  A name, period
    or seed the scenario leaves out is left out of the form too, and the fleet page runs its
    own default for it.  A null battery capacity reads as 0 kWh, a home with no battery
    either way.  A setting the form needs but cannot hold exactly is refused, naming it,
    since loading it anyway would run a different fleet.  Every other setting, and a
    location other than the page's, is named in not_loaded.  A form the page could not run,
    as parse_fleet_form refuses it, is refused too.

    Raises:
        ValueError: For a document that is not a fleet_distribution scenario, or a setting
            the form needs but cannot hold exactly, naming it.
        ValueError, TypeError, ConfigurationError: From the loaders, for a scenario they
            refuse, or from parse_fleet_form, for a form the page could not run.
    """
    scenario = _fleet_scenario(document)
    _refuse_what_the_loaders_refuse(scenario)
    form, not_loaded = _read_blocks(
        scenario,
        "",
        {
            "name": _read_name(scenario.get("name")),
            "period": _read_period(scenario.get("period")),
            "location": _read_location(scenario.get("location")),
            "fleet_distribution": _read_fleet_distribution(scenario["fleet_distribution"]),
            "tariff": _read_tariff(scenario.get("tariff")),
            "seg": _read_seg(scenario.get("seg")),
        },
    )
    parse_fleet_form(form)
    return ImportedFleetForm(form=form, not_loaded=not_loaded)


#: A scenario block read as its part of the fleet form, and the path of each setting in it
#: the form does not hold.
_BlockRead = tuple[dict[str, Any], tuple[str, ...]]

#: Reads a setting the fleet form holds from its value in a scenario and its path there.
_SettingReader = Callable[[Any, str], Any]


def _fleet_scenario(document: object) -> dict[str, Any]:
    """*document*, which must be a scenario with a fleet_distribution block, the fleet the fleet page holds.

    Raises:
        ValueError: For a document that is not a mapping or has no fleet_distribution block.
    """
    if not isinstance(document, dict):
        raise ValueError(f"A fleet scenario must be a mapping, got {type(document).__name__}")
    if "fleet_distribution" not in document:
        raise ValueError(
            "The scenario has no fleet_distribution block, the fleet the fleet page loads"
        )
    return document


def _refuse_what_the_loaders_refuse(scenario: Mapping[str, Any]) -> None:
    """Refuse *scenario* where the loaders refuse it, with their message; the readers below read only what they accept."""
    parse_location_block(scenario.get("location"))
    parse_fleet_distribution_config(scenario["fleet_distribution"])
    parse_tariff_config(scenario.get("tariff"))
    parse_seg_rate(scenario.get("seg"))


def _child_path(path: str, key: str) -> str:
    """The path of the *key* setting inside the block at *path*; "" is the scenario's top level."""
    return f"{path}.{key}" if path else key


def _not_loaded(
    block: Mapping[str, Any], path: str, held: Mapping[str, tuple[str, ...]]
) -> tuple[str, ...]:
    """The path of each setting in the *path* block that the fleet form does not hold, in the block's order.

    *held* maps each key of the block the form holds to the paths of the settings within it
    that the form does not hold.
    """
    return tuple(
        not_loaded
        for key in block
        for not_loaded in held.get(key, (_child_path(path, key),))
    )


def _read_blocks(block: Mapping[str, Any], path: str, reads: Mapping[str, _BlockRead]) -> _BlockRead:
    """The *path* block as the fleet form holds it, from the *reads* of its keys the form holds."""
    form = {setting: value for read_form, _ in reads.values() for setting, value in read_form.items()}
    held = {key: not_loaded for key, (_, not_loaded) in reads.items()}
    return form, _not_loaded(block, path, held)


def _read_name(name: Any) -> _BlockRead:
    """The fleet form's name: the scenario's, none when it is absent or null.

    Raises:
        ValueError: For a name that is not a string.
    """
    if name is None:
        return {}, ()
    if not isinstance(name, str):
        raise ValueError(f"name must be a string, got {name!r}")
    return {"name": name}, ()


def _read_period(period: Any) -> _BlockRead:
    """The fleet form's start and end dates: the scenario's period, none when it is absent or null.

    Raises:
        ValueError: For a period that is not a mapping, or a date that is not one, naming it.
    """
    if period is None:
        return {}, ()
    if not isinstance(period, Mapping):
        raise ValueError(f"period must be a mapping, got {type(period).__name__}")
    form = {
        "start": _iso_date(period.get("start_date"), "period.start_date"),
        "end": _iso_date(period.get("end_date"), "period.end_date"),
    }
    return form, _not_loaded(period, "period", {"start_date": (), "end_date": ()})


def _iso_date(value: Any, path: str) -> str:
    """*value*, a date as YAML reads one or a date string, as the fleet form's date string.

    A YAML timestamp is its day when it is that day's midnight with no time zone.

    Raises:
        ValueError: For any other value, a missing one read as None, or a timestamp with a
            time of day or a time zone, which the form's date fields cannot hold, naming *path*.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.time() != time.min:
            raise ValueError(
                f"{path} must be a day, got {value!r}: the fleet page's date fields hold "
                "no time of day or time zone"
            )
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        return value
    raise ValueError(f"{path} must be a date, got {value!r}")


def _read_location(location: Any) -> _BlockRead:
    """Nothing of the fleet form, which has no location control: a location other than the one it runs at is not loaded."""
    if parse_location_block(location) == _fleet_form_location({}):
        return {}, ()
    return {}, ("location",)


def _read_fleet_distribution(fleet: Mapping[str, Any]) -> _BlockRead:
    """The fleet form's fleet size, seed, distributions and dispatch strategy: the scenario's fleet_distribution block."""
    path = "fleet_distribution"
    seed = fleet.get("seed")
    return _read_blocks(
        fleet,
        path,
        {
            "n_homes": ({"n_homes": fleet["n_homes"]}, ()),
            "seed": ({} if seed is None else {"seed": seed}, ()),
            "pv": _read_component(fleet, path, "pv", "capacity_kw"),
            "battery": _read_battery(fleet.get("battery"), _child_path(path, "battery")),
            "load": _read_component(fleet, path, "load", "annual_consumption_kwh"),
        },
    )


def _read_component(
    fleet: Mapping[str, Any], path: str, component: str, distribution_key: str
) -> _BlockRead:
    """The fleet form's *component* block, its *distribution_key* distribution, read from the *path* fleet's.

    Raises:
        ValueError: From distribution_form_spec, for a distribution the editor cannot hold,
            an absent one included.
    """
    block_path = _child_path(path, component)
    block = fleet.get(component, {})
    spec = distribution_form_spec(
        block.get(distribution_key), _child_path(block_path, distribution_key)
    )
    return {component: {distribution_key: spec}}, _not_loaded(block, block_path, {distribution_key: ()})


def _read_battery(battery: Any, path: str) -> _BlockRead:
    """The fleet form's battery capacity and dispatch strategy: the *path* battery block's, none when it is absent or null.

    A null capacity reads as 0 kWh: a home with no battery either way.

    Raises:
        ValueError: From distribution_form_spec, for a capacity the editor cannot hold, or
            for a dispatch strategy the form cannot hold.
    """
    if battery is None:
        return {}, ()
    capacity_path = _child_path(path, "capacity_kwh")
    capacity = distribution_form_spec(_null_capacity_as_zero(battery["capacity_kwh"]), capacity_path)
    dispatch, dispatch_not_loaded = _read_dispatch(
        battery.get("dispatch_strategy"), _child_path(path, "dispatch_strategy")
    )
    held = {"capacity_kwh": (), "dispatch_strategy": dispatch_not_loaded}
    return {"battery": {"capacity_kwh": capacity}, **dispatch}, _not_loaded(battery, path, held)


def _null_capacity_as_zero(spec: Any) -> Any:
    """The battery capacity *spec* with each null value read as 0 kWh: a home with no battery either way."""
    if isinstance(spec, Mapping) and isinstance(spec.get("values"), list):
        return {**spec, "values": [0.0 if value is None else value for value in spec["values"]]}
    return spec


def _required(value: Any, path: str) -> Any:
    """*value*, a setting the fleet page always sets.

    Raises:
        ValueError: When the scenario leaves it out, naming *path*.
    """
    if value is None:
        raise ValueError(f"{path} must be set: the fleet page always sets it")
    return value


def _one_peak_window(peak_hours: Any, path: str) -> list[list[Any]]:
    """*peak_hours* as the fleet form's one [start, end] peak window.

    Raises:
        ValueError: For any other number of windows, naming *path*.
    """
    if not isinstance(peak_hours, list) or len(peak_hours) != 1:
        raise ValueError(
            f"{path} must hold exactly one [start, end] window, the fleet page's one "
            f"peak window, got {peak_hours!r}"
        )
    return [list(peak_hours[0])]


#: Each tariff type the fleet form holds, with a reader for each setting of it the form holds.
_FORM_TARIFF_SETTINGS: Mapping[str, Mapping[str, _SettingReader]] = MappingProxyType({
    "flat_rate": {"rate_per_kwh": _required},
    "economy_7": {"peak_rate": _required, "off_peak_rate": _required},
    "economy_10": {"peak_rate": _required, "off_peak_rate": _required},
})

#: Each dispatch strategy the fleet form holds, with a reader for each setting of it the form holds.
_FORM_DISPATCH_SETTINGS: Mapping[str, Mapping[str, _SettingReader]] = MappingProxyType({
    "self_consumption": {},
    "tou_optimized": {"peak_hours": _one_peak_window},
    "peak_shaving": {"import_limit_kw": _required},
})


def _read_tariff(tariff: Any) -> _BlockRead:
    """The fleet form's tariff: the scenario's tariff block, none when it is absent or null.

    Raises:
        ValueError: For a tariff the form cannot hold, naming its setting.
    """
    if tariff is None:
        return {}, ()
    form_tariff, not_loaded = _read_typed_block(tariff, "tariff", "type", _FORM_TARIFF_SETTINGS)
    return {"tariff": form_tariff}, not_loaded


def _read_dispatch(dispatch: Any, path: str) -> _BlockRead:
    """The fleet form's dispatch strategy: the *path* dispatch block, none when it is absent or null.

    Raises:
        ValueError: For a dispatch strategy the form cannot hold, naming its setting.
    """
    if dispatch is None:
        return {}, ()
    form_dispatch, not_loaded = _read_typed_block(
        dispatch, path, "strategy_type", _FORM_DISPATCH_SETTINGS
    )
    return {"dispatch_strategy": form_dispatch}, not_loaded


def _read_typed_block(
    block: Mapping[str, Any],
    path: str,
    type_key: str,
    settings: Mapping[str, Mapping[str, _SettingReader]],
) -> _BlockRead:
    """The *path* block, whose *type_key* names its type, as the fleet form holds it: its type and the settings *settings* reads for that type.

    Raises:
        ValueError: For a type *settings* has no readers for, naming the block's *type_key*,
            or from a setting's reader.
    """
    block_type = block[type_key]
    readers = settings.get(block_type)
    if readers is None:
        raise ValueError(
            f"{_child_path(path, type_key)} must be one the fleet page holds "
            f"({', '.join(settings)}), got {block_type!r}"
        )
    form = {
        type_key: block_type,
        **{key: read(block.get(key), _child_path(path, key)) for key, read in readers.items()},
    }
    return form, _not_loaded(block, path, dict.fromkeys((type_key, *readers), ()))


def _read_seg(seg: Any) -> _BlockRead:
    """The fleet form's SEG: the scenario's seg block as given, none when it is absent or null.

    The loaders accepted it, so it names exactly one preset or rate, both of which the form holds.
    """
    if seg is None:
        return {}, ()
    return {"seg": dict(seg)}, ()
