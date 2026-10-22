# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files of a git checkout's working tree, as a fresh clone would hold them with the checkout's uncommitted edits and new files.

They serve the tests that build or run the project away from the checkout, and those that read every file of the project.

Usage::

    from tests._working_tree import copy_working_tree, working_tree_files

    source = copy_working_tree(project_root, tmp_path / "source")
    package_files = [path for path in working_tree_files(project_root) if path.is_relative_to("src/solar_challenge")]
"""

import shutil
import subprocess
from pathlib import Path, PurePosixPath


def working_tree_files(checkout: Path) -> list[PurePosixPath]:
    """List each regular file git lists in *checkout*, tracked or untracked but not ignored, relative to *checkout*.

    A tracked file deleted from the tree is left out, and so is a listed path
    that is not a regular file, such as a symlink to a directory.
    In a directory git does not know as a checkout, it raises CalledProcessError
    naming the command.
    """
    listing = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=checkout,
        capture_output=True,
        text=True,
        check=True,
    )
    return [PurePosixPath(path) for path in filter(None, listing.stdout.split("\0")) if (checkout / path).is_file()]


def copy_working_tree(checkout: Path, destination: Path) -> Path:
    """Copy each of *checkout*'s working_tree_files to the same path under *destination*, and return *destination*."""
    relative_paths = working_tree_files(checkout)
    destination.mkdir(parents=True, exist_ok=True)
    for relative_path in relative_paths:
        copied = destination / relative_path
        copied.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(checkout / relative_path, copied)
    return destination
