# SPDX-License-Identifier: AGPL-3.0-or-later
"""The files a pointer gate scans in a git checkout, and how it reads them.

A pointer gate checks that the paths the scanned files name are in the tree. It scans every file git lists in the
checkout, as tests/_working_tree.py's working_tree_files lists them, except the paths it leaves unscanned. Among those
are RECORD_DIRECTORIES, which hold the records: they name files as they were when written, so a pointer from one is
history, not a claim about the tree. A file that is not UTF-8 text holds no pointer.

Usage::

    from tests._pointer_scan import RECORD_DIRECTORIES, scanned_files, utf8_text

    for source in scanned_files(project_root, (PurePosixPath("tests"), *RECORD_DIRECTORIES)):
        text = utf8_text(project_root / source)
"""

from collections.abc import Collection
from pathlib import Path, PurePosixPath

from tests._working_tree import working_tree_files

RECORD_DIRECTORIES = tuple(PurePosixPath(directory) for directory in ("docs/prds", "docs/research", "plans", "review"))


def scanned_files(checkout: Path, unscanned: Collection[PurePosixPath]) -> list[PurePosixPath]:
    """Return the files working_tree_files lists in *checkout*, in its order, but those at or under an *unscanned* path."""
    return [path for path in working_tree_files(checkout) if not any(path.is_relative_to(entry) for entry in unscanned)]


def utf8_text(path: Path) -> str | None:
    """Return the text of the file at *path*, or None if it is not UTF-8."""
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        return None
