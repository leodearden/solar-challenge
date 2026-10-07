# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helper module for fleet configuration in the web dashboard.

Provides utilities for sampling distributions, converting form data to
fleet distribution configs and their distributions back to the form's,
and fleet-wide overlay application for tariff/dispatch/SEG settings.
"""

from __future__ import annotations

import dataclasses
import random
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any


from solar_challenge.home import HomeConfig
from solar_challenge.web.number_fields import as_finite_float, as_int, as_int_within

if TYPE_CHECKING:
    from solar_challenge.config import DispatchStrategyConfig
    from solar_challenge.seg import SEGTariff
    from solar_challenge.tariff import TariffConfig

#: The most homes a dashboard fleet holds. The fleet forms refuse a larger fleet, a
#: shuffled pool that holds values for more homes, and a preview that draws more values.
MAX_FLEET_HOMES = 10_000


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
        dist_type: Distribution type. One of ``'weighted_discrete'``,
            ``'normal'``, ``'uniform'``, ``'shuffled_pool'``.
        params: Distribution parameters (varies by type), read the way
            :func:`_build_distribution_dict` reads a fleet form's spec, as the
            distribution named ``params``; must be a dict.
        n_samples: Number of samples to generate, read as int() reads it; from 1
            to :data:`MAX_FLEET_HOMES`.

    Returns:
        List of sampled float values.

    Raises:
        ValueError: If dist_type is unknown or params are invalid, params are
            not a dict (see :func:`_require_dict`), a
            weighted_discrete/shuffled_pool row list is malformed (see
            :func:`_named_rows`), n_samples is one int() cannot read or outside
            1 to MAX_FLEET_HOMES (see
            :func:`~solar_challenge.web.number_fields.as_int_within`), a shuffled_pool
            count is one int() cannot read or outside 0 to MAX_FLEET_HOMES, or
            the counts total more than that (see :func:`_pool_counts`), or a number
            is one :func:`~solar_challenge.web.number_fields.as_finite_float` refuses;
            a row, count or number refusal names its field under ``params``, such as
            ``params.entries[0].count`` or ``params.mean``.
    """
    n_samples = as_int_within(n_samples, "n_samples", 1, MAX_FLEET_HOMES)
    params = _require_dict(params, "params")
    spec = _build_distribution_dict({**params, "type": dist_type}, "params")

    rng = random.Random(42)

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

    raise ValueError(f"Unknown distribution type: {dist_type}")


def form_to_fleet_distribution_config(form_data: dict[str, Any]) -> dict[str, Any]:
    """Convert web form data to a fleet distribution config dict.

    The returned dict mirrors the structure of the ``fleet_distribution``
    section in scenario YAML files and can be used with
    :func:`solar_challenge.config.generate_homes_from_distribution`.

    Its pv/battery/load blocks follow the fleet form's presence rule (see
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`).

    Args:
        form_data: Form data dict from the web UI.

    Returns:
        Fleet distribution config dict.

    Raises:
        ValueError: If required fields are missing or invalid, n_homes is one
            int() cannot read or outside 1 to MAX_FLEET_HOMES (see
            :func:`~solar_challenge.web.number_fields.as_int_within`), seed is one
            int() cannot read (see :func:`~solar_challenge.web.number_fields.as_int`),
            a pv/battery/load block is neither null nor a dict (see
            :func:`_component_block`), a weighted_discrete/shuffled_pool
            row list is malformed (see :func:`_named_rows`), a shuffled_pool
            count is one int() cannot read or outside 0 to MAX_FLEET_HOMES, or
            the counts total more than that (see :func:`_pool_counts`), a
            distribution number is one
            :func:`~solar_challenge.web.number_fields.as_finite_float` refuses, or a
            block's other setting is one it refuses (see :func:`_other_setting`); a row,
            count or number refusal names its field under its distribution's, such as
            ``pv.capacity_kw.entries[0].count`` or ``pv.capacity_kw.mean``, and another
            setting's names ``<block>.<key>``, such as ``pv.tilt``.
    """
    config: dict[str, Any] = {
        "n_homes": as_int_within(form_data.get("n_homes", 100), "n_homes", 1, MAX_FLEET_HOMES),
        "seed": as_int(form_data.get("seed", 42), "seed"),
    }

    # Process PV distribution
    pv_data = _component_block_or_empty(form_data, "pv")
    config["pv"] = _parse_component_distribution(pv_data, "pv", "capacity_kw")

    # Process Battery distribution
    battery_data = _component_block(form_data, "battery")
    if battery_data is not None and battery_data.get("enabled", True):
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


