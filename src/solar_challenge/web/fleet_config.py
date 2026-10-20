# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helper module for fleet configuration in the web dashboard.

Provides utilities for sampling distributions, converting form data to
fleet distribution configs and their distributions back to the form's,
writing either fleet form's distributions in config.py's grammar, and
fleet-wide overlay application for tariff/dispatch/SEG settings.
"""

from __future__ import annotations

import dataclasses
import math
import random
from collections.abc import Callable, Iterable, Mapping, Sequence
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypeGuard


from solar_challenge.home import HomeConfig
from solar_challenge.web.number_fields import (
    as_finite_float,
    as_whole_number_within,
)

if TYPE_CHECKING:
    from solar_challenge.config import DispatchStrategyConfig
    from solar_challenge.seg import SEGTariff
    from solar_challenge.tariff import TariffConfig

#: The most homes a dashboard fleet holds. The fleet forms refuse a larger fleet, a
#: shuffled pool that holds values for more homes, and a preview that draws more values.
MAX_FLEET_HOMES = 10_000


def read_fleet_size(value: Any, field: str) -> int:
    """Read *value*, the setting named *field*, as a dashboard fleet's number of homes, a whole number from 1 to :data:`MAX_FLEET_HOMES`.

    Raises:
        ValueError: From :func:`~solar_challenge.web.number_fields.as_whole_number_within`,
            naming *field* and the value sent.
    """
    return as_whole_number_within(value, field, 1, MAX_FLEET_HOMES)


#: The largest seed, positive or negative, a dashboard fleet holds: Number.MAX_SAFE_INTEGER,
#: past which the JavaScript number the fleet page holds its seed in rounds some whole numbers.
MAX_FLEET_SEED = 2**53 - 1


def read_fleet_seed(value: Any, field: str) -> int:
    """Read *value*, the setting named *field*, as a dashboard fleet's seed, a whole number from -:data:`MAX_FLEET_SEED` to :data:`MAX_FLEET_SEED`.

    Raises:
        ValueError: From :func:`~solar_challenge.web.number_fields.as_whole_number_within`,
            naming *field* and the value sent.
    """
    return as_whole_number_within(value, field, -MAX_FLEET_SEED, MAX_FLEET_SEED)


def read_pool_counts(counts: Iterable[tuple[str, Any]], pool_field: str) -> list[int]:
    """Read *counts*, each count of the *pool_field* shuffled pool with its field, as a dashboard fleet's pool counts: each a whole number from 0 to :data:`MAX_FLEET_HOMES`, totalling at most :data:`MAX_FLEET_HOMES`.

    Raises:
        ValueError: From :func:`~solar_challenge.web.number_fields.as_whole_number_within`,
            naming a count's field and the value sent; or, when the counts total more than
            MAX_FLEET_HOMES, more values than a dashboard fleet has homes to take, naming
            *pool_field* and the total.
    """
    read_counts = [
        as_whole_number_within(value, field, 0, MAX_FLEET_HOMES) for field, value in counts
    ]
    total = sum(read_counts)
    if total > MAX_FLEET_HOMES:
        raise ValueError(
            f"{pool_field} counts must total at most {MAX_FLEET_HOMES}, got {total}"
        )
    return read_counts


def apply_fleet_overlay(
    configs: list[HomeConfig],
    *,
    tariff_config: TariffConfig | None = None,
    dispatch_strategy: DispatchStrategyConfig | None = None,
    seg_tariff: SEGTariff | None = None,
) -> list[HomeConfig]:
    """Apply fleet-wide tariff, dispatch strategy, and SEG overlay to all homes.

    Uses :func:`dataclasses.replace` to produce new frozen :class:`HomeConfig`
    objects; the originals are never mutated.

    The dispatch strategy is applied only to homes that already have a
    :class:`~solar_challenge.battery.BatteryConfig` (i.e. ``battery_config is
    not None``).  Battery-less homes are left unchanged so no battery is ever
    fabricated merely to hold a dispatch strategy.

    Args:
        configs: List of :class:`~solar_challenge.home.HomeConfig` instances to
            overlay.  Must not be mutated by the caller after passing in.
        tariff_config: Optional tariff to set on every home.
        dispatch_strategy: Optional dispatch strategy to set on every home that
            has a battery.
        seg_tariff: Optional SEG tariff to set on every home.

    Returns:
        A new list of :class:`~solar_challenge.home.HomeConfig` with the overlay
        applied.  Items whose overlay is a no-op are returned as-is (same
        object, not a copy) for efficiency.
    """
    result: list[HomeConfig] = []
    for home in configs:
        replacements: dict[str, Any] = {}
        if tariff_config is not None:
            replacements["tariff_config"] = tariff_config
        if seg_tariff is not None:
            replacements["seg_tariff"] = seg_tariff
        if dispatch_strategy is not None and home.battery_config is not None:
            replacements["battery_config"] = dataclasses.replace(
                home.battery_config, dispatch_strategy=dispatch_strategy
            )
        result.append(dataclasses.replace(home, **replacements) if replacements else home)
    return result


def sample_distribution(
    dist_type: str, params: object, n_samples: object = 100
) -> list[float]:
    """Generate sample values from a distribution for preview histogram.

    Args:
        dist_type: Distribution type, sent in the field ``type``. One of the types the
            distribution editor offers: ``'normal'``, ``'uniform'``,
            ``'weighted_discrete'``, ``'shuffled_pool'``.
        params: The distribution's other keys, as the distribution editor holds them,
            read by :func:`distribution_grammar_spec` as the distribution named
            ``params``; must be a dict holding what its type is drawn from.
        n_samples: Number of samples to generate, a whole number from 1 to
            :data:`MAX_FLEET_HOMES`.

    Returns:
        List of sampled values, each a finite float.

    Raises:
        ValueError: If n_samples is not a whole number from 1 to MAX_FLEET_HOMES (see
            :func:`~solar_challenge.web.number_fields.as_whole_number_within`), params are
            not a dict (see :func:`_require_dict`), :func:`distribution_grammar_spec`
            refuses the distribution, naming type or the field under ``params``, params
            leave out what the type is drawn from (see
            :func:`_refuse_a_preview_without_what_its_type_is_drawn_from`),
            :func:`_draw_samples` cannot draw from them, or they draw a sample that is not
            a finite number, as finite params whose draws overflow a float can; that error
            names params and the sample.
    """
    n_samples = as_whole_number_within(n_samples, "n_samples", 1, MAX_FLEET_HOMES)
    params = _require_dict(params, "params")
    fields = {**_fields_under("params"), "type": "type"}
    distribution = {**params, "type": dist_type}
    spec = distribution_grammar_spec(distribution, fields)
    _refuse_a_preview_without_what_its_type_is_drawn_from(distribution, fields)
    samples = _draw_samples(spec, n_samples)
    for sample in samples:
        if not math.isfinite(sample):
            raise ValueError(
                f"params must draw samples that are finite numbers, got a sample of {sample!r}"
            )
    return samples


def _refuse_a_preview_without_what_its_type_is_drawn_from(
    distribution: Mapping[str, Any], fields: Mapping[str, str]
) -> None:
    """Refuse *distribution*, an editor distribution of a type the editor offers, when it leaves out, or sends as null, a key the preview draws its type from: the preview never runs config.py's grammar, which would name it.

    Raises:
        ValueError: Naming the first such key's field, from *fields*, and the keys the
            type is drawn from.
    """
    dist_type = distribution["type"]
    drawn_from = _EDITOR_TYPES[dist_type].drawn_from
    for key in drawn_from:
        if distribution.get(key) is None:
            raise ValueError(
                f"{fields[key]} must be given: the preview draws a {dist_type} distribution "
                f"from its {' and '.join(drawn_from)}"
            )


def _draw_samples(spec: dict[str, Any], n_samples: int) -> list[float]:
    """Draw *n_samples* values from *spec*, a distribution :func:`distribution_grammar_spec` wrote, with a fixed seed.

    Raises:
        ValueError: If its parameters are ones it cannot draw from, such as a negative std
            or a min above max.
    """
    rng = random.Random(42)
    dist_type = spec["type"]

    if dist_type == "normal":
        if spec["std"] < 0:
            raise ValueError("Standard deviation cannot be negative")
        samples = [rng.gauss(spec["mean"], spec["std"]) for _ in range(n_samples)]
        if "min" in spec:
            samples = [max(spec["min"], s) for s in samples]
        if "max" in spec:
            samples = [min(spec["max"], s) for s in samples]
        return samples

    if dist_type == "uniform":
        if spec["min"] > spec["max"]:
            raise ValueError("min cannot be greater than max")
        return [rng.uniform(spec["min"], spec["max"]) for _ in range(n_samples)]

    if dist_type == "weighted_discrete":
        if not spec["values"]:
            raise ValueError("weighted_discrete requires non-empty 'values' list")
        if sum(spec["weights"]) == 0:
            raise ValueError("Weights cannot all be zero")
        return rng.choices(spec["values"], weights=spec["weights"], k=n_samples)

    if dist_type == "shuffled_pool":
        if not spec["values"]:
            raise ValueError("shuffled_pool requires non-empty 'entries' list")
        pool: list[float] = []
        for value, count in zip(spec["values"], spec["counts"]):
            pool.extend([value] * count)
        if not pool:
            raise ValueError("shuffled_pool produced an empty pool")
        rng.shuffle(pool)
        # Cycle through pool to fill n_samples
        samples = [pool[i % len(pool)] for i in range(n_samples)]
        return samples

    raise AssertionError(
        "_draw_samples draws each type distribution_grammar_spec writes, "
        f"but has no draw for {dist_type!r}"
    )


#: The top-level keys of a fleet form that form_to_fleet_distribution_config reads.
FLEET_DISTRIBUTION_FORM_KEYS: frozenset[str] = frozenset({"n_homes", "seed", "pv", "battery", "load"})


def form_to_fleet_distribution_config(form_data: dict[str, Any]) -> dict[str, Any]:
    """Convert web form data to a fleet distribution config dict.

    The returned dict mirrors the structure of the ``fleet_distribution``
    section in scenario YAML files and can be used with
    :func:`solar_challenge.config.generate_homes_from_distribution`.

    Its pv/battery/load blocks follow the fleet form's presence rule (see
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`).  Its battery block sets
    no dispatch strategy: every battery takes the form's dispatch_strategy.

    Args:
        form_data: A fleet form, of which only the FLEET_DISTRIBUTION_FORM_KEYS are read.

    Returns:
        Fleet distribution config dict.

    Raises:
        ValueError: If n_homes is not a whole number from 1 to MAX_FLEET_HOMES (see
            :func:`read_fleet_size`), seed is not a whole number from -MAX_FLEET_SEED to
            MAX_FLEET_SEED (see :func:`read_fleet_seed`), a pv/battery/load block is
            neither null nor a dict (see :func:`_component_block`),
            a battery block sets a dispatch strategy (see
            :func:`_refuse_battery_dispatch_strategy`), or
            :func:`_parse_component_distribution` refuses a block; each refusal names its
            field as a dot path from the form's root.
    """
    config: dict[str, Any] = {
        "n_homes": read_fleet_size(form_data.get("n_homes", 100), "n_homes"),
        "seed": read_fleet_seed(form_data.get("seed", 42), "seed"),
    }

    # Process PV distribution
    pv_data = _component_block_or_empty(form_data, "pv")
    config["pv"] = _parse_component_distribution(pv_data, "pv", "capacity_kw")

    # Process Battery distribution
    battery_data = _component_block(form_data, "battery")
    if battery_data is not None:
        _refuse_battery_dispatch_strategy(battery_data)
        config["battery"] = _parse_component_distribution(battery_data, "battery", "capacity_kwh")

    # Process Load distribution
    load_data = _component_block_or_empty(form_data, "load")
    config["load"] = _parse_component_distribution(load_data, "load", "annual_consumption_kwh")

    return config


def _component_block(form_data: dict[str, Any], key: str) -> dict[str, Any] | None:
    """Return the *key* component block of *form_data*: None when it is absent or null.

    Raises:
        ValueError: If the block is neither null nor a dict (see :func:`_require_dict`).
    """
    block = form_data.get(key)
    return None if block is None else _require_dict(block, key)


def _component_block_or_empty(form_data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return the *key* component block of *form_data*, reading an absent or null block as empty.

    Raises:
        ValueError: If the block is neither null nor a dict (see :func:`_component_block`).
    """
    block = _component_block(form_data, key)
    return {} if block is None else block


def _refuse_battery_dispatch_strategy(battery: dict[str, Any]) -> None:
    """Refuse the fleet form's *battery* block when it sets a dispatch strategy: every battery takes the form's dispatch_strategy.

    config.py's grammar reads a battery block's dispatch_strategy, but the fleet form
    spells the setting once, at its root:
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form` gives the form's
    dispatch_strategy to every battery, over any the block sets.

    Raises:
        ValueError: If the block's dispatch_strategy is present and not null; the error
            names battery.dispatch_strategy, the form's dispatch_strategy and the value sent.
    """
    strategy = battery.get("dispatch_strategy")
    if strategy is not None:
        raise ValueError(
            "battery.dispatch_strategy must be absent or null: every battery takes the "
            f"fleet's dispatch_strategy, got {strategy!r}"
        )


def _require_dict(value: object, field: str) -> dict[str, Any]:
    """Return *value*, refusing one that is not a dict.

    Raises:
        ValueError: If *value* is not a dict; the error names *field* and the type sent.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping, got {type(value).__name__}")
    return value


