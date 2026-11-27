# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form contract: the fleet scenario document a form describes, and why it is refused.

The builder posts the form scenario-builder.js's getFormData() builds: flat general
fields, the number of homes and the fleet page's seed, and the fleet page's pv, battery
and load blocks, each component's field the grammar's own spec.  A field the form leaves out, or sends as null
or '' (a cleared input), is left out of the block that carries it, so config.parse_scenario
reports or defaults it as it would for a hand-written scenario file.  The tariff: and
seg: blocks carry nothing but their rate, so a form without the import or SEG rate writes
that block as null: a scenario with no tariff, or no SEG.

A form is judged in one order: the dashboard's own limits, then the fleet blocks as
fleet_config.read_form_fleet reads them, naming a field at the form's own path, then the
whole document as config.parse_scenario reads it.
"""

from collections.abc import Callable, Mapping
from typing import Any, Optional

from solar_challenge.config import ScenarioConfig, parse_scenario
from solar_challenge.errors import ConfigurationError
from solar_challenge.location import LOCATION_PRESETS
from solar_challenge.number_fields import as_finite_float, as_whole_number
from solar_challenge.scenario_writer import location_block
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    page_limits,
    refuse_homes_outside_ranges,
)
from solar_challenge.web.fleet_config import read_form_fleet
from solar_challenge.web.request_boundary import (
    present_fields,
    refusal_text,
    refuse_unrecognised_keys,
    require_json_object,
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
    errors = _dashboard_limit_errors(present_fields(form))
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


def _dashboard_limit_errors(fields: Mapping[str, Any]) -> list[str]:
    """The dashboard's own rules: a scenario name, and 1 to MAX_FLEET_HOMES homes.

    A value its number reader refuses is left to scenario_from_builder_form to report.
    Each fleet component's value_range is checked on the homes parse_scenario generates, by
    _scenario_reader_errors, so a fixed value and a drawn one are bounded alike.
    """
    errors: list[str] = []
    if "name" not in fields:
        errors.append("Scenario name is required.")
    if not _home_count_allowed(_readable(fields, "n_homes", as_whole_number)):
        fleet_size = page_limits().fleet_size
        errors.append(f"Number of homes must be between {fleet_size.low} and {fleet_size.high:,}.")
    return errors


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
