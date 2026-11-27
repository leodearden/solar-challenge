# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form contract both ways: the fleet scenario document a form describes and why it is refused, and the builder form a fleet scenario describes.

The builder posts the form scenario-builder.js's getFormData() builds: flat general
fields, the number of homes and the fleet page's seed, and the fleet page's pv, battery
and load blocks, each component's field the grammar's own spec.  A field the form leaves
out, or sends as null or '' (a cleared input), is left out of the block that carries it,
so config.parse_scenario reports or defaults it as it would for a hand-written scenario
file.  The tariff: and seg: blocks carry nothing but their rate, so a form without the
import or SEG rate writes that block as null: a scenario with no tariff, or no SEG.

A form is judged in one order: the dashboard's own limits, then the fleet blocks as
fleet_config.read_form_fleet reads them, naming a field at the form's own path, then the
whole document as config.parse_scenario reads it.

A scenario is imported as a builder form by docs/web-ui-design.md's *Scenario import
policy*, with the readers of scenario_import.py; this module declares what the form holds.
"""

from collections.abc import Callable, Mapping
from datetime import date
from types import MappingProxyType
from typing import Any, Optional

from solar_challenge.config import ScenarioConfig, parse_scenario, read_fleet_scenario
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import ComponentDistribution
from solar_challenge.location import LOCATION_PRESETS, Location
from solar_challenge.number_fields import as_finite_float, as_whole_number
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    page_limits,
    refuse_homes_outside_ranges,
)
from solar_challenge.web.fleet_config import read_form_fleet, refuse_a_fleet_the_dashboard_cannot_run
from solar_challenge.web.request_boundary import (
    present_fields,
    refusal_text,
    refuse_unrecognised_keys,
    require_json_object,
)
from solar_challenge.web.scenario_import import (
    BlockRead,
    ImportedForm,
    SettingReader,
    fleet_scenario_document,
    not_loaded,
    read_as_given,
    read_blocks,
    read_component,
    read_fleet_distribution,
    read_period,
    read_seg,
    read_typed_block,
    required,
    scenario_yaml_document,
)

_BUILDER_FORM = "Builder form"

_CUSTOM_LOCATION_FORM_KEYS: Mapping[str, str] = {
    coordinate: coordinate for coordinate in ("latitude", "longitude", "altitude")
}

_RECOGNISED_KEYS = frozenset(
    {
        "name",
        "description",
        "start_date",
        "end_date",
        "location_preset",
        *_CUSTOM_LOCATION_FORM_KEYS.values(),
        "n_homes",
        "seed",
        "import_rate",
        "seg_rate_pence_per_kwh",
    }
    | set(FLEET_COMPONENTS)
)


def scenario_from_builder_form(form: object) -> dict[str, Any]:
    """The fleet scenario document the builder *form* describes.

    Each component block is written as sent, for the fleet's readers to refuse, as
    builder_form_errors reports.

    Raises:
        ConfigurationError: naming the form field at fault, for a form that is not an object, a
            key the builder does not send, a flat field that is not the number it should
            be, or an unknown location preset.
    """
    form = require_json_object(form, _BUILDER_FORM)
    refuse_unrecognised_keys(form, _RECOGNISED_KEYS, _BUILDER_FORM)
    fields = present_fields(form)

    document: dict[str, Any] = {
        key: str(fields[key]) for key in ("name", "description") if key in fields
    }
    document["period"] = {
        key: str(fields[key]) for key in ("start_date", "end_date") if key in fields
    }
    if "location_preset" in fields:
        document["location"] = _location_block(fields)
    document["fleet_distribution"] = _fleet_distribution_block(fields)
    import_rate = _optional_number(fields, "import_rate")
    seg_rate = _optional_number(fields, "seg_rate_pence_per_kwh")
    document["tariff"] = (
        None if import_rate is None else {"type": "flat_rate", "rate_per_kwh": import_rate}
    )
    document["seg"] = None if seg_rate is None else {"rate_pence_per_kwh": seg_rate}
    return document


def builder_form_errors(form: object) -> list[str]:
    """Why the dashboard refuses the builder *form*; no reason for a scenario it accepts.

    A form that is not a JSON object has that one reason.  For any other, the dashboard's
    own limits come first.  Then the form becomes its scenario, and, unless its number of
    homes is out of bounds, read_form_fleet reads its fleet blocks: a refusal, naming the
    field at the form's own path, is the one fleet reason.  So is any other ValueError it
    raises, a probable defect, which refusal_text logs once, as _scenario_reader_errors
    treats one from the scenario reader.  Otherwise config.parse_scenario judges the document
    in memory.  A refused location or tariff is then the one reason.
    Otherwise the homes' value_range reasons come first, then the reader's first refusal of
    the period or SEG rate, the period's before the SEG's: one of the two, never both, and
    neither hides a fleet reason.
    """
    try:
        form = require_json_object(form, _BUILDER_FORM)
    except ValueError as refusal:
        return [refusal_text(refusal)]
    return [*_name_errors(form), *_errors_but_the_name(form)]


def _name_errors(form: Mapping[str, Any]) -> list[str]:
    """The dashboard's rule that a builder *form* names its scenario: its one reason when the form sends no name."""
    return [] if "name" in present_fields(form) else ["Scenario name is required."]


