# SPDX-License-Identifier: AGPL-3.0-or-later
"""The verify-suite tests the newest-releases check deselects, because its copy of the tree breaks them by design.

The newest-releases check, tests/newest_releases/test_verify_suite_on_newest_releases.py,
runs the verify suite in a copy of the tree whose uv.lock is upgraded and whose
pyproject.toml has a [tool.uv] table appended. A test of a property of the
committed pyproject.toml and uv.lock pair fails there by construction, so the
check deselects it. --deselect matches a node id by prefix.
tests/unit/test_newest_releases_lane.py checks, in the per-task verify, that
each entry matches exactly the cases of one collected test.

Usage::

    from tests._newest_releases_deselections import NEWEST_RELEASES_DESELECTIONS

    addopts = shlex.join(f"--deselect={deselected.node_id}" for deselected in NEWEST_RELEASES_DESELECTIONS)
"""

from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class DeselectedTest:
    """A test function the check deselects: its module, relative to the rootdir as node ids are, and its name."""

    module: PurePosixPath
    function: str

    @property
    def node_id(self) -> str:
        """The function's node id, the prefix by which --deselect matches every case of it."""
        return f"{self.module}::{self.function}"


NEWEST_RELEASES_DESELECTIONS: tuple[DeselectedTest, ...] = (
    # The copy upgrades uv.lock past pyproject.toml's floors, so the floor test's rule, floor == lock, is false there.
    DeselectedTest(
        PurePosixPath("tests/unit/test_dependency_floors.py"), "test_every_declared_floor_is_the_locked_release"
    ),
    # The copy's pyproject.toml already holds the [tool.uv] table the declaration appends, so appending it fails there.
    DeselectedTest(
        PurePosixPath("tests/unit/test_required_environment_helper.py"),
        "test_the_declaration_is_valid_toml_in_this_projects_pyproject",
    ),
)
