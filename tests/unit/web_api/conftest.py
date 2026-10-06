# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for the Flask test app the /api endpoint test modules drive, with its JobManager mocked.

mock_job_manager installs a MagicMock whose submit, status and event calls answer at once
with canned values, so no test starts a real simulation. client requests it, so a test
that sends a request runs against the mock unless its module defines its own client.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from tests._web_app import build_test_app

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def mock_job_manager(app: Flask) -> MagicMock:
    """Replace the real JobManager on the app with a MagicMock.

    The mock is pre-configured with sensible return values so that
    tests can focus on request/response behaviour.
    """
    jm = MagicMock()
    jm.submit_home_job.return_value = ("job-home-001", "run-home-001")
    jm.submit_fleet_job.return_value = ("job-fleet-001", "run-fleet-001")
    jm.get_job_status.return_value = {
        "job_id": "job-home-001",
        "run_id": "run-home-001",
        "status": "running",
        "progress_pct": 42.0,
        "current_step": "Simulating",
        "message": "Running home simulation...",
    }
    jm.get_events.return_value = iter([
        {
            "event": "complete",
            "data": {"status": "completed", "run_id": "run-home-001"},
        }
    ])
    app.extensions["job_manager"] = jm
    return jm


@pytest.fixture
def client(app: Flask, mock_job_manager: MagicMock) -> FlaskClient:
    """Create a Flask test client with the mocked JobManager."""
    return app.test_client()
