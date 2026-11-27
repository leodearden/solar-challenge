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
import yaml

from solar_challenge.config import read_fleet_scenario
from solar_challenge.dispatch import TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import ComponentDistribution, FleetDistributionConfig
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.scenario_blocks import child_path, parse_dispatch_strategy_config
from solar_challenge.scenario_writer import location_block
from solar_challenge.tariff import PRESET_RATES, PresetRates
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    FLEET_SIZE_DEFAULT,
    SEED_DEFAULT,
    ComponentLimits,
    refuse_homes_outside_ranges,
)
from solar_challenge.web.fleet_config import (
    FLEET_DISTRIBUTION_FORM_KEYS,
    read_form_fleet,
    refuse_a_fleet_the_dashboard_cannot_run,
)
from solar_challenge.web.request_boundary import (
    WEB_DEFAULT_LOCATION,
    present_fields,
    read_location,
    read_optional_string,
    refuse_unrecognised_keys,
)
from solar_challenge.web.run_names import is_run_name
from solar_challenge.web.simulation_params import (
    DATE_RANGE_KEYS,
    parse_date_range,
    read_iso_date,
    refuse_reversed_or_overlong_window,
)

#: The top-level keys of a fleet form: those parse_fleet_form reads, itself or through the readers it calls.
_FLEET_FORM_KEYS: frozenset[str] = (
    FLEET_DISTRIBUTION_FORM_KEYS
    | DATE_RANGE_KEYS
    | {"name", "location", "tariff", "dispatch_strategy", "seg"}
)


@dataclass(frozen=True)
class ParsedFleetForm:
    """The fleet a fleet form describes: the run the simulate endpoint submits, and its scenario document.

    Attributes:
        name: The form's name, None when it sends none or a blank one, which cannot name a
            run (is_run_name), so the run submitted takes its kind's default name.
        homes: The fleet's homes, each with the form's tariff and SEG and, given a battery,
            its dispatch strategy: the scenario's homes as parse_scenario reads them.
        start_date: The first day simulated, at the fleet's location.
        end_date: The last day simulated, at the fleet's location.
        scenario: The fleet scenario document, which load_scenario reads back as these homes
            and dates.
    """

    name: str | None
    homes: tuple[HomeConfig, ...]
    start_date: pd.Timestamp
    end_date: pd.Timestamp
    scenario: Mapping[str, Any]


def parse_fleet_form(form: Mapping[str, Any]) -> ParsedFleetForm:
    """The fleet the fleet *form* describes, as POST /api/simulate/fleet-from-distribution runs it, with its scenario document.

    The run's homes and dates are config.parse_scenario's reading of the scenario document
    returned, so the run and the export are one reading. The document's fleet_distribution:
    block is the form's fleet blocks as sent, with its dispatch strategy in the battery
    block; it writes the form's name only when it can name a run, and the tariff: and seg:
    blocks as given, null when the form sends none. A top-level field sent as null or ""
    reads as not sent, so a seed, n_homes or location so sent takes its default.

    It reads, in order: the form's keys; the name; its fleet blocks, by read_form_fleet at
    the form's own paths, so a refusal names the field the page posted; the location; the
    dispatch strategy, at the form's own key; the window; then, through read_fleet_scenario,
    the document's location, period, tariff, SEG and fleet; and only then generates the
    homes and bounds each one's values, so a value a reader refuses costs no home generation.

    Raises:
        ConfigurationError: For the first value read in that order that is refused, naming
            its field.
    """
    refuse_unrecognised_keys(form, _FLEET_FORM_KEYS, "Fleet form")
    fields = present_fields(form)
    sent_name = read_optional_string(fields.get("name"), "name")
    name = sent_name if is_run_name(sent_name) else None
    blocks = _fleet_blocks(fields)
    read_form_fleet(blocks)
    location = _fleet_form_location(fields)
    parse_dispatch_strategy_config(fields.get("dispatch_strategy"))
    start, end = parse_date_range(fields)
    document = {
        **({} if name is None else {"name": name}),
        "period": {"start_date": start, "end_date": end},
        "location": location_block(location),
        "fleet_distribution": _document_fleet_distribution(blocks, fields.get("dispatch_strategy")),
        "tariff": fields.get("tariff"),
        "seg": fields.get("seg"),
    }
    scenario = read_fleet_scenario(document).scenario()
    homes = scenario.simulated_homes()
    refuse_homes_outside_ranges(homes)
    start_date, end_date = scenario.simulation_bounds()
    return ParsedFleetForm(name=name, homes=homes, start_date=start_date, end_date=end_date, scenario=document)


