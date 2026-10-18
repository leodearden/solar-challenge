# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form contract: the fleet scenario document a form describes, and why it is refused.

The builder posts one flat form, the one scenario-builder.js's getFormData() builds.
A field the form leaves out, or sends as null or '' (a cleared input), is left out
of the block that carries it, so the loaders report or default it as they would
for a hand-written scenario file.  The tariff: and seg: blocks carry nothing but
their rate, so a form without the import or SEG rate writes that block as null:
a scenario with no tariff, or no SEG.
"""

import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any, Optional

from solar_challenge.config import (
    SimulationPeriod,
    load_fleet_config,
    parse_seg_rate,
)
from solar_challenge.errors import ConfigurationError
from solar_challenge.scenario_writer import location_block, scenario_yaml
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, FleetComponent
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES, read_pool_counts
from solar_challenge.web.number_fields import as_finite_float, as_whole_number
from solar_challenge.web.shared import (
    LOCATION_PRESETS,
    NotAJsonObject,
    refuse_unrecognised_keys,
    require_json_object,
)

_BUILDER_FORM = "Builder form"

#: Reads a column of distribution rows, given as (field, value sent) cells, as its numbers.
_ColumnReader = Callable[[list[tuple[str, Any]]], Sequence[float]]


def _prefixed(prefix: str, *keys: str) -> dict[str, str]:
    """Each of *keys*, mapped to the form field that carries it for the component with *prefix*."""
    return {key: f"{prefix}_{key}" for key in keys}


_DISTRIBUTION_FIELDS = (
    "distribution_type",
    "mean",
    "std",
    "min",
    "max",
    "wd_values",
    "sp_entries",
)

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
        "import_rate",
        "seg_rate_pence_per_kwh",
    }
    | {component.fixed_field for component in FLEET_COMPONENTS.values()}
    | {
        form_key
        for component in FLEET_COMPONENTS.values()
        for form_key in _prefixed(component.key, *_DISTRIBUTION_FIELDS).values()
    }
)


def scenario_from_builder_form(form: object) -> dict[str, Any]:
    """The fleet scenario document the builder *form* describes.

    Raises:
        ValueError: naming the form field at fault, for a form that is not an object, a
            key the builder does not send, a value that is not the number it should be,
            an unknown location preset or distribution type, a malformed distribution row,
            or a shuffled pool too large for a dashboard fleet: a count outside 0 to
            MAX_FLEET_HOMES, or counts totalling more.
    """
    form = require_json_object(form, _BUILDER_FORM)
    refuse_unrecognised_keys(form, _RECOGNISED_KEYS, _BUILDER_FORM)
    fields = _present_fields(form)

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
    """Every reason the dashboard refuses the builder *form*; none for a scenario it accepts.

    A form that is not a JSON object has that one reason.  For any other, the dashboard's
    own limits come first.  Then the form becomes its scenario, and, unless its number of
    homes is out of bounds, the scenario readers judge the YAML text the builder previews:
    load_fleet_config, the seg: reader and the period's dates.
    """
    try:
        form = require_json_object(form, _BUILDER_FORM)
    except NotAJsonObject as refusal:
        return [str(refusal)]
    errors = _dashboard_limit_errors(_present_fields(form))
    try:
        document = scenario_from_builder_form(form)
    except ValueError as exc:
        return [*errors, str(exc)]
    if _home_count_allowed(document["fleet_distribution"].get("n_homes")):
        errors.extend(_scenario_reader_errors(document))
    return errors


def _present_fields(form: Mapping[str, Any]) -> dict[str, Any]:
    """The fields *form* gives: each one it neither leaves out nor sends as null or ''."""
    return {key: value for key, value in form.items() if value is not None and value != ""}


def _dashboard_limit_errors(fields: Mapping[str, Any]) -> list[str]:
    """The dashboard's own rules: a scenario name, 1 to MAX_FLEET_HOMES homes, and each fleet component's fixed value within its fixed_range.

    A value its number reader refuses is left to scenario_from_builder_form to report.
    """
    errors: list[str] = []
    if "name" not in fields:
        errors.append("Scenario name is required.")
    if not _home_count_allowed(_readable(fields, "n_homes", as_whole_number)):
        errors.append(f"Number of homes must be between 1 and {MAX_FLEET_HOMES:,}.")
    for component in FLEET_COMPONENTS.values():
        fixed_value = _readable(fields, component.fixed_field, as_finite_float)
        if fixed_value is not None and not component.admits_fixed_value(fixed_value):
            low, high = component.fixed_range
            errors.append(
                f"{component.heading} must be between {low:g} and {high:g}, "
                f"got {fields[component.fixed_field]!r}."
            )
    return errors


def _home_count_allowed(n_homes: Optional[float]) -> bool:
    """Whether the dashboard allows *n_homes*: absent, or within 1 to MAX_FLEET_HOMES."""
    return n_homes is None or 1 <= n_homes <= MAX_FLEET_HOMES


def _readable(
    fields: Mapping[str, Any], key: str, as_number: Callable[[Any, str], float]
) -> Optional[float]:
    """The form's *key* as *as_number* reads it; None when the form leaves it out or it does not read."""
    if key not in fields:
        return None
    try:
        return as_number(fields[key], key)
    except ValueError:
        return None


def _scenario_reader_errors(document: Mapping[str, Any]) -> list[str]:
    """What the scenario readers refuse in *document*, written as the YAML text the builder previews.

    load_fleet_config refuses a scenario with ConfigurationError, or with ValueError from
    a config it builds, and a shuffled pool smaller than the fleet with IndexError.
    Anything else it raises is a defect in the loader, not a refusal, so it propagates.
    """
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "scenario.yaml"
        path.write_text(scenario_yaml(document), encoding="utf-8")
        try:
            load_fleet_config(path)
        except (ConfigurationError, ValueError, IndexError) as exc:
            errors.append(str(exc))
    try:
        parse_seg_rate(document["seg"])
    except ConfigurationError as exc:
        errors.append(str(exc))
    errors.extend(_period_errors(document["period"]))
    return errors


