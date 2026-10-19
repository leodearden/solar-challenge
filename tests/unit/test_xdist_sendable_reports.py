# SPDX-License-Identifier: AGPL-3.0-or-later
"""Pins that the job manager's lone-surrogate failure test reports only text a pytest-xdist worker can send.

A pytest-xdist worker sends every report to its controller through execnet.
execnet refuses text that UTF-8 cannot encode, and the worker then crashes, so
the tests still queued on it never run. pytest-xdist is not in uv.lock, so a
pytest session of its own stands in for a worker: its plugin serializes each
report as a worker does and encodes it as execnet does.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")

XDIST_WORKER_STAND_IN = """
    import json


    class SendsEachReportAsAnXdistWorkerDoes:
        def __init__(self, config):
            self.config = config

        def pytest_runtest_logreport(self, report):
            sent = self.config.hook.pytest_report_to_serializable(config=self.config, report=report)
            json.dumps(sent, ensure_ascii=False).encode("utf-8")


    def pytest_configure(config):
        config.pluginmanager.register(SendsEachReportAsAnXdistWorkerDoes(config))
"""

JOB_MANAGER_TESTS = Path("tests/unit/web_jobs/test_job_manager.py")

LONE_SURROGATE_TEST = (
    "TestJobManagerUnrecordedFailures"
    "::test_a_failure_whose_message_sqlite_cannot_store_is_logged_for_each_table_and_still_reported"
)


def test_the_lone_surrogate_failure_test_reports_only_text_an_xdist_worker_can_send(
    pytester: pytest.Pytester, project_root: Path
) -> None:
    """Every report of the lone-surrogate test survives being serialized and encoded as an xdist worker does.

    The sub-session's exit status is checked as well as its outcome: when its
    plugin raises, the session aborts with INTERNALERROR while its summary
    still counts the test as passed.
    """
    stand_in = pytester.makepyfile(sends_each_report_as_an_xdist_worker_does=XDIST_WORKER_STAND_IN)

    result = pytester.runpytest_subprocess(
        f"{project_root / JOB_MANAGER_TESTS}::{LONE_SURROGATE_TEST}", "-p", stand_in.stem, "-p", "no:cacheprovider"
    )

    assert result.ret == pytest.ExitCode.OK
    result.assert_outcomes(passed=1)