def _parse_component_distribution(
    data: dict[str, Any], block: str, primary_field: str
) -> dict[str, Any]:
    """Return the config.py grammar block for *data*, the *block* component block of a fleet form.

    Its distribution is what *data* holds at *primary_field*: a distribution (see
    :func:`_is_distribution`), read by :func:`distribution_grammar_spec`, or a fixed value
    (see :func:`_is_fixed_value`), read by
    :func:`~solar_challenge.web.number_fields.as_finite_float`.  A mapping without a type
    passes as given, and an absent or null field as an empty mapping, for config.py's
    grammar to refuse.  The block's other settings are read by :func:`_other_setting`.

    Args:
        data: Component form data dict.
        block: The block's name in the form, ``pv``, ``battery`` or ``load``.
        primary_field: Name of the primary distribution field.

    Returns:
        Component distribution config dict.

    Raises:
        ValueError: If *data* is itself a distribution (see
            :func:`_refuse_block_that_is_a_distribution`), or one of those readers refuses
            what it reads; the error names its field as a dot path under *block*.
    """
    _refuse_block_that_is_a_distribution(data, block, primary_field)
    result: dict[str, Any] = {}
    spec = data.get(primary_field)

    if _is_distribution(spec):
        result[primary_field] = distribution_grammar_spec(
            spec, _fields_under(f"{block}.{primary_field}")
        )
    elif _is_fixed_value(spec):
        result[primary_field] = as_finite_float(spec, f"{block}.{primary_field}")
    else:
        result[primary_field] = {} if spec is None else spec

    for key, value in data.items():
        if key != primary_field:
            result[key] = _other_setting(value, f"{block}.{key}")

    return result


