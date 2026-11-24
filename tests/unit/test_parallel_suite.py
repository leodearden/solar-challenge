# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins on how the suite runs on pytest-xdist workers."""

from pathlib import Path

import pytest

from tests._orchestrator_config import pytest_arguments, verify_command, verify_env


def test_a_console_the_cli_builds_at_import_follows_a_columns_set_after_it_on_an_xdist_worker(
    pytester_under_root_conftest: pytest.Pytester,
) -> None:
    """An xdist worker would start with COLUMNS=80 and LINES=24 in os.environ, which a serial session's lacks, and rich.Console fixes its width from COLUMNS when it is built.

    They come from the controller: pytest imports readline at startup, which
    sets them in the C environment, and every child started without an
    environment of its own inherits that, as execnet starts each worker. So the
    CLI's module-level consoles would ignore the COLUMNS a CliRunner test passes.
    tests/unit/test_cli_web_store_versions.py and
    tests/integration/test_web_store_upgrade.py failed that way under -n auto.
    """
    pytester_under_root_conftest.makepyfile(
        """
        from solar_challenge.cli.utils import error_console


        def test_the_error_console_is_as_wide_as_columns_says(monkeypatch):
            monkeypatch.setenv("COLUMNS", "1000")
            assert error_console.width == 1000
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-n", "1", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)


@pytest.mark.parametrize("workers", ["0", "1"], ids=["serially", "on-a-worker"])
def test_a_child_a_test_starts_inherits_no_terminal_size(
    pytester_under_root_conftest: pytest.Pytester, workers: str
) -> None:
    """A child that a test starts with no environment of its own inherits neither COLUMNS nor LINES, serially as on a worker.

    readline, which pytest imports at startup, sets both in the C environment
    beneath os.environ, and such a child inherits that environment.
    """
    pytester_under_root_conftest.makepyfile(
        """
        import json
        import subprocess
        import sys

        REPORTS_ITS_TERMINAL_SIZE = (
            "import json, os; print(json.dumps({name: os.environ.get(name) for name in ('COLUMNS', 'LINES')}))"
        )


        def test_starts_a_child_with_no_terminal_size():
            child = subprocess.run(
                [sys.executable, "-c", REPORTS_ITS_TERMINAL_SIZE], capture_output=True, text=True, check=True
            )

            assert json.loads(child.stdout) == {"COLUMNS": None, "LINES": None}
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-n", workers, "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)


def test_a_pytest_session_a_test_not_marked_slow_starts_runs_n_auto_in_its_own_process(pytester: pytest.Pytester) -> None:
    """A session that a test not marked slow starts with `-n auto`, as a test that runs the verify's test command verbatim passes it, starts no workers.

    The verify already spreads the suite over workers. A child session that
    started a worker per core would multiply the run's workers, and would break
    the tests that count a session's outcomes or need its tests run in order.
    """
    pytester.makepyfile(
        """
        from xdist import is_xdist_worker


        def test_runs_in_the_sessions_own_process(request):
            assert not is_xdist_worker(request)
        """
    )

    result = pytester.runpytest_subprocess("-n", "auto", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)


