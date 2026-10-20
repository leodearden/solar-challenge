# Throwaway probe for task 855's planning; deleted after the measurement runs.
from dataclasses import replace
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.web.jobs import JobState

_RUNNING = JobState(
    job_id="job-running",
    run_id="run-running",
    status="running",
    progress_pct=50.0,
    current_step="Simulating",
    message="Running home simulation...",
    created_at="2024-06-01T12:00:00+00:00",
)


def test_probe_running_409_whole_body(client: FlaskClient, mock_job_manager: NonCallableMagicMock) -> None:
    mock_job_manager.job_state.return_value = _RUNNING
    resp = client.get("/api/jobs/job-running/results")
    assert resp.status_code == 409
    assert resp.get_json() == {"error": "Job not yet completed", "status": "running", "progress_pct": 50.0}


def test_probe_missing_run_body(client: FlaskClient, mock_job_manager: NonCallableMagicMock) -> None:
    mock_job_manager.job_state.return_value = replace(
        _RUNNING, job_id="job-complete", run_id="run-does-not-exist", status="completed", progress_pct=100.0
    )
    resp = client.get("/api/jobs/job-complete/results")
    assert resp.status_code == 404
    assert resp.get_json() == {"error": "Run not found"}
