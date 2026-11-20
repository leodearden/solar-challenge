# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that the e2e suite runs in its pytest session's own process wherever its command omits `-n 0`.

pyproject's addopts pass `-n auto`, so `pytest tests/e2e`, or a file or node-id under it, would start a
worker per core. Every worker would start its own live server and Chromium beside the others', and their
pages would contend for the cores they need to draw. tests/e2e/conftest.py therefore resolves `auto` to no
workers in a session that runs it as an initial conftest. An explicit `-n N` is left as given.
"""

import shutil
from pathlib import Path

import pytest

pytest.importorskip("flask")

RUNS_IN_THE_SESSIONS_OWN_PROCESS = """\
from xdist import is_xdist_worker


def test_runs_in_the_sessions_own_process(request):
    assert not is_xdist_worker(request)
"""


def test_the_e2e_suite_runs_in_its_sessions_own_process_when_addopts_ask_for_a_worker_per_core(
    pytester_importing_test_helpers: pytest.Pytester,
    project_root: Path,
    e2e_conftest: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session that reads this project's addopts and runs the e2e conftest as an initial conftest starts no xdist worker, though `auto` would give it a worker per core.

    PYTEST_XDIST_AUTO_NUM_WORKERS=2 stands in for a worker per core. It also
    overrides the "0" that tests/conftest.py's window sets for every test not
    marked slow, which would otherwise resolve `auto` to no workers by itself
    and let this test pass without the hook it pins. The conftest sits in the
    directory the run names, as it does for `pytest tests/e2e`; that directory is
    not named tests/e2e, because a tests directory there would compete with the
    tests package the conftest imports its helpers from.

    The scenario asks its own session's config whether it is a worker, because
    PYTEST_XDIST_WORKER in os.environ cannot answer: the verify runs this test on
    a worker, and every session that test starts inherits that worker's variable.
    """
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    pytester = pytester_importing_test_helpers
    pytester.makepyprojecttoml((project_root / "pyproject.toml").read_text(encoding="utf-8"))
    e2e_directory = pytester.mkdir("e2e")
    shutil.copy(e2e_conftest, e2e_directory / "conftest.py")
    (e2e_directory / "test_scenario.py").write_text(RUNS_IN_THE_SESSIONS_OWN_PROCESS, encoding="utf-8")

    result = pytester.runpytest_subprocess("e2e", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)
