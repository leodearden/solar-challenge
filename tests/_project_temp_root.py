# SPDX-License-Identifier: AGPL-3.0-or-later
"""Where this project's pytest sessions keep their temp dirs: in a temp root of the project's own, not in the pytest-of-<user> root that every pytest run of the user shares, and, for those made before any fixture can be asked, in pre_fixture_temp_dir.

A session's exit deletes the numbered dirs beyond pytest's retention count and every garbage-* dir under its
temp root, whichever run left them. In the shared /tmp/pytest-of-<user> those were other projects' xdist
trees, so a session of this project spent its exit deleting them.

Usage: tests/conftest.py's pytest_configure calls name_the_project_temp_root(config) before any other plugin
configures; a hook that runs before any fixture makes its temp dirs in pre_fixture_temp_dir(config).
"""

import os
import stat
import tempfile
from pathlib import Path

import pytest

TEMP_ROOT_VARIABLE = "PYTEST_DEBUG_TEMPROOT"


def project_temp_root(temp_dir: Path) -> Path:
    """Return the project's temp root in *temp_dir*, named for the user's uid, since pytest makes pytest-of-<user> inside it and a root shared between users would belong to whichever made it first."""
    return temp_dir / f"solar-challenge-pytest-{os.getuid()}"


def name_the_project_temp_root(config: pytest.Config) -> None:
    """Name the project's temp root in TEMP_ROOT_VARIABLE while *config* is in use, having made the root, in which pytest makes pytest-of-<user> without parents.

    A root the environment already names stands, so the sessions a test starts use their parent's root, and those pytester runs the one pytester names.
    """
    if os.environ.get(TEMP_ROOT_VARIABLE):
        return
    root = project_temp_root(Path(tempfile.gettempdir()))
    _make_private_root(root)
    patch = pytest.MonkeyPatch()
    config.add_cleanup(patch.undo)
    patch.setenv(TEMP_ROOT_VARIABLE, str(root))


def worker_run_basetemp(config: pytest.Config) -> Path | None:
    """Return the run's basetemp if *config* is an xdist worker's whose controller gave it a basetemp, else None.

    That is the parent of the worker's basetemp, the controller's, which the controller made before it started the
    worker and pytest's retention reaps. The worker's own is emptied at its first getbasetemp(), which can come after
    a hook made a dir in it.
    """
    if not hasattr(config, "workerinput"):
        return None
    given = config.getoption("basetemp")
    return None if given is None else Path(given).parent


def pre_fixture_temp_dir(config: pytest.Config) -> Path:
    """Return the dir in which code that runs before any fixture can be asked makes its temp dirs in *config*'s session: on an xdist worker the run's basetemp, else the session's temp root, which TEMP_ROOT_VARIABLE names.

    Raise RuntimeError if TEMP_ROOT_VARIABLE names none, since name_the_project_temp_root names one for the session's
    lifetime.
    """
    run_basetemp = worker_run_basetemp(config)
    if run_basetemp is not None:
        return run_basetemp
    root = os.environ.get(TEMP_ROOT_VARIABLE)
    if not root:
        raise RuntimeError(
            f"{TEMP_ROOT_VARIABLE} names no temp root, though name_the_project_temp_root names one for the session's "
            "lifetime: something unset it, or no pytest_configure of the session called it"
        )
    return Path(root)


def _make_private_root(root: Path) -> None:
    """Make *root* a directory of this user's closed to other users, as pytest makes the pytest-of-<user> inside it, or raise OSError naming *root* when it is a symbolic link or another user's, since whoever controls it could swap that pytest-of-<user> after pytest has checked it."""
    root.mkdir(mode=0o700, exist_ok=True)
    root_stat = root.lstat()
    uid = os.getuid()
    if stat.S_ISLNK(root_stat.st_mode):
        raise OSError(
            f"The temp root {root} is a symbolic link, so whoever made the link chose where pytest makes this "
            f"session's temp dirs: name another root in {TEMP_ROOT_VARIABLE}"
        )
    if root_stat.st_uid != uid:
        raise OSError(
            f"The temp root {root} belongs to uid {root_stat.st_uid}, not to uid {uid}, so its owner could swap the "
            f"temp dirs pytest makes in it: name another root in {TEMP_ROOT_VARIABLE}"
        )
    if root_stat.st_mode & 0o077:
        root.chmod(stat.S_IMODE(root_stat.st_mode) & ~0o077)
