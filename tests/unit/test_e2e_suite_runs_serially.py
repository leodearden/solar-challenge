# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that the e2e suite runs in its pytest session's own process wherever its command omits `-n 0`.

pyproject's addopts pass `-n auto`, so `pytest tests/e2e`, or a file or node-id under it, would start a
worker per core. Every worker would start its own live server and Chromium beside the others', and their
pages would contend for the cores they need to draw. tests/e2e/conftest.py therefore resolves `auto` to no
workers in a session that runs it as an initial conftest. An explicit `-n N` is left as given.
"""

import pytest

pytest.importorskip("flask")

RUNS_IN_THE_SESSIONS_OWN_PROCESS = """\
from xdist import is_xdist_worker


def test_runs_in_the_sessions_own_process(request):
    assert not is_xdist_worker(request)
"""


def test_the_e2e_suite_runs_in_its_sessions_own_process_when_addopts_ask_for_a_worker_per_core(
    pytester_laid_out_as_the_e2e_suite: pytest.Pytester,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A session that reads this project's addopts and runs the e2e conftest as an initial conftest starts no xdist worker, though `auto` would give it a worker per core.

    PYTEST_XDIST_AUTO_NUM_WORKERS=2 stands in for a worker per core. It also
    overrides the "0" that tests/conftest.py's window sets for every test not
    marked slow, which would otherwise resolve `auto` to no workers by itself
    and let this test pass without the hook it pins.

    The scenario asks its own session's config whether it is a worker, because
    PYTEST_XDIST_WORKER in os.environ cannot answer: the verify runs this test on
    a worker, and every session that test starts inherits that worker's variable.
    """
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    pytester_laid_out_as_the_e2e_suite.makepyfile(**{"e2e/test_scenario": RUNS_IN_THE_SESSIONS_OWN_PROCESS})

    result = pytester_laid_out_as_the_e2e_suite.runpytest_subprocess("-p", "no:cacheprovider", "e2e")

    result.assert_outcomes(passed=1)
