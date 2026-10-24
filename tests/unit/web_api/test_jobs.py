# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the job endpoints: GET /api/jobs/<id>, GET /api/jobs/<id>/progress (an SSE stream) and GET /api/jobs/<id>/results."""

from dataclasses import asdict, replace
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.fleet import calculate_fleet_summary
from solar_challenge.home import calculate_summary
from solar_challenge.web.jobs import JobEvent, JobState
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._sse import SseFrame, parse_sse_events
from tests._web_runs import store_fleet_run, store_home_run

_A_RUNNING_JOB = JobState(
    job_id="job-running",
    run_id="run-running",
    status="running",
    progress_pct=50.0,
    current_step="Simulating",
    message="Running home simulation...",
    created_at="2024-06-01T12:00:00+00:00",
)
_A_COMPLETED_JOB = replace(
    _A_RUNNING_JOB,
    status="completed",
    progress_pct=100.0,
    current_step="Done",
    message="Simulation completed successfully",
)
_A_FAILED_JOB = replace(_A_RUNNING_JOB, status="failed", message="Something went wrong")
_A_CANCELLED_JOB = replace(_A_RUNNING_JOB, status="cancelled", message="Cancelled: its run was deleted")

_FINAL_EVENTS_AND_THEIR_FRAMES = [
    pytest.param(
        JobEvent("complete", _A_COMPLETED_JOB),
        SseFrame(
            "complete",
            {
                "status": "completed",
                "progress_pct": 100.0,
                "current_step": "Done",
                "message": "Simulation completed successfully",
                "run_id": "run-running",
            },
        ),
        id="completed",
    ),
    pytest.param(
        JobEvent("error", _A_FAILED_JOB),
        SseFrame("error", {"status": "failed", "message": "Something went wrong"}),
        id="failed",
    ),
]