def _refuse_block_that_is_a_distribution(
    data: dict[str, Any], block: str, primary_field: str
) -> None:
    """Refuse *data*, the fleet form's *block* component block, when it is itself a distribution: a block holds its distribution in *primary_field*.

    Raises:
        ValueError: If *data* is a distribution (see :func:`_is_distribution`), whatever
            else it holds; the error names ``block.type``, ``block.primary_field`` and the
            type sent.
    """
    if _is_distribution(data):
        raise ValueError(
            f"{block}.type must be absent: the {block} block's distribution goes in "
            f"{block}.{primary_field}, got {data['type']!r}"
        )


def _other_setting(value: object, field: str) -> object:
    """Return *value*, a block setting other than its distribution, as it is passed to config.py's grammar.

    A distribution (see :func:`_is_distribution`) is read as the block's own is, by
    :func:`distribution_grammar_spec`.  Null, booleans (flags such as load.use_stochastic)
    and any other mapping (a block such as battery.grid_charging) pass as given, for
    config.py's grammar to read or refuse; any other value is read as a number, named
    *field*.

    Raises:
        ValueError: If :func:`distribution_grammar_spec` or
            :func:`~solar_challenge.web.number_fields.as_finite_float` refuses *value*; the
            error names its field under *field* and what was sent.
    """
    if _is_distribution(value):
        return distribution_grammar_spec(value, _fields_under(field))
    if value is None or isinstance(value, (bool, dict)):
        return value
    return as_finite_float(value, field)


