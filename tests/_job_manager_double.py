# SPDX-License-Identifier: AGPL-3.0-or-later
"""The test double of the web dashboard's JobManager that the web tests share.

Usage::

    from tests._job_manager_double import autospecced_job_manager

    job_manager = autospecced_job_manager()
    job_manager.submit_home_job.return_value = ("job-1", "run-1")
"""

from unittest.mock import NonCallableMagicMock, create_autospec

from solar_challenge.web.jobs import JobManager


def autospecced_job_manager() -> NonCallableMagicMock:
    """Return a mock autospecced to a JobManager instance, so a test that uses a stale name or makes a wrong call fails.

    Getting an attribute JobManager lacks raises AttributeError, calling a
    method with arguments its signature refuses raises TypeError, and the
    mock itself cannot be called, as a JobManager cannot. Its methods return
    mocks until a test configures them.
    """
    job_manager: NonCallableMagicMock = create_autospec(JobManager, instance=True)
    return job_manager
