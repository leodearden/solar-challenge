# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the endpoints that submit and report jobs, driven through the web app against a real JobManager."""

import time
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.location import Location
from solar_challenge.weather import WeatherCache
from solar_challenge.web.jobs import HomeSimulator, JobManager
from tests._synthetic_weather import synthetic_june_weather
from tests._web_app import build_test_app
from tests.unit.web_jobs._app_client import A_HOME_JOB_REQUEST, client_using
from tests.unit.web_jobs._fakes import BlockingSimulation, CountingIds, RecordingSimulation, a_failing_simulation
from tests.unit.web_jobs._jobs_table import job_row, job_rows


def _client_whose_jobs_run(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Install a JobManager that runs *simulation* as the app's job manager, and return a client of the app."""
    return client_using(app, JobManager(simulate_home=simulation))


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A client whose jobs run a fake simulation that returns at once, so the teardown drain has nothing to wait for."""
    return _client_whose_jobs_run(app, RecordingSimulation())


@pytest.fixture
def real_simulation_client(app: Flask, weather_cache: WeatherCache) -> FlaskClient:
    """A client of the JobManager create_app built, whose jobs run the real simulate_home.

    Bristol's TMY is a clear day on 1 June 2024, the first day of every days window the API simulates.
    """
    weather_cache.put(synthetic_june_weather("2024-06-01"), "tmy", Location.bristol())
    return app.test_client()


@pytest.fixture
def blocking_client(app: Flask, blocking_simulation: BlockingSimulation) -> FlaskClient:
    """A client whose jobs wait inside blocking_simulation until it is released."""
    return _client_whose_jobs_run(app, blocking_simulation)


class TestSimulateHomeEndpoint:
    """Tests for POST /api/simulate/home."""

    def test_submit_home_job_returns_201(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home returns 201 with job_id and run_id."""
        response = client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "name": "Test Simulation"})
        assert response.status_code == 201
        data = response.get_json()
        assert "job_id" in data
        assert "run_id" in data
        assert len(data["job_id"]) > 0
        assert len(data["run_id"]) > 0

    def test_submit_home_job_invalid_pv_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with invalid PV returns 400."""
        response = client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "pv_kw": 0.1})
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_submit_home_job_negative_battery_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with negative battery returns 400."""
        response = client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "battery_kwh": -5.0})
        assert response.status_code == 400

    def test_submit_home_job_no_json_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with no JSON body returns 400."""
        response = client.post(
            "/api/simulate/home",
            data="not json",
            content_type="text/plain",
        )
        assert response.status_code == 400


def _client_of_a_finished_job(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Return a client of *app* whose JobManager has run one home job through *simulation* to its end.

    The job's id is "id-1" and its run's id is "id-2".
    """
    manager = JobManager(simulate_home=simulation, new_id=CountingIds())
    client = client_using(app, manager)
    assert client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).status_code == 201
    assert manager.wait_until_idle(timeout=30)
    return client


def _client_of_a_finished_fleet_job(app: Flask) -> FlaskClient:
    """Return a client of *app* whose JobManager has run a fleet job of one home to its end.

    The job's id is "id-1" and its run's id is "id-2".
    """
    manager = JobManager(simulate_home=RecordingSimulation(), new_id=CountingIds())
    client = client_using(app, manager)
    assert client.post("/api/simulate/fleet", json={"homes": [A_HOME_JOB_REQUEST]}).status_code == 201
    assert manager.wait_until_idle(timeout=30)
    return client


def _sse(event: str, data: str) -> str:
    """Return the SSE message a progress stream sends for *event* with the JSON text *data*."""
    return f"event: {event}\ndata: {data}\n\n"


_STARTING = _sse(
    "progress",
    '{"progress_pct": 5.0, "current_step": "Starting", "message": "Initializing...", "status": "running"}',
)
_SIMULATING = _sse(
    "progress",
    '{"progress_pct": 20.0, "current_step": "Simulating", "message": "Running home simulation...", "status": "running"}',
)
_COMPLETED = _sse(
    "complete",
    '{"status": "completed", "progress_pct": 100.0, "current_step": "Done",'
    ' "message": "Simulation completed successfully", "run_id": "id-2"}',
)
_FLEET_COMPLETED = _sse(
    "complete",
    '{"status": "completed", "progress_pct": 100.0, "current_step": "Done",'
    ' "message": "Fleet simulation completed successfully", "run_id": "id-2"}',
)
_FAILED = _sse("error", '{"status": "failed", "message": "the simulation failed"}')


