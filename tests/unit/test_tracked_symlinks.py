# SPDX-License-Identifier: AGPL-3.0-or-later
"""No symlink the git index tracks points outside the checkout, where its target would depend on where the checkout sits."""

import posixpath
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None, reason="git is not installed; the tree's symlinks are listed with it"
)


def _git(checkout: Path, *arguments: str) -> str:
    """Return what git, run with *arguments* in *checkout*, writes to its standard output; raise CalledProcessError if it fails."""
    return subprocess.run(["git", *arguments], cwd=checkout, capture_output=True, text=True, check=True).stdout


def _tracked_symlinks_pointing_outside(checkout: Path) -> dict[str, str]:
    """Map the path of each symlink in *checkout*'s git index whose target leaves the checkout to that target.

    The target is the text the index holds for the link, resolved lexically from the link's own directory.
    """
    outside: dict[str, str] = {}
    for entry in filter(None, _git(checkout, "ls-files", "--stage", "-z").split("\0")):
        metadata, path = entry.split("\t", 1)
        mode, blob, _stage = metadata.split(" ")
        if mode != "120000":
            continue
        target = _git(checkout, "cat-file", "blob", blob)
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), target))
        if posixpath.isabs(resolved) or resolved == ".." or resolved.startswith("../"):
            outside[path] = target
    return outside


def test_no_tracked_symlink_points_outside_the_checkout(project_root: Path) -> None:
    outside = _tracked_symlinks_pointing_outside(project_root)

    assert outside == {}, (
        "these tracked symlinks point outside the checkout, so each resolves to a different place from the main"
        f" checkout and from each worktree under .worktrees/: {outside}; track the content itself, or a symlink"
        " to a path inside the tree"
    )


def test_reports_only_the_symlinks_whose_target_leaves_the_checkout(tmp_path: Path) -> None:
    checkout = tmp_path / "checkout"
    (checkout / "nested").mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=checkout, check=True)
    (checkout / "inside").symlink_to("nested", target_is_directory=True)
    (checkout / "nested" / "up_and_back").symlink_to("../inside", target_is_directory=True)
    (checkout / "climbing").symlink_to("../outside")
    (checkout / "nested" / "climbing_twice").symlink_to("../../outside")
    (checkout / "parent").symlink_to("..", target_is_directory=True)
    (checkout / "absolute").symlink_to("/outside")
    subprocess.run(["git", "add", "--all"], cwd=checkout, check=True)

    assert _tracked_symlinks_pointing_outside(checkout) == {
        "absolute": "/outside",
        "climbing": "../outside",
        "nested/climbing_twice": "../../outside",
        "parent": "..",
    }
