# SPDX-License-Identifier: AGPL-3.0-or-later
"""The shipped YAML sweep file with its sweep multiplier moved to another field, and the refusals of a misplaced or second sweep multiplier, as the fleet tests expect them.

A fleet_distribution sweeps through one proportional_to whose multiplier has type: sweep, and
only at fleet_distribution.battery.capacity_kwh. A sweep multiplier anywhere else is refused
naming its path and that placement; a fleet holding more than one is refused naming every one.

Usage::

    from tests._misplaced_sweeps import MISPLACED_SWEEP_FIELDS, misplaced_sweep_refusal, sweep_moved_to

    @pytest.mark.parametrize(("component", "key", "block"), MISPLACED_SWEEP_FIELDS)
    def test_a_misplaced_sweep_is_refused(component: str, key: str, block: dict[str, object]) -> None:
        with pytest.raises(ConfigurationError) as refused:
            parse_fleet_distribution_config(sweep_moved_to(component, key, **block)["fleet_distribution"])
        assert str(refused.value) == misplaced_sweep_refusal(f"fleet_distribution.{component}.{key}")
"""

from collections.abc import Sequence
from typing import Any

import pytest
import yaml

from solar_challenge.scenario_blocks import (
    BATTERY_BLOCK,
    EV_BLOCK,
    HEAT_PUMP_BLOCK,
    LOAD_BLOCK,
    PV_BLOCK,
    ComponentBlock,
    FieldKind,
)
from tests._repository_paths import SCENARIOS_DIR

#: The committed YAML sweep file: a fleet whose battery.capacity_kwh sweeps a proportional_to's multiplier.
SHIPPED_SWEEP = SCENARIOS_DIR / "bristol-phase1-proportional-battery-sweep.yaml"

#: The one field a fleet's sweep multiplier may sit at.
_THE_SWEEP_PLACEMENT = ("battery", "capacity_kwh")


def sweep_moved_to(component: str, key: str, **block: object) -> dict[str, Any]:
    """The shipped sweep file's document with its sweep multiplier moved to a proportional_to of pv.capacity_kw at fleet_distribution.<component>.<key>.

    battery.capacity_kwh keeps its proportional_to at a multiplier of 1.0. *component*'s block
    is created if the file has none, and holds *block*'s keys besides.
    """
    document: dict[str, Any] = yaml.safe_load(SHIPPED_SWEEP.read_text())
    fleet = document["fleet_distribution"]
    capacity = fleet["battery"]["capacity_kwh"]
    sweep = capacity["multiplier"]
    capacity["multiplier"] = 1.0
    fleet[component] = {
        **fleet.get(component, {}),
        **block,
        key: {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": sweep},
    }
    return document


def misplaced_sweep_refusal(path: str, placement: str = "fleet_distribution.battery.capacity_kwh") -> str:
    """The refusal of the sweep multiplier at *path*, which a fleet holds only at *placement*."""
    return f"{path}: a sweep multiplier, which a fleet holds only at {placement}"


def two_sweeps_refusal(block_path: str, paths: Sequence[str]) -> str:
    """The refusal of the fleet at *block_path* holding a sweep multiplier at each of *paths*."""
    return f"{block_path}: holds {len(paths)} sweep multipliers, at {', '.join(paths)}; a fleet sweeps at most one"


#: The keys a component's block must give beside the moved sweep: an EV's charger type; a heat
#: pump's type, without which the block is still read, so each heat pump field is moved both ways.
_BLOCK_BESIDE_THE_SWEEP: dict[str, dict[str, object]] = {
    "ev": {"charger_type": "7kW"},
    "heat_pump": {"heat_pump_type": "ASHP"},
}


def _number_and_count_keys(block: ComponentBlock[Any]) -> list[str]:
    """The keys *block*'s fleet rows draw as a number or a count, in fleet order."""
    return [key for key, row in block.fleet.items() if row.kind in (FieldKind.NUMBER, FieldKind.COUNT)]


#: Every number or count field of a fleet's components but the sweep placement, each as
#: (component, key, block): the block's other keys a moved sweep needs beside it.
MISPLACED_SWEEP_FIELDS = (
    *(
        pytest.param(name, key, _BLOCK_BESIDE_THE_SWEEP.get(name, {}), id=f"{name}.{key}")
        for name, block in (
            ("pv", PV_BLOCK), ("battery", BATTERY_BLOCK), ("load", LOAD_BLOCK),
            ("heat_pump", HEAT_PUMP_BLOCK), ("ev", EV_BLOCK),
        )
        for key in _number_and_count_keys(block)
        if (name, key) != _THE_SWEEP_PLACEMENT
    ),
    *(
        pytest.param("heat_pump", key, {}, id=f"heat_pump.{key}-without-heat_pump_type")
        for key in _number_and_count_keys(HEAT_PUMP_BLOCK)
    ),
)