class TestGetJobStatus:
    """Tests for GET /api/jobs/<id>."""

    def test_known_job_returns_200(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Known job returns 200 with every field of the state its manager reports, as JSON."""
        resp = client.get("/api/jobs/job-home-001")
        assert resp.status_code == 200
        assert resp.get_json() == asdict(mock_job_manager.job_state.return_value)
        mock_job_manager.job_state.assert_called_with("job-home-001")

    def test_unknown_job_returns_404(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Unknown job_id returns 404."""
        mock_job_manager.job_state.return_value = None
        resp = client.get("/api/jobs/nonexistent-id")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Job not found"}


class TestGetJobProgress:
    """Tests for GET /api/jobs/<id>/progress (SSE endpoint)."""

    def test_is_served_with_the_event_stream_response_policy(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """The job's queued complete event ends the stream at once, so the body can be read whole."""
        resp = client.get("/api/jobs/job-home-001/progress")
        resp.get_data()

        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        assert resp.headers["X-Accel-Buffering"] == "no"

    def test_unknown_job_sends_error_event(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Unknown job sends an SSE error event."""
        mock_job_manager.job_state.return_value = None
        resp = client.get("/api/jobs/unknown-id/progress")
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        body = resp.get_data(as_text=True)
        assert parse_sse_events(body) == [SseFrame("error", {"error": "Job not found"})]
        assert body == 'event: error\ndata: {"error": "Job not found"}\n\n'

    @pytest.mark.parametrize(("final_event", "final_frame"), _FINAL_EVENTS_AND_THEIR_FRAMES)
    def test_each_queued_event_is_sent_named_by_its_type_with_the_fields_of_its_state_the_browser_reads(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, final_event: JobEvent, final_frame: SseFrame
    ) -> None:
        mock_job_manager.job_state.return_value = final_event.state
        mock_job_manager.get_events.return_value = iter([JobEvent("progress", _A_RUNNING_JOB), final_event])

        frames = parse_sse_events(client.get("/api/jobs/job-running/progress").get_data(as_text=True))

        assert frames == [
            SseFrame(
                "progress",
                {
                    "progress_pct": 50.0,
                    "current_step": "Simulating",
                    "message": "Running home simulation...",
                    "status": "running",
                },
            ),
            final_frame,
        ]

    @pytest.mark.parametrize(("final_event", "final_frame"), _FINAL_EVENTS_AND_THEIR_FRAMES)
    def test_a_finished_job_whose_events_another_stream_drained_is_sent_the_frame_of_its_final_event(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, final_event: JobEvent, final_frame: SseFrame
    ) -> None:
        mock_job_manager.job_state.return_value = final_event.state
        mock_job_manager.get_events.return_value = iter([])

        frames = parse_sse_events(client.get("/api/jobs/job-running/progress").get_data(as_text=True))

        assert frames == [final_frame]

    def test_a_cancelled_job_whose_events_another_stream_drained_is_sent_its_final_frame_at_once(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A cancelled job ends its stream as a failed one does, with an error frame."""
        mock_job_manager.job_state.return_value = _A_CANCELLED_JOB
        mock_job_manager.get_events.return_value = iter([])

        response = client.get("/api/jobs/job-running/progress", buffered=False)
        try:
            chunks = iter(response.response)
            first = next(chunks)

            assert parse_sse_events(first.decode()) == [
                SseFrame("error", {"status": "cancelled", "message": "Cancelled: its run was deleted"})
            ]
            assert next(chunks, None) is None
        finally:
            response.close()


class TestGetJobResults:
    """Tests for GET /api/jobs/<id>/results."""

    def test_unknown_job_returns_404(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Unknown job returns 404."""
        mock_job_manager.job_state.return_value = None
        resp = client.get("/api/jobs/nonexistent/results")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Job not found"}

    def test_running_job_returns_409(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A job not yet completed answers 409 with the error, its status and its progress."""
        mock_job_manager.job_state.return_value = _A_RUNNING_JOB
        resp = client.get("/api/jobs/job-running/results")
        assert resp.status_code == 409
        assert resp.get_json() == {"error": "Job not yet completed", "status": "running", "progress_pct": 50.0}

    def test_completed_job_answers_its_run_s_id_name_type_creation_time_and_summary(
        self, storage: RunStorage, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A completed job whose run has a row answers the run's id, name, type, creation time and its summary's field tree."""
        run_id = "run-complete-001"
        mock_job_manager.job_state.return_value = replace(
            _A_RUNNING_JOB, job_id="job-complete", run_id=run_id, status="completed", progress_pct=100.0
        )
        results = make_sim_results(days=1)
        store_home_run(storage, run_id, make_home_config(), results, name="Test Run", created_at="2024-01-01T00:00:00")

        resp = client.get("/api/jobs/job-complete/results")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "run_id": run_id,
            "name": "Test Run",
            "type": "home",
            "created_at": "2024-01-01T00:00:00",
            "summary": asdict(calculate_summary(results)),
        }

    def test_completed_fleet_job_answers_its_run_s_fleet_summary(
        self, storage: RunStorage, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A completed fleet job's run answers its FleetSummary's field tree as its summary."""
        run_id = "fleet-complete-001"
        mock_job_manager.job_state.return_value = replace(
            _A_RUNNING_JOB, job_id="job-complete", run_id=run_id, status="completed", progress_pct=100.0
        )
        fleet = make_fleet_results(n_homes=2, days=1)
        store_fleet_run(storage, run_id, fleet, name="Fleet Run", created_at="2024-01-02T00:00:00")

        resp = client.get("/api/jobs/job-complete/results")
        assert resp.status_code == 200
        assert resp.get_json() == {
            "run_id": run_id,
            "name": "Fleet Run",
            "type": "fleet",
            "created_at": "2024-01-02T00:00:00",
            "summary": asdict(calculate_fleet_summary(fleet)),
        }

    def test_completed_job_missing_run_returns_404(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Completed job with no matching run record returns 404."""
        mock_job_manager.job_state.return_value = replace(
            _A_RUNNING_JOB, job_id="job-complete", run_id="run-does-not-exist", status="completed", progress_pct=100.0
        )
        resp = client.get("/api/jobs/job-complete/results")
        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Run not found"}
