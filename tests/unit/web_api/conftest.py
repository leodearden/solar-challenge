# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for the Flask test app the /api endpoint test modules drive, with its JobManager mocked.

mock_job_manager installs a mock autospecced to JobManager, whose submit, state and event
calls answer at once with canned values, so no test starts a real simulation. client
requests it, so a test that sends a request runs against the mock unless its module
defines its own client.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import NonCallableMagicMock, create_autospec

import pytest

from solar_challenge.web.jobs import JobEvent, JobManager, JobState
from tests._web_app import build_test_app

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def mock_job_manager(app: Flask) -> NonCallableMagicMock:
    """Replace the real JobManager on the app with a mock autospecced to it.

    The mock has JobManager's interface: configuring or calling an attribute
    JobManager lacks raises AttributeError, and calling a method with arguments
    its signature refuses raises TypeError. It is pre-configured with sensible
    return values so that tests can focus on request/response behaviour.
    """
    jm = create_autospec(JobManager, instance=True)
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
    jm.get_events.return_value = iter([
        JobEvent(
            "complete",
            replace(
                running,
                status="completed",
                progress_pct=100.0,
                current_step="Done",
                message="Simulation completed successfully",
            ),
        )
    ])
    app.extensions["job_manager"] = jm
    return jm


@pytest.fixture
def client(app: Flask, mock_job_manager: NonCallableMagicMock) -> FlaskClient:
    """Create a Flask test client with the mocked JobManager."""
    return app.test_client()
