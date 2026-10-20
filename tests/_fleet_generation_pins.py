# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reproducibility pins: the values each pinned fleet file draws for its homes, and the goldens that hold them.

A pin is generated through the fleet loaders the CLI uses. Home by home, it records every
value the file's fleet_distribution: block gives a component, or None for a component the
home lacks, so a field the file leaves to a default is never pinned. A battery's grid_charging
and dispatch_strategy sub-blocks hold no single drawn value and are left out; any other value
that is not None, a bool, a number or a string is refused, naming the fleet and the setting.

Usage::

    from tests._fleet_generation_pins import PINNED_FLEETS, fleet_pin, golden_path

    for fleet in PINNED_FLEETS:
        golden = json.loads(golden_path(project_root, fleet).read_text(encoding="utf-8"))
        assert fleet_pin(project_root, fleet) == golden

Only a change meant to move generated fleets regenerates the goldens, from the worktree root::

    uv run --locked --extra dev python -m tests._fleet_generation_pins
"""

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

from solar_challenge.config import detect_fleet_sweep_spec, load_config, parse_fleet_config, parse_sweep_fleet_configs
from solar_challenge.home import HomeConfig

SHIPPED_FLEETS: tuple[str, ...] = (
    "scenarios/bristol-phase1.yaml",
    "scenarios/bristol-phase1-aged.yaml",
    "scenarios/bristol-with-evs.yaml",
    "scenarios/bristol-phase1-flex.yaml",
    "scenarios/bristol-fin-calibration.yaml",
    "scenarios/bristol-phase1-proportional-battery-sweep.yaml",
)

PROBE_FLEETS: tuple[str, ...] = (
    "tests/fixtures/fleet_generation/probe-conditional-battery-draws.yaml",
    "tests/fixtures/fleet_generation/probe-weighted-heat-pump-type.yaml",
    "tests/fixtures/fleet_generation/probe-ev-pools-and-normals.yaml",
    "tests/fixtures/fleet_generation/probe-legacy-pre-sampling.yaml",
    "tests/fixtures/fleet_generation/probe-proportional-battery.yaml",
    "tests/fixtures/fleet_generation/probe-pooled-heat-pump-type.yaml",
)

PINNED_FLEETS: tuple[str, ...] = SHIPPED_FLEETS + PROBE_FLEETS

REGENERATE_COMMAND = "uv run --locked --extra dev python -m tests._fleet_generation_pins"

_COMPONENTS: tuple[str, ...] = ("pv", "battery", "load", "heat_pump", "ev")

#: The (component, key) settings whose value is a sub-block, which holds no single drawn value.
_SUB_BLOCKS: frozenset[tuple[str, str]] = frozenset({("battery", "grid_charging"), ("battery", "dispatch_strategy")})

_PINNED_VALUE_TYPES: tuple[type, ...] = (type(None), bool, int, float, str)


def golden_path(project_root: Path, fleet: str) -> Path:
    """Return the golden file that pins the repo-relative fleet file *fleet*."""
    return project_root / "tests" / "fixtures" / "fleet_generation" / f"{Path(fleet).stem}.json"


def fleet_pin(project_root: Path, fleet: str) -> dict[str, Any]:
    """Return the pin of the homes the repo-relative fleet file *fleet* generates, one point per sweep value.

    A file without a sweep has one point, whose sweep value is None.
    """
    document = load_config(project_root / fleet)
    blocks = _given_component_blocks(document["fleet_distribution"])
    return {
        "fleet": fleet,
        "points": [
            {"sweep_value": value, "homes": [_home_record(fleet, home, blocks) for home in homes]}
            for value, homes in _generated_points(document)
        ],
    }


def golden_text(pin: Mapping[str, Any]) -> str:
    """Return *pin* as the JSON its golden file holds, one home per line."""
    points = ",\n".join(
        f'{{"sweep_value": {_json(point["sweep_value"])}, "homes": [\n'
        + ",\n".join(_json(home) for home in point["homes"])
        + "\n]}"
        for point in pin["points"]
    )
    return f'{{"fleet": {_json(pin["fleet"])}, "points": [\n{points}\n]}}\n'


def _json(value: object) -> str:
    return json.dumps(value, allow_nan=False)


def _generated_points(document: Mapping[str, Any]) -> list[tuple[Optional[float], list[HomeConfig]]]:
    if detect_fleet_sweep_spec(document) is None:
        return [(None, parse_fleet_config(document).homes)]
    return [(value, fleet_config.homes) for value, fleet_config in parse_sweep_fleet_configs(document)]


def _given_component_blocks(distribution: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        component: distribution[component]
        for component in _COMPONENTS
        if isinstance(distribution.get(component), Mapping) and distribution[component]
    }


def _home_record(
    fleet: str, home: HomeConfig, blocks: Mapping[str, Mapping[str, Any]]
) -> dict[str, Optional[dict[str, Any]]]:
    configs: dict[str, object] = {
        "pv": home.pv_config,
        "battery": home.battery_config,
        "load": home.load_config,
        "heat_pump": home.heat_pump_config,
        "ev": home.ev_config,
    }
    return {
        component: _component_record(fleet, component, configs[component], block)
        for component, block in blocks.items()
    }


def _component_record(
    fleet: str, component: str, config: object, block: Mapping[str, Any]
) -> Optional[dict[str, Any]]:
    if config is None:
        return None
    record = {key: getattr(config, key) for key in block if (component, key) not in _SUB_BLOCKS}
    for key, value in record.items():
        if not isinstance(value, _PINNED_VALUE_TYPES):
            raise TypeError(
                f"{fleet} gives a home {component}.{key} = {value!r}, which no golden can hold: a pin holds "
                "None, a bool, a number or a string. Record the setting's drawn value as one of those, or, if "
                f"it is a sub-block holding no single drawn value, add ({component!r}, {key!r}) to _SUB_BLOCKS "
                "in tests/_fleet_generation_pins.py"
            )
    return record


def main() -> None:
    """Write the golden of every pinned fleet, generated in the current directory, which must be the worktree root."""
    project_root = Path.cwd()
    for fleet in PINNED_FLEETS:
        path = golden_path(project_root, fleet)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(golden_text(fleet_pin(project_root, fleet)), encoding="utf-8")
        print(path)


if __name__ == "__main__":
    main()