def _is_distribution(value: object) -> TypeGuard[dict[str, Any]]:
    """Whether *value* is a fleet form distribution: a mapping with a type."""
    return isinstance(value, dict) and "type" in value


def _is_fixed_value(value: object) -> bool:
    """Whether *value* is a fleet form block's fixed value: any value but null or a mapping."""
    return value is not None and not isinstance(value, dict)


@dataclasses.dataclass(frozen=True)
class _EditorRows:
    """An editor distribution's *key* rows, each a mapping of a value and its *column*, which config.py's grammar spells as parallel lists: values, and the *grammar_key* list *read_column* reads."""

    key: str
    column: str
    grammar_key: str
    #: Reads the column whole, from its (field, value sent) cells and the rows' field, so
    #: its rule may bound each cell or the column's total.
    read_column: Callable[[list[tuple[str, Any]], str], Sequence[float]]


@dataclasses.dataclass(frozen=True)
class _EditorType:
    """A distribution type the distribution editor offers: its scalar parameters, the editor keys the preview draws it from, and its rows, if it has rows."""

    parameters: tuple[str, ...]
    #: The editor keys the preview draws the type from: the forms leave a missing one for
    #: config.py's grammar to name, and only the preview, which never runs the grammar,
    #: refuses it.
    drawn_from: tuple[str, ...]
    rows: _EditorRows | None = None


