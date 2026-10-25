# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the endpoints that submit and report jobs, driven through the web app against a real JobManager."""

import threading
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.weather import WeatherCache
from solar_challenge.web.jobs import HomeSimulator, JobManager
from tests._fleet_form import valid_distribution_form
from tests._run_storage_layout import stored_run_dir
from tests._web_app import build_test_app, database_of, release_store_lock, run_storage_of
from tests.unit.web_jobs._app_client import A_HOME_JOB_DAYS, A_HOME_JOB_REQUEST, client_using
from tests.unit.web_jobs._fakes import (
    BlockingSimulation,
    CountingIds,
    RecordingSimulation,
    RunStorageWithGatedHomeSaves,
    SaveGate,
    a_failing_simulation,
)


def _client_whose_jobs_run(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Install a JobManager that runs *simulation* as the app's job manager, and return a client of the app."""
    return client_using(app, JobManager(run_storage_of(app), simulate_home=simulation))


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A client whose jobs run a fake simulation that returns at once, so the teardown drain has nothing to wait for."""
    return _client_whose_jobs_run(app, RecordingSimulation())


@pytest.fixture
def real_simulation_client(app: Flask, weather_cache: WeatherCache) -> FlaskClient:
    """A client of the JobManager create_app built, whose jobs run the real simulate_home.

    Its jobs run on the weather create_app bound, the test's own weather cache. There Bristol's TMY is a
    clear day on the first day of every days window the API simulates.
    """
    A_HOME_JOB_DAYS.seed_as_bristol_tmy(weather_cache)
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
    manager = JobManager(run_storage_of(app), simulate_home=simulation, new_id=CountingIds())
    client = client_using(app, manager)
    assert client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).status_code == 201
    assert manager.wait_until_idle(timeout=30)
    return client


def _client_of_a_finished_fleet_job(app: Flask) -> FlaskClient:
    """Return a client of *app* whose JobManager has run a fleet job of one home to its end.

    The job's id is "id-1" and its run's id is "id-2".
    """
    manager = JobManager(run_storage_of(app), simulate_home=RecordingSimulation(), new_id=CountingIds())
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
_CANCELLED = _sse("error", '{"status": "cancelled", "message": "Cancelled: its run was deleted"}')


class TestGetJobStatusEndpoint:
    """Tests for GET /api/jobs/<id>."""

    def test_after_a_restart_an_earlier_job_is_not_found_although_its_run_remains(self, tmp_path: Path) -> None:
        before_restart = build_test_app(tmp_path)
        submitted = (
            _client_whose_jobs_run(before_restart, RecordingSimulation())
            .post("/api/simulate/home", json=A_HOME_JOB_REQUEST)
            .get_json()
        )
        assert before_restart.extensions["job_manager"].wait_until_idle(timeout=30)

        release_store_lock(before_restart)
        after_restart = build_test_app(tmp_path).test_client()

        assert after_restart.get(f"/api/jobs/{submitted['job_id']}").status_code == 404
        run = after_restart.get(f"/api/history/runs/{submitted['run_id']}")
        assert run.status_code == 200
        assert run.get_json()["status"] == "completed"

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
    def test_a_finished_jobs_status_answers_its_ids_its_last_state_and_its_runs_creation_time(
        self, app: Flask, simulation: HomeSimulator, last_state: dict[str, Any]
    ) -> None:
        client = _client_of_a_finished_job(app, simulation)

        response = client.get("/api/jobs/id-1")

        assert response.status_code == 200
        assert response.get_json() == {
            "job_id": "id-1",
            "run_id": "id-2",
            **last_state,
            "created_at": client.get("/api/history/runs/id-2").get_json()["created_at"],
        }


def _status_and_name_while_running_and_once_completed(
    app: Flask, blocking_simulation: BlockingSimulation, endpoint: str, request_body: dict[str, Any]
) -> list[tuple[str, str]]:
    """The status and name Run History reads for the run *request_body*'s POST to *endpoint* submits, while its job is held in *blocking_simulation*, then once it completes."""
    manager = JobManager(run_storage_of(app), simulate_home=blocking_simulation)
    client = client_using(app, manager)

    response = client.post(endpoint, json=request_body)
    assert response.status_code == 201
    run_id = response.get_json()["run_id"]
    blocking_simulation.wait_until_started()
    running = client.get(f"/api/history/runs/{run_id}").get_json()
    blocking_simulation.release()
    assert manager.wait_until_idle(timeout=30)
    completed = client.get(f"/api/history/runs/{run_id}").get_json()
    return [(running["status"], running["name"]), (completed["status"], completed["name"])]


class TestASubmittedJobsRunInRunHistory:
    """A submitted job's run shows in Run History from its submit on: running, then completed or failed.

    A run its job left running reads failed once the app is rebuilt on the same store.
    """

    @pytest.mark.parametrize(
        ("endpoint", "request_body"),
        [
            ("/api/simulate/home", {**A_HOME_JOB_REQUEST, "name": "North Roof"}),
            ("/api/simulate/fleet", {"name": "Street", "homes": [A_HOME_JOB_REQUEST]}),
        ],
        ids=["home", "fleet"],
    )
    def test_a_submitted_jobs_run_reads_running_then_completed_under_the_submits_name(
        self,
        app: Flask,
        blocking_simulation: BlockingSimulation,
        endpoint: str,
        request_body: dict[str, Any],
    ) -> None:
        assert _status_and_name_while_running_and_once_completed(app, blocking_simulation, endpoint, request_body) == [
            ("running", request_body["name"]),
            ("completed", request_body["name"]),
        ]

    @pytest.mark.parametrize(
        ("endpoint", "request_body", "default_name"),
        [
            ("/api/simulate/home", A_HOME_JOB_REQUEST, "Web Simulation"),
            ("/api/simulate/fleet", {"homes": [A_HOME_JOB_REQUEST]}, "Fleet Simulation"),
        ],
        ids=["home", "fleet"],
    )
    def test_a_job_submitted_without_a_name_runs_under_its_run_kinds_default_name(
        self,
        app: Flask,
        blocking_simulation: BlockingSimulation,
        endpoint: str,
        request_body: dict[str, Any],
        default_name: str,
    ) -> None:
        """The run lists under the name its kind gives a run created with none (RunKind.default_name)."""
        assert _status_and_name_while_running_and_once_completed(app, blocking_simulation, endpoint, request_body) == [
            ("running", default_name),
            ("completed", default_name),
        ]

    @pytest.mark.parametrize("name_sent", [{}, {"name": ""}], ids=["no-name", "an-empty-name"])
    def test_a_fleet_form_submitted_without_a_name_runs_as_fleet_simulation(
        self, app: Flask, name_sent: dict[str, str]
    ) -> None:
        """The run lists under the fleet kind's default name (RunKind.default_name)."""
        manager = JobManager(run_storage_of(app), simulate_home=RecordingSimulation())
        client = client_using(app, manager)

        response = client.post(
            "/api/simulate/fleet-from-distribution", json={**valid_distribution_form(), "days": 1, **name_sent}
        )
        assert response.status_code == 201, response.get_json()
        assert manager.wait_until_idle(timeout=30)
        run = client.get(f"/api/history/runs/{response.get_json()['run_id']}").get_json()

        assert (run["status"], run["name"]) == ("completed", "Fleet Simulation")

    def test_a_failed_jobs_run_reads_failed_with_the_jobs_message(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, a_failing_simulation)

        run = client.get("/api/history/runs/id-2").get_json()

        assert (run["status"], run["error_message"]) == ("failed", "the simulation failed")

    def test_a_run_its_job_left_running_reads_failed_as_interrupted_once_the_app_is_rebuilt_on_its_store(
        self, tmp_path: Path, blocking_simulation: BlockingSimulation
    ) -> None:
        before_restart = build_test_app(tmp_path)
        manager = JobManager(run_storage_of(before_restart), max_workers=1, simulate_home=blocking_simulation)
        client = client_using(before_restart, manager)
        first_run_id, second_run_id = [
            client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()["run_id"] for _ in range(2)
        ]
        blocking_simulation.wait_until_started()
        manager.shutdown()
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        release_store_lock(before_restart)
        after_restart = build_test_app(tmp_path).test_client()

        interrupted = after_restart.get(f"/api/history/runs/{second_run_id}").get_json()
        assert (interrupted["status"], interrupted["error_message"]) == ("failed", "Interrupted by server restart")
        assert interrupted["completed_at"] is not None
        assert after_restart.get(f"/api/history/runs/{first_run_id}").get_json()["status"] == "completed"


class TestDeletingARunCancelsItsJob:
    """DELETE /api/history/runs/<id> of a run whose job is queued or running cancels the job, which saves nothing: contract C8."""

    def test_a_run_deleted_while_its_home_job_simulates_stays_deleted_and_its_job_reports_cancelled(
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        manager = JobManager(run_storage_of(app), simulate_home=blocking_simulation, new_id=CountingIds())
        client = client_using(app, manager)
        assert client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).status_code == 201
        blocking_simulation.wait_until_started()
        running = client.get("/api/jobs/id-1").get_json()

        assert client.delete("/api/history/runs/id-2").status_code == 200
        assert client.get("/api/history/runs/id-2").status_code == 404
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        assert client.get("/api/history/runs/id-2").status_code == 404
        assert not stored_run_dir(run_storage_of(app), "id-2").exists()
        assert client.get("/api/jobs/id-1").get_json() == {
            **running,
            "status": "cancelled",
            "message": "Cancelled: its run was deleted",
        }
        assert client.get("/api/jobs/id-1/progress").get_data(as_text=True) == _STARTING + _SIMULATING + _CANCELLED

    def test_a_run_deleted_while_its_job_waits_in_the_queue_is_never_simulated(
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        manager = JobManager(run_storage_of(app), max_workers=1, simulate_home=blocking_simulation)
        client = client_using(app, manager)
        ahead = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()
        blocking_simulation.wait_until_started()
        queued = client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "pv_kw": 3.0}).get_json()

        assert client.delete(f"/api/history/runs/{queued['run_id']}").status_code == 200

        assert client.get(f"/api/jobs/{queued['job_id']}").get_json()["status"] == "cancelled"
        assert client.get(f"/api/jobs/{queued['job_id']}/progress").get_data(as_text=True) == _CANCELLED
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        assert [config.pv_config.capacity_kw for config, _, _ in blocking_simulation.calls] == [4.0]
        assert client.get(f"/api/history/runs/{queued['run_id']}").status_code == 404
        assert not stored_run_dir(run_storage_of(app), queued["run_id"]).exists()
        assert client.get(f"/api/history/runs/{ahead['run_id']}").get_json()["status"] == "completed"

    def test_a_fleet_run_deleted_while_its_first_home_simulates_never_simulates_the_others_and_saves_nothing(
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        manager = JobManager(run_storage_of(app), simulate_home=blocking_simulation)
        client = client_using(app, manager)
        submitted = client.post(
            "/api/simulate/fleet",
            json={
                "homes": [
                    A_HOME_JOB_REQUEST,
                    {**A_HOME_JOB_REQUEST, "pv_kw": 3.0},
                    {**A_HOME_JOB_REQUEST, "pv_kw": 2.0},
                ]
            },
        ).get_json()
        blocking_simulation.wait_until_started()

        assert client.delete(f"/api/history/runs/{submitted['run_id']}").status_code == 200
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        assert [config.pv_config.capacity_kw for config, _, _ in blocking_simulation.calls] == [4.0]
        assert client.get(f"/api/history/runs/{submitted['run_id']}").status_code == 404
        assert not stored_run_dir(run_storage_of(app), submitted["run_id"]).exists()
        job = client.get(f"/api/jobs/{submitted['job_id']}").get_json()
        assert (job["status"], job["current_step"], job["message"]) == (
            "cancelled",
            "Home 1/3",
            "Cancelled: its run was deleted",
        )

    def test_a_delete_that_comes_while_the_jobs_final_save_runs_waits_for_the_save_then_removes_the_saved_run(
        self, app: Flask, save_gate: SaveGate
    ) -> None:
        storage = RunStorageWithGatedHomeSaves(database_of(app), run_storage_of(app).data_dir, save_gate)
        manager = JobManager(storage, simulate_home=RecordingSimulation())
        client = client_using(app, manager)
        submitted = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()
        save_gate.wait_until_a_save_waits()
        answers: list[int] = []
        delete = threading.Thread(
            target=lambda: answers.append(
                app.test_client().delete(f"/api/history/runs/{submitted['run_id']}").status_code
            ),
            daemon=True,
        )

        delete.start()
        delete.join(timeout=0.2)
        assert delete.is_alive(), "the DELETE answered while the job's final save still ran"
        save_gate.open()
        delete.join(timeout=30)

        assert answers == [200]
        assert manager.wait_until_idle(timeout=30)
        assert client.get(f"/api/history/runs/{submitted['run_id']}").status_code == 404
        assert not stored_run_dir(run_storage_of(app), submitted["run_id"]).exists()
        assert client.get(f"/api/jobs/{submitted['job_id']}").get_json()["status"] == "completed"


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


class TestJobCompletion:
    """Test that a job completes successfully end-to-end."""

    def test_home_job_completes(self, app: Flask, real_simulation_client: FlaskClient) -> None:
        """A submitted home job completes, and its summary shows it generated power on the clear day real_simulation_client seeds."""
        # Submit a minimal 1-day simulation
        submit_resp = real_simulation_client.post("/api/simulate/home", json={**A_HOME_JOB_REQUEST, "name": "E2E Test"})
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]
        run_id = submit_resp.get_json()["run_id"]

        assert app.extensions["job_manager"].wait_until_idle(timeout=120)

        status_resp = real_simulation_client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        assert status_resp.get_json()["status"] == "completed", status_resp.get_json()

        # Now fetch results
        results_resp = real_simulation_client.get(f"/api/jobs/{job_id}/results")
        assert results_resp.status_code == 200
        results_data = results_resp.get_json()
        assert results_data["run_id"] == run_id
        assert "summary" in results_data
        assert results_data["summary"]["total_generation_kwh"] > 0

    def test_home_job_with_battery_completes(self, app: Flask, real_simulation_client: FlaskClient) -> None:
        """A submitted home job with a battery completes, and its summary shows it generated power on the clear day real_simulation_client seeds."""
        submit_resp = real_simulation_client.post(
            "/api/simulate/home",
            json={**A_HOME_JOB_REQUEST, "battery_kwh": 5.0, "occupants": 2, "name": "Battery Test"},
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]

        assert app.extensions["job_manager"].wait_until_idle(timeout=120)

        status_resp = real_simulation_client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        assert status_resp.get_json()["status"] == "completed", status_resp.get_json()

        results_resp = real_simulation_client.get(f"/api/jobs/{job_id}/results")
        assert results_resp.status_code == 200
        assert results_resp.get_json()["summary"]["total_generation_kwh"] > 0

    def test_a_two_home_fleet_job_completes_with_its_results_stored(
        self, app: Flask, real_simulation_client: FlaskClient
    ) -> None:
        """Each home of the fleet runs on the weather create_app bound, and the fleet's summary is stored for its run."""
        submit_resp = real_simulation_client.post(
            "/api/simulate/fleet", json={"homes": [A_HOME_JOB_REQUEST, {**A_HOME_JOB_REQUEST, "pv_kw": 3.0}]}
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]
        run_id = submit_resp.get_json()["run_id"]

        assert app.extensions["job_manager"].wait_until_idle(timeout=120)

        results_resp = real_simulation_client.get(f"/api/jobs/{job_id}/results")
        assert results_resp.status_code == 200
        results_data = results_resp.get_json()
        assert (results_data["run_id"], results_data["type"]) == (run_id, "fleet")
        assert results_data["summary"]["n_homes"] == 2
        assert results_data["summary"]["per_home_generation_min_kwh"] > 0


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