def _period_errors(period: Mapping[str, str]) -> list[str]:
    """What keeps the period: block from giving the simulated dates: a date it lacks or one that does not parse."""
    missing = [key for key in ("start_date", "end_date") if key not in period]
    if missing:
        return [f"The period needs {' and '.join(missing)}"]
    simulation_period = SimulationPeriod(
        start_date=period["start_date"], end_date=period["end_date"]
    )
    errors: list[str] = []
    for key, timestamp in (
        ("start_date", simulation_period.get_start_timestamp),
        ("end_date", simulation_period.get_end_timestamp),
    ):
        try:
            timestamp()
        except ValueError as exc:
            errors.append(f"period.{key} is not a date: {exc}")
    return errors


def _location_block(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The location: block for the form's location_preset: a dashboard preset, or 'custom'.

    A custom block holds the coordinates the form gives, as numbers.  A coordinate the
    form leaves out is left out of the block, for the loader to default.

    Raises:
        ValueError: for any other preset, naming it, or for a custom coordinate that is
            not a finite number.
    """
    preset = fields["location_preset"]
    if preset == "custom":
        return _present_numbers(fields, _CUSTOM_LOCATION_FORM_KEYS)
    if isinstance(preset, str) and preset in LOCATION_PRESETS:
        return location_block(LOCATION_PRESETS[preset])
    raise ValueError(
        f"location_preset must be 'custom' or one of "
        f"{', '.join(map(repr, LOCATION_PRESETS))}, got {preset!r}"
    )


def _fleet_distribution_block(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet_distribution: block: the number of homes, then each component's block."""
    block: dict[str, Any] = {}
    if "n_homes" in fields:
        block["n_homes"] = as_whole_number(fields["n_homes"], "n_homes")
    for component in FLEET_COMPONENTS.values():
        block[component.key] = _component_block(fields, component)
    return block


def _component_block(fields: Mapping[str, Any], component: FleetComponent) -> dict[str, Any]:
    """*component*'s block: the distribution the form sets a type for, else the form's fixed value."""
    form_keys = _prefixed(component.key, *_DISTRIBUTION_FIELDS)
    if form_keys["distribution_type"] in fields:
        return {component.grammar_key: _distribution_spec(fields, form_keys)}
    return _present_numbers(fields, {component.grammar_key: component.fixed_field})


def _distribution_spec(fields: Mapping[str, Any], form_keys: Mapping[str, str]) -> dict[str, Any]:
    """The distribution the form's fields describe, as the grammar spells it.

    *form_keys* maps each distribution field to the form field carrying it for one component.

    Raises:
        ValueError: naming the distribution type, when the builder offers no such distribution.
    """
    type_field = form_keys["distribution_type"]
    distribution_type = fields[type_field]
    parameters: Mapping[str, Any]
    if distribution_type == "normal":
        parameters = _present_numbers(
            fields, {key: form_keys[key] for key in ("mean", "std", "min", "max")}
        )
    elif distribution_type == "uniform":
        parameters = _present_numbers(fields, {key: form_keys[key] for key in ("min", "max")})
    elif distribution_type == "weighted_discrete":
        parameters = _row_lists(
            fields, form_keys["wd_values"], "weight", "weights", _finite_floats
        )
    elif distribution_type == "shuffled_pool":
        entries_field = form_keys["sp_entries"]
        parameters = _row_lists(
            fields,
            entries_field,
            "count",
            "counts",
            lambda counts: read_pool_counts(counts, entries_field),
        )
    else:
        raise ValueError(
            f"{type_field} must be one of normal, uniform, weighted_discrete or "
            f"shuffled_pool, got {distribution_type!r}"
        )
    return {"type": distribution_type, **parameters}


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


def _row_lists(
    fields: Mapping[str, Any],
    rows_field: str,
    column: str,
    grammar_key: str,
    read_column: _ColumnReader,
) -> dict[str, list[float]]:
    """The values, and the *grammar_key* list of each row's *column*, of the form's *rows_field* rows.

    Each row is an object holding a value and its *column*.  A form without the rows
    gives neither list.  Each value is read by as_finite_float.  The column is read whole,
    by *read_column*, from each row's cell with its field, ``rows_field[index].column``,
    so its rule may bound each cell or the column's total.

    Raises:
        ValueError: naming *rows_field*, and the row's index, when the rows are not a list
            of such objects or a value is not a finite number; or *read_column*'s refusal.
    """
    if rows_field not in fields:
        return {}
    rows = fields[rows_field]
    if not isinstance(rows, list):
        raise ValueError(f"{rows_field} must be a list of rows, got {rows!r}")
    values: list[float] = []
    cells: list[tuple[str, Any]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not {"value", column} <= row.keys():
            raise ValueError(
                f"{rows_field}[{index}] must be an object with 'value' and {column!r}, got {row!r}"
            )
        values.append(as_finite_float(row["value"], f"{rows_field}[{index}].value"))
        cells.append((f"{rows_field}[{index}].{column}", row[column]))
    return {"values": values, grammar_key: list(read_column(cells))}


def _finite_floats(cells: list[tuple[str, Any]]) -> list[float]:
    """Each of *cells*, a row's cell with its field, read by as_finite_float under that field."""
    return [as_finite_float(value, field) for field, value in cells]
