# SPDX-License-Identifier: AGPL-3.0-or-later
"""The work the root conftest adds to every pytest process the suite starts."""

import gc
import subprocess
import sys
from pathlib import Path

import pytest

_SIMULATION_STACK = ("pandas", "pvlib", "scipy", "solar_challenge.weather")

_LIST_FIXTURES_WITH_MODULES_BLOCKED = """\
import sys

test_module, *blocked = sys.argv[1:]
for name in blocked:
    sys.modules[name] = None

import pytest

raise SystemExit(pytest.main(["--fixtures", "-p", "no:cacheprovider", test_module]))
"""


def test_a_session_that_runs_no_test_never_imports_the_simulation_stack(project_root: Path) -> None:
    """`pytest --fixtures` runs no test; it lists this module's alone, since unrestricted it imports every test module."""
    result = subprocess.run(
        [sys.executable, "-c", _LIST_FIXTURES_WITH_MODULES_BLOCKED, __file__, *_SIMULATION_STACK],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode == 0, (
        f"`pytest --fixtures` exited {result.returncode} with {', '.join(_SIMULATION_STACK)} "
        "blocked. Every child pytest session the suite starts loads tests/conftest.py, and a "
        "session that opens no offline window, such as a collect-only probe or --markers, "
        "should not pay ~3 s CPU to import pandas, pvlib and scipy.\n"
        f"{result.stderr}{result.stdout[-2000:]}"
    )
    assert "weather_cache" in result.stdout, (
        "`pytest --fixtures` listed no weather_cache, so the session never loaded "
        "tests/conftest.py, and nothing tried to import it with the simulation stack blocked.\n"
        f"{result.stdout[-2000:]}"
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


def test_a_session_nested_in_this_run_leaves_its_heap_unfrozen(
    pytester_under_root_conftest: pytest.Pytester,
) -> None:
    """An in-process pytester session, which plain runpytest() starts, shares this run's heap, already frozen once."""
    created_by_this_test: list[object] = []

    nested = pytester_under_root_conftest.runpytest_inprocess("--fixtures", "-p", "no:cacheprovider")

    assert "weather_cache" in nested.stdout.str(), (
        "the nested session listed no weather_cache, so it never loaded the copy of "
        f"tests/conftest.py whose freeze this test is about (exit {nested.ret}).\n{nested.stdout.str()[-2000:]}"
    )
    assert any(tracked is created_by_this_test for tracked in gc.get_objects()), (
        "a session nested in this run, under a copy of tests/conftest.py, froze the heap again, "
        "with this test's own objects in it. Nothing frees a frozen object, so the garbage the "
        "run's live objects become would stay for the rest of the run: a process freezes its "
        "heap once, after its first collection."
    )
