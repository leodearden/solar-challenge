# SPDX-License-Identifier: AGPL-3.0-or-later
"""Helper module for fleet configuration in the web dashboard.

Provides utilities for sampling distributions, converting form data to
fleet distribution configs, YAML import/export, and fleet-wide overlay
application for tariff/dispatch/SEG settings.
"""

from __future__ import annotations

import dataclasses
import random
from typing import TYPE_CHECKING, Any

import yaml

from solar_challenge.home import HomeConfig

if TYPE_CHECKING:
    from solar_challenge.config import DispatchStrategyConfig
    from solar_challenge.seg import SEGTariff
    from solar_challenge.tariff import TariffConfig

#: The most homes a dashboard fleet holds. The fleet forms refuse a larger fleet, a
#: shuffled-pool row that assigns its value to more homes, and a preview that draws more values.
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
    dist_type: str, params: object, n_samples: int = 100
) -> list[float]:
    """Generate sample values from a distribution for preview histogram.

    Args:
        dist_type: Distribution type. One of ``'weighted_discrete'``,
            ``'normal'``, ``'uniform'``, ``'shuffled_pool'``.
        params: Distribution parameters (varies by type), read the way
            :func:`_build_distribution_dict` reads a fleet form's spec; must be
            a dict.
        n_samples: Number of samples to generate.

    Returns:
        List of sampled float values.

    Raises:
        ValueError: If dist_type is unknown or params are invalid, params are
            not a dict (see :func:`_require_dict`), or a
            weighted_discrete/shuffled_pool row list is malformed (see
            :func:`_dict_list`).
    """
    if n_samples < 1:
        raise ValueError("n_samples must be at least 1")
    params = _require_dict(params, "params")
    spec = _build_distribution_dict({**params, "type": dist_type})

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

    Args:
        form_data: Form data dict from the web UI.

    Returns:
        Fleet distribution config dict.

    Raises:
        ValueError: If required fields are missing or invalid, a
            pv/battery/load block is not a dict (see
            :func:`_component_block`), or a weighted_discrete/shuffled_pool
            row list is malformed (see :func:`_dict_list`).
    """
    n_homes = int(form_data.get("n_homes", 100))
    if n_homes < 1:
        raise ValueError("n_homes must be at least 1")

    config: dict[str, Any] = {
        "n_homes": n_homes,
        "seed": int(form_data.get("seed", 42)),
    }

    # Process PV distribution
    pv_data = _component_block(form_data, "pv")
    config["pv"] = _parse_component_distribution(pv_data, "capacity_kw", default_field="capacity_kw")

    # Process Battery distribution
    battery_data = _component_block(form_data, "battery")
    if battery_data and battery_data.get("enabled", True):
        config["battery"] = _parse_component_distribution(
            battery_data, "capacity_kwh", default_field="capacity_kwh"
        )

    # Process Load distribution
    load_data = _component_block(form_data, "load")
    config["load"] = _parse_component_distribution(
        load_data, "annual_consumption_kwh", default_field="annual_consumption_kwh"
    )

    return config


def _component_block(form_data: dict[str, Any], key: str) -> dict[str, Any]:
    """Return the *key* component block of *form_data*, reading an absent or falsy block as empty.

    Raises:
        ValueError: If the block is truthy but not a dict (see :func:`_require_dict`).
    """
    return _require_dict(form_data.get(key) or {}, key)


def _require_dict(value: object, field: str) -> dict[str, Any]:
    """Return *value*, refusing one that is not a dict.

    Raises:
        ValueError: If *value* is not a dict; the error names *field* and the type sent.
    """
    if not isinstance(value, dict):
        raise ValueError(f"{field} must be a mapping, got {type(value).__name__}")
    return value


def _dict_list(spec: dict[str, Any], key: str) -> list[dict[str, Any]]:
    """Return the *key* row list of *spec*, reading an absent list as empty.

    Raises:
        ValueError: If the value is not a list (the error names *key* and the type sent),
            or a row is not a dict (see :func:`_require_dict`; the row is named ``key[index]``).
    """
    rows = spec.get(key, [])
    if not isinstance(rows, list):
        raise ValueError(f"{key} must be a list, got {type(rows).__name__}")
    return [_require_dict(row, f"{key}[{index}]") for index, row in enumerate(rows)]


def _parse_component_distribution(
    data: dict[str, Any], primary_field: str, default_field: str = ""
) -> dict[str, Any]:
    """Parse a component distribution section from form data.

    Args:
        data: Component form data dict.
        primary_field: Name of the primary distribution field.
        default_field: Unused (kept for API consistency).

    Returns:
        Component distribution config dict.
    """
    result: dict[str, Any] = {}
    dist_data = data.get(primary_field, data)

    if isinstance(dist_data, dict) and "type" in dist_data:
        result[primary_field] = _build_distribution_dict(dist_data)
    elif isinstance(dist_data, (int, float)):
        result[primary_field] = float(dist_data)
    else:
        # Try to treat the whole data dict as the distribution
        if "type" in data:
            result[primary_field] = _build_distribution_dict(data)
        else:
            result[primary_field] = data

    # Copy through extra scalar fields (azimuth, tilt, etc.)
    for key, value in data.items():
        if key not in (primary_field, "type", "enabled") and not isinstance(value, dict):
            try:
                result[key] = float(value)
            except (ValueError, TypeError):
                result[key] = value

    return result


def _build_distribution_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Build a standardised distribution dict from form input.

    Args:
        data: Dict with at least a ``type`` key.

    Returns:
        Distribution specification dict.

    Raises:
        ValueError: If a weighted_discrete/shuffled_pool row list is malformed
            (see :func:`_dict_list`).
    """
    dist_type = data["type"]
    result: dict[str, Any] = {"type": dist_type}

    if dist_type == "normal":
        result["mean"] = float(data.get("mean", 0))
        result["std"] = float(data.get("std", 1))
        if data.get("min") is not None:
            result["min"] = float(data["min"])
        if data.get("max") is not None:
            result["max"] = float(data["max"])

    elif dist_type == "uniform":
        result["min"] = float(data.get("min", 0))
        result["max"] = float(data.get("max", 1))

    elif dist_type == "weighted_discrete":
        values_raw = _dict_list(data, "values")
        result["values"] = [float(v.get("value", 0)) for v in values_raw]
        result["weights"] = [float(v.get("weight", 1)) for v in values_raw]

    elif dist_type == "shuffled_pool":
        entries = _dict_list(data, "entries")
        result["values"] = [float(e.get("value", 0)) for e in entries]
        result["counts"] = [int(e.get("count", 1)) for e in entries]

    return result


