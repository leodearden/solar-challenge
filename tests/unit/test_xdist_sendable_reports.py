# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that the job manager's lone-surrogate failure test reports only text a pytest-xdist worker can send.

A pytest-xdist worker sends each report to its controller through execnet,
which refuses text that UTF-8 cannot encode. The worker then crashes, so the
tests still queued on it never run.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

JOB_MANAGER_TESTS = Path("tests/unit/web_jobs/test_job_manager.py")

LONE_SURROGATE_TEST = (
    "TestJobManagerUnrecordedFailures"
    "::test_a_failure_whose_message_sqlite_cannot_store_is_logged_and_still_reported"
)


def test_the_lone_surrogate_failure_test_reports_only_text_an_xdist_worker_can_send(
    pytester: pytest.Pytester, project_root: Path
) -> None:
    """The lone-surrogate test passes on the one xdist worker of a session of its own, which sends each of its reports.

    The sub-session's output and exit status are checked as well as its outcome:
    a worker crashed by a report it could not send has printed INTERNALERROR and
    'no tests ran', yet exited 0.
    """
    result = pytester.runpytest_subprocess(
        f"{project_root / JOB_MANAGER_TESTS}::{LONE_SURROGATE_TEST}", "-n", "1", "-p", "no:cacheprovider"
    )

    result.assert_outcomes(passed=1)
    assert "INTERNALERROR" not in result.stdout.str()
    assert result.ret == pytest.ExitCode.OK
