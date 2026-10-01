# SPDX-License-Identifier: AGPL-3.0-or-later
"""The scenario builder's form contract: the fleet scenario document a form describes, and why it is refused.

The builder posts one flat form, the one scenario-builder.js's getFormData() builds.
A field the form leaves out, or sends as null or '' (a cleared input), is left out
of the block that carries it, so the loaders report or default it as they would
for a hand-written scenario file.
"""

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, NamedTuple, Optional

from solar_challenge.config import (
    ConfigurationError,
    SimulationPeriod,
    load_fleet_config,
    parse_seg_rate,
)
from solar_challenge.location import Location
from solar_challenge.scenario_writer import location_block, scenario_yaml
from solar_challenge.web.shared import LOCATION_PRESETS

_MAX_HOMES = 10_000


class _Component(NamedTuple):
    """A fleet component the builder distributes: its form keys, and where its spec goes in the grammar."""

    prefix: str
    fixed_field: str
    block: str
    grammar_key: str


def _prefixed(prefix: str, *keys: str) -> dict[str, str]:
    """Each of *keys*, mapped to the form field that carries it for the component with *prefix*."""
    return {key: f"{prefix}_{key}" for key in keys}


_COMPONENTS = (
    _Component("pv", "pv_capacity_kw", "pv", "capacity_kw"),
    _Component("battery", "battery_capacity_kwh", "battery", "capacity_kwh"),
    _Component("load", "annual_consumption_kwh", "load", "annual_consumption_kwh"),
)

_DISTRIBUTION_FIELDS = (
    "distribution_type",
    "mean",
    "std",
    "min",
    "max",
    "wd_values",
    "sp_entries",
)

_CUSTOM_COORDINATES = ("latitude", "longitude", "altitude")

_RECOGNISED_KEYS = frozenset(
    {
        "name",
        "description",
        "start_date",
        "end_date",
        "location_preset",
        *_CUSTOM_COORDINATES,
        "n_homes",
        "import_rate",
        "seg_rate_pence_per_kwh",
    }
    | {component.fixed_field for component in _COMPONENTS}
    | {
        form_key
        for component in _COMPONENTS
        for form_key in _prefixed(component.prefix, *_DISTRIBUTION_FIELDS).values()
    }
)


def scenario_from_builder_form(form: object) -> dict[str, Any]:
    """The fleet scenario document the builder *form* describes.

    Raises:
        ValueError: naming the form field at fault, for a form that is not an object, a
            key the builder does not send, a value that is not the number it should be,
            an unknown location preset or distribution type, or a malformed distribution row.
    """
    if not isinstance(form, Mapping):
        raise ValueError(f"Builder form must be a JSON object, got {type(form).__name__}")
    _refuse_unrecognised_keys(form)
    fields = _present_fields(form)

    document: dict[str, Any] = {
        key: str(fields[key]) for key in ("name", "description") if key in fields
    }
    document["period"] = {
        key: str(fields[key]) for key in ("start_date", "end_date") if key in fields
    }
    if "location_preset" in fields:
        document["location"] = location_block(_location(fields))
    document["fleet_distribution"] = _fleet_distribution_block(fields)
    document["tariff"] = {
        "type": "flat_rate",
        **_present_numbers(fields, {"rate_per_kwh": "import_rate"}),
    }
    document["seg"] = _present_numbers(
        fields, {"rate_pence_per_kwh": "seg_rate_pence_per_kwh"}
    )
    return document


def builder_form_errors(form: object) -> list[str]:
    """Every reason the dashboard refuses the builder *form*; none for a scenario it accepts.

    The dashboard's own limits come first.  Then the form becomes its scenario, and,
    unless its number of homes is out of bounds, the scenario readers judge the YAML
    text the builder previews: load_fleet_config, the seg: reader and the period's dates.
    """
    fields = _present_fields(form) if isinstance(form, Mapping) else {}
    errors = _dashboard_limit_errors(fields)
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
    """The dashboard's own rules: a scenario name, 1 to 10,000 homes, and a fixed PV size of 0.5-20 kW.

    A value that does not read as a number is left to scenario_from_builder_form to report.
    """
    errors: list[str] = []
    if "name" not in fields:
        errors.append("Scenario name is required.")
    if not _home_count_allowed(_readable(fields, "n_homes", _as_count)):
        errors.append("Number of homes must be between 1 and 10,000.")
    pv_capacity_kw = _readable(fields, "pv_capacity_kw", _as_float)
    if pv_capacity_kw is not None and not 0.5 <= pv_capacity_kw <= 20.0:
        errors.append("PV capacity must be between 0.5 and 20 kW.")
    return errors


