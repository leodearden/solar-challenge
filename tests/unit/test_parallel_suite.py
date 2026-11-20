# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins on how the suite runs on pytest-xdist workers."""

import pytest


def test_a_console_the_cli_builds_at_import_follows_a_columns_set_after_it_on_an_xdist_worker(
    pytester_under_root_conftest: pytest.Pytester,
) -> None:
    """An xdist worker starts with COLUMNS=80 and LINES=24 in its environment, which a serial session lacks, and rich.Console fixes its width from COLUMNS when it is built.

    They come from the controller: pytest imports readline at startup, which
    exports them to every child started without an environment of its own, as
    execnet starts each worker. So the CLI's module-level consoles would ignore
    the COLUMNS a CliRunner test passes. tests/unit/test_cli_web_store_versions.py
    and tests/integration/test_web_store_upgrade.py failed that way under -n auto.
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