def scenario_from_fleet_form(form: Mapping[str, Any]) -> Mapping[str, Any]:
    """The fleet scenario document the fleet *form* describes, which load_scenario reads back as its homes and dates: :func:`parse_fleet_form`'s.

    Raises:
        ConfigurationError: As :func:`parse_fleet_form`, for a form whose simulation is
            refused.
    """
    return parse_fleet_form(form).scenario


def _fleet_blocks(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet blocks of *fields*, a fleet form's present fields: the fleet page's FLEET_SIZE_DEFAULT homes and SEED_DEFAULT seed, then each FLEET_DISTRIBUTION_FORM_KEYS field the form sends, as sent."""
    sent = {key: fields[key] for key in FLEET_DISTRIBUTION_FORM_KEYS if key in fields}
    return {"n_homes": FLEET_SIZE_DEFAULT, "seed": SEED_DEFAULT, **sent}


def _fleet_form_location(form: Mapping[str, Any]) -> Location:
    """The location of the fleet *form* describes: its 'location' as read_location reads it, WEB_DEFAULT_LOCATION when not sent."""
    return read_location(form.get("location", WEB_DEFAULT_LOCATION))


def _document_fleet_distribution(
    distribution: Mapping[str, Any], dispatch_strategy: Any
) -> dict[str, Any]:
    """The scenario document's fleet_distribution block: *distribution* with the form's *dispatch_strategy*, as sent, in its battery block; as it is without a battery or a strategy."""
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

    The document is read as config.read_fleet_scenario reads it, its period first by the page's
    own stricter rules, and its fleet held to the dashboard's bounds; no home of it is
    generated. The form holds the name, period, fleet size and seed, each component's field as
    its editor loads the grammar's reading of it (ComponentLimits.editor_spec), the battery's
    dispatch strategy, the tariff and the SEG; a setting the scenario leaves out is left out
    of the form, but an economy tariff's rate, which loads as the PRESET_RATES rate
    parse_scenario charges it. A setting the form has no control for, or a location other than the page's,
    is named in not_loaded; one the form needs but cannot hold exactly is refused, since
    loading it anyway would run another fleet. The form loaded is then read by
    parse_fleet_form, the import's one generation of homes.

    Raises:
        ConfigurationError: For a document that is not a fleet_distribution scenario, a period
            the page cannot run, or a setting the form needs but cannot hold exactly, naming it.
        ConfigurationError: From read_fleet_scenario, refuse_a_fleet_the_dashboard_cannot_run or
            parse_fleet_form, for a scenario, fleet or loaded form each refuses.
    """
    scenario = _fleet_scenario(document)
    period = _read_period(scenario.get("period"))
    read = read_fleet_scenario(scenario)
    refuse_a_fleet_the_dashboard_cannot_run(read.fleet, "fleet_distribution")
    form, not_loaded = _read_blocks(
        scenario,
        "",
        {
            "name": _read_name(scenario.get("name")),
            "period": period,
            "location": _read_location(read.location),
            "fleet_distribution": _read_fleet_distribution(scenario["fleet_distribution"], read.fleet),
            "tariff": _read_tariff(scenario.get("tariff")),
            "seg": _read_seg(scenario.get("seg")),
        },
    )
    parse_fleet_form(form)
    return ImportedFleetForm(form=form, not_loaded=not_loaded)


def fleet_form_from_yaml(yaml_text: str) -> ImportedFleetForm:
    """The fleet form the fleet scenario YAML *yaml_text* describes, as :func:`fleet_form_from_scenario` reads its document.

    Raises:
        ConfigurationError: For text that does not parse as YAML, "Invalid YAML: " and the parser's error.
        ConfigurationError: As fleet_form_from_scenario.
    """
    try:
        document = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"Invalid YAML: {exc}") from exc
    return fleet_form_from_scenario(document)


