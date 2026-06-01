"""Tests for the API blueprint endpoints with mocked JobManager.

Tests all endpoints in solar_challenge.web.api without running real
simulations.  The JobManager is mocked so that submit/status/event
calls return canned responses instantly.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


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


# ---------------------------------------------------------------------------
# Valid home config payload reused across tests
# ---------------------------------------------------------------------------

VALID_HOME_PAYLOAD: dict = {
    "pv_kw": 4.0,
    "battery_kwh": 5.0,
    "occupants": 3,
    "location": "bristol",
    "days": 7,
    "name": "Test Home",
}

VALID_FLEET_PAYLOAD: dict = {
    "name": "Test Fleet",
    "homes": [
        {
            "pv_kw": 4.0,
            "battery_kwh": 5.0,
            "occupants": 3,
            "location": "bristol",
            "days": 7,
        },
        {
            "pv_kw": 3.0,
            "battery_kwh": 0,
            "occupants": 2,
            "location": "london",
            "days": 7,
        },
    ],
}


# ===================================================================
# POST /api/simulate/home
# ===================================================================


class TestSimulateHomeAPI:
    """Tests for POST /api/simulate/home."""

    def test_valid_config_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid JSON body returns 201 with job_id and run_id."""
        resp = client.post("/api/simulate/home", json=VALID_HOME_PAYLOAD)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["job_id"] == "job-home-001"
        assert data["run_id"] == "run-home-001"
        mock_job_manager.submit_home_job.assert_called_once()

    def test_default_values_accepted(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with empty JSON uses defaults and still returns 201."""
        resp = client.post("/api/simulate/home", json={})
        assert resp.status_code == 201

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST without JSON content type returns 400."""
        resp = client.post(
            "/api/simulate/home",
            data="not-json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "JSON" in data["error"]

    def test_invalid_pv_too_low_returns_400(self, client: FlaskClient) -> None:
        """PV capacity below 0.5 kW triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "pv_kw": 0.1},
        )
        assert resp.status_code == 400
        assert "PV capacity" in resp.get_json()["error"]

    def test_invalid_pv_too_high_returns_400(self, client: FlaskClient) -> None:
        """PV capacity above 20 kW triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "pv_kw": 25.0},
        )
        assert resp.status_code == 400
        assert "PV capacity" in resp.get_json()["error"]

    def test_negative_battery_returns_400(self, client: FlaskClient) -> None:
        """Negative battery capacity triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "battery_kwh": -1.0},
        )
        assert resp.status_code == 400
        assert "Battery" in resp.get_json()["error"] or "negative" in resp.get_json()["error"]

    def test_days_365_sets_full_year(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Setting days=365 should use the full-year date range."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "days": 365},
        )
        assert resp.status_code == 201
        # The start_date and end_date are passed to submit_home_job
        call_kwargs = mock_job_manager.submit_home_job.call_args
        start = call_kwargs.kwargs.get("start_date") or call_kwargs[1].get("start_date")
        # call_args may be positional or keyword; handle either
        if start is None:
            # positional: config, start_date, end_date, ...
            start = call_kwargs[0][1]
            end = call_kwargs[0][2]
        else:
            end = call_kwargs.kwargs.get("end_date") or call_kwargs[1].get("end_date")
        assert str(start.date()) == "2024-01-01"
        assert str(end.date()) == "2024-12-31"

    def test_custom_start_end_dates(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Explicit start/end date strings are forwarded correctly."""
        payload = {
            "pv_kw": 4.0,
            "battery_kwh": 0,
            "start": "2024-03-01",
            "end": "2024-03-31",
            "location": "bristol",
        }
        resp = client.post("/api/simulate/home", json=payload)
        assert resp.status_code == 201

    def test_zero_battery_treated_as_none(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """battery_kwh=0 results in battery_config=None on the HomeConfig."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "battery_kwh": 0},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.battery_config is None


# ===================================================================
# POST /api/simulate/fleet
# ===================================================================


class TestSimulateFleetAPI:
    """Tests for POST /api/simulate/fleet."""

    def test_valid_fleet_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid fleet config returns 201 with job_id and run_id."""
        resp = client.post("/api/simulate/fleet", json=VALID_FLEET_PAYLOAD)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["job_id"] == "job-fleet-001"
        assert data["run_id"] == "run-fleet-001"
        mock_job_manager.submit_fleet_job.assert_called_once()

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_empty_homes_returns_400(self, client: FlaskClient) -> None:
        """Fleet with empty homes array returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={"name": "Empty", "homes": []},
        )
        assert resp.status_code == 400
        assert "at least one" in resp.get_json()["error"]

    def test_missing_homes_key_returns_400(self, client: FlaskClient) -> None:
        """Fleet without 'homes' key returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={"name": "No homes key"},
        )
        assert resp.status_code == 400

    def test_invalid_home_in_fleet_returns_400(self, client: FlaskClient) -> None:
        """Fleet with an invalid home config returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={
                "name": "Bad Fleet",
                "homes": [
                    {"pv_kw": 0.01},  # invalid: PV < 0.5
                ],
            },
        )
        assert resp.status_code == 400

    def test_fleet_uses_first_home_dates(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Fleet date range is taken from the first home config."""
        resp = client.post("/api/simulate/fleet", json=VALID_FLEET_PAYLOAD)
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs[0][0]
        assert len(configs) == 2


