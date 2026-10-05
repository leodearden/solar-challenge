# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the job endpoints: GET /api/jobs/<id>, GET /api/jobs/<id>/progress (an SSE stream) and GET /api/jobs/<id>/results."""

import json
from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.database import get_db


class TestGetJobStatus:
    """Tests for GET /api/jobs/<id>."""

    def test_known_job_returns_200(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Known job returns 200 with correct status JSON."""
        resp = client.get("/api/jobs/job-home-001")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["job_id"] == "job-home-001"
        assert data["status"] == "running"
        assert data["progress_pct"] == 42.0
        assert data["current_step"] == "Simulating"
        mock_job_manager.get_job_status.assert_called_with("job-home-001")

    def test_unknown_job_returns_404(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Unknown job_id returns 404."""
        mock_job_manager.get_job_status.return_value = None
        resp = client.get("/api/jobs/nonexistent-id")
        assert resp.status_code == 404
        assert "error" in resp.get_json()

    def test_completed_job_status(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Completed job returns status='completed'."""
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-done",
            "run_id": "run-done",
            "status": "completed",
            "progress_pct": 100.0,
            "current_step": "Done",
            "message": "Simulation completed successfully",
        }
        resp = client.get("/api/jobs/job-done")
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "completed"

    def test_failed_job_status(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Failed job returns status='failed' with message."""
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-fail",
            "run_id": "run-fail",
            "status": "failed",
            "progress_pct": 20.0,
            "current_step": "Simulating",
            "message": "Something went wrong",
        }
        resp = client.get("/api/jobs/job-fail")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["status"] == "failed"
        assert "wrong" in data["message"]


class TestGetJobProgress:
    """Tests for GET /api/jobs/<id>/progress (SSE endpoint)."""

    def test_returns_event_stream_content_type(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """SSE endpoint returns text/event-stream Content-Type."""
        resp = client.get("/api/jobs/job-home-001/progress")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

    def test_no_cache_header(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """SSE response includes Cache-Control: no-cache header."""
        resp = client.get("/api/jobs/job-home-001/progress")
        assert resp.headers.get("Cache-Control") == "no-cache"

    def test_unknown_job_sends_error_event(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Unknown job sends an SSE error event."""
        mock_job_manager.get_job_status.return_value = None
        resp = client.get("/api/jobs/unknown-id/progress")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        body = resp.get_data(as_text=True)
        assert "event: error" in body
        assert "Job not found" in body

    def test_completed_job_sends_complete_event(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Completed job with no queued events sends a complete event."""
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-done",
            "run_id": "run-done",
            "status": "completed",
            "progress_pct": 100.0,
            "current_step": "Done",
            "message": "Done",
        }
        # No events in queue
        mock_job_manager.get_events.return_value = iter([])
        resp = client.get("/api/jobs/job-done/progress")
        body = resp.get_data(as_text=True)
        assert "event: complete" in body

    def test_queued_events_are_streamed(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Events from job queue are streamed as SSE."""
        mock_job_manager.get_events.return_value = iter([
            {
                "event": "progress",
                "data": {"progress_pct": 50.0, "message": "Half done"},
            },
            {
                "event": "complete",
                "data": {"status": "completed", "run_id": "run-home-001"},
            },
        ])
        resp = client.get("/api/jobs/job-home-001/progress")
        body = resp.get_data(as_text=True)
        assert "event: progress" in body
        assert "Half done" in body
        assert "event: complete" in body


class TestGetJobResults:
    """Tests for GET /api/jobs/<id>/results."""

    def test_unknown_job_returns_404(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Unknown job returns 404."""
        mock_job_manager.get_job_status.return_value = None
        resp = client.get("/api/jobs/nonexistent/results")
        assert resp.status_code == 404

    def test_running_job_returns_409(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Running job returns 409 (conflict)."""
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-running",
            "run_id": "run-running",
            "status": "running",
            "progress_pct": 50.0,
        }
        resp = client.get("/api/jobs/job-running/results")
        assert resp.status_code == 409
        data = resp.get_json()
        assert "not yet completed" in data["error"]
        assert data["status"] == "running"

    def test_completed_job_returns_summary(
        self, app: Flask, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Completed job with a matching run record returns summary data."""
        run_id = "run-complete-001"
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-complete",
            "run_id": run_id,
            "status": "completed",
            "progress_pct": 100.0,
        }
        # Insert a run row into the test database so the results endpoint
        # can retrieve it.
        db_path = app.config["DATABASE"]
        summary = {"total_generation_kwh": 1234.5, "self_consumption_pct": 45.0}
        with get_db(db_path) as conn:
            conn.execute(
                "INSERT INTO runs (id, name, type, summary_json, status, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (run_id, "Test Run", "home", json.dumps(summary), "completed", "2024-01-01T00:00:00"),
            )

        resp = client.get("/api/jobs/job-complete/results")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["run_id"] == run_id
        assert data["name"] == "Test Run"
        assert data["summary"]["total_generation_kwh"] == 1234.5

    def test_completed_job_missing_run_returns_404(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Completed job with no matching run record returns 404."""
        mock_job_manager.get_job_status.return_value = {
            "job_id": "job-complete",
            "run_id": "run-does-not-exist",
            "status": "completed",
            "progress_pct": 100.0,
        }
        resp = client.get("/api/jobs/job-complete/results")
        assert resp.status_code == 404