#: A scenario block read as its part of the fleet form, and the path of each setting in it
#: the form does not hold.
_BlockRead = tuple[dict[str, Any], tuple[str, ...]]

#: Reads a setting the fleet form holds from its value in a scenario and its path there.
_SettingReader = Callable[[Any, str], Any]


def _fleet_scenario(document: object) -> dict[str, Any]:
    """*document*, which must be a scenario with a fleet_distribution block, the fleet the fleet page holds.

    Raises:
        ConfigurationError: For a document that is not a mapping or has no fleet_distribution block,
            or a fleet_distribution block that is not a mapping.
    """
    if not isinstance(document, dict):
        raise ConfigurationError(f"A fleet scenario must be a mapping, got {type(document).__name__}")
    if "fleet_distribution" not in document:
        raise ConfigurationError(
            "The scenario has no fleet_distribution block, the fleet the fleet page loads"
        )
    fleet = document["fleet_distribution"]
    if not isinstance(fleet, dict):
        raise ConfigurationError(f"fleet_distribution must be a mapping, got {type(fleet).__name__}")
    return document


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
        for not_loaded in held.get(key, (child_path(path, key),))
    )


def _read_blocks(block: Mapping[str, Any], path: str, reads: Mapping[str, _BlockRead]) -> _BlockRead:
    """The *path* block as the fleet form holds it, from the *reads* of its keys the form holds."""
    form = {setting: value for read_form, _ in reads.values() for setting, value in read_form.items()}
    held = {key: not_loaded for key, (_, not_loaded) in reads.items()}
    return form, _not_loaded(block, path, held)


def _read_name(name: str | None) -> _BlockRead:
    """The fleet form's name: the scenario's, which read_fleet_scenario accepted as a string, none when it is absent or null."""
    if name is None:
        return {}, ()
    return {"name": name}, ()


def _read_period(period: Any) -> _BlockRead:
    """The fleet form's start and end dates: the scenario's period, none when it is absent or null.

    Raises:
        ConfigurationError: For a period that is not a mapping, or a date that is not a day,
            naming it as period.start_date or period.end_date; or for a window the page
            cannot run, naming period.start_date and period.end_date.
    """
    if period is None:
        return {}, ()
    if not isinstance(period, Mapping):
        raise ConfigurationError(f"period must be a mapping, got {type(period).__name__}")
    start_path, end_path = "period.start_date", "period.end_date"
    start = _read_day(period.get("start_date"), start_path)
    end = _read_day(period.get("end_date"), end_path)
    refuse_reversed_or_overlong_window(start, end, start_field=start_path, end_field=end_path)
    form = {"start": start.isoformat(), "end": end.isoformat()}
    return form, _not_loaded(period, "period", {"start_date": (), "end_date": ()})


def _read_day(value: Any, path: str) -> date:
    """*value*, a date as YAML reads one or an ISO 8601 date string, as the day it names.

    A YAML timestamp is its day when it is that day's midnight with no time zone.

    Raises:
        ConfigurationError: For a timestamp with a time of day or a time zone, which the form's
            date fields cannot hold, or, from read_iso_date, any other value that is not
            an ISO 8601 date string, a missing one read as None included, naming *path*.
    """
    if isinstance(value, datetime):
        if value.tzinfo is not None or value.time() != time.min:
            raise ConfigurationError(
                f"{path} must be a day, got {value!r}: the fleet page's date fields hold "
                "no time of day or time zone"
            )
        return value.date()
    if isinstance(value, date):
        return value
    return read_iso_date(value, path)


