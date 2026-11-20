# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins on how the suite runs on pytest-xdist workers."""

import pytest


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
    """A session that a test not marked slow starts with `-n auto`, as a copy of pyproject's addopts gives it, starts no workers.

    The suite already spreads its tests over every core. A child session that
    started a worker per core multiplied the run's CPU, 1853 s against 1195 s,
    and broke the tests that count a session's outcomes: errors=32, doubled
    rerun counts, and e2e-conftest scenarios whose second test needs the first.
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


@pytest.mark.xfail(
    strict=True,
    reason=(
        "pytest 9.2's Node.nodeid reads its structured NodeId, while pytest-xdist 3.8.0 appends the group to "
        "item._nodeid, which nothing reads, so --dist loadgroup schedules a group's tests as --dist load does"
    ),
)
def test_the_tests_of_an_xdist_group_run_on_one_worker(pytester: pytest.Pytester) -> None:
    """Under `--dist loadgroup`, the tests sharing an xdist_group run on one worker, as tests/integration/test_external_install.py asks for its wheel build.

    Strict, so a release that honours the group again fails it, in the
    newest-releases lane first; then the caveats in that module's docstring
    and in CLAUDE.md go with the xfail.
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
    assert len({path.read_text() for path in pytester.path.glob("worker-of-case-*")}) == 1