def test_a_pytest_session_a_slow_test_starts_runs_n_auto_on_workers(
    pytester_under_root_conftest: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session that a slow test starts with `-n auto` starts workers, so the lanes' slow tests run the verify suite on workers, as the verify runs it.

    The slow test runs under a copy of the root conftest, without the variable
    this test's own window sets, and `--maxprocesses 1` caps its session at one
    worker.
    """
    monkeypatch.delenv("PYTEST_XDIST_AUTO_NUM_WORKERS", raising=False)
    pytester_under_root_conftest.makepyfile(
        """
        import pytest


        @pytest.mark.slow
        def test_starts_a_session_whose_test_runs_on_a_worker(pytester):
            pytester.makepyfile(
                '''
                from xdist import is_xdist_worker


                def test_runs_on_a_worker(request):
                    assert is_xdist_worker(request)
                '''
            )

            result = pytester.runpytest_subprocess("-n", "auto", "--maxprocesses", "1", "-p", "no:cacheprovider")

            result.assert_outcomes(passed=1)
        """
    )

    result = pytester_under_root_conftest.runpytest_subprocess("-p", "no:cacheprovider")

    result.assert_outcomes(passed=1)


def test_a_pytest_session_that_reads_the_project_ini_and_passes_no_n_runs_in_its_own_process(
    pytester: pytest.Pytester, pytester_sessions_read_the_project_ini: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A session that reads this project's pytest ini and passes no `-n` starts no xdist worker, though `auto` would give it two.

    So an agent's or a person's pytest run rooted at the repo never starts a
    worker per core of the shared host; the verify's test command asks for its
    workers itself.

    PYTEST_XDIST_AUTO_NUM_WORKERS=2 stands in for a worker per core. It also
    overrides the "0" that tests/conftest.py's window sets for every test not
    marked slow, which would otherwise resolve an `-n auto` in the ini's addopts
    to no workers by itself and let this test pass without pinning the ini.

    The scenario asks its own session's config whether it is a worker, because
    PYTEST_XDIST_WORKER in os.environ cannot answer: the verify runs this test on
    a worker, and every session that test starts inherits that worker's variable.
    The session names the scenario's module, since the ini's testpaths name a
    tests/ directory pytester's lacks.
    """
    monkeypatch.setenv("PYTEST_XDIST_AUTO_NUM_WORKERS", "2")
    scenario = pytester.makepyfile(
        """
        from xdist import is_xdist_worker


        def test_runs_in_the_sessions_own_process(request):
            assert not is_xdist_worker(request)
        """
    )

    result = pytester.runpytest_subprocess("-p", "no:cacheprovider", scenario)

    result.assert_outcomes(passed=1)


def test_the_verify_test_command_spreads_the_suite_over_xdist_workers_by_xdist_group(project_root: Path) -> None:
    """The verify's test command passes pytest `-n auto --dist loadgroup`, so the verify runs the suite on pytest-xdist workers, scheduled by xdist_group."""
    test_command = verify_command(project_root, "test_command")
    arguments = pytest_arguments(test_command)
    adjacent_arguments = set(zip(arguments, arguments[1:]))
    missing = [f"`{' '.join(pair)}`" for pair in [("-n", "auto"), ("--dist", "loadgroup")] if pair not in adjacent_arguments]

    assert not missing, (
        f"the {test_command.label} {test_command.command!r} does not pass pytest {' and '.join(missing)}. Without "
        "`-n auto`, the verify, and the interpreter-matrix and newest-releases lanes that re-run its suite verbatim, "
        "run serially, since pyproject's addopts start no worker; without `--dist loadgroup`, an xdist_group mark "
        "asks for nothing"
    )


def test_the_verify_env_caps_the_workers_n_auto_starts(project_root: Path) -> None:
    """dark-factory-orchestrator.yaml's verify_env sets PYTEST_XDIST_AUTO_NUM_WORKERS to a positive count, so `-n auto` in a verify never takes one worker per core of the shared workstation."""
    cap = verify_env(project_root).get("PYTEST_XDIST_AUTO_NUM_WORKERS")

    assert cap is not None and cap.isdecimal() and int(cap) > 0, (
        f"dark-factory-orchestrator.yaml's verify_env sets PYTEST_XDIST_AUTO_NUM_WORKERS to {cap!r} (None if it "
        "sets none), not a positive count of workers, so the verify test command's `-n auto` takes one worker per "
        "host core, and every concurrent verify on the shared workstation does so at once"
    )


def test_dist_loadgroup_spreads_the_tests_of_an_xdist_group_over_workers(pytester: pytest.Pytester) -> None:
    """Under `--dist loadgroup`, the tests sharing an xdist_group are spread over the workers as ungrouped tests are, so no test may need a group to pass.

    pytest 9.2's Node.nodeid reads its structured NodeId, while pytest-xdist
    3.8.0 appends the group to item._nodeid, which nothing reads, so the
    scheduler never sees the group. A release that honours it again fails this
    test, in the newest-releases lane first.
    """
    pytester.makepyfile(
        """
        from pathlib import Path

        import pytest

        pytestmark = pytest.mark.xdist_group("shared")


        @pytest.mark.parametrize("case", range(4))
        def test_records_its_worker(case, worker_id):
            (Path(__file__).parent / f"worker-of-case-{case}").write_text(worker_id)
        """
    )

    result = pytester.runpytest_subprocess("-n", "2", "--dist", "loadgroup", "-p", "no:cacheprovider")

    result.assert_outcomes(passed=4)
    workers = sorted({path.read_text() for path in pytester.path.glob("worker-of-case-*")})
    assert workers == ["gw0", "gw1"], (
        f"the four tests of one xdist_group ran on {workers}: a release honours the group again, so lock it, "
        "drop the caveat in CLAUDE.md's parallel-suite bullet, and assert here that the four share one worker"
    )
