# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet page's form both ways: the fleet a fleet form describes, as the simulate endpoint runs it and as a scenario document, and the fleet form a scenario describes; and the tariffs and dispatch strategies the form offers, FLEET_FORM_TARIFFS and FLEET_FORM_DISPATCH.

A fleet form is the body fleet-simulator.js's buildPayload() posts; this module is the
fleet page's counterpart of builder_form.py.
"""

from collections.abc import Mapping
from dataclasses import dataclass, fields
from datetime import date
from types import MappingProxyType
from typing import Any

import pandas as pd

from solar_challenge.config import read_fleet_scenario
from solar_challenge.dispatch import STRATEGY_CONFIG_BY_TYPE, DispatchStrategyConfig, TOUOptimizedStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import ComponentDistribution
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.number_fields import Interval
from solar_challenge.scenario_blocks import child_path, parse_dispatch_strategy_config, parse_tariff_config
from solar_challenge.scenario_writer import location_block
from solar_challenge.tariff import PRESET_RATES
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    FLEET_SIZE_DEFAULT,
    SEED_DEFAULT,
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
from solar_challenge.web.scenario_import import (
    RATE_STEP,
    RATE_WITHIN,
    BlockRead,
    FormChoice,
    FormSetting,
    ImportedForm,
    SettingInput,
    SettingReader,
    editor_field,
    flat_rate_choice,
    fleet_scenario_document,
    not_loaded,
    read_as_given,
    read_blocks,
    read_fleet_distribution,
    read_period,
    read_seg,
    read_typed_block,
    required,
    scenario_yaml_document,
)
from solar_challenge.web.simulation_params import (
    DATE_RANGE_KEYS,
    parse_date_range,
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


_PAGE = "fleet page"

#: The seg keys the fleet form holds: a preset or a rate.
_HELD_SEG_KEYS = frozenset({"preset", "rate_pence_per_kwh"})


def fleet_form_from_scenario(document: object) -> ImportedForm:
    """The fleet form the fleet scenario *document* describes, naming the settings of it the form has no control for, by docs/web-ui-design.md's *Scenario import policy*.

    Raises:
        ConfigurationError: For a document that is not a fleet_distribution scenario, a period
            the page cannot run, or a setting the form needs but cannot hold exactly, naming it.
        ConfigurationError: From read_fleet_scenario, refuse_a_fleet_the_dashboard_cannot_run or
            parse_fleet_form, for a scenario, fleet or loaded form each refuses.
    """
    scenario = fleet_scenario_document(document, _PAGE)
    period = read_period(scenario.get("period"), _PAGE)
    if period is not None:
        refuse_reversed_or_overlong_window(
            *period, start_field="period.start_date", end_field="period.end_date"
        )
    read = read_fleet_scenario(scenario)
    refuse_a_fleet_the_dashboard_cannot_run(read.fleet, "fleet_distribution")
    form, unheld = read_blocks(
        scenario,
        "",
        {
            "name": read_as_given("name", scenario.get("name")),
            "period": _read_period(period),
            "location": _read_location(read.location),
            "fleet_distribution": read_fleet_distribution(scenario["fleet_distribution"], read.fleet, _read_battery),
            "tariff": _read_tariff(scenario.get("tariff")),
            "seg": read_seg(scenario.get("seg"), _HELD_SEG_KEYS, _PAGE),
        },
    )
    parse_fleet_form(form)
    return ImportedForm(form=form, not_loaded=unheld)


def fleet_form_from_yaml(yaml_text: str) -> ImportedForm:
    """The fleet form the fleet scenario YAML *yaml_text* describes, as :func:`fleet_form_from_scenario` reads its document.

    Raises:
        ConfigurationError: For text that does not parse as YAML, "Invalid YAML: " and the parser's error.
        ConfigurationError: As fleet_form_from_scenario.
    """
    return fleet_form_from_scenario(scenario_yaml_document(yaml_text))


def _read_period(period: tuple[date, date] | None) -> BlockRead:
    """The fleet form's start and end dates: the *period* read_period read, none when the scenario sets none; read_fleet_scenario refuses any other key of the period block."""
    if period is None:
        return {}, ()
    start, end = period
    return {"start": start.isoformat(), "end": end.isoformat()}, ()


def _read_location(location: Location) -> BlockRead:
    """Nothing of the fleet form, which has no location control: a scenario *location*, as read_fleet_scenario reads it, other than the one the form runs at is not loaded."""
    if location == _fleet_form_location({}):
        return {}, ()
    return {}, ("location",)


def _read_battery(fleet: Mapping[str, Any], path: str, read: ComponentDistribution | None) -> BlockRead:
    """The fleet form's battery capacity and dispatch strategy: the battery block of the *path* fleet block *fleet*, whose grammar reading is *read*, none when it is absent or null.

    A dispatch strategy on its tariff's clock loads none, and its path is named not loaded.

    Raises:
        ConfigurationError: From ComponentLimits.editor_spec, for a capacity the editor cannot
            hold, or for a dispatch strategy the form cannot hold.
    """
    if read is None:
        return {}, ()
    limits = FLEET_COMPONENTS["battery"]
    battery = fleet[limits.key]
    battery_path = child_path(path, limits.key)
    capacity = editor_field(limits, read, battery_path)
    dispatch, dispatch_not_loaded = _read_dispatch(
        battery.get("dispatch_strategy"), child_path(battery_path, "dispatch_strategy")
    )
    held = {limits.grammar_key: (), "dispatch_strategy": dispatch_not_loaded}
    return {limits.key: {limits.grammar_key: capacity}, **dispatch}, not_loaded(battery, battery_path, held)


