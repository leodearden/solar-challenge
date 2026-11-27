# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet a dashboard form's blocks describe, held to the dashboard's bounds, and the distribution preview's sampler.

read_form_fleet reads a form's fleet blocks as a fleet_distribution: block's are, at the
form's own paths, with nothing invented. sample_distribution reads a distribution in the
grammar's spelling but never runs the grammar, so it reads and bounds its own numbers.
"""

from __future__ import annotations

import dataclasses
import math
import random
from collections.abc import Callable, Mapping, Sequence
from types import MappingProxyType
from typing import Any


from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    ComponentDistribution,
    DistributionSpec,
    FleetDistributionConfig,
    ShuffledPoolDistribution,
    WeightedDiscreteDistribution,
    parse_fleet_distribution_config,
)
from solar_challenge.number_fields import (
    Interval,
    as_finite_float,
    as_finite_floats,
    as_whole_number,
    as_whole_numbers,
)
from solar_challenge.scenario_blocks import child_path, refusal, require_mapping
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    FLEET_SIZE,
    MAX_FLEET_HOMES,
    read_fleet_seed,
    read_fleet_size,
)


def refuse_a_fleet_the_dashboard_cannot_run(fleet: FleetDistributionConfig, path: str) -> None:
    """Refuse *fleet*, a fleet fleet_distribution.py's grammar has read from the block at *path*, when the dashboard cannot run it: more than :data:`MAX_FLEET_HOMES` homes, a seed beyond :data:`MAX_FLEET_SEED`, or a field every home needs that some home may draw null.

    A shuffled pool needs no bound of its own: the grammar's F6 holds every pool's counts
    to the fleet's n_homes, so a fleet within MAX_FLEET_HOMES holds no larger pool.

    Raises:
        ConfigurationError: From :func:`read_fleet_size` or :func:`read_fleet_seed`, naming
            n_homes or seed under *path* and the value read; or naming the field under *path*
            and the null a home may draw.
    """
    read_fleet_size(fleet.n_homes, child_path(path, "n_homes"))
    if fleet.seed is not None:
        read_fleet_seed(fleet.seed, child_path(path, "seed"))
    _refuse_a_required_field_a_home_may_draw_null(fleet, path)


def _refuse_a_required_field_a_home_may_draw_null(fleet: FleetDistributionConfig, path: str) -> None:
    """Refuse *fleet*, read from the block at *path*, when a component gives a field its fleet row requires, other than its presence field, a spec some home may draw null from.

    The grammar refuses such a draw only as it generates the homes, naming the field under
    fleet_distribution, and a form's cleared input posts null; so it is refused before any home
    is generated, under *path*. A presence field's null is a home without the component.

    Raises:
        ConfigurationError: Naming the field under *path* and the null a home may draw.
    """
    for component in FLEET_COMPONENTS.values():
        distribution: ComponentDistribution | None = getattr(fleet, component.key)
        if distribution is None:
            continue
        for key, spec in distribution.draws.items():
            row = component.block.fleet[key]
            null = _null_a_home_may_draw(spec)
            if row.required and key != component.block.presence and null is not None:
                field = child_path(child_path(path, component.key), key)
                raise refusal(field, f"required, so no home may draw null, got {null}")


def _null_a_home_may_draw(spec: DistributionSpec) -> str | None:
    """The null in *spec* some home may draw: 'null' for the null spec, or 'a null at values[<index>]' for the first value left null with a count or weight above 0; None when no home may draw null."""
    if spec is None:
        return "null"
    if isinstance(spec, ShuffledPoolDistribution):
        shares: tuple[float, ...] = spec.counts
    elif isinstance(spec, WeightedDiscreteDistribution):
        shares = spec.weights
    else:
        return None
    for index, (value, share) in enumerate(zip(spec.values, shares, strict=True)):
        if value is None and share > 0:
            return f"a null at values[{index}]"
    return None


def sample_distribution(
    dist_type: str, params: object, n_samples: object = 100
) -> list[float]:
    """Generate sample values from a distribution for preview histogram.

    Args:
        dist_type: Distribution type, sent in the field ``type``. One of the types the
            distribution editor offers: ``'normal'``, ``'uniform'``,
            ``'weighted_discrete'``, ``'shuffled_pool'``.
        params: The distribution's other keys, in fleet_distribution.py's spelling: a
            weighted_discrete's values and weights lists, a shuffled_pool's values and
            counts lists. A key sent as null is left out.
        n_samples: Number of samples to generate, a whole number from 1 to
            :data:`MAX_FLEET_HOMES`.

    Returns:
        List of sampled values, each a finite float.

    Raises:
        ConfigurationError: For an n_samples that is not a whole number from 1 to
            MAX_FLEET_HOMES; params that are not a mapping; a type the editor does not
            offer; params without what the type is drawn from; a parameter or list cell
            that is not a finite number, or a count the preview cannot pool; lists of
            unequal length; params the sampler cannot draw from; or a sample that is not a
            finite number, as finite params whose draws overflow a float can. Each names
            its field, n_samples, type or one under params, or the sample.
    """
    n_samples = as_whole_number(n_samples, "n_samples", within=FLEET_SIZE)
    spec = _preview_spec(dist_type, require_mapping("params", params))
    samples = _draw_samples(spec, n_samples)
    for sample in samples:
        if not math.isfinite(sample):
            raise ConfigurationError(
                f"params must draw samples that are finite numbers, got a sample of {sample!r}"
            )
    return samples


def _draw_samples(spec: dict[str, Any], n_samples: int) -> list[float]:
    """Draw *n_samples* values from *spec*, a distribution :func:`_preview_spec` read, with a fixed seed.

    Raises:
        ConfigurationError: If its parameters are ones it cannot draw from, such as a negative std
            or a min above max.
    """
    rng = random.Random(42)
    dist_type = spec["type"]

    if dist_type == "normal":
        if spec["std"] < 0:
            raise ConfigurationError("Standard deviation cannot be negative")
        samples = [rng.gauss(spec["mean"], spec["std"]) for _ in range(n_samples)]
        if "min" in spec:
            samples = [max(spec["min"], s) for s in samples]
        if "max" in spec:
            samples = [min(spec["max"], s) for s in samples]
        return samples

    if dist_type == "uniform":
        if spec["min"] > spec["max"]:
            raise ConfigurationError("min cannot be greater than max")
        return [rng.uniform(spec["min"], spec["max"]) for _ in range(n_samples)]

    if dist_type == "weighted_discrete":
        if not spec["values"]:
            raise ConfigurationError("weighted_discrete requires non-empty 'values' list")
        if sum(spec["weights"]) == 0:
            raise ConfigurationError("Weights cannot all be zero")
        return rng.choices(spec["values"], weights=spec["weights"], k=n_samples)

    if dist_type == "shuffled_pool":
        if not spec["values"]:
            raise ConfigurationError("shuffled_pool requires non-empty 'values' list")
        pool: list[float] = []
        for value, count in zip(spec["values"], spec["counts"]):
            pool.extend([value] * count)
        if not pool:
            raise ConfigurationError("shuffled_pool produced an empty pool")
        rng.shuffle(pool)
        # Cycle through pool to fill n_samples
        samples = [pool[i % len(pool)] for i in range(n_samples)]
        return samples

    raise AssertionError(
        f"_draw_samples draws each type _preview_spec reads, but has no draw for {dist_type!r}"
    )


#: The top-level keys of a dashboard form that read_form_fleet reads: its fleet's blocks.
FLEET_DISTRIBUTION_FORM_KEYS: frozenset[str] = frozenset({"n_homes", "seed", "pv", "battery", "load"})


def read_form_fleet(blocks: Mapping[str, Any]) -> FleetDistributionConfig:
    """The fleet *blocks*, a dashboard form's n_homes, seed and pv, battery and load blocks, describe: read as a fleet_distribution: block's are, at the form's own paths, with nothing invented, and held to the dashboard's bounds.

    A battery block may not set a dispatch strategy: every battery takes the form's.

    Raises:
        ConfigurationError: For a battery block setting a dispatch strategy, a block the grammar
            refuses, or a fleet the dashboard cannot run, a cleared PV capacity among them,
            naming the field as the form posts it.
    """
    battery = blocks.get("battery")
    if isinstance(battery, dict):
        _refuse_battery_dispatch_strategy(battery)
    fleet = parse_fleet_distribution_config(dict(blocks), block_path="")
    refuse_a_fleet_the_dashboard_cannot_run(fleet, "")
    return fleet


def _refuse_battery_dispatch_strategy(battery: dict[str, Any]) -> None:
    """Refuse a dashboard form's *battery* block when it sets a dispatch strategy: a dashboard form gives every battery one dispatch strategy, its own or the default.

    fleet_distribution.py's grammar reads a battery block's dispatch_strategy, but no dashboard
    form sets one per block: the fleet page spells the setting once, at its form's root, and the
    scenario builder has none, so every battery takes the default.

    Raises:
        ConfigurationError: If the block's dispatch_strategy is present and not null; the error
            names battery.dispatch_strategy, the rule and the value sent.
    """
    strategy = battery.get("dispatch_strategy")
    if strategy is not None:
        raise ConfigurationError(
            "battery.dispatch_strategy must be absent or null: a dashboard form gives every "
            f"battery one dispatch strategy, its own or the default, got {strategy!r}"
        )


@dataclasses.dataclass(frozen=True)
class _EditorRows:
    """A distribution's rows as fleet_distribution.py's grammar spells them, parallel lists: its values, and the *paired_key* list, which the preview reads with *read_paired*."""

    paired_key: str
    #: Reads the paired list sent, under its field, for the preview, so its rule may bound
    #: each cell or the list's total.
    read_paired: Callable[[object, str], Sequence[float]]


@dataclasses.dataclass(frozen=True)
class _EditorType:
    """A distribution type the distribution editor offers: its scalar parameters, the keys the preview draws it from, and its rows, if it has rows."""

    parameters: tuple[str, ...]
    #: The keys the preview draws the type from: the forms leave a missing one for
    #: fleet_distribution.py's grammar to name, and only the preview, which never runs the
    #: grammar, refuses it.
    drawn_from: tuple[str, ...]
    rows: _EditorRows | None = None


def _preview_pool_counts(counts: object, counts_field: str) -> tuple[int, ...]:
    """Read *counts*, a shuffled pool's counts list sent in *counts_field*, as the counts of the pool the preview builds: each a whole number from 0 to :data:`MAX_FLEET_HOMES`, totalling at most MAX_FLEET_HOMES.

    The preview never runs fleet_distribution.py's grammar, whose F6 holds a fleet's pools to
    its n_homes, so it bounds the pool it builds itself.

    Raises:
        ConfigurationError: For a list or count as_whole_numbers refuses, naming its field, or
            counts totalling more than MAX_FLEET_HOMES, naming *counts_field* and the total.
    """
    read_counts = as_whole_numbers(counts, counts_field, within=Interval(0, MAX_FLEET_HOMES))
    total = sum(read_counts)
    if total > MAX_FLEET_HOMES:
        raise ConfigurationError(
            f"{counts_field} must total at most {MAX_FLEET_HOMES}, got {total}"
        )
    return read_counts


#: The distribution types the fleet pages' distribution editor holds besides a fixed value.
_EDITOR_TYPES: Mapping[str, _EditorType] = MappingProxyType({
    "normal": _EditorType(parameters=("mean", "std", "min", "max"), drawn_from=("mean", "std")),
    "uniform": _EditorType(parameters=("min", "max"), drawn_from=("min", "max")),
    "weighted_discrete": _EditorType(
        parameters=(),
        drawn_from=("values", "weights"),
        rows=_EditorRows("weights", as_finite_floats),
    ),
    "shuffled_pool": _EditorType(
        parameters=(),
        drawn_from=("values", "counts"),
        rows=_EditorRows("counts", _preview_pool_counts),
    ),
})


def _preview_spec(dist_type: object, params: Mapping[str, Any]) -> dict[str, Any]:
    """The spec the preview draws from: *dist_type* and *params*, a distribution in fleet_distribution.py's spelling, each parameter and list cell its type draws read under its field, ``params.<key>`` or ``params.<list>[index]``.

    A key sent as null is left out, and a key its type does not draw is ignored.

    Raises:
        ConfigurationError: For a type the editor does not offer, naming type and the type
            sent; params without a key the type is drawn from, naming it; a parameter, list
            or cell those reads refuse, naming its field; or lists of unequal length, naming
            both.
    """
    editor_type = _EDITOR_TYPES.get(dist_type) if isinstance(dist_type, str) else None
    if editor_type is None:
        raise ConfigurationError(
            f"type must be one of {', '.join(_EDITOR_TYPES)}, got {dist_type!r}"
        )
    for key in editor_type.drawn_from:
        if params.get(key) is None:
            raise ConfigurationError(
                f"params.{key} must be given: the preview draws a {dist_type} distribution "
                f"from its {' and '.join(editor_type.drawn_from)}"
            )
    spec: dict[str, Any] = {
        key: as_finite_float(params[key], f"params.{key}")
        for key in editor_type.parameters
        if params.get(key) is not None
    }
    if editor_type.rows is not None:
        spec.update(_preview_rows(params, editor_type.rows))
    return {"type": dist_type, **spec}


def _preview_rows(params: Mapping[str, Any], rows: _EditorRows) -> dict[str, Sequence[float]]:
    """The values list and the *rows* paired list of *params*, each cell read under ``params.<list>[index]``.

    Raises:
        ConfigurationError: For a list or cell the reads refuse, naming its field, or lists of
            unequal length, naming both and their lengths.
    """
    paired_field = f"params.{rows.paired_key}"
    values = as_finite_floats(params["values"], "params.values")
    paired = rows.read_paired(params[rows.paired_key], paired_field)
    if len(values) != len(paired):
        raise ConfigurationError(
            f"params.values and {paired_field} must have the same length, "
            f"got {len(values)} and {len(paired)}"
        )
    return {"values": values, rows.paired_key: paired}