# ===================================================================
# GET /api/jobs/<id>
# ===================================================================


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


# ===================================================================
# GET /api/jobs/<id>/progress (SSE)
# ===================================================================


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


# ===================================================================
# GET /api/jobs/<id>/results
# ===================================================================


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
        from solar_challenge.web.database import get_db

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


# ===================================================================
# GET /api/presets  (list)
# ===================================================================


class TestListPresets:
    """Tests for GET /api/presets."""

    def test_list_presets_returns_200(self, client: FlaskClient) -> None:
        """GET /api/presets returns 200 with a JSON array."""
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_builtin_presets_present(self, client: FlaskClient) -> None:
        """Built-in presets are included in the response."""
        resp = client.get("/api/presets")
        data = resp.get_json()
        names = [p["name"] for p in data]
        assert "Small Urban" in names
        assert "Medium Suburban" in names
        assert "Large with Battery" in names

    def test_builtin_presets_tagged(self, client: FlaskClient) -> None:
        """Built-in presets have source='builtin'."""
        resp = client.get("/api/presets")
        data = resp.get_json()
        for preset in data:
            if preset["name"] in ("Small Urban", "Medium Suburban", "Large with Battery"):
                assert preset["source"] == "builtin"


# ===================================================================
# POST /api/presets  (save)
# ===================================================================