def fleet_distribution_to_yaml(config: dict[str, Any]) -> str:
    """Convert a fleet distribution config dict to a YAML string.

    Args:
        config: Fleet distribution config dict (as returned by
            :func:`form_to_fleet_distribution_config` or parsed from UI).

    Returns:
        YAML-formatted string.
    """
    # Build a clean scenario structure
    scenario: dict[str, Any] = {
        "name": config.get("name", "Fleet Configuration"),
        "fleet_distribution": {
            "n_homes": config.get("n_homes", 100),
            "seed": config.get("seed", 42),
        },
    }

    fleet = scenario["fleet_distribution"]

    for component in ("pv", "battery", "load"):
        if component in config:
            fleet[component] = config[component]

    return yaml.dump(scenario, default_flow_style=False, sort_keys=False)  # type: ignore[no-any-return]


def yaml_to_fleet_distribution(yaml_str: str) -> dict[str, Any]:
    """Parse a YAML string to a fleet distribution config dict.

    Supports both full scenario YAML files (with a ``fleet_distribution``
    key) and bare fleet distribution dicts.

    Args:
        yaml_str: YAML-formatted string.

    Returns:
        Fleet distribution config dict.

    Raises:
        ValueError: If the YAML is invalid or missing required fields.
    """
    try:
        data = yaml.safe_load(yaml_str)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError("YAML must contain a mapping at the top level")

    # Support both full scenario files and bare fleet_distribution dicts
    if "fleet_distribution" in data:
        fleet_data = data["fleet_distribution"]
    elif "n_homes" in data:
        fleet_data = data
    else:
        raise ValueError(
            "YAML must contain either a 'fleet_distribution' key or an 'n_homes' key"
        )

    if not isinstance(fleet_data, dict):
        raise ValueError("Fleet distribution data must be a mapping")

    result: dict[str, Any] = {
        "n_homes": fleet_data.get("n_homes", 100),
        "seed": fleet_data.get("seed", 42),
        "name": data.get("name", "Imported Configuration"),
    }

    for component in ("pv", "battery", "load"):
        if component in fleet_data:
            result[component] = fleet_data[component]

    return result