def _or_default(default: float) -> SettingReader:
    """A reader of a setting the loaders default: the scenario's value as given, or *default* when the scenario leaves it out."""

    def read_or_default(value: Any, path: str) -> Any:
        return default if value is None else value

    return read_or_default


def _economy_choice(tariff_type: str, title: str) -> FormChoice:
    """The *tariff_type* economy preset as the fleet form holds it: its peak and off-peak rates, each starting at its PRESET_RATES rate, the rate a scenario that leaves it out is charged."""
    rates = PRESET_RATES[tariff_type]
    return FormChoice(
        tariff_type,
        title,
        (
            FormSetting(
                "peak_rate", "Peak Rate (£/kWh)", RATE_WITHIN, RATE_STEP, rates.peak_rate, _or_default(rates.peak_rate)
            ),
            FormSetting(
                "off_peak_rate",
                "Off-peak Rate (£/kWh)",
                RATE_WITHIN,
                RATE_STEP,
                rates.off_peak_rate,
                _or_default(rates.off_peak_rate),
            ),
        ),
    )


#: The tariffs the fleet form offers, the one it starts at first.
FLEET_FORM_TARIFFS: tuple[FormChoice, ...] = (
    flat_rate_choice(_PAGE),
    _economy_choice("economy_7", "Economy 7"),
    _economy_choice("economy_10", "Economy 10"),
)


def _one_window_or_the_clock(peak_hours: Any, path: str) -> list[list[Any]] | None:
    """*peak_hours* as the fleet form holds it: None, the tariff's clock, or its one [start, end] peak window.

    Raises:
        ConfigurationError: For any other value, naming *path*.
    """
    if peak_hours is None:
        return None
    if not isinstance(peak_hours, list) or len(peak_hours) != 1:
        raise ConfigurationError(
            f"{path} must be null, the tariff's clock, or hold exactly one [start, end] window, "
            f"the fleet page's one peak window, got {peak_hours!r}"
        )
    return [list(peak_hours[0])]


#: The title of each dispatch strategy the fleet form offers, by its tag.
_DISPATCH_TITLES: Mapping[str, str] = MappingProxyType({
    "self_consumption": "Self Consumption (default)",
    "tou_optimized": "Time-of-Use Optimised",
    "peak_shaving": "Peak Shaving",
})

#: The setting the fleet form holds for each field of a dispatch strategy, by the field's name.
_DISPATCH_SETTINGS: Mapping[str, FormSetting] = MappingProxyType({
    setting.key: setting
    for setting in (
        FormSetting(
            "peak_hours",
            "Peak window",
            Interval(0, 24),
            1,
            ((16, 19),),
            _one_window_or_the_clock,
            SettingInput.CLOCK_OR_WINDOW,
        ),
        FormSetting("import_limit_kw", "Import limit (kW)", Interval(0.1, 100), 0.1, 3.0, required(_PAGE)),
    )
})


def fleet_form_dispatch_choices(configs: Mapping[str, type[DispatchStrategyConfig]]) -> tuple[FormChoice, ...]:
    """The dispatch strategies the fleet form offers: one choice per strategy of *configs*, by its tag, in its order, holding a setting for each field its constructor takes, in field order.

    Raises:
        KeyError: For a tag the form has no title for, or a field it has no setting for,
            naming it.
    """
    return tuple(
        FormChoice(
            tag,
            _DISPATCH_TITLES[tag],
            tuple(_DISPATCH_SETTINGS[each.name] for each in fields(config) if each.init),
        )
        for tag, config in configs.items()
    )


#: The dispatch strategies the fleet form offers, the one a battery that names none runs first.
FLEET_FORM_DISPATCH: tuple[FormChoice, ...] = fleet_form_dispatch_choices(STRATEGY_CONFIG_BY_TYPE)


def _refuse_a_start_the_grammar_does_not_read() -> None:
    """Read each choice's starting block, the block the fleet form posts at its starts, with the grammar's reader of that block, at a path naming its table and its type.

    Raises:
        ConfigurationError: From parse_tariff_config or parse_dispatch_strategy_config, for a
            type the grammar does not read or a start it refuses.
    """
    for choice in FLEET_FORM_TARIFFS:
        parse_tariff_config(choice.starting_block("type"), block_path=f"FLEET_FORM_TARIFFS[{choice.type!r}]")
    for choice in FLEET_FORM_DISPATCH:
        parse_dispatch_strategy_config(
            choice.starting_block("strategy_type"), block_path=f"FLEET_FORM_DISPATCH[{choice.type!r}]"
        )


_refuse_a_start_the_grammar_does_not_read()


def _read_tariff(tariff: Any) -> BlockRead:
    """The fleet form's tariff: the scenario's tariff block, none when it is absent or null.

    Raises:
        ConfigurationError: For a tariff the form cannot hold, naming its setting.
    """
    if tariff is None:
        return {}, ()
    form_tariff, unheld = read_typed_block(tariff, "tariff", "type", FLEET_FORM_TARIFFS, _PAGE)
    return {"tariff": form_tariff}, unheld


def _read_dispatch(dispatch: Any, path: str) -> BlockRead:
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
    form_dispatch, unheld = read_typed_block(
        dispatch, path, "strategy_type", FLEET_FORM_DISPATCH, _PAGE
    )
    return {"dispatch_strategy": form_dispatch}, unheld


def _on_its_tariffs_clock(dispatch: dict[str, Any], path: str) -> bool:
    """Whether the *path* dispatch block, one read_fleet_scenario accepted, is tou_optimized on its tariff's clock: it sets no peak_hours."""
    strategy = parse_dispatch_strategy_config(dispatch, block_path=path)
    return isinstance(strategy, TOUOptimizedStrategyConfig) and strategy.peak_hours is None