class TestSavePreset:
    """Tests for POST /api/presets."""

    def test_save_preset_returns_201(self, client: FlaskClient) -> None:
        """Valid preset save returns 201 with name and id."""
        resp = client.post(
            "/api/presets",
            json={"name": "My Custom Preset", "pv_kw": 5.0, "battery_kwh": 10.0},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My Custom Preset"
        assert "id" in data

    def test_saved_preset_appears_in_list(self, client: FlaskClient) -> None:
        """Saved preset appears in GET /api/presets listing."""
        client.post(
            "/api/presets",
            json={"name": "Listed Preset", "pv_kw": 3.5},
        )
        resp = client.get("/api/presets")
        names = [p["name"] for p in resp.get_json()]
        assert "Listed Preset" in names

    def test_save_no_json_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/presets",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_save_empty_name_returns_400(self, client: FlaskClient) -> None:
        """POST with empty preset name returns 400."""
        resp = client.post(
            "/api/presets",
            json={"name": "", "pv_kw": 4.0},
        )
        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"].lower()

    def test_save_whitespace_name_returns_400(self, client: FlaskClient) -> None:
        """POST with whitespace-only preset name returns 400."""
        resp = client.post(
            "/api/presets",
            json={"name": "   ", "pv_kw": 4.0},
        )
        assert resp.status_code == 400


# ===================================================================
# GET /api/presets/<name>  (get single)
# ===================================================================


class TestGetPreset:
    """Tests for GET /api/presets/<name>."""

    def test_get_builtin_preset(self, client: FlaskClient) -> None:
        """Fetch a built-in preset by name."""
        resp = client.get("/api/presets/Small Urban")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Small Urban"
        assert data["source"] == "builtin"

    def test_get_saved_preset(self, client: FlaskClient) -> None:
        """Fetch a saved preset by name."""
        client.post(
            "/api/presets",
            json={"name": "Saved One", "pv_kw": 6.0},
        )
        resp = client.get("/api/presets/Saved One")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Saved One"
        assert data["source"] == "saved"

    def test_get_nonexistent_preset_returns_404(self, client: FlaskClient) -> None:
        """Unknown preset name returns 404."""
        resp = client.get("/api/presets/Does Not Exist")
        assert resp.status_code == 404
        assert "error" in resp.get_json()


# ===================================================================
# POST /api/simulate/sweep
# ===================================================================


class TestSimulateSweep:
    """Tests for POST /api/simulate/sweep."""

    def test_valid_linear_sweep_returns_201(self, client: FlaskClient) -> None:
        """Linear sweep with valid params returns 201 with job_ids."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 1.0,
                "max": 10.0,
                "steps": 5,
                "mode": "linear",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["parameter"] == "pv_capacity_kw"
        assert len(data["values"]) == 5
        assert "job_ids" in data
        assert len(data["job_ids"]) == 5
        # First and last values should match min/max
        assert data["values"][0] == pytest.approx(1.0, abs=0.01)
        assert data["values"][-1] == pytest.approx(10.0, abs=0.01)

    def test_valid_geometric_sweep_returns_201(self, client: FlaskClient) -> None:
        """Geometric sweep with valid params returns 201 with job_ids."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "battery_capacity_kwh",
                "min": 1.0,
                "max": 16.0,
                "steps": 3,
                "mode": "geometric",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert len(data["values"]) == 3
        assert "job_ids" in data
        assert data["values"][0] == pytest.approx(1.0, abs=0.01)
        assert data["values"][-1] == pytest.approx(16.0, abs=0.01)

    def test_no_json_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_steps_less_than_2_returns_400(self, client: FlaskClient) -> None:
        """Steps < 2 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 10.0, "steps": 1},
        )
        assert resp.status_code == 400
        assert "Steps" in resp.get_json()["error"]

    def test_min_gte_max_returns_400(self, client: FlaskClient) -> None:
        """min >= max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 10.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Min" in resp.get_json()["error"]

    def test_min_equals_max_returns_400(self, client: FlaskClient) -> None:
        """min == max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 5.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400

    def test_geometric_negative_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min <= 0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": -1.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400
        assert "positive" in resp.get_json()["error"]

    def test_geometric_zero_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min=0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 0.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400

    def test_invalid_numeric_param_returns_400(self, client: FlaskClient) -> None:
        """Non-numeric min/max/steps returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": "abc", "max": 10.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Invalid numeric" in resp.get_json()["error"]

    def test_sweep_default_parameter_name(self, client: FlaskClient) -> None:
        """Default parameter name is pv_capacity_kw."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2},
        )
        assert resp.status_code == 201
        assert resp.get_json()["parameter"] == "pv_capacity_kw"


# ===================================================================
# POST /api/fleet/preview-distribution
# ===================================================================


class TestPreviewDistribution:
    """Tests for POST /api/fleet/preview-distribution."""

    def test_normal_distribution_returns_samples(self, client: FlaskClient) -> None:
        """Normal distribution preview returns expected number of samples."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "normal",
                "params": {"mean": 4.0, "std": 1.0},
                "n_samples": 50,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["samples"]) == 50

    def test_uniform_distribution_returns_samples(self, client: FlaskClient) -> None:
        """Uniform distribution preview returns samples within range."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "uniform",
                "params": {"min": 2.0, "max": 8.0},
                "n_samples": 20,
            },
        )
        assert resp.status_code == 200
        samples = resp.get_json()["samples"]
        assert len(samples) == 20
        assert all(2.0 <= s <= 8.0 for s in samples)

    def test_unknown_distribution_returns_400(self, client: FlaskClient) -> None:
        """Unknown distribution type returns 400."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "banana", "params": {}},
        )
        assert resp.status_code == 400
        assert "Unknown" in resp.get_json()["error"]

    def test_default_n_samples(self, client: FlaskClient) -> None:
        """Default n_samples is 100."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "normal", "params": {"mean": 3.0, "std": 0.5}},
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["samples"]) == 100


# ===================================================================
# POST /api/simulate/fleet-from-distribution
# ===================================================================


class TestFleetFromDistribution:
    """Tests for POST /api/simulate/fleet-from-distribution."""

    def test_valid_distribution_config_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid 3-home distribution POST returns 201 with job_id/run_id (B+H boundary test).

        Asserts:
        - status_code == 201 (not 501)
        - body contains job_id and run_id from the mock
        - submit_fleet_job called exactly once
        - the configs argument is a list of exactly 3 HomeConfig instances
        - the 3 homes have distinct PV capacities (they were sampled, not copied)
        """
        from solar_challenge.home import HomeConfig

        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                "n_homes": 3,
                "seed": 42,
                "location": "bristol",
                "days": 1,
                "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
                "battery": {
                    "enabled": True,
                    "capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0},
                },
                "load": {"annual_consumption_kwh": 3500.0},
            },
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        body = resp.get_json()
        assert body["job_id"] == "job-fleet-001"
        assert body["run_id"] == "run-fleet-001"

        mock_job_manager.submit_fleet_job.assert_called_once()
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) == 3
        assert all(isinstance(c, HomeConfig) for c in configs)
        # Homes were sampled from distributions — not all identical
        pv_caps = {round(c.pv_config.capacity_kw, 3) for c in configs}
        assert len(pv_caps) > 1, f"Expected distinct PV capacities but got {pv_caps}"

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON returns 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_invalid_n_homes_returns_400(self, client: FlaskClient) -> None:
        """n_homes < 1 returns 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={"n_homes": 0},
        )
        assert resp.status_code == 400


# ===================================================================
# POST /api/fleet/export-yaml
# ===================================================================


class TestExportFleetYAML:
    """Tests for POST /api/fleet/export-yaml."""

    def test_export_returns_yaml_content_type(self, client: FlaskClient) -> None:
        """YAML export returns text/yaml content type."""
        resp = client.post(
            "/api/fleet/export-yaml",
            json={"n_homes": 5, "name": "Test Fleet"},
        )
        assert resp.status_code == 200
        assert "text/yaml" in resp.content_type

    def test_export_contains_yaml_content(self, client: FlaskClient) -> None:
        """YAML export contains fleet_distribution key."""
        resp = client.post(
            "/api/fleet/export-yaml",
            json={"n_homes": 5, "name": "Test Fleet"},
        )
        body = resp.get_data(as_text=True)
        assert "fleet_distribution" in body
        assert "n_homes" in body

    def test_export_content_disposition(self, client: FlaskClient) -> None:
        """YAML export has Content-Disposition attachment header."""
        resp = client.post(
            "/api/fleet/export-yaml",
            json={"n_homes": 5},
        )
        assert "attachment" in resp.headers.get("Content-Disposition", "")
        assert "fleet-config.yaml" in resp.headers.get("Content-Disposition", "")


# ===================================================================
# POST /api/fleet/import-yaml
# ===================================================================


class TestImportFleetYAML:
    """Tests for POST /api/fleet/import-yaml."""

    def test_valid_yaml_returns_200(self, client: FlaskClient) -> None:
        """Valid YAML import returns 200 with parsed config."""
        yaml_str = "fleet_distribution:\n  n_homes: 10\n  seed: 99\nname: Imported\n"
        resp = client.post(
            "/api/fleet/import-yaml",
            data=yaml_str,
            content_type="text/yaml",
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["n_homes"] == 10
        assert data["seed"] == 99

    def test_bare_config_yaml_returns_200(self, client: FlaskClient) -> None:
        """Bare fleet distribution YAML (no wrapper key) returns 200."""
        yaml_str = "n_homes: 25\nseed: 7\n"
        resp = client.post(
            "/api/fleet/import-yaml",
            data=yaml_str,
            content_type="text/yaml",
        )
        assert resp.status_code == 200
        assert resp.get_json()["n_homes"] == 25

    def test_empty_body_returns_400(self, client: FlaskClient) -> None:
        """Empty request body returns 400."""
        resp = client.post(
            "/api/fleet/import-yaml",
            data="",
            content_type="text/yaml",
        )
        assert resp.status_code == 400

    def test_invalid_yaml_returns_400(self, client: FlaskClient) -> None:
        """Malformed YAML returns 400."""
        resp = client.post(
            "/api/fleet/import-yaml",
            data="[[[not valid yaml",
            content_type="text/yaml",
        )
        assert resp.status_code == 400

    def test_yaml_missing_required_keys_returns_400(self, client: FlaskClient) -> None:
        """YAML without fleet_distribution or n_homes returns 400."""
        resp = client.post(
            "/api/fleet/import-yaml",
            data="something_else: 42\n",
            content_type="text/yaml",
        )
        assert resp.status_code == 400


# ===================================================================
# Error path tests (miscellaneous)
# ===================================================================


class TestErrorPaths:
    """Catch-all tests for error handling across the API."""

    def test_bad_json_simulate_home(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for home simulation."""
        resp = client.post(
            "/api/simulate/home",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_simulate_fleet(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for fleet simulation."""
        resp = client.post(
            "/api/simulate/fleet",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_save_preset(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for preset save."""
        resp = client.post(
            "/api/presets",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_sweep(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for sweep."""
        resp = client.post(
            "/api/simulate/sweep",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_get_method_not_allowed_simulate_home(self, client: FlaskClient) -> None:
        """GET on POST-only endpoint returns 405."""
        resp = client.get("/api/simulate/home")
        assert resp.status_code == 405

    def test_get_method_not_allowed_simulate_fleet(self, client: FlaskClient) -> None:
        """GET on POST-only endpoint returns 405."""
        resp = client.get("/api/simulate/fleet")
        assert resp.status_code == 405

    def test_delete_method_not_allowed_on_jobs(self, client: FlaskClient) -> None:
        """DELETE on job status endpoint returns 405."""
        resp = client.delete("/api/jobs/some-id")
        assert resp.status_code == 405


# ===================================================================
# UI render smoke test
# ===================================================================


class TestHomeFormRender:
    """Smoke test: GET /simulate/home renders the new tabs and controls."""

    def test_home_form_shows_heat_pump_tariff_and_dispatch(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/home returns 200 with Heat Pump, Tariff tabs and dispatch control."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Heat Pump" in html
        assert "Tariff" in html
        assert "Dispatch Strategy" in html

    def test_home_form_shows_pv_age_inputs(self, client: FlaskClient) -> None:
        """GET /simulate/home returns HTML containing the two PV-age number inputs."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'name="system_age_years"' in html
        assert 'name="degradation_rate_per_year"' in html


# ===================================================================
# _parse_home_config boundary tests (call the function directly)
# ===================================================================


class TestParseHomeConfigCapabilities:
    """Boundary tests calling _parse_home_config directly."""

    def test_heat_pump_fields_populate_home_config(self) -> None:
        """heat_pump dict in payload populates HomeConfig.heat_pump_config."""
        from solar_challenge.web.api import _parse_home_config

        payload = {
            **VALID_HOME_PAYLOAD,
            "heat_pump": {
                "type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
        }
        home_config, _start, _end, _name = _parse_home_config(payload)
        assert home_config.heat_pump_config is not None
        assert home_config.heat_pump_config.heat_pump_type == "ASHP"
        assert home_config.heat_pump_config.thermal_capacity_kw == 8.0

    def test_tariff_fields_populate_home_config(self) -> None:
        """tariff dict in payload populates HomeConfig.tariff_config."""
        from solar_challenge.web.api import _parse_home_config

        payload = {
            **VALID_HOME_PAYLOAD,
            "tariff": {
                "type": "flat_rate",
                "rate_per_kwh": 0.30,
            },
        }
        home_config, _start, _end, _name = _parse_home_config(payload)
        assert home_config.tariff_config is not None
        # flat_rate TariffConfig has at least one period
        assert len(home_config.tariff_config.periods) > 0

    def test_combined_heat_pump_tariff_dispatch_populate_home_config(self) -> None:
        """heat_pump + tariff + dispatch_strategy all populate when battery is enabled."""
        from solar_challenge.web.api import _parse_home_config

        payload = {
            **VALID_HOME_PAYLOAD,
            "battery_kwh": 5.0,
            "heat_pump": {
                "type": "ASHP",
                "thermal_capacity_kw": 8.0,
                "annual_heat_demand_kwh": 8000,
            },
            "tariff": {
                "type": "flat_rate",
                "rate_per_kwh": 0.30,
            },
            "dispatch_strategy": {
                "strategy_type": "self_consumption",
            },
        }
        home_config, _start, _end, _name = _parse_home_config(payload)
        assert home_config.heat_pump_config is not None
        assert home_config.tariff_config is not None
        assert home_config.battery_config is not None
        assert home_config.battery_config.dispatch_strategy is not None
        assert home_config.battery_config.dispatch_strategy.strategy_type == "self_consumption"

    def test_dispatch_strategy_ignored_without_battery(self) -> None:
        """dispatch_strategy is silently ignored when no battery is enabled."""
        from solar_challenge.web.api import _parse_home_config

        payload = {
            **VALID_HOME_PAYLOAD,
            "battery_kwh": 0,
            "dispatch_strategy": {
                "strategy_type": "self_consumption",
            },
        }
        home_config, _start, _end, _name = _parse_home_config(payload)
        assert home_config.battery_config is None  # no battery => no dispatch either


# ===================================================================
# Endpoint error-path tests (400 for bad tariff / dispatch)
# ===================================================================


class TestParseHomeConfigErrorPaths:
    """Endpoint 400 error-path tests for new optional config fields."""

    def test_invalid_tariff_returns_400(
        self, client: FlaskClient
    ) -> None:
        """POST with an unrecognised tariff type returns 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "tariff": {"type": "nonsense"}},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_invalid_dispatch_returns_400(
        self, client: FlaskClient
    ) -> None:
        """POST with tou_optimized dispatch but missing peak_hours returns 400."""
        resp = client.post(
            "/api/simulate/home",
            json={
                **VALID_HOME_PAYLOAD,
                "battery_kwh": 5.0,
                "dispatch_strategy": {
                    "strategy_type": "tou_optimized",
                    # peak_hours intentionally omitted — required for tou_optimized
                },
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data


# ===================================================================
# _parse_date_range unit tests
# ===================================================================


class TestParseDateRange:
    """Unit tests for the module-level _parse_date_range(data) helper."""

    def test_days_seven_returns_june_window(self) -> None:
        """days=7 returns a 7-day window starting 2024-06-01."""
        from solar_challenge.web.api import _parse_date_range

        start, end = _parse_date_range({"days": 7})
        assert start == "2024-06-01"
        assert end == "2024-06-07"

    def test_days_365_returns_full_year(self) -> None:
        """days=365 is the special case: returns the full 2024 calendar year."""
        from solar_challenge.web.api import _parse_date_range

        start, end = _parse_date_range({"days": 365})
        assert start == "2024-01-01"
        assert end == "2024-12-31"

    def test_explicit_start_end_returned_verbatim(self) -> None:
        """Explicit start/end strings are returned as-is."""
        from solar_challenge.web.api import _parse_date_range

        start, end = _parse_date_range({"start": "2024-03-01", "end": "2024-03-05"})
        assert start == "2024-03-01"
        assert end == "2024-03-05"

    def test_empty_data_returns_full_year_defaults(self) -> None:
        """Empty dict returns the default full-year window."""
        from solar_challenge.web.api import _parse_date_range

        start, end = _parse_date_range({})
        assert start == "2024-01-01"
        assert end == "2024-12-31"

    def test_days_zero_raises_value_error(self) -> None:
        """days=0 is not a valid window; must raise ValueError."""
        import pytest
        from solar_challenge.web.api import _parse_date_range

        with pytest.raises(ValueError, match="positive"):
            _parse_date_range({"days": 0})

    def test_days_negative_raises_value_error(self) -> None:
        """Negative days must raise ValueError."""
        import pytest
        from solar_challenge.web.api import _parse_date_range

        with pytest.raises(ValueError, match="positive"):
            _parse_date_range({"days": -7})


# ===================================================================
# PV-age form→engine boundary tests (task #20)
# ===================================================================


class TestParseHomeConfigPVAge:
    """PV-age boundary tests: form→PVConfig threading (§D contract)."""

    def test_endpoint_threads_system_age_years_to_pv_config(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with system_age_years=20 returns 201 and HomeConfig carries the value."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "system_age_years": 20},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.pv_config.system_age_years == 20.0

    def test_direct_parse_sets_both_age_fields(self) -> None:
        """_parse_home_config with explicit age values sets both PVConfig fields."""
        from solar_challenge.web.api import _parse_home_config

        payload = {
            **VALID_HOME_PAYLOAD,
            "system_age_years": 15,
            "degradation_rate_per_year": 0.01,
        }
        home_config, _start, _end, _name = _parse_home_config(payload)
        assert home_config.pv_config.system_age_years == 15.0
        assert home_config.pv_config.degradation_rate_per_year == 0.01

    def test_absent_age_keys_yield_pv_config_defaults(self) -> None:
        """_parse_home_config with no age keys yields PVConfig default values."""
        from solar_challenge.web.api import _parse_home_config

        home_config, _start, _end, _name = _parse_home_config(VALID_HOME_PAYLOAD)
        assert home_config.pv_config.system_age_years == 0.0
        assert home_config.pv_config.degradation_rate_per_year == 0.005

    def test_negative_system_age_returns_400(self, client: FlaskClient) -> None:
        """POST with system_age_years=-5 returns HTTP 400 (PVConfig validates age >= 0)."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "system_age_years": -5},
        )
        assert resp.status_code == 400

    def test_invalid_degradation_rate_returns_400(self, client: FlaskClient) -> None:
        """POST with degradation_rate_per_year=1.5 returns HTTP 400 (PVConfig validates rate 0-1)."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "degradation_rate_per_year": 1.5},
        )
        assert resp.status_code == 400