def _finite_floats(cells: Iterable[tuple[str, Any]]) -> list[float]:
    """Each of *cells*, a row's cell with its field, read by as_finite_float under that field."""
    return [as_finite_float(value, field) for field, value in cells]


#: The distribution types the fleet pages' distribution editor holds besides a fixed value.
_EDITOR_TYPES: Mapping[str, _EditorType] = MappingProxyType({
    "normal": _EditorType(parameters=("mean", "std", "min", "max"), drawn_from=("mean", "std")),
    "uniform": _EditorType(parameters=("min", "max"), drawn_from=("min", "max")),
    "weighted_discrete": _EditorType(
        parameters=(),
        drawn_from=("values",),
        rows=_EditorRows(
            "values", "weight", "weights", lambda cells, _rows_field: _finite_floats(cells)
        ),
    ),
    "shuffled_pool": _EditorType(
        parameters=(),
        drawn_from=("entries",),
        rows=_EditorRows("entries", "count", "counts", read_pool_counts),
    ),
})


def _editor_type(dist_type: object) -> _EditorType | None:
    """The distribution editor's record of *dist_type*; None for a type the editor does not offer, or one that is not a string."""
    return _EDITOR_TYPES.get(dist_type) if isinstance(dist_type, str) else None


#: The keys of a distribution as the distribution editor holds it: the keys a form's
#: *fields* map for :func:`distribution_grammar_spec`.
DISTRIBUTION_KEYS = ("type", "mean", "std", "min", "max", "values", "entries")


def _fields_under(path: str) -> dict[str, str]:
    """Each key of an editor distribution, mapped to its field in the distribution at *path*: ``path.key``."""
    return {key: f"{path}.{key}" for key in DISTRIBUTION_KEYS}


def distribution_grammar_spec(
    distribution: Mapping[str, Any], fields: Mapping[str, str]
) -> dict[str, Any]:
    """config.py's grammar spec of *distribution*, a distribution as the distribution editor holds it; :func:`distribution_form_spec` reads such a spec back.

    *fields* maps each of its keys to the field a form sends it in, which every refusal
    names.  A key the distribution leaves out, or sends as null, is left out of the spec,
    for config.py's grammar to name; a key its type does not read is ignored.

    Raises:
        ValueError: For a type the editor does not offer, a parameter
            :func:`~solar_challenge.web.number_fields.as_finite_float` refuses, or rows
            :func:`_rows_spec` refuses; each error names its field.
    """
    dist_type = distribution.get("type")
    editor_type = _editor_type(dist_type)
    if editor_type is None:
        raise ValueError(
            f"{fields['type']} must be one of {', '.join(_EDITOR_TYPES)}, got {dist_type!r}"
        )
    spec: dict[str, Any] = {"type": dist_type}
    for key in editor_type.parameters:
        if distribution.get(key) is not None:
            spec[key] = as_finite_float(distribution[key], fields[key])
    if editor_type.rows is not None:
        spec.update(_rows_spec(distribution, fields, editor_type.rows))
    return spec


