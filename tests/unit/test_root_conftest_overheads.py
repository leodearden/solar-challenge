# SPDX-License-Identifier: AGPL-3.0-or-later
"""The work the root conftest adds to every pytest process the suite starts."""

import gc
import subprocess
import sys
from pathlib import Path

import pytest

_SIMULATION_STACK = ("pandas", "pvlib", "scipy", "solar_challenge.weather")

_MARKERS_WITH_MODULES_BLOCKED = """\
import sys

for name in sys.argv[1:]:
    sys.modules[name] = None

import pytest

raise SystemExit(pytest.main(["--markers", "-p", "no:cacheprovider"]))
"""


def test_a_session_that_runs_no_test_never_imports_the_simulation_stack(project_root: Path) -> None:
    result = subprocess.run(
        [sys.executable, "-c", _MARKERS_WITH_MODULES_BLOCKED, *_SIMULATION_STACK],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"`pytest --markers` exited {result.returncode} with {', '.join(_SIMULATION_STACK)} "
        "blocked. Every child pytest session the suite starts loads tests/conftest.py, and a "
        "session that opens no offline window, such as a collect-only probe or --markers, "
        "should not pay ~3 s CPU to import pandas, pvlib and scipy.\n"
        f"{result.stderr}{result.stdout[-2000:]}"
    )


def test_the_heap_collection_built_is_frozen_before_the_first_test(
    request: pytest.FixtureRequest,
) -> None:
    item = request.node
    assert not any(tracked is item for tracked in gc.get_objects()), (
        f"{item.nodeid}, built by collection, is among the objects the collector scans: "
        "nothing froze the heap collection built, so the imported modules and the ~5,400 "
        "test items and their stashes stay in the generations every full collection "
        "rescans. Unfrozen, the verify selection spent 37 s in GC, 29.9 s of it in 76 "
        "full collections over a ~1 GB heap."
    )
