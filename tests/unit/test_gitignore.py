# SPDX-License-Identifier: AGPL-3.0-or-later
"""Git ignores what runs leave at the root of a checkout: the orchestrator's runtime state under data/, the worktrees it abandons under .worktrees-orphaned/, and simulation output under results/.

It does so because working_tree_files' listing feeds the pointer gate's scan and the wheel build's copy of the tree.
It ignores them only at the root, since project directories of those names exist deeper.
"""

import shutil
from pathlib import Path, PurePosixPath

import pytest

from tests._synthetic_checkout import synthetic_checkout, write_file
from tests._working_tree import working_tree_files

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the tree's files are listed with it"
)

_GITIGNORE = PurePosixPath(".gitignore")

_RUNTIME_STATE = (
    PurePosixPath(".worktrees-orphaned/12-20260531T140823Z/CLAUDE.md"),
    PurePosixPath("data/orchestrator/runs.db"),
    PurePosixPath("results/proportional-battery-sweep/sweep_summary.csv"),
)

_PROJECT_FILES_IN_DIRECTORIES_NAMED_LIKE_RUNTIME_ONES = (
    PurePosixPath("src/solar_challenge/web/templates/results/new.html"),
    PurePosixPath("src/solar_challenge/data/profile.csv"),
)


@pytest.fixture
def checkout(project_root: Path, tmp_path: Path) -> Path:
    """Return a new hermetic git checkout holding a copy of the project's .gitignore."""
    return synthetic_checkout(tmp_path / "checkout", {_GITIGNORE: (project_root / _GITIGNORE).read_bytes()})


def _write_untracked(checkout: Path, paths: tuple[PurePosixPath, ...]) -> None:
    """Write a file at each of *paths* in *checkout*, its text its name, and leave it out of git's index."""
    for path in paths:
        write_file(checkout, path, path.name)


def test_git_lists_none_of_the_state_runs_leave_at_the_root_of_the_checkout(checkout: Path) -> None:
    _write_untracked(checkout, _RUNTIME_STATE)

    listed = working_tree_files(checkout)

    assert listed == [_GITIGNORE], (
        f"git still lists {[str(path) for path in listed if path != _GITIGNORE]}, which runs leave at the root of the"
        " checkout; ignore that directory in .gitignore, anchored at the root with a leading /, because the pointer"
        " gate would scan its files and the wheel build would copy them"
    )


def test_git_lists_new_project_files_in_directories_named_like_the_runtime_ones(checkout: Path) -> None:
    _write_untracked(checkout, _PROJECT_FILES_IN_DIRECTORIES_NAMED_LIKE_RUNTIME_ONES)

    listed = working_tree_files(checkout)

    expected = [_GITIGNORE, *_PROJECT_FILES_IN_DIRECTORIES_NAMED_LIKE_RUNTIME_ONES]
    assert sorted(listed) == sorted(expected), (
        f"git leaves out {[str(path) for path in expected if path not in listed]}, new files of the project; a"
        " runtime-directory pattern without a leading / ignores a project directory of the same name anywhere in the"
        " tree, so anchor it at the root"
    )