def _read_location(location: Location) -> _BlockRead:
    """Nothing of the fleet form, which has no location control: a scenario *location*, as read_fleet_scenario reads it, other than the one the form runs at is not loaded."""
    if location == _fleet_form_location({}):
        return {}, ()
    return {}, ("location",)


def _read_fleet_distribution(fleet: Mapping[str, Any], parsed: FleetDistributionConfig) -> _BlockRead:
    """The fleet form's fleet size, seed, distributions and dispatch strategy: the scenario's fleet_distribution block *fleet*, as the grammar read it, *parsed*, a seed it leaves out none.

    Raises:
        ConfigurationError: From the readers of its distributions and dispatch strategy.
    """
    path = "fleet_distribution"
    return _read_blocks(
        fleet,
        path,
        {
            "n_homes": ({"n_homes": parsed.n_homes}, ()),
            "seed": ({} if parsed.seed is None else {"seed": parsed.seed}, ()),
            "pv": _read_component(fleet, path, FLEET_COMPONENTS["pv"], parsed.pv),
            "battery": _read_battery(fleet.get("battery"), child_path(path, "battery"), parsed.battery),
            "load": _read_component(fleet, path, FLEET_COMPONENTS["load"], parsed.load),
        },
    )


def _read_component(
    fleet: Mapping[str, Any], path: str, limits: ComponentLimits, read: ComponentDistribution
) -> _BlockRead:
    """The fleet form's *limits* component block of the *path* fleet: its field as its editor loads *read*, the grammar's reading of the block.

    Raises:
        ConfigurationError: From ComponentLimits.editor_spec, for a field the editor cannot hold.
    """
    block_path = child_path(path, limits.key)
    form = {limits.key: {limits.grammar_key: _editor_field(limits, read, block_path)}}
    return form, _not_loaded(fleet.get(limits.key) or {}, block_path, {limits.grammar_key: ()})


def _read_battery(battery: Any, path: str, read: ComponentDistribution | None) -> _BlockRead:
    """The fleet form's battery capacity and dispatch strategy: the *path* battery block's, whose grammar reading is *read*, none when it is absent or null.

    A dispatch strategy on its tariff's clock loads none, and its path is named not loaded.

    Raises:
        ConfigurationError: From ComponentLimits.editor_spec, for a capacity the editor cannot
            hold, or for a dispatch strategy the form cannot hold.
    """
    if read is None:
        return {}, ()
    limits = FLEET_COMPONENTS["battery"]
    capacity = _editor_field(limits, read, path)
    dispatch, dispatch_not_loaded = _read_dispatch(
        battery.get("dispatch_strategy"), child_path(path, "dispatch_strategy")
    )
    held = {limits.grammar_key: (), "dispatch_strategy": dispatch_not_loaded}
    return {"battery": {limits.grammar_key: capacity}, **dispatch}, _not_loaded(battery, path, held)


def _editor_field(limits: ComponentLimits, read: ComponentDistribution, block_path: str) -> object:
    """The *limits* component's field as its editor loads it from *read*, the grammar's reading of the *block_path* block: its draw, null when the block draws none, the editor's blank Fixed Value."""
    field_path = child_path(block_path, limits.grammar_key)
    return limits.editor_spec(read.draws.get(limits.grammar_key), field_path)


def _required(value: Any, path: str) -> Any:
    """*value*, a setting the fleet page always sets.

    Raises:
        ConfigurationError: When the scenario leaves it out, naming *path*.
    """
    if value is None:
        raise ConfigurationError(f"{path} must be set: the fleet page always sets it")
    return value


def _or_default(default: float) -> _SettingReader:
    """A reader of a setting the loaders default: the scenario's value as given, or *default* when the scenario leaves it out."""

    def read_or_default(value: Any, path: str) -> Any:
        return default if value is None else value

    return read_or_default


