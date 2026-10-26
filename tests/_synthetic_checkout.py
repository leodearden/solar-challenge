# SPDX-License-Identifier: AGPL-3.0-or-later
"""A throwaway git checkout for a test, holding the files the test lays out in it.

It is tests/_hermetic_checkout.py's checkout, so git lists each file laid out in it, untracked, whatever the user's or
the system's git configuration excludes.

Usage::

    from tests._synthetic_checkout import synthetic_checkout, write_file

    checkout = synthetic_checkout(tmp_path, {"README.md": "# Title", "src/pkg/logo.png": b"PNG"})
    source = write_file(checkout, "src/pkg/module.py", "VALUE = 1")
"""

from collections.abc import Mapping
from pathlib import Path, PurePosixPath

from tests._hermetic_checkout import init_hermetic_checkout


def synthetic_checkout(directory: Path, files: Mapping[str, str | bytes]) -> Path:
    """Make *directory* a new hermetic git checkout holding *files*, and return it.

    Each of *files* maps a POSIX path relative to *directory* to the content write_file writes there.
    """
    checkout = init_hermetic_checkout(directory)
    for path, content in files.items():
        write_file(checkout, path, content)
    return checkout


def write_file(checkout: Path, path: str, content: str | bytes) -> PurePosixPath:
    """Write *content* to *path*, a POSIX path relative to *checkout*, making its missing directories; return *path*.

    Text is written as UTF-8, and bytes as they are. An absolute *path*, or one holding a '..', is refused with
    ValueError before anything is written: git lists no file by it.
    """
    relative = PurePosixPath(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"write_file takes a path relative to the checkout {checkout}, without '..', not {path}")
    written = checkout / relative
    written.parent.mkdir(parents=True, exist_ok=True)
    written.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
    return relative
