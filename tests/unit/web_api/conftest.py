# SPDX-License-Identifier: AGPL-3.0-or-later
"""A mocked JobManager for the /api endpoint tests, which tests/unit/conftest.py's app is built on through the jobs fixture, and a client that requests the mock.

mock_job_manager is a mock autospecced to JobManager, whose submit, state and snapshot
calls answer at once with canned values, so no test starts a real simulation. client
requests it, so a test that sends a request runs against the mock unless its module
defines its own client.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import TYPE_CHECKING
from unittest.mock import NonCallableMagicMock

import pytest

from solar_challenge.web.jobs import JobManager, JobSnapshot, JobState
from tests._job_manager_double import autospecced_job_manager

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient

    from solar_challenge.web.storage import RunStorage


@pytest.fixture
def mock_job_manager() -> NonCallableMagicMock:
    """autospecced_job_manager()'s mock, pre-configured with sensible return values so that tests can focus on request/response behaviour."""
    jm = autospecced_job_manager()
    jm.submit_home_job.return_value = ("job-home-001", "run-home-001")
    jm.submit_fleet_job.return_value = ("job-fleet-001", "run-fleet-001")
    running = JobState(
        job_id="job-home-001",
        run_id="run-home-001",
        status="running",
        progress_pct=42.0,
        current_step="Simulating",
        message="Running home simulation...",
        created_at="2024-06-01T12:00:00+00:00",
    )
    jm.job_state.return_value = running
    jm.job_snapshot.return_value = JobSnapshot(
        5,
        replace(
            running,
            status="completed",
            progress_pct=100.0,
            current_step="Done",
            message="Simulation completed successfully",
        ),
    )
    return jm


@pytest.fixture
def jobs(mock_job_manager: NonCallableMagicMock) -> Callable[[RunStorage], JobManager]:
    """Build every app of this package on the mock."""
    return lambda storage: mock_job_manager


@pytest.fixture
def client(app: Flask, mock_job_manager: NonCallableMagicMock) -> FlaskClient:
    """Create a Flask test client with the mocked JobManager."""
    return app.test_client()
