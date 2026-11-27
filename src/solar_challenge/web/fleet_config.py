# SPDX-License-Identifier: AGPL-3.0-or-later
"""The fleet a dashboard form's fleet blocks describe, read at the form's own paths with nothing invented, and held to the dashboard's bounds.

read_form_fleet reads a form's fleet blocks, its FLEET_DISTRIBUTION_FORM_KEYS fields, as a
fleet_distribution: block's are, and refuse_a_fleet_the_dashboard_cannot_run holds the fleet
read to what the dashboard can run.
"""

from __future__ import annotations

from collections.abc import Mapping
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
from solar_challenge.scenario_blocks import child_path, refusal
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, read_fleet_seed, read_fleet_size


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
