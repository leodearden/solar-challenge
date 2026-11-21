# SPDX-License-Identifier: AGPL-3.0-or-later
"""A pytest plugin that roots this project's pytest sessions in a temp root of the project's own, not in the pytest-of-<user> root that every pytest run of the user shares.

A session's exit deletes the numbered dirs beyond pytest's retention count and every garbage-* dir under its
temp root, whichever run left them. In the shared /tmp/pytest-of-<user> those were other projects' xdist
trees, so a session of this project spent its exit deleting them.

Usage: listed in tests/conftest.py's pytest_plugins.
"""

import os
import tempfile
from pathlib import Path

import pytest

TEMP_ROOT_VARIABLE = "PYTEST_DEBUG_TEMPROOT"


def project_temp_root(temp_dir: Path) -> Path:
    """Return the project's temp root in *temp_dir*, named for the user's uid, since pytest makes pytest-of-<user> inside it and a root shared between users would belong to whichever made it first."""
    return temp_dir / f"solar-challenge-pytest-{os.getuid()}"


@pytest.hookimpl(tryfirst=True)
def pytest_configure(config: pytest.Config) -> None:
    """Name the project's temp root in TEMP_ROOT_VARIABLE while *config* is in use, having made the root, in which pytest makes pytest-of-<user> without parents.

    A root the environment already names stands, so the sessions a test starts use their parent's root, and those pytester runs the one pytester names.
    """
    if os.environ.get(TEMP_ROOT_VARIABLE):
        return
    root = project_temp_root(Path(tempfile.gettempdir()))
    root.mkdir(mode=0o700, exist_ok=True)
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    patch.setenv(TEMP_ROOT_VARIABLE, str(root))