def _errors_but_the_name(form: Mapping[str, Any]) -> list[str]:
    """Every reason builder_form_errors gives the builder *form*, a JSON object, but a missing name, in its order."""
    errors = _fleet_size_errors(present_fields(form))
    try:
        document = scenario_from_builder_form(form)
    except ValueError as refusal:
        return [*errors, refusal_text(refusal)]
    fleet_distribution = document["fleet_distribution"]
    if _home_count_allowed(fleet_distribution.get("n_homes")):
        try:
            read_form_fleet(fleet_distribution)
        except ValueError as refusal:
            return [*errors, refusal_text(refusal)]
        errors.extend(_scenario_reader_errors(document))
    return errors


def _fleet_size_errors(fields: Mapping[str, Any]) -> list[str]:
    """The dashboard's own limit on a fleet: 1 to MAX_FLEET_HOMES homes.

    A value its number reader refuses is left to scenario_from_builder_form to report.
    Each fleet component's value_range is checked on the homes parse_scenario generates, by
    _scenario_reader_errors, so a fixed value and a drawn one are bounded alike.
    """
    if _home_count_allowed(_readable(fields, "n_homes", as_whole_number)):
        return []
    fleet_size = page_limits().fleet_size
    return [f"Number of homes must be between {fleet_size.low} and {fleet_size.high:,}."]


def _home_count_allowed(n_homes: Optional[float]) -> bool:
    """Whether the dashboard allows *n_homes*: absent, or within page_limits().fleet_size, 1 to MAX_FLEET_HOMES."""
    return n_homes is None or page_limits().fleet_size.admits(n_homes)


def _readable(
    fields: Mapping[str, Any], key: str, as_number: Callable[[Any, str], float]
) -> Optional[float]:
    """The form's *key* as *as_number* reads it; None when the form leaves it out or it does not read."""
    if key not in fields:
        return None
    try:
        return as_number(fields[key], key)
    except ConfigurationError:
        return None


def _scenario_reader_errors(document: Mapping[str, Any]) -> list[str]:
    """Why config.parse_scenario refuses *document*, judged in memory, as builder_form_errors lists the reader's reasons.

    An accepted document has its homes' value_range reasons alone.  One the reader refuses,
    with a ConfigurationError, has the reasons _fleet_reasons_beside gives beside the
    refusal.  Any other ValueError is a probable defect, not a refusal of one block, so it is
    the one reason, which refusal_text logs once, and the reader is not asked again.
    Anything else the reader raises is a defect, not a refusal, so it propagates.
    """
    try:
        scenario = parse_scenario(document)
    except ConfigurationError as refusal:
        return _fleet_reasons_beside(document, str(refusal))
    except ValueError as defect:
        return [refusal_text(defect)]
    return _range_errors(scenario)


def _fleet_reasons_beside(document: Mapping[str, Any], refusal: str) -> list[str]:
    """The reasons for *document*, which parse_scenario refused with *refusal*: its fleet's, read with the period: and seg: blocks left null, then *refusal*.

    The reader reads a null period as the default window and a null seg as no rate.  A
    refused location, tariff or fleet_distribution in that read is the one reason.  An
    accepted read gives its homes' value_range reasons, then *refusal*, which can then only
    be the reader's first refusal of the period or SEG rate, the blocks it reads before the
    homes: the period's when both are refused.
    """
    try:
        fleet = parse_scenario({**document, "period": None, "seg": None})
    except ValueError as refusal:
        return [refusal_text(refusal)]
    return [*_range_errors(fleet), refusal]


