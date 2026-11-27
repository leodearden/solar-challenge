# SPDX-License-Identifier: AGPL-3.0-or-later
"""A throwaway lane project that logs each collection of its lane job, for tests that count how often the job was collected.

It is a tests/_throwaway_lane_project.py project whose PROBE_JOB runs this
interpreter's pytest on its one test module, test_kept.py, beside a conftest
that appends a line to the project's log each time a collection loads it.
collections_logged counts those lines.

Usage::

    from tests._lane_project_logging_each_collection import (
        collections_logged,
        throwaway_lane_project_logging_each_collection,
    )
    from tests._throwaway_lane_project import PROBE_JOB

    project_root = throwaway_lane_project_logging_each_collection(tmp_path)
    collection = collect_lane_job(project_root, PROBE_JOB, env_for=lambda command: os.environ)
    assert collection.node_ids() == ("test_kept.py::test_case",)
    assert collections_logged(project_root) == 1
"""

import shlex
import sys
from pathlib import Path

from tests._throwaway_lane_project import throwaway_lane_project

_TEST_MODULE = "test_kept.py"

_COLLECTIONS_LOG = "collections.log"

_ONE_PASSING_TEST = "def test_case():\n    pass\n"

_APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG = f"""\
from pathlib import Path

with (Path(__file__).parent / {_COLLECTIONS_LOG!r}).open("a", encoding="utf-8") as log:
    log.write("collected\\n")
"""


def throwaway_lane_project_logging_each_collection(root: Path, test_module_source: str = _ONE_PASSING_TEST) -> Path:
    """Make *root* a throwaway_lane_project whose PROBE_JOB collects test_kept.py, written from *test_module_source*.

    By default test_kept.py holds one passing test, test_case. The project's
    conftest logs each collection that loads it, for collections_logged to count.
    """
    throwaway_lane_project(root, f"{shlex.quote(sys.executable)} -m pytest -p no:cacheprovider {_TEST_MODULE}")
    (root / _TEST_MODULE).write_text(test_module_source, encoding="utf-8")
    (root / "conftest.py").write_text(_APPENDS_A_LINE_TO_THE_COLLECTIONS_LOG, encoding="utf-8")
    return root


def collections_logged(root: Path) -> int:
    """Return how many collections the conftest of *root*, a throwaway_lane_project_logging_each_collection, logged: 0 when it logged none."""
    log = root / _COLLECTIONS_LOG
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0