def _economy_rate_readers(rates: PresetRates) -> Mapping[str, _SettingReader]:
    """The readers of an economy tariff's two rates, each filling a rate the scenario leaves out from *rates*, its preset's default rates."""
    return {"peak_rate": _or_default(rates.peak_rate), "off_peak_rate": _or_default(rates.off_peak_rate)}


def _one_peak_window(peak_hours: Any, path: str) -> list[list[Any]]:
    """*peak_hours* as the fleet form's one [start, end] peak window.

    Raises:
        ConfigurationError: For any other number of windows, naming *path*.
    """
    if not isinstance(peak_hours, list) or len(peak_hours) != 1:
        raise ConfigurationError(
            f"{path} must hold exactly one [start, end] window, the fleet page's one "
            f"peak window, got {peak_hours!r}"
        )
    return [list(peak_hours[0])]


#: Each tariff type the fleet form holds, with a reader for each setting of it the form holds.
_FORM_TARIFF_SETTINGS: Mapping[str, Mapping[str, _SettingReader]] = MappingProxyType({
    "flat_rate": {"rate_per_kwh": _required},
    "economy_7": _economy_rate_readers(PRESET_RATES["economy_7"]),
    "economy_10": _economy_rate_readers(PRESET_RATES["economy_10"]),
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
        ConfigurationError: For a tariff the form cannot hold, naming its setting.
    """
    if tariff is None:
        return {}, ()
    form_tariff, not_loaded = _read_typed_block(tariff, "tariff", "type", _FORM_TARIFF_SETTINGS)
    return {"tariff": form_tariff}, not_loaded


def _read_dispatch(dispatch: Any, path: str) -> _BlockRead:
    """The fleet form's dispatch strategy: the *path* dispatch block, none when it is absent or null.

    A tou_optimized on its tariff's clock, which the form has no control for, loads none and
    names *path* not loaded.

    Raises:
        ConfigurationError: For a dispatch strategy the form cannot hold, naming its setting.
    """
    if dispatch is None:
        return {}, ()
    if _on_its_tariffs_clock(dispatch, path):
        return {}, (path,)
    form_dispatch, not_loaded = _read_typed_block(
        dispatch, path, "strategy_type", _FORM_DISPATCH_SETTINGS
    )
    return {"dispatch_strategy": form_dispatch}, not_loaded


def _on_its_tariffs_clock(dispatch: dict[str, Any], path: str) -> bool:
    """Whether the *path* dispatch block, one read_fleet_scenario accepted, is tou_optimized on its tariff's clock: it sets no peak_hours."""
    strategy = parse_dispatch_strategy_config(dispatch, block_path=path)
    return isinstance(strategy, TOUOptimizedStrategyConfig) and strategy.peak_hours is None


def _read_typed_block(
    block: Mapping[str, Any],
    path: str,
    type_key: str,
    settings: Mapping[str, Mapping[str, _SettingReader]],
) -> _BlockRead:
    """The *path* block, whose *type_key* names its type, as the fleet form holds it: its type and the settings *settings* reads for that type.

    Raises:
        ConfigurationError: For a type *settings* has no readers for, naming the block's *type_key*,
            or from a setting's reader.
    """
    block_type = block[type_key]
    readers = settings.get(block_type)
    if readers is None:
        raise ConfigurationError(
            f"{child_path(path, type_key)} must be one the fleet page holds "
            f"({', '.join(settings)}), got {block_type!r}"
        )
    form = {
        type_key: block_type,
        **{key: read(block.get(key), child_path(path, key)) for key, read in readers.items()},
    }
    return form, _not_loaded(block, path, dict.fromkeys((type_key, *readers), ()))


def _read_seg(seg: Any) -> _BlockRead:
    """The fleet form's SEG: the scenario's seg block as given, none when it is absent or null.

    read_fleet_scenario accepted it, so it names exactly one preset or rate, both of which the form holds.
    """
    if seg is None:
        return {}, ()
    return {"seg": dict(seg)}, ()