class TestGetJobStatusEndpoint:
    """Tests for GET /api/jobs/<id>."""

    def test_after_a_restart_an_earlier_job_is_not_found_although_its_rows_remain(self, tmp_path: Path) -> None:
        before_restart = build_test_app(tmp_path)
        submitted = (
            _client_whose_jobs_run(before_restart, RecordingSimulation())
            .post("/api/simulate/home", json=A_HOME_JOB_REQUEST)
            .get_json()
        )
        assert before_restart.extensions["job_manager"].wait_until_idle(timeout=30)

        after_restart = build_test_app(tmp_path)

        response = after_restart.test_client().get(f"/api/jobs/{submitted['job_id']}")
        assert response.status_code == 404
        assert job_rows(after_restart.extensions["storage"]) == [(submitted["job_id"], submitted["run_id"])]

    @pytest.mark.parametrize(
        ("simulation", "last_state"),
        [
            (
                RecordingSimulation(),
                {
                    "status": "completed",
                    "progress_pct": 100.0,
                    "current_step": "Done",
                    "message": "Simulation completed successfully",
                },
            ),
            (
                a_failing_simulation,
                {
                    "status": "failed",
                    "progress_pct": 20.0,
                    "current_step": "Simulating",
                    "message": "the simulation failed",
                },
            ),
        ],
        ids=["completed", "failed"],
    )
    def test_a_finished_jobs_status_answers_its_ids_its_last_state_and_its_rows_creation_time(
        self, app: Flask, simulation: HomeSimulator, last_state: dict[str, Any]
    ) -> None:
        client = _client_of_a_finished_job(app, simulation)

        response = client.get("/api/jobs/id-1")

        assert response.status_code == 200
        assert response.get_json() == {
            "job_id": "id-1",
            "run_id": "id-2",
            **last_state,
            "created_at": job_row(app.extensions["storage"], "id-1")["created_at"],
        }


class TestJobProgressEndpoint:
    """Tests for GET /api/jobs/<id>/progress (SSE)."""

    def test_the_stream_of_a_completed_job_sends_each_progress_event_then_its_completion(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, RecordingSimulation())

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == "".join(
            [
                _STARTING,
                _SIMULATING,
                _sse(
                    "progress",
                    '{"progress_pct": 90.0, "current_step": "Saving",'
                    ' "message": "Persisting results to storage...", "status": "running"}',
                ),
                _COMPLETED,
            ]
        )

    def test_the_stream_of_a_failed_job_sends_each_progress_event_then_its_error(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, a_failing_simulation)

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == _STARTING + _SIMULATING + _FAILED

    @pytest.mark.parametrize(
        ("simulation", "final_event"),
        [
            (RecordingSimulation(), _COMPLETED),
            (a_failing_simulation, _FAILED),
        ],
        ids=["completed", "failed"],
    )
    def test_a_stream_opened_after_another_drained_the_events_sends_only_the_final_event(
        self, app: Flask, simulation: HomeSimulator, final_event: str
    ) -> None:
        client = _client_of_a_finished_job(app, simulation)
        client.get("/api/jobs/id-1/progress").get_data()

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == final_event

    def test_the_stream_of_a_completed_fleet_job_sends_each_progress_event_then_its_completion(
        self, app: Flask
    ) -> None:
        client = _client_of_a_finished_fleet_job(app)

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == "".join(
            [
                _STARTING,
                _sse(
                    "progress",
                    '{"progress_pct": 5.0, "current_step": "Home 1/1",'
                    ' "message": "Simulating home 1 of 1...", "status": "running"}',
                ),
                _sse(
                    "progress",
                    '{"progress_pct": 97.0, "current_step": "Saving",'
                    ' "message": "Persisting fleet results...", "status": "running"}',
                ),
                _FLEET_COMPLETED,
            ]
        )

    def test_a_stream_opened_after_another_drained_a_fleet_jobs_events_sends_the_fleet_jobs_own_completion(
        self, app: Flask
    ) -> None:
        client = _client_of_a_finished_fleet_job(app)
        live_stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        late_stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert late_stream == _FLEET_COMPLETED
        assert live_stream.endswith(late_stream)