def _range_errors(scenario: ScenarioConfig) -> list[str]:
    """refuse_homes_outside_ranges' refusal of *scenario*'s homes, a value outside a fleet component's value_range; none when it accepts them."""
    try:
        refuse_homes_outside_ranges(scenario.simulated_homes())
    except ConfigurationError as exc:
        return [str(exc)]
    return []


def _location_block(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The location: block for the form's location_preset: a key of location.LOCATION_PRESETS, or 'custom'.

    A custom block holds the coordinates the form gives, as numbers, and leaves out each
    one the form leaves out; scenario_blocks.parse_location_block reads it as any location: block.

    Raises:
        ConfigurationError: for any other preset, naming it, or for a custom coordinate that is
            not a finite number.
    """
    preset = fields["location_preset"]
    if preset == "custom":
        return _present_numbers(fields, _CUSTOM_LOCATION_FORM_KEYS)
    if isinstance(preset, str) and preset in LOCATION_PRESETS:
        return location_block(LOCATION_PRESETS[preset])
    raise ConfigurationError(
        f"location_preset must be 'custom' or one of "
        f"{', '.join(map(repr, LOCATION_PRESETS))}, got {preset!r}"
    )


def _fleet_distribution_block(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet_distribution: block: the number of homes and the seed, then each component block the form sends, as sent."""
    block: dict[str, Any] = {
        key: as_whole_number(fields[key], key) for key in ("n_homes", "seed") if key in fields
    }
    block.update({key: fields[key] for key in FLEET_COMPONENTS if key in fields})
    return block


def _optional_number(fields: Mapping[str, Any], form_key: str) -> Optional[float]:
    """The form's *form_key* as a number; None when the form leaves it out."""
    return as_finite_float(fields[form_key], form_key) if form_key in fields else None


def _present_numbers(fields: Mapping[str, Any], form_keys: Mapping[str, str]) -> dict[str, float]:
    """Each grammar key of *form_keys* whose form field the form gives, with that field as a number."""
    return {
        grammar_key: as_finite_float(fields[form_key], form_key)
        for grammar_key, form_key in form_keys.items()
        if form_key in fields
    }


_PAGE = "builder"

#: The seg keys the builder form holds: a rate, its seg_rate_pence_per_kwh.
_HELD_SEG_KEYS = frozenset({"rate_pence_per_kwh"})

#: The tariff type the builder form holds, with a reader for its one setting, the import_rate.
_FORM_TARIFF_SETTINGS: Mapping[str, Mapping[str, SettingReader]] = MappingProxyType({
    "flat_rate": {"rate_per_kwh": required(_PAGE)},
})


def builder_form_from_scenario(document: object) -> ImportedForm:
    """The builder form the fleet scenario *document* describes, naming the settings of it the form has no control for, by docs/web-ui-design.md's *Scenario import policy*.

    Raises:
        ConfigurationError: For a document that is not a fleet_distribution scenario, a period
            date that is not a day, or a setting the form needs but cannot hold exactly, naming it.
        ConfigurationError: From read_fleet_scenario or refuse_a_fleet_the_dashboard_cannot_run,
            for a scenario or fleet each refuses; or, for a loaded form builder_form_errors
            refuses for any reason but a missing name, those reasons joined by '; '.
    """
    scenario = fleet_scenario_document(document, _PAGE)
    period = read_period(scenario.get("period"), _PAGE)
    read = read_fleet_scenario(scenario)
    refuse_a_fleet_the_dashboard_cannot_run(read.fleet, "fleet_distribution")
    form, unheld = read_blocks(
        scenario,
        "",
        {
            "name": read_as_given("name", scenario.get("name")),
            "description": read_as_given("description", scenario.get("description")),
            "period": _read_period(period or page_limits().default_window),
            "location": _read_location(scenario.get("location"), read.location),
            "fleet_distribution": read_fleet_distribution(scenario["fleet_distribution"], read.fleet, _read_battery),
            "tariff": _read_tariff(scenario.get("tariff")),
            "seg": _read_seg(scenario.get("seg")),
        },
    )
    reasons = _errors_but_the_name(form)
    if reasons:
        raise ConfigurationError("; ".join(reasons))
    return ImportedForm(form=form, not_loaded=unheld)


def builder_form_from_yaml(yaml_text: str) -> ImportedForm:
    """The builder form the fleet scenario YAML *yaml_text* describes, as :func:`builder_form_from_scenario` reads its document.

    Raises:
        ConfigurationError: For text that does not parse as YAML, "Invalid YAML: " and the parser's error.
        ConfigurationError: As builder_form_from_scenario.
    """
    return builder_form_from_scenario(scenario_yaml_document(yaml_text))


def builder_form_from_saved_preset(name: str, config: Mapping[str, Any]) -> ImportedForm:
    """The builder form the saved fleet preset *name*, whose stored config is *config*, describes, as :func:`builder_form_from_scenario` reads its document.

    The builder saves the scenario document its form describes, which always holds a
    fleet_distribution block; neither of the builder's former form formats holds one.

    Raises:
        ConfigurationError: For a config with no fleet_distribution key, naming the preset as
            saved in the builder's former form format; or as builder_form_from_scenario.
    """
    if "fleet_distribution" not in config:
        raise ConfigurationError(
            f"Saved preset {name!r} was saved in the builder's former form format and must be saved again"
        )
    return builder_form_from_scenario(dict(config))


def _read_period(period: tuple[date, date]) -> BlockRead:
    """The builder form's start and end dates: *period*'s days as ISO dates, the default window when the scenario sets none; read_fleet_scenario refuses any other key of the period block."""
    start, end = period
    return {"start_date": start.isoformat(), "end_date": end.isoformat()}, ()


def _read_location(block: Any, location: Location) -> BlockRead:
    """The builder form's location: the LOCATION_PRESETS key of *location*, the scenario's location as read_fleet_scenario reads it, when it is a preset's.

    Any other location loads as 'custom' with its coordinates, and each other key of the
    scenario's location: *block*, such as its timezone or name, is named not loaded.
    """
    for preset, preset_location in LOCATION_PRESETS.items():
        if location == preset_location:
            return {"location_preset": preset}, ()
    coordinates = {
        form_key: getattr(location, grammar_key) for grammar_key, form_key in _CUSTOM_LOCATION_FORM_KEYS.items()
    }
    held = dict.fromkeys(_CUSTOM_LOCATION_FORM_KEYS, ())
    return {"location_preset": "custom", **coordinates}, not_loaded(block or {}, "location", held)


def _read_battery(fleet: Mapping[str, Any], path: str, read: ComponentDistribution | None) -> BlockRead:
    """The builder form's battery capacity: the battery block of the *path* fleet block *fleet*, whose grammar reading is *read*.

    A fleet without a battery loads a null capacity, a home without a battery, since the
    builder always posts a battery block.

    Raises:
        ConfigurationError: From ComponentLimits.editor_spec, for a capacity the editor cannot hold.
    """
    limits = FLEET_COMPONENTS["battery"]
    if read is None:
        return {limits.key: {limits.grammar_key: None}}, ()
    return read_component(fleet, path, limits, read)


def _read_tariff(tariff: Any) -> BlockRead:
    """The builder form's import rate: the rate of the scenario's flat_rate tariff, none when it sets no tariff.

    Raises:
        ConfigurationError: For a tariff the form cannot hold, naming its setting.
    """
    if tariff is None:
        return {}, ()
    form_tariff, unheld = read_typed_block(tariff, "tariff", "type", _FORM_TARIFF_SETTINGS, _PAGE)
    return {"import_rate": form_tariff["rate_per_kwh"]}, unheld


def _read_seg(seg: Any) -> BlockRead:
    """The builder form's SEG rate: the scenario's seg rate, none when it sets no SEG.

    Raises:
        ConfigurationError: For a SEG preset, which the form cannot hold, naming it.
    """
    form_seg, unheld = read_seg(seg, _HELD_SEG_KEYS, _PAGE)
    if not form_seg:
        return {}, unheld
    return {"seg_rate_pence_per_kwh": form_seg["seg"]["rate_pence_per_kwh"]}, unheld