def _require_dict(value: object, field: str) -> dict[str, Any]:
    """Return *value*, refusing one that is not a dict.

    Raises:
        ValueError: If *value* is not a dict; the error names *field* and the type sent.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping, got {type(value).__name__}")
    return value


def _named_rows(
    spec: dict[str, Any], key: str, path: str
) -> list[tuple[str, dict[str, Any]]]:
    """Return each row of the *key* row list of the *path* distribution *spec* with its field, reading an absent list as empty.

    A row's field is ``path.key[index]``.

    Raises:
        ValueError: If the value is not a list (the error names ``path.key`` and the type
            sent), or a row is not a dict (see :func:`_require_dict`; the error names the
            row's field).
    """
    rows_field = f"{path}.{key}"
    rows = spec.get(key, [])
    if not isinstance(rows, list):
        raise ValueError(f"{rows_field} must be a list, got {type(rows).__name__}")
    named_rows: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(rows):
        field = f"{rows_field}[{index}]"
        named_rows.append((field, _require_dict(row, field)))
    return named_rows


def _parse_component_distribution(
    data: dict[str, Any], block: str, primary_field: str
) -> dict[str, Any]:
    """Return the config.py grammar block for *data*, the *block* component block of a fleet form.

    Its *primary_field* is the distribution *data* holds there: a mapping with a type, or a
    fixed value, which is any other value but null or a mapping, read by
    :func:`~solar_challenge.web.number_fields.as_finite_float`; else *data* itself, when it
    has a type; else *data* whole.  Its other settings, but for ``type``, ``enabled`` and
    mappings, are read by :func:`_other_setting`, each named ``block.key``.

    Args:
        data: Component form data dict.
        block: The block's name in the form, ``pv``, ``battery`` or ``load``.
        primary_field: Name of the primary distribution field.

    Returns:
        Component distribution config dict.

    Raises:
        ValueError: As :func:`_build_distribution_dict`, for the distribution at
            ``block.primary_field``, or at ``block`` when *data* itself is the distribution;
            if the fixed value there is one
            :func:`~solar_challenge.web.number_fields.as_finite_float` refuses, a boolean
            included, named ``block.primary_field``; or if :func:`_other_setting` refuses
            another setting.
    """
    result: dict[str, Any] = {}
    spec = data.get(primary_field)

    if isinstance(spec, dict) and "type" in spec:
        result[primary_field] = _build_distribution_dict(spec, f"{block}.{primary_field}")
    elif spec is not None and not isinstance(spec, dict):
        result[primary_field] = as_finite_float(spec, f"{block}.{primary_field}")
    elif "type" in data:
        result[primary_field] = _build_distribution_dict(data, block)
    else:
        result[primary_field] = data

    for key, value in data.items():
        if key not in (primary_field, "type", "enabled") and not isinstance(value, dict):
            result[key] = _other_setting(value, f"{block}.{key}")

    return result


def _other_setting(value: object, field: str) -> object:
    """Return *value*, a block setting other than its distribution, as it is passed to config.py's grammar.

    Null (the grammar's default) and booleans (flags such as load.use_stochastic) pass as
    given; any other value is read as a number, named *field*.

    Raises:
        ValueError: If :func:`~solar_challenge.web.number_fields.as_finite_float` refuses
            *value*; the error names *field* and the value sent.
    """
    if value is None or isinstance(value, bool):
        return value
    return as_finite_float(value, field)


def _build_distribution_dict(data: dict[str, Any], path: str) -> dict[str, Any]:
    """Build a standardised distribution dict from form input.

    Args:
        data: Dict with at least a ``type`` key.
        path: The distribution's field, a dot path from the request body's root, such
            as ``pv.capacity_kw`` or ``params``.

    Returns:
        Distribution specification dict.

    Raises:
        ValueError: If a weighted_discrete/shuffled_pool row list is malformed
            (see :func:`_named_rows`), a shuffled_pool count is one int() cannot
            read or outside 0 to MAX_FLEET_HOMES, or the counts total more than
            that (see :func:`_pool_counts`), or a number is one
            :func:`~solar_challenge.web.number_fields.as_finite_float` refuses (see
            :func:`_spec_number`); each error names its field under *path*.
    """
    dist_type = data["type"]
    result: dict[str, Any] = {"type": dist_type}

    if dist_type == "normal":
        result["mean"] = _spec_number(data, "mean", 0, path)
        result["std"] = _spec_number(data, "std", 1, path)
        if data.get("min") is not None:
            result["min"] = as_finite_float(data["min"], f"{path}.min")
        if data.get("max") is not None:
            result["max"] = as_finite_float(data["max"], f"{path}.max")

    elif dist_type == "uniform":
        result["min"] = _spec_number(data, "min", 0, path)
        result["max"] = _spec_number(data, "max", 1, path)

    elif dist_type == "weighted_discrete":
        rows = _named_rows(data, "values", path)
        result["values"] = [_spec_number(row, "value", 0, field) for field, row in rows]
        result["weights"] = [_spec_number(row, "weight", 1, field) for field, row in rows]

    elif dist_type == "shuffled_pool":
        rows = _named_rows(data, "entries", path)
        result["values"] = [_spec_number(row, "value", 0, field) for field, row in rows]
        result["counts"] = _pool_counts(rows, f"{path}.entries")

    return result


def _spec_number(spec: dict[str, Any], key: str, default: float, path: str) -> float:
    """Return the *key* number of *spec*, the distribution or row at *path*, *default* when absent.

    Raises:
        ValueError: If :func:`~solar_challenge.web.number_fields.as_finite_float` refuses
            it; the error names ``path.key`` and the value sent.
    """
    return as_finite_float(spec.get(key, default), f"{path}.{key}")


#: The distribution types the fleet page's distribution editor holds.
_EDITOR_DISTRIBUTION_TYPES: tuple[str, ...] = (
    "normal", "uniform", "weighted_discrete", "shuffled_pool",
)


def distribution_form_spec(spec: object, path: str) -> dict[str, Any]:
    """The fleet form's distribution for the config.py grammar *spec* at *path*: the inverse of :func:`_build_distribution_dict`.

    *spec* is one the grammar accepts.  The form's distribution is the editor's: a normal
    with both clamps, a uniform, or weighted_discrete or shuffled_pool rows, its numbers
    read as _build_distribution_dict reads them.

    Raises:
        ValueError: For a *spec* the editor cannot hold, naming *path*: a fixed value, a type
            the editor has no form for, a normal without both clamps, or a value that is not
            a finite number.
    """
    if not isinstance(spec, Mapping) or spec.get("type") not in _EDITOR_DISTRIBUTION_TYPES:
        raise ValueError(
            f"{path} must be one of the fleet page's distributions "
            f"({', '.join(_EDITOR_DISTRIBUTION_TYPES)}), got {spec!r}"
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
    counts = _form_number_list(spec["counts"], f"{path}.counts")
    return {
        "type": dist_type,
        "entries": [{"value": value, "count": int(count)} for value, count in zip(values, counts)],
    }


def _form_numbers(spec: Mapping[str, Any], path: str, keys: Iterable[str]) -> dict[str, float]:
    """The *keys* of the *path* distribution *spec*, each read by :func:`~solar_challenge.web.number_fields.as_finite_float`, a missing one as None."""
    return {key: as_finite_float(spec.get(key), f"{path}.{key}") for key in keys}


def _form_number_list(numbers: Iterable[Any], path: str) -> list[float]:
    """Each of *numbers*, the *path* list, read by :func:`~solar_challenge.web.number_fields.as_finite_float`."""
    return [as_finite_float(number, f"{path}[{index}]") for index, number in enumerate(numbers)]


def _pool_counts(rows: list[tuple[str, dict[str, Any]]], entries_field: str) -> list[int]:
    """Return the count of each shuffled_pool row in *rows*, the (field, row) pairs of the *entries_field* list, an absent count reading as 1.

    Raises:
        ValueError: If a count is one int() cannot read or outside 0 to MAX_FLEET_HOMES
            (see :func:`~solar_challenge.web.number_fields.as_int_within`; the count is
            named under its row's field), or the counts total more than MAX_FLEET_HOMES,
            more values than a dashboard fleet has homes to take; that error names
            *entries_field* and the total.
    """
    counts = [
        as_int_within(row.get("count", 1), f"{field}.count", 0, MAX_FLEET_HOMES)
        for field, row in rows
    ]
    total = sum(counts)
    if total > MAX_FLEET_HOMES:
        raise ValueError(
            f"{entries_field} counts must total at most {MAX_FLEET_HOMES}, got {total}"
        )
    return counts
