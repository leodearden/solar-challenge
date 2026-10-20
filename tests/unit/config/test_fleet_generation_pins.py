# SPDX-License-Identifier: AGPL-3.0-or-later
"""The reproducibility pins of review/briefing.yaml's seed rule: each pinned fleet file generates the homes its golden holds."""

import json
from pathlib import Path

import pytest

from solar_challenge.config import load_config
from tests._fleet_generation_pins import PINNED_FLEETS, REGENERATE_COMMAND, SHIPPED_FLEETS, fleet_pin, golden_path


@pytest.mark.parametrize("fleet", PINNED_FLEETS, ids=[Path(fleet).stem for fleet in PINNED_FLEETS])
def test_the_fleet_generates_the_homes_its_golden_pins(project_root: Path, fleet: str) -> None:
    """Every value the fleet file draws for its homes, home by home and sweep point by sweep point, is its golden's."""
    golden_file = golden_path(project_root, fleet)
    golden_name = golden_file.relative_to(project_root).as_posix()
    assert golden_file.is_file(), f"{fleet} has no golden {golden_name}; write it with `{REGENERATE_COMMAND}`"
    golden = json.loads(golden_file.read_text(encoding="utf-8"))
    generated = fleet_pin(project_root, fleet)
    message = (
        f"{fleet} no longer generates the homes {golden_name} pins. Only a change meant to move generated "
        f"fleets regenerates the goldens, with `{REGENERATE_COMMAND}`, and says so in an Unreleased on main "
        "line of docs/domain-library-consumption.md."
    )
    generated_sweep = [point["sweep_value"] for point in generated["points"]]
    golden_sweep = [point["sweep_value"] for point in golden["points"]]
    assert generated_sweep == golden_sweep, message
    for generated_point, golden_point in zip(generated["points"], golden["points"]):
        assert generated_point["homes"] == golden_point["homes"], (
            f"{message} Sweep value: {golden_point['sweep_value']}"
        )


def test_every_fleet_scenario_is_pinned(project_root: Path) -> None:
    """Every scenarios/*.yaml with a fleet_distribution: block is a shipped fleet the pins hold."""
    fleet_scenarios = sorted(
        path.relative_to(project_root).as_posix()
        for path in (project_root / "scenarios").glob("*.yaml")
        if "fleet_distribution" in load_config(path)
    )
    assert fleet_scenarios == sorted(SHIPPED_FLEETS), (
        "Add each fleet scenario to SHIPPED_FLEETS in tests/_fleet_generation_pins.py, then write its golden "
        f"with `{REGENERATE_COMMAND}`"
    )
