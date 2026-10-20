# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every dependency floor pyproject.toml declares is the release uv.lock pins.

Each requirement in [project].dependencies and in every extra declares a >= floor equal to the release uv.lock pins
for it. A consumer that re-locks then gets at least the releases this repo tests, and a re-lock that moves a pin
must raise the floor with it. Where uv.lock forks a distribution across environment markers, the floor is its
lowest pin.

[build-system].requires is out: uv.lock does not lock build requirements, so they have no locked release to equal.
docs/prds/lane-harness-one-collection-source.md §3 decisions 7 and 8 give the rationale.
"""

from pathlib import Path
from typing import Any

import pytest
from _pytest.mark import ParameterSet
from packaging.requirements import Requirement

from tests._pyproject import declared_floor, load_project_table, load_uv_lock, locked_versions

# Parametrization happens at collection time, before any fixture exists.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _declared_requirements(project_root: Path) -> list[ParameterSet]:
    """Return a (table, requirement) case for each requirement string pyproject.toml declares, as declared."""
    project = load_project_table(project_root)
    tables = (
        ("dependencies", "[project].dependencies", project["dependencies"]),
        *(
            (extra, f"[project.optional-dependencies].{extra}", requirements)
            for extra, requirements in project["optional-dependencies"].items()
        ),
    )
    return [
        pytest.param(table, requirement, id=f"{key}-{Requirement(requirement).name}")
        for key, table, requirements in tables
        for requirement in requirements
    ]


@pytest.fixture(scope="module")
def uv_lock() -> dict[str, Any]:
    """Return PROJECT_ROOT's uv.lock, parsed once for every case rather than at collection."""
    return load_uv_lock(PROJECT_ROOT)


@pytest.mark.parametrize(("table", "requirement"), _declared_requirements(PROJECT_ROOT))
def test_every_declared_floor_is_the_locked_release(table: str, requirement: str, uv_lock: dict[str, Any]) -> None:
    """The requirement's >= floor is the lowest release uv.lock pins for its distribution.

    tests/newest_releases deselects this test by its node id, because its copy upgrades uv.lock past the floors on
    purpose, so a rename changes both. --deselect matches by node-id prefix, so no other test in this module may
    begin with this test's name.
    """
    name = Requirement(requirement).name
    pinned = locked_versions(uv_lock, name)
    assert pinned, f"uv.lock pins no release of {name}, which {table} requires as {requirement!r}; run `uv lock`."

    lowest = min(pinned)
    assert declared_floor([requirement], name) == lowest, (
        f"{table} declares {requirement!r}, but uv.lock pins {name} at {', '.join(map(str, pinned))}. "
        f"Declare {name}>={lowest} in {table}, then run `uv lock`."
    )