def _rows_spec(
    distribution: Mapping[str, Any], fields: Mapping[str, str], rows: _EditorRows
) -> dict[str, list[float]]:
    """The values list and the *rows* column list of *distribution*'s rows, as config.py's grammar spells them; neither when it leaves its rows out or sends them as null.

    Each value is read by as_finite_float, and the column by the rows' read_column, each
    cell under its field, ``<rows field>[index].<column>``.

    Raises:
        ValueError: Naming the rows' field from *fields*, with a row's index, for rows that
            are not a list, a row that is not a mapping or lacks its value or its column, or
            a value that is not a finite number; or the read_column's refusal.
    """
    rows_field = fields[rows.key]
    sent_rows = distribution.get(rows.key)
    if sent_rows is None:
        return {}
    if not isinstance(sent_rows, list):
        raise ValueError(f"{rows_field} must be a list, got {type(sent_rows).__name__}")
    values: list[float] = []
    cells: list[tuple[str, Any]] = []
    for index, sent_row in enumerate(sent_rows):
        row_field = f"{rows_field}[{index}]"
        row = _require_dict(sent_row, row_field)
        if not {"value", rows.column} <= row.keys():
            raise ValueError(
                f"{row_field} must be a mapping with 'value' and {rows.column!r}, got {row!r}"
            )
        values.append(as_finite_float(row["value"], f"{row_field}.value"))
        cells.append((f"{row_field}.{rows.column}", row[rows.column]))
    return {"values": values, rows.grammar_key: list(rows.read_column(cells, rows_field))}


def distribution_form_spec(spec: object, path: str) -> float | dict[str, Any]:
    """The fleet form's distribution for the config.py grammar *spec* at *path*: the inverse of the form's conversion of a block's distribution (see :func:`_parse_component_distribution`).

    *spec* is one the grammar accepts.  The form's distribution is the editor's: a fixed
    value, which the grammar spells as a number or as a fixed distribution, and which the
    form holds as its number; a normal with both clamps; a uniform; or weighted_discrete
    or shuffled_pool rows.  A shuffled_pool's counts are read by :func:`read_pool_counts`,
    and any other number by :func:`~solar_challenge.web.number_fields.as_finite_float`, as
    the form's conversion reads them.

    Raises:
        ValueError: For a *spec* the editor cannot hold, naming *path*: an absent
            distribution, a type the editor has no form for, a normal without both clamps,
            a value that is not a finite number, a boolean included, or shuffled_pool
            counts :func:`read_pool_counts` refuses.
    """
    if _is_fixed_value(spec):
        return as_finite_float(spec, path)
    if _is_distribution(spec) and spec["type"] == "fixed":
        return as_finite_float(spec.get("value"), f"{path}.value")
    if not _is_distribution(spec) or _editor_type(spec["type"]) is None:
        raise ValueError(
            f"{path} must be a fixed value or one of the fleet page's distributions "
            f"({', '.join(_EDITOR_TYPES)}), got {spec!r}"
        )
    dist_type = spec["type"]
    if dist_type == "normal":
        return {"type": dist_type, **_form_numbers(spec, path, ("mean", "std", "min", "max"))}
    if dist_type == "uniform":
        return {"type": dist_type, **_form_numbers(spec, path, ("min", "max"))}
    values = _form_number_list(spec["values"], f"{path}.values")
    if dist_type == "weighted_discrete":
        weights = _form_number_list(spec["weights"], f"{path}.weights")
        return {
            "type": dist_type,
            "values": [{"value": value, "weight": weight} for value, weight in zip(values, weights)],
        }
    counts = read_pool_counts(
        [(f"{path}.counts[{index}]", count) for index, count in enumerate(spec["counts"])],
        path,
    )
    return {
        "type": dist_type,
        "entries": [{"value": value, "count": count} for value, count in zip(values, counts)],
    }


def _form_numbers(spec: Mapping[str, Any], path: str, keys: Iterable[str]) -> dict[str, float]:
    """The *keys* of the *path* distribution *spec*, each read by :func:`~solar_challenge.web.number_fields.as_finite_float`, a missing one as None."""
    return {key: as_finite_float(spec.get(key), f"{path}.{key}") for key in keys}


def _form_number_list(numbers: Iterable[Any], path: str) -> list[float]:
    """Each of *numbers*, the *path* list, read by :func:`~solar_challenge.web.number_fields.as_finite_float`."""
    return [as_finite_float(number, f"{path}[{index}]") for index, number in enumerate(numbers)]

