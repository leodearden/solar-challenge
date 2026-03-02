"""Helper module for fleet configuration in the web dashboard.

Provides utilities for sampling distributions, converting form data to
fleet distribution configs, and YAML import/export.
"""

import random
from typing import Any

import yaml


def sample_distribution(
    dist_type: str, params: dict[str, Any], n_samples: int = 100
) -> list[float]:
    """Generate sample values from a distribution for preview histogram.

    Args:
        dist_type: Distribution type. One of ``'weighted_discrete'``,
            ``'normal'``, ``'uniform'``, ``'shuffled_pool'``.
        params: Distribution parameters (varies by type).
        n_samples: Number of samples to generate.

    Returns:
        List of sampled float values.

    Raises:
        ValueError: If dist_type is unknown or params are invalid.
    """
    if n_samples < 1:
        raise ValueError("n_samples must be at least 1")

    rng = random.Random(42)

    if dist_type == "normal":
        mean = float(params.get("mean", 0.0))
        std = float(params.get("std", 1.0))
        min_val = params.get("min")
        max_val = params.get("max")
        if std < 0:
            raise ValueError("Standard deviation cannot be negative")
        samples = [rng.gauss(mean, std) for _ in range(n_samples)]
        if min_val is not None:
            min_val = float(min_val)
            samples = [max(min_val, s) for s in samples]
        if max_val is not None:
            max_val = float(max_val)
            samples = [min(max_val, s) for s in samples]
        return samples

    if dist_type == "uniform":
        min_val = float(params.get("min", 0.0))
        max_val = float(params.get("max", 1.0))
        if min_val > max_val:
            raise ValueError("min cannot be greater than max")
        return [rng.uniform(min_val, max_val) for _ in range(n_samples)]

    if dist_type == "weighted_discrete":
        values_raw = params.get("values", [])
        if not values_raw:
            raise ValueError("weighted_discrete requires non-empty 'values' list")
        values = []
        weights = []
        for entry in values_raw:
            values.append(float(entry.get("value", 0)))
            weights.append(float(entry.get("weight", 1)))
        if sum(weights) == 0:
            raise ValueError("Weights cannot all be zero")
        population = values
        cum_weights = weights
        samples = rng.choices(population, weights=cum_weights, k=n_samples)
        return [float(s) for s in samples]

    if dist_type == "shuffled_pool":
        entries = params.get("entries", [])
        if not entries:
            raise ValueError("shuffled_pool requires non-empty 'entries' list")
        pool: list[float] = []
        for entry in entries:
            val = float(entry.get("value", 0))
            count = int(entry.get("count", 1))
            pool.extend([val] * count)
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
        ValueError: If required fields are missing or invalid.
    """
    n_homes = int(form_data.get("n_homes", 100))
    if n_homes < 1:
        raise ValueError("n_homes must be at least 1")

    config: dict[str, Any] = {
        "n_homes": n_homes,
        "seed": int(form_data.get("seed", 42)),
    }

    # Process PV distribution
    pv_data = form_data.get("pv", {})
    config["pv"] = _parse_component_distribution(pv_data, "capacity_kw", default_field="capacity_kw")

    # Process Battery distribution
    battery_data = form_data.get("battery", {})
    if battery_data and battery_data.get("enabled", True):
        config["battery"] = _parse_component_distribution(
            battery_data, "capacity_kwh", default_field="capacity_kwh"
        )

    # Process Load distribution
    load_data = form_data.get("load", {})
    config["load"] = _parse_component_distribution(
        load_data, "annual_consumption_kwh", default_field="annual_consumption_kwh"
    )

    return config


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
        values_raw = data.get("values", [])
        result["values"] = [float(v.get("value", 0)) for v in values_raw]
        result["weights"] = [float(v.get("weight", 1)) for v in values_raw]

    elif dist_type == "shuffled_pool":
        entries = data.get("entries", [])
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

    return yaml.dump(scenario, default_flow_style=False, sort_keys=False)


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