def _home_count_allowed(n_homes: Optional[float]) -> bool:
    """Whether the dashboard allows *n_homes*: absent, or within 1 to 10,000."""
    return n_homes is None or 1 <= n_homes <= _MAX_HOMES


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


def _refuse_unrecognised_keys(form: Mapping[str, Any]) -> None:
    unrecognised = sorted(form.keys() - _RECOGNISED_KEYS)
    if unrecognised:
        raise ValueError(
            f"Unrecognised builder form keys: {', '.join(map(repr, unrecognised))}; "
            f"recognised keys: {', '.join(sorted(_RECOGNISED_KEYS))}"
        )


def _location(fields: Mapping[str, Any]) -> Location:
    """The location the form's location_preset names: a dashboard preset, or 'custom' for the form's coordinates.

    Raises:
        ValueError: for any other preset, naming it, or for custom coordinates that are
            missing, not numbers, or out of range.
    """
    preset = fields["location_preset"]
    if preset == "custom":
        missing = [key for key in _CUSTOM_COORDINATES if key not in fields]
        if missing:
            raise ValueError(f"A custom location needs {', '.join(missing)}")
        latitude, longitude, altitude = (
            _as_float(fields[key], key) for key in _CUSTOM_COORDINATES
        )
        return Location(latitude=latitude, longitude=longitude, altitude=altitude)
    if isinstance(preset, str) and preset in LOCATION_PRESETS:
        return LOCATION_PRESETS[preset]
    raise ValueError(
        f"location_preset must be 'custom' or one of "
        f"{', '.join(map(repr, LOCATION_PRESETS))}, got {preset!r}"
    )


def _fleet_distribution_block(fields: Mapping[str, Any]) -> dict[str, Any]:
    """The fleet_distribution: block: the number of homes, then each component's block."""
    block: dict[str, Any] = {}
    if "n_homes" in fields:
        block["n_homes"] = _as_count(fields["n_homes"], "n_homes")
    for component in _COMPONENTS:
        block[component.block] = _component_block(fields, component)
    return block


def _component_block(fields: Mapping[str, Any], component: _Component) -> dict[str, Any]:
    """*component*'s block: the distribution the form sets a type for, else the form's fixed value."""
    form_keys = _prefixed(component.prefix, *_DISTRIBUTION_FIELDS)
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
        parameters = _row_lists(fields, form_keys["wd_values"], "weight", "weights", _as_float)
    elif distribution_type == "shuffled_pool":
        parameters = _row_lists(fields, form_keys["sp_entries"], "count", "counts", _as_count)
    else:
        raise ValueError(
            f"{type_field} must be one of normal, uniform, weighted_discrete or "
            f"shuffled_pool, got {distribution_type!r}"
        )
    return {"type": distribution_type, **parameters}


def _present_numbers(fields: Mapping[str, Any], form_keys: Mapping[str, str]) -> dict[str, float]:
    """Each grammar key of *form_keys* whose form field the form gives, with that field as a number."""
    return {
        grammar_key: _as_float(fields[form_key], form_key)
        for grammar_key, form_key in form_keys.items()
        if form_key in fields
    }


def _row_lists(
    fields: Mapping[str, Any],
    rows_field: str,
    column: str,
    grammar_key: str,
    as_number: Callable[[Any, str], float],
) -> dict[str, list[float]]:
    """The values, and the *grammar_key* list of each row's *column*, of the form's *rows_field* rows.

    Each row is an object holding a value and its *column*.  A form without the rows
    gives neither list.

    Raises:
        ValueError: naming *rows_field*, and the row's index, when the rows are not a list
            of such objects or hold something other than numbers.
    """
    if rows_field not in fields:
        return {}
    rows = fields[rows_field]
    if not isinstance(rows, list):
        raise ValueError(f"{rows_field} must be a list of rows, got {rows!r}")
    values: list[float] = []
    column_values: list[float] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping) or not {"value", column} <= row.keys():
            raise ValueError(
                f"{rows_field}[{index}] must be an object with 'value' and {column!r}, got {row!r}"
            )
        values.append(_as_float(row["value"], f"{rows_field}[{index}].value"))
        column_values.append(as_number(row[column], f"{rows_field}[{index}].{column}"))
    return {"values": values, grammar_key: column_values}


def _as_float(value: Any, field: str) -> float:
    """*value*, the form's *field*, as a number.

    Raises:
        ValueError: naming *field*, when *value* is not a number.
    """
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{field} must be a number, got {value!r}") from exc


def _as_count(value: Any, field: str) -> int:
    """*value*, the form's *field*, as a whole number.

    Raises:
        ValueError: naming *field*, when *value* is not a whole number.
    """
    number = _as_float(value, field)
    if not number.is_integer():
        raise ValueError(f"{field} must be a whole number, got {value!r}")
    return int(number)