class TestJobResultsEndpoint:
    """Tests for GET /api/jobs/<id>/results."""

    def test_results_returns_409_while_running(
        self, blocking_client: FlaskClient, blocking_simulation: BlockingSimulation
    ) -> None:
        """Test GET /api/jobs/<id>/results returns 409 while job is running."""
        submit_resp = blocking_client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST)
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]
        blocking_simulation.wait_until_started()

        results_resp = blocking_client.get(f"/api/jobs/{job_id}/results")

        assert results_resp.status_code == 409
        assert results_resp.get_json() == {"error": "Job not yet completed", "status": "running", "progress_pct": 20.0}

    def test_a_failed_jobs_results_answer_409_with_its_status_and_its_last_progress(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, a_failing_simulation)

        response = client.get("/api/jobs/id-1/results")

        assert response.status_code == 409
        assert response.get_json() == {"error": "Job not yet completed", "status": "failed", "progress_pct": 20.0}

    def test_results_returns_404_unknown_job(self, client: FlaskClient) -> None:
        """Test GET /api/jobs/<unknown_id>/results returns 404."""
        response = client.get("/api/jobs/nonexistent-id/results")
        assert response.status_code == 404


class TestJobCompletion:
    """Test that a job completes successfully end-to-end."""

    def test_home_job_completes(self, real_simulation_client: FlaskClient) -> None:
        """Test that a submitted home job eventually completes with results."""
        # Submit a minimal 1-day simulation
        submit_resp = real_simulation_client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "name": "E2E Test"})
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]
        run_id = submit_resp.get_json()["run_id"]

        # Poll until completed (with timeout)
        deadline = time.monotonic() + 120  # 120 second timeout
        status = "queued"
        while time.monotonic() < deadline:
            status_resp = real_simulation_client.get(f"/api/jobs/{job_id}")
            assert status_resp.status_code == 200
            status_data = status_resp.get_json()
            status = status_data["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(1)

        assert status == "completed", f"Job did not complete in time, last status: {status}"

        # Now fetch results
        results_resp = real_simulation_client.get(f"/api/jobs/{job_id}/results")
        assert results_resp.status_code == 200
        results_data = results_resp.get_json()
        assert results_data["run_id"] == run_id
        assert "summary" in results_data
        assert results_data["summary"].get("total_generation_kwh") is not None

    def test_home_job_with_battery_completes(self, real_simulation_client: FlaskClient) -> None:
        """Test that a home job with battery completes successfully."""
        submit_resp = real_simulation_client.post(
            "/api/simulate/home",
            json={**A_HOME_JOB_REQUEST, "battery_kwh": 5.0, "occupants": 2, "name": "Battery Test"},
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]

        # Poll until completed
        deadline = time.monotonic() + 120
        status = "queued"
        while time.monotonic() < deadline:
            status_resp = real_simulation_client.get(f"/api/jobs/{job_id}")
            status_data = status_resp.get_json()
            status = status_data["status"]
            if status in ("completed", "failed"):
                break
            time.sleep(1)

        assert status == "completed", f"Job did not complete, last status: {status}"


class TestSimulateFleetEndpoint:
    """Tests for POST /api/simulate/fleet."""

    def test_submit_fleet_job_returns_201(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/fleet returns 201 with job_id and run_id."""
        response = client.post(
            "/api/simulate/fleet",
            json={
                "name": "Test Fleet",
                "homes": [
                    A_HOME_JOB_REQUEST,
                    {**A_HOME_JOB_REQUEST, "pv_kw": 3.0, "battery_kwh": 5.0, "occupants": 2, "location": "london"},
                ],
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert "job_id" in data
        assert "run_id" in data

    def test_submit_fleet_job_empty_homes_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/fleet with empty homes returns 400."""
        response = client.post(
            "/api/simulate/fleet",
            json={
                "name": "Empty Fleet",
                "homes": [],
            },
        )
        assert response.status_code == 400


class TestAppJobManager:
    """Tests for the JobManager create_app registers as the app's job_manager extension."""

    def test_job_manager_exists_on_app(self, app: Flask) -> None:
        """Test that JobManager is registered as an app extension."""
        assert "job_manager" in app.extensions
        assert isinstance(app.extensions["job_manager"], JobManager)

    def test_job_state_returns_none_for_unknown(self, app: Flask) -> None:
        """Test that job_state returns None for unknown job IDs."""
        jm = app.extensions["job_manager"]
        assert jm.job_state("nonexistent") is None
