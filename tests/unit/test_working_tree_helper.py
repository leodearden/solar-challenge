# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_working_tree.py, on a real throwaway git checkout, with no mocks."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._working_tree import copy_working_tree

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the helper lists the tree's files with it"
)


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    """Return a git checkout holding a tracked file, an untracked one, an ignored one and a tracked one since deleted."""
    root = tmp_path / "checkout"
    root.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    (root / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
    (root / "tracked.txt").write_text("tracked", encoding="utf-8")
    (root / "deleted.txt").write_text("deleted", encoding="utf-8")
    subprocess.run(["git", "add", ".gitignore", "tracked.txt", "deleted.txt"], cwd=root, check=True)
    (root / "nested").mkdir()
    (root / "nested" / "untracked.txt").write_text("untracked", encoding="utf-8")
    (root / "ignored.txt").write_text("ignored", encoding="utf-8")
    (root / "deleted.txt").unlink()
    return root


def test_copies_tracked_and_untracked_files_but_not_ignored_or_deleted_ones(checkout: Path, tmp_path: Path) -> None:
    copy = copy_working_tree(checkout, tmp_path / "copy")

    copied = sorted(path.relative_to(copy).as_posix() for path in copy.rglob("*") if path.is_file())
    assert copied == [".gitignore", "nested/untracked.txt", "tracked.txt"]
    assert (copy / "nested" / "untracked.txt").read_text(encoding="utf-8") == "untracked"


def test_leaves_out_a_listed_path_that_is_not_a_regular_file(checkout: Path, tmp_path: Path) -> None:
    """git lists a symlink to a directory, such as a worktree's .claude, as one path; the copy leaves it out."""
    (checkout / "linked").symlink_to("nested", target_is_directory=True)
    subprocess.run(["git", "add", "linked"], cwd=checkout, check=True)

    copy = copy_working_tree(checkout, tmp_path / "copy")

    assert not os.path.lexists(copy / "linked")


def test_raises_called_process_error_outside_a_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    plain_directory = tmp_path / "plain"
    plain_directory.mkdir()
    # So git finds no checkout above tmp_path either, wherever the temporary directory lives.
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))

    with pytest.raises(subprocess.CalledProcessError):
        copy_working_tree(plain_directory, tmp_path / "copy")
