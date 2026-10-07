# SPDX-License-Identifier: AGPL-3.0-or-later
"""A copy of a git checkout's working tree, as a fresh clone would hold it with the checkout's uncommitted edits and new files.

It serves the tests that build or run the project away from the checkout.

Usage::

    from tests._working_tree import copy_working_tree

    source = copy_working_tree(project_root, tmp_path / "source")
"""

import shutil
import subprocess
from pathlib import Path


def copy_working_tree(checkout: Path, destination: Path) -> Path:
    """Copy each file git lists in *checkout*, tracked or untracked but not ignored, to its path under *destination*.

    A tracked file deleted from the tree is not copied, nor is a listed path that
    is not a regular file, such as a worktree's .claude symlink to a directory.
    In a directory git does not know as a checkout, it raises CalledProcessError
    naming the command. Returns *destination*.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    )
    destination.mkdir(parents=True, exist_ok=True)
    for relative_path in filter(None, listing.stdout.split("\0")):
        source = checkout / relative_path
        if source.is_file():
            copied = destination / relative_path
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
    return destination
