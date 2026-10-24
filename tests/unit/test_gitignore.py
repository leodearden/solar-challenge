# SPDX-License-Identifier: AGPL-3.0-or-later
"""Git ignores what runs leave at the root of a checkout: the orchestrator's runtime state under data/, the worktrees it abandons under .worktrees-orphaned/, and simulation output under results/.

It does so because working_tree_files' listing feeds the pointer gate's scan and the wheel build's copy of the tree.
It ignores them only at the root, since project directories of those names exist deeper.
"""

import os
import shutil
import subprocess
from pathlib import Path, PurePosixPath

import pytest

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
    """Return a new git checkout holding a copy of the project's .gitignore, where git reads no excludes file of the user's or the system's."""
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "core.excludesFile", os.devnull], cwd=root, check=True)
    shutil.copyfile(project_root / ".gitignore", root / ".gitignore")
    return root


def _write_untracked(checkout: Path, paths: tuple[PurePosixPath, ...]) -> None:
    """Write a file at each of *paths* in *checkout*, creating its directories, and leave it out of git's index."""
    for path in paths:
        written = checkout / path
        written.parent.mkdir(parents=True, exist_ok=True)
        written.write_text(path.name, encoding="utf-8")


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
