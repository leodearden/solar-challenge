# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins what tests/e2e/conftest.py does with `-n auto`: a session that names the e2e suite runs it in its own process, with or without pytest-xdist registered.

pyproject's addopts pass `-n auto`, so `pytest tests/e2e`, or a file or node-id under it, would start a
worker per core. Every worker would start its own live server and Chromium beside the others', and their
pages would contend for the cores they need to draw. The conftest therefore resolves `auto` to no workers
in a session that runs it as an initial conftest, so the suite runs serially unless the command passes an
explicit `-n N`, which is left as given.

The conftest does so through pytest-xdist's pytest_xdist_auto_num_workers hook. pytest knows that hook only
while pytest-xdist is registered, and a plain implementation of a hook it does not know aborts the session,
as it starts to collect, with a PluginValidationError. So the implementation is optional, and the second
test runs the serial recovery form, `-p no:xdist -o addopts='-v --tb=short'` (CLAUDE.md), which a plain
implementation would abort.
"""

import pytest

pytest.importorskip("flask")

RUNS_IN_THE_SESSIONS_OWN_PROCESS = """\
from xdist import is_xdist_worker


def test_runs_in_the_sessions_own_process(request):
    assert not is_xdist_worker(request)
"""

RUNS_WITHOUT_PYTEST_XDIST_REGISTERED = """\
def test_runs_without_pytest_xdist_registered(request):
    assert not request.config.pluginmanager.hasplugin("xdist")
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


def test_the_e2e_suite_runs_in_the_serial_recovery_form_without_pytest_xdist_registered(
    pytester_laid_out_as_the_e2e_suite: pytest.Pytester,
) -> None:
    """A session that disables pytest-xdist and clears the project's addopts, as dark-factory's serial recovery run does, collects and runs the e2e suite.

    The scenario asks its own session's pluginmanager whether pytest-xdist is
    registered, so a pytest-xdist that `-p no:xdist` no longer disables would
    fail this test instead of leaving it to pass without pinning anything.
    """
    pytester_laid_out_as_the_e2e_suite.makepyfile(**{"e2e/test_scenario": RUNS_WITHOUT_PYTEST_XDIST_REGISTERED})

    result = pytester_laid_out_as_the_e2e_suite.runpytest_subprocess(
        "-p", "no:xdist", "-p", "no:cacheprovider", "-o", "addopts=-v --tb=short", "e2e"
    )

    result.assert_outcomes(passed=1)
