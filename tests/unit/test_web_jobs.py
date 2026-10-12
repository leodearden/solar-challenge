"""Tests for the background simulation API endpoints and job lifecycle."""

import json
import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
pytest.importorskip("flask")
import pandas as pd
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.weather import WeatherCache
from solar_challenge.web.database import get_db, init_db
from solar_challenge.web.jobs import (
    HomeSimulator,
    JobEvent,
    JobEventType,
    JobManager,
    JobState,
    live_managers,
    recover_stale_jobs,
    shutdown_all_managers,
)
from solar_challenge.web.storage import RunRecord, RunStorage

from tests._synthetic_weather import synthetic_june_weather
from tests._web_app import build_test_app


def _an_hour_at(generation_kw: float) -> SimulationResults:
    index = pd.date_range("2024-06-01 12:00", periods=60, freq="1min")

    def constant(kw: float) -> pd.Series:
        return pd.Series([kw] * 60, index=index)

    return SimulationResults(
        generation=constant(generation_kw),
        demand=constant(1.0),
        self_consumption=constant(1.0),
        battery_charge=constant(0.0),
        battery_discharge=constant(0.0),
        battery_soc=constant(0.0),
        grid_import=constant(0.0),
        grid_export=constant(generation_kw - 1.0),
        import_cost=constant(0.0),
        export_revenue=constant(0.0),
        tariff_rate=constant(0.25),
    )


class _RecordingSimulation:
    """Stands in for simulate_home: records each home it is asked to simulate and returns an hour at the home's PV size."""

    def __init__(self) -> None:
        self.calls: list[tuple[HomeConfig, pd.Timestamp, pd.Timestamp]] = []

    def __call__(self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        self.calls.append((config, start_date, end_date))
        return _an_hour_at(config.pv_config.capacity_kw)


def _a_failing_simulation(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
    """Stands in for simulate_home: every job it runs fails."""
    raise RuntimeError("the simulation failed")


_A_MESSAGE_SQLITE_CANNOT_STORE = "the simulation failed on " + chr(0xDCFF)


def _a_simulation_failing_with_a_message_sqlite_cannot_store(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> SimulationResults:
    """Stands in for simulate_home: every job it runs fails with a message holding a lone surrogate, which sqlite3 cannot bind."""
    raise RuntimeError(_A_MESSAGE_SQLITE_CANNOT_STORE)


class _BlockingSimulation:
    """Stands in for simulate_home: every job waits inside the simulation until release(), then gets an hour at its home's PV size.

    wait_until_started() returns once the first job is inside the simulation.
    """

    def __init__(self) -> None:
        self._started = threading.Event()
        self._released = threading.Event()

    def __call__(self, config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        self._started.set()
        self._released.wait()
        return _an_hour_at(config.pv_config.capacity_kw)

    def wait_until_started(self) -> None:
        if not self._started.wait(timeout=30):
            pytest.fail("no job entered the simulation within 30 s")

    def release(self) -> None:
        self._released.set()


class _CountingIds:
    """Stands in for a JobManager's id source: issues "id-1", "id-2", ... and keeps every id it issued."""

    def __init__(self) -> None:
        self.issued: list[str] = []

    def __call__(self) -> str:
        self.issued.append(f"id-{len(self.issued) + 1}")
        return self.issued[-1]


class _ManualClock:
    """Stands in for a JobManager's clock: time stands still until advance() moves it on."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with temporary database."""
    return build_test_app(tmp_path)


def _client_using(app: Flask, manager: JobManager) -> FlaskClient:
    """Install *manager* as the app's job manager, and return a client of the app."""
    app.extensions["job_manager"] = manager
    return app.test_client()


def _client_whose_jobs_run(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Install a JobManager that runs *simulation* as the app's job manager, and return a client of the app."""
    return _client_using(app, JobManager(simulate_home=simulation))


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A client whose jobs run a fake simulation that returns at once, so the teardown drain has nothing to wait for."""
    return _client_whose_jobs_run(app, _RecordingSimulation())


@pytest.fixture
def real_simulation_client(app: Flask, weather_cache: WeatherCache) -> FlaskClient:
    """A client of the JobManager create_app built, whose jobs run the real simulate_home.

    Bristol's TMY is a clear day on 1 June 2024, the first day of every days window the API simulates.
    """
    weather_cache.put(synthetic_june_weather("2024-06-01"), "tmy", Location.bristol())
    return app.test_client()


@pytest.fixture
def blocking_simulation() -> Iterator[_BlockingSimulation]:
    """A _BlockingSimulation released at teardown, before tests/conftest.py drains the job managers."""
    simulation = _BlockingSimulation()
    yield simulation
    simulation.release()


@pytest.fixture
def blocking_client(app: Flask, blocking_simulation: _BlockingSimulation) -> FlaskClient:
    """A client whose jobs wait inside blocking_simulation until it is released."""
    return _client_whose_jobs_run(app, blocking_simulation)


class TestSimulateHomeEndpoint:
    """Tests for POST /api/simulate/home."""

    def test_submit_home_job_returns_201(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home returns 201 with job_id and run_id."""
        response = client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
                "name": "Test Simulation",
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert "job_id" in data
        assert "run_id" in data
        assert len(data["job_id"]) > 0
        assert len(data["run_id"]) > 0

    def test_submit_home_job_invalid_pv_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with invalid PV returns 400."""
        response = client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 0.1,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
        )
        assert response.status_code == 400
        data = response.get_json()
        assert "error" in data

    def test_submit_home_job_negative_battery_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with negative battery returns 400."""
        response = client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": -5.0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
        )
        assert response.status_code == 400

    def test_submit_home_job_no_json_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/home with no JSON body returns 400."""
        response = client.post(
            "/api/simulate/home",
            data="not json",
            content_type="text/plain",
        )
        assert response.status_code == 400


_A_HOME_JOB_REQUEST = {"pv_kw": 4.0, "battery_kwh": 0, "occupants": 3, "location": "bristol", "days": 1}


def _client_of_a_finished_job(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Return a client of *app* whose JobManager has run one home job through *simulation* to its end.

    The job's id is "id-1" and its run's id is "id-2".
    """
    manager = JobManager(simulate_home=simulation, new_id=_CountingIds())
    client = _client_using(app, manager)
    assert client.post("/api/simulate/home", json=_A_HOME_JOB_REQUEST).status_code == 201
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


class TestGetJobStatusEndpoint:
    """Tests for GET /api/jobs/<id>."""

    def test_get_job_status_returns_200(self, client: FlaskClient) -> None:
        """Test GET /api/jobs/<id> returns job status after submission."""
        # Submit a job first
        submit_resp = client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]

        # Check status
        status_resp = client.get(f"/api/jobs/{job_id}")
        assert status_resp.status_code == 200
        data = status_resp.get_json()
        assert data["job_id"] == job_id
        assert "status" in data
        assert "progress_pct" in data
        assert "current_step" in data

    def test_get_unknown_job_returns_404(self, client: FlaskClient) -> None:
        """Test GET /api/jobs/<unknown_id> returns 404."""
        response = client.get("/api/jobs/nonexistent-job-id-12345")
        assert response.status_code == 404
        data = response.get_json()
        assert "error" in data

    def test_after_a_restart_an_earlier_job_is_not_found_although_its_rows_remain(self, tmp_path: Path) -> None:
        before_restart = build_test_app(tmp_path)
        submitted = (
            _client_whose_jobs_run(before_restart, _RecordingSimulation())
            .post("/api/simulate/home", json=_A_HOME_JOB_REQUEST)
            .get_json()
        )
        assert before_restart.extensions["job_manager"].wait_until_idle(timeout=30)

        after_restart = build_test_app(tmp_path)

        response = after_restart.test_client().get(f"/api/jobs/{submitted['job_id']}")
        assert response.status_code == 404
        assert _job_rows(after_restart.extensions["storage"]) == [(submitted["job_id"], submitted["run_id"])]

    @pytest.mark.parametrize(
        ("simulation", "last_state"),
        [
            (
                _RecordingSimulation(),
                {
                    "status": "completed",
                    "progress_pct": 100.0,
                    "current_step": "Done",
                    "message": "Simulation completed successfully",
                },
            ),
            (
                _a_failing_simulation,
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
            "created_at": _job_row(app.extensions["storage"], "id-1")["created_at"],
        }


class TestJobProgressEndpoint:
    """Tests for GET /api/jobs/<id>/progress (SSE)."""

    def test_progress_returns_event_stream(self, client: FlaskClient) -> None:
        """Test GET /api/jobs/<id>/progress returns text/event-stream content type."""
        # Submit a job first
        submit_resp = client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]

        # Request progress stream
        response = client.get(f"/api/jobs/{job_id}/progress")
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type

    def test_progress_unknown_job_sends_error(self, client: FlaskClient) -> None:
        """Test GET /api/jobs/<unknown>/progress sends error event."""
        response = client.get("/api/jobs/nonexistent-id/progress")
        assert response.status_code == 200
        assert "text/event-stream" in response.content_type
        # The stream should contain an error event
        data = response.get_data(as_text=True)
        assert "error" in data

    def test_the_stream_of_a_completed_job_sends_each_progress_event_then_its_completion(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, _RecordingSimulation())

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == "".join(
            [
                _STARTING,
                _SIMULATING,
                _sse(
                    "progress",
                    '{"progress_pct": 80.0, "current_step": "Summarizing",'
                    ' "message": "Calculating summary statistics...", "status": "running"}',
                ),
                _sse(
                    "progress",
                    '{"progress_pct": 90.0, "current_step": "Saving",'
                    ' "message": "Persisting results to storage...", "status": "running"}',
                ),
                _sse(
                    "complete",
                    '{"status": "completed", "progress_pct": 100.0, "current_step": "Done",'
                    ' "message": "Simulation completed successfully", "run_id": "id-2"}',
                ),
            ]
        )

    def test_the_stream_of_a_failed_job_sends_each_progress_event_then_its_error(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, _a_failing_simulation)

        stream = client.get("/api/jobs/id-1/progress").get_data(as_text=True)

        assert stream == _STARTING + _SIMULATING + _sse(
            "error", '{"status": "failed", "message": "the simulation failed"}'
        )

    @pytest.mark.parametrize(
        ("simulation", "final_event"),
        [
            (_RecordingSimulation(), _sse("complete", '{"status": "completed", "run_id": "id-2"}')),
            (_a_failing_simulation, _sse("error", '{"status": "failed", "message": "the simulation failed"}')),
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


class TestJobResultsEndpoint:
    """Tests for GET /api/jobs/<id>/results."""

    def test_results_returns_409_while_running(
        self, blocking_client: FlaskClient, blocking_simulation: _BlockingSimulation
    ) -> None:
        """Test GET /api/jobs/<id>/results returns 409 while job is running."""
        submit_resp = blocking_client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
            },
        )
        assert submit_resp.status_code == 201
        job_id = submit_resp.get_json()["job_id"]
        blocking_simulation.wait_until_started()

        results_resp = blocking_client.get(f"/api/jobs/{job_id}/results")

        assert results_resp.status_code == 409
        assert results_resp.get_json() == {"error": "Job not yet completed", "status": "running", "progress_pct": 20.0}

    def test_a_failed_jobs_results_answer_409_with_its_status_and_its_last_progress(self, app: Flask) -> None:
        client = _client_of_a_finished_job(app, _a_failing_simulation)

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
        submit_resp = real_simulation_client.post(
            "/api/simulate/home",
            json={
                "pv_kw": 4.0,
                "battery_kwh": 0,
                "occupants": 3,
                "location": "bristol",
                "days": 1,
                "name": "E2E Test",
            },
        )
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
            json={
                "pv_kw": 4.0,
                "battery_kwh": 5.0,
                "occupants": 2,
                "location": "bristol",
                "days": 1,
                "name": "Battery Test",
            },
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
                    {
                        "pv_kw": 4.0,
                        "battery_kwh": 0,
                        "occupants": 3,
                        "location": "bristol",
                        "days": 1,
                    },
                    {
                        "pv_kw": 3.0,
                        "battery_kwh": 5.0,
                        "occupants": 2,
                        "location": "london",
                        "days": 1,
                    },
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


class TestJobManagerIntegration:
    """Tests for JobManager class directly."""

    def test_job_manager_exists_on_app(self, app: Flask) -> None:
        """Test that JobManager is registered as an app extension."""
        assert "job_manager" in app.extensions
        assert isinstance(app.extensions["job_manager"], JobManager)

    def test_job_state_returns_none_for_unknown(self, app: Flask) -> None:
        """Test that job_state returns None for unknown job IDs."""
        jm = app.extensions["job_manager"]
        assert jm.job_state("nonexistent") is None


# ---------------------------------------------------------------------------
# Direct JobManager unit tests (no Flask required)
# ---------------------------------------------------------------------------


class TestJobManagerDirect:
    """Unit tests for JobManager exercised directly without Flask."""

    def test_thread_safety_concurrent_access(self, blocking_simulation: _BlockingSimulation, tmp_path: Path) -> None:
        """Test that concurrent job_state and get_events calls are thread-safe."""
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_ids = [_submit_home_job(manager, tmp_path) for _ in range(10)]
        blocking_simulation.wait_until_started()

        errors: list[Exception] = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            try:
                barrier.wait()
                for job_id in job_ids:
                    assert manager.job_state(job_id) is not None
                    list(manager.get_events(job_id))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            # A bounded join turns a deadlock into a clear failure instead of a hung suite.
            t.join(timeout=60)
            assert not t.is_alive(), f"Thread did not finish within 60 s: {t}"

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_get_events_drains_queue(self, blocking_simulation: _BlockingSimulation, tmp_path: Path) -> None:
        """Test that get_events yields each queued event once."""
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        events = list(manager.get_events(job_id))

        assert [event.state.current_step for event in events] == ["Starting", "Simulating"]
        assert list(manager.get_events(job_id)) == []

    def test_each_progress_event_carries_the_state_the_job_reported_at_that_step(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        simulating = manager.job_state(job_id)
        assert simulating is not None

        events = list(manager.get_events(job_id))

        assert events == [
            JobEvent(
                "progress",
                replace(simulating, progress_pct=5.0, current_step="Starting", message="Initializing..."),
            ),
            JobEvent("progress", simulating),
        ]

    @pytest.mark.parametrize(
        ("simulation", "event_type"),
        [(_RecordingSimulation(), "complete"), (_a_failing_simulation, "error")],
        ids=["completed", "failed"],
    )
    def test_a_finished_jobs_last_event_carries_the_state_its_manager_reports(
        self, simulation: HomeSimulator, event_type: JobEventType, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=simulation)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        state = manager.job_state(job_id)
        assert state is not None

        assert list(manager.get_events(job_id))[-1] == JobEvent(event_type, state)

    def test_get_events_unknown_job_yields_nothing(self) -> None:
        """Test that get_events for an unknown job yields no events."""
        jm = JobManager(max_workers=1)
        events = list(jm.get_events("nonexistent-job-id"))
        assert events == []


_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500))
_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")


def _run_storage(tmp_path: Path) -> RunStorage:
    storage = RunStorage(db_path=tmp_path / "jobs.db", data_dir=tmp_path / "data")
    init_db(storage.db_path)
    return storage


def _refuse_new_rows(storage: RunStorage, table: str) -> None:
    """Make storage's database refuse every row inserted into *table*."""
    with get_db(storage.db_path) as conn:
        conn.execute(
            f"CREATE TRIGGER refuse_new_{table} BEFORE INSERT ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'the database refuses new {table} rows'); END"
        )


def _refuse_failed_rows(storage: RunStorage, table: str) -> None:
    """Make storage's database refuse every update that marks a row of *table* failed."""
    with get_db(storage.db_path) as conn:
        conn.execute(
            f"CREATE TRIGGER refuse_failed_{table} BEFORE UPDATE ON {table} WHEN NEW.status = 'failed' "
            f"BEGIN SELECT RAISE(ABORT, 'the database refuses failed {table} rows'); END"
        )


_JOBS_LOGGER = "solar_challenge.web.jobs"


def _records_logged_by_jobs_py(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _JOBS_LOGGER]


def _ids_tracked_by(manager: JobManager, ids: list[str]) -> list[str]:
    return [job_id for job_id in ids if manager.job_state(job_id) is not None]


def _job_rows(storage: RunStorage) -> list[tuple[str, str]]:
    """Return (id, run_id) of every row in storage's jobs table."""
    with get_db(storage.db_path) as conn:
        return [(row["id"], row["run_id"]) for row in conn.execute("SELECT id, run_id FROM jobs")]


def _job_row(storage: RunStorage, job_id: str) -> dict[str, Any]:
    """Return every column of job *job_id*'s row in storage's jobs table, by name."""
    with get_db(storage.db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None, f"storage's jobs table has no row for job {job_id}"
    return dict(row)


def _state_recorded_in_job_row(storage: RunStorage, job_id: str) -> JobState:
    """Return the state job *job_id*'s row in storage's jobs table records: its ids, status, progress, step, message and creation time."""
    row = _job_row(storage, job_id)
    return JobState(
        job_id=row["id"],
        run_id=row["run_id"],
        status=row["status"],
        progress_pct=row["progress_pct"],
        current_step=row["current_step"],
        message=row["message"],
        created_at=row["created_at"],
    )


def _run_of_job(manager: JobManager, job_id: str, storage: RunStorage) -> RunRecord:
    """Return the record storage holds for the run of job *job_id*, which *manager* tracks."""
    state = manager.job_state(job_id)
    assert state is not None, f"the manager does not track job {job_id}"
    run = storage.run_record(state.run_id)
    assert run is not None, f"no run has job {job_id}'s run id {state.run_id}"
    return run


def _wait_until_finished(manager: JobManager, job_id: str) -> JobState:
    deadline = time.monotonic() + 30
    while True:
        state = manager.job_state(job_id)
        if state is None:
            pytest.fail(f"the manager does not track job {job_id}")
        if state.status in ("completed", "failed"):
            return state
        if time.monotonic() > deadline:
            pytest.fail(f"job {job_id} did not finish within 30 s; its last state was {state}")
        time.sleep(0.01)


def _status_of(manager: JobManager, job_id: str) -> str | None:
    state = manager.job_state(job_id)
    return None if state is None else state.status


def _submit_home_job(manager: JobManager, tmp_path: Path) -> str:
    storage = _run_storage(tmp_path)
    job_id, _ = manager.submit_home_job(
        config=_A_HOME,
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.db_path),
        data_dir=str(storage.data_dir),
    )
    return job_id


def _submit_fleet_job(manager: JobManager, tmp_path: Path) -> str:
    storage = _run_storage(tmp_path)
    job_id, _ = manager.submit_fleet_job(
        configs=[_A_HOME],
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.db_path),
        data_dir=str(storage.data_dir),
    )
    return job_id


class TestJobManagerSimulation:
    """Tests for the simulation a JobManager runs."""

    def test_a_home_job_runs_the_simulation_the_manager_was_given(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        simulation = _RecordingSimulation()
        manager = JobManager(max_workers=1, simulate_home=simulation)

        job_id, run_id = manager.submit_home_job(
            config=_A_HOME,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.db_path),
            data_dir=str(storage.data_dir),
        )

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        assert simulation.calls == [(_A_HOME, _JUNE_1, _JUNE_2)]
        _, _, summary = storage.load_home_run(run_id)
        assert summary.total_generation_kwh == pytest.approx(4.0)

    def test_a_fleet_job_runs_the_managers_simulation_once_per_home(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        simulation = _RecordingSimulation()
        manager = JobManager(max_workers=1, simulate_home=simulation)
        homes = [
            _A_HOME,
            HomeConfig(pv_config=PVConfig(capacity_kw=2.0), load_config=LoadConfig(annual_consumption_kwh=3500)),
        ]

        job_id, run_id = manager.submit_fleet_job(
            configs=homes,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.db_path),
            data_dir=str(storage.data_dir),
        )

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        assert simulation.calls == [(home, _JUNE_1, _JUNE_2) for home in homes]
        _, _, per_home_summaries = storage.load_fleet_run(run_id)
        assert [summary.total_generation_kwh for summary in per_home_summaries] == pytest.approx([4.0, 2.0])


class TestJobManagerIds:
    """Tests for the ids a JobManager gives its jobs and their runs."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_job_and_its_run_take_their_ids_from_the_managers_id_source(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        ids = _CountingIds()
        manager = JobManager(max_workers=1, simulate_home=_RecordingSimulation(), new_id=ids)

        job_id = submit_job(manager, tmp_path)

        state = manager.job_state(job_id)
        assert state is not None
        run_id = state.run_id
        assert {job_id, run_id} == set(ids.issued)
        storage = _run_storage(tmp_path)
        assert [run["id"] for run in storage.list_runs()] == [run_id]
        assert _job_rows(storage) == [(job_id, run_id)]


class TestJobManagerState:
    """Tests for the state a JobManager reports for a job: only while it tracks the job in memory."""

    def test_a_jobs_state_holds_its_ids_its_progress_and_its_rows_creation_time(
        self, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=_RecordingSimulation())

        job_id, run_id = manager.submit_home_job(
            config=_A_HOME,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.db_path),
            data_dir=str(storage.data_dir),
        )
        assert manager.wait_until_idle(timeout=30)

        assert manager.job_state(job_id) == JobState(
            job_id=job_id,
            run_id=run_id,
            status="completed",
            progress_pct=100.0,
            current_step="Done",
            message="Simulation completed successfully",
            created_at=_job_row(storage, job_id)["created_at"],
        )

    def test_a_state_the_manager_reported_stays_as_it_was_after_the_job_moves_on(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        running = manager.job_state(job_id)
        assert running is not None

        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        assert (running.status, running.progress_pct, running.current_step, running.message) == (
            "running",
            20.0,
            "Simulating",
            "Running home simulation...",
        )
        assert _status_of(manager, job_id) == "completed"

    def test_a_manager_does_not_know_a_job_another_manager_ran_although_its_rows_remain(
        self, tmp_path: Path
    ) -> None:
        first = JobManager(max_workers=1, simulate_home=_RecordingSimulation())
        job_id = _submit_home_job(first, tmp_path)
        assert first.wait_until_idle(timeout=30)

        assert JobManager(max_workers=1).job_state(job_id) is None
        assert _job_row(_run_storage(tmp_path), job_id)["status"] == "completed"


class TestRunLabelsEditedWhileItsJobRuns:
    """A run renamed or annotated in Run History while its job runs keeps those labels when the job finishes."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_run_edited_while_its_job_runs_keeps_its_labels_when_the_job_completes(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: _BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        storage = _run_storage(tmp_path)
        run_id = _run_of_job(manager, job_id, storage).id
        storage.update_run_labels(run_id, {"name": "Renamed by user", "notes": "my note"})

        blocking_simulation.release()

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        run = storage.run_record(run_id)
        assert run is not None
        assert (run.status, run.name, run.notes) == ("completed", "Renamed by user", "my note")


_A_MINUTE = 60.0
_A_DAY = 24 * 60 * 60.0


class TestJobManagerAgeLimit:
    """Tests for how long a JobManager tracks a job: until it finishes, and for a while after."""

    def test_a_finished_job_is_still_tracked_at_a_submit_a_minute_after_it_finished(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        manager = JobManager(max_workers=1, simulate_home=_RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_MINUTE)

        _submit_home_job(manager, tmp_path)

        assert _status_of(manager, job_id) == "completed"

    def test_a_finished_job_is_not_tracked_after_a_submit_a_day_after_it_finished(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        manager = JobManager(max_workers=1, simulate_home=_RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_DAY)

        _submit_home_job(manager, tmp_path)

        assert manager.job_state(job_id) is None

    def test_a_job_that_finished_a_minute_ago_is_still_tracked_though_it_was_submitted_a_day_before(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation, clock=clock)
        job_id = _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_MINUTE)

        _submit_home_job(manager, tmp_path)

        assert _status_of(manager, job_id) == "completed"

    def test_a_job_still_running_a_day_after_it_was_submitted_is_still_reported_after_a_later_submit(
        self, app: Flask, blocking_simulation: _BlockingSimulation
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(simulate_home=blocking_simulation, clock=clock)
        client = _client_using(app, manager)
        job_id = client.post("/api/simulate/home", json=_A_HOME_JOB_REQUEST).get_json()["job_id"]
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)

        assert client.post("/api/simulate/home", json=_A_HOME_JOB_REQUEST).status_code == 201

        assert _status_of(manager, job_id) == "running"
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        assert response.get_json()["status"] == "running"

    def test_the_progress_stream_of_a_job_that_ran_past_a_later_submit_a_day_on_ends_with_its_completion(
        self, app: Flask, blocking_simulation: _BlockingSimulation
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(simulate_home=blocking_simulation, clock=clock)
        client = _client_using(app, manager)
        submitted = client.post("/api/simulate/home", json=_A_HOME_JOB_REQUEST).get_json()
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)
        assert client.post("/api/simulate/home", json=_A_HOME_JOB_REQUEST).status_code == 201

        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        stream = client.get(f"/api/jobs/{submitted['job_id']}/progress").get_data(as_text=True)
        assert "event: complete" in stream
        assert submitted["run_id"] in stream


class TestJobManagerQueuedJobs:
    """Tests for a job that waits in the queue behind a running one."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_queued_job_is_in_the_same_state_in_memory_and_in_its_job_row(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: _BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        queued_job_id = submit_job(manager, tmp_path)

        stored = _state_recorded_in_job_row(_run_storage(tmp_path), queued_job_id)
        assert stored.status == "queued"
        assert manager.job_state(queued_job_id) == stored


class TestJobManagerRuns:
    """Tests for the row a JobManager writes for each job's run, as RunStorage reads it."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_jobs_run_is_running_while_its_simulation_runs(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: _BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message, run.completed_at) == ("running", None, None)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failed_jobs_run_is_failed_with_the_jobs_error_and_a_completion_time(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message) == ("failed", "the simulation failed")
        assert run.completed_at is not None


class TestJobManagerJobRows:
    """Tests for the row a JobManager writes for each job in the jobs table."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_jobs_row_is_running_with_a_start_time_while_its_simulation_runs(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: _BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        row = _job_row(storage, job_id)

        assert (row["status"], row["completed_at"]) == ("running", None)
        assert row["started_at"] is not None

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failed_jobs_row_is_failed_with_the_jobs_error_its_traceback_and_a_completion_time(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        row = _job_row(storage, job_id)

        assert (row["status"], row["message"]) == ("failed", "the simulation failed")
        assert "RuntimeError: the simulation failed" in row["error_traceback"]
        assert row["completed_at"] is not None

    @pytest.mark.parametrize(
        ("simulation", "status"),
        [(_RecordingSimulation(), "completed"), (_a_failing_simulation, "failed")],
        ids=["completed", "failed"],
    )
    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_finished_jobs_row_records_the_state_its_manager_reports(
        self, submit_job: Callable[[JobManager, Path], str], simulation: HomeSimulator, status: str, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        stored = _state_recorded_in_job_row(storage, job_id)

        assert stored.status == status
        assert manager.job_state(job_id) == stored


class TestJobManagerRefusedRows:
    """Tests for a submit whose run or job row the database refuses."""

    @pytest.mark.parametrize("table", ["runs", "jobs"])
    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_job_whose_row_the_database_refuses_leaves_no_record(
        self, submit_job: Callable[[JobManager, Path], str], table: str, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_new_rows(storage, table)
        ids = _CountingIds()
        manager = JobManager(max_workers=1, new_id=ids)

        with pytest.raises(sqlite3.IntegrityError, match=f"refuses new {table} rows"):
            submit_job(manager, tmp_path)

        assert ids.issued
        assert _ids_tracked_by(manager, ids.issued) == []
        assert storage.list_runs() == []


class TestJobManagerUnrecordedFailures:
    """Tests for a failed job whose failure the database does not record in its jobs row or in its run's row."""

    @pytest.mark.parametrize("table", ["jobs", "runs"])
    def test_a_failure_a_table_refuses_to_record_is_logged_naming_the_job_its_run_and_the_refusal(
        self, table: str, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_failed_rows(storage, table)
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation, new_id=_CountingIds())

        with caplog.at_level(logging.ERROR, logger=_JOBS_LOGGER):
            _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)

        records = _records_logged_by_jobs_py(caplog)
        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                f"Could not record in the {table} table that job id-1 of run id-2 failed with 'the simulation failed'",
            )
        ]
        assert records[0].exc_info is not None
        refusal = records[0].exc_info[1]
        assert (type(refusal), str(refusal)) == (sqlite3.IntegrityError, f"the database refuses failed {table} rows")
        assert (type(refusal.__context__), str(refusal.__context__)) == (RuntimeError, "the simulation failed")

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failure_the_jobs_table_refuses_to_record_is_still_recorded_in_the_runs_table(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_failed_rows(storage, "jobs")
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert _job_row(storage, job_id)["status"] == "running"
        assert (run.status, run.error_message) == ("failed", "the simulation failed")
        assert run.completed_at is not None

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failure_the_runs_table_refuses_to_record_is_still_recorded_in_the_jobs_table(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_failed_rows(storage, "runs")
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        row = _job_row(storage, job_id)

        assert _run_of_job(manager, job_id, storage).status == "running"
        assert (row["status"], row["message"]) == ("failed", "the simulation failed")
        assert "RuntimeError: the simulation failed" in row["error_traceback"]
        assert row["completed_at"] is not None

    @pytest.mark.parametrize("table", ["jobs", "runs"])
    def test_a_job_whose_failure_a_table_refuses_to_record_is_still_reported_failed_with_its_error_event(
        self, table: str, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_failed_rows(storage, table)
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        state = manager.job_state(job_id)

        assert state is not None
        assert (state.status, state.message) == ("failed", "the simulation failed")
        assert list(manager.get_events(job_id))[-1] == JobEvent("error", state)

    def test_a_failure_whose_message_sqlite_cannot_store_is_logged_for_each_table_and_still_reported(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = JobManager(
            max_workers=1, simulate_home=_a_simulation_failing_with_a_message_sqlite_cannot_store, new_id=_CountingIds()
        )

        with caplog.at_level(logging.ERROR, logger=_JOBS_LOGGER):
            job_id = _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)

        records = _records_logged_by_jobs_py(caplog)
        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                f"Could not record in the {table} table that job id-1 of run id-2 failed with {_A_MESSAGE_SQLITE_CANNOT_STORE!r}",
            )
            for table in ("jobs", "runs")
        ]
        assert [type(record.exc_info[1]) for record in records if record.exc_info] == [UnicodeEncodeError] * 2
        assert _status_of(manager, job_id) == "failed"


class TestJobManagerShutdown:
    """Tests for JobManager shutdown."""

    def test_a_shut_down_manager_refuses_new_jobs(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1)

        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager, tmp_path)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_refused_job_leaves_no_record(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        ids = _CountingIds()
        manager = JobManager(max_workers=1, new_id=ids)
        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            submit_job(manager, tmp_path)

        assert ids.issued
        assert _ids_tracked_by(manager, ids.issued) == []
        assert _run_storage(tmp_path).list_runs() == []

    def test_shutdown_all_managers_shuts_down_every_live_manager(self, tmp_path: Path) -> None:
        managers = [JobManager(max_workers=1), JobManager(max_workers=1)]

        shutdown_all_managers()

        for manager in managers:
            with pytest.raises(RuntimeError, match="after shutdown"):
                _submit_home_job(manager, tmp_path)

    def test_shutdown_all_managers_is_idempotent(self) -> None:
        """Test that calling shutdown_all_managers() twice does not raise."""
        # Bind to a local variable so the manager has a strong reference and
        # is not garbage-collected from the WeakSet before the first shutdown
        # call — without this the WeakSet could be empty and the test would
        # pass trivially without exercising the double-shutdown path.
        jm = JobManager(max_workers=1)

        shutdown_all_managers()
        shutdown_all_managers()  # must not raise

        # Suppress "local variable 'jm' assigned but never used" lint; the
        # strong reference is the point — it keeps jm alive through both calls.
        del jm


class TestJobManagerWaitUntilIdle:
    """Tests for JobManager.wait_until_idle, which blocks until no job is queued or running."""

    def test_a_manager_never_given_a_job_is_idle(self) -> None:
        assert JobManager(max_workers=1).wait_until_idle(timeout=0) is True

    def test_waiting_returns_false_when_the_timeout_passes_while_a_job_runs(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        assert manager.wait_until_idle(timeout=0.05) is False

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_waiting_returns_true_once_every_submitted_job_has_finished(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: _BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_ids = [submit_job(manager, tmp_path), submit_job(manager, tmp_path)]
        blocking_simulation.wait_until_started()

        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True
        assert [_status_of(manager, job_id) for job_id in job_ids] == ["completed", "completed"]

    def test_a_failed_job_counts_as_finished(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_id = _submit_home_job(manager, tmp_path)

        assert manager.wait_until_idle(timeout=30) is True
        assert _status_of(manager, job_id) == "failed"

    def test_a_job_dropped_by_shutdown_does_not_keep_the_manager_busy(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        manager.shutdown()
        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True

    def test_a_job_the_manager_refused_does_not_keep_it_busy(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1)
        manager.shutdown()
        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager, tmp_path)

        assert manager.wait_until_idle(timeout=0) is True


class TestLiveManagers:
    """Tests for live_managers(), the snapshot of every JobManager not yet garbage-collected."""

    def test_live_managers_reports_a_newly_constructed_manager(self) -> None:
        manager = JobManager(max_workers=1)

        assert manager in live_managers()

    def test_an_earlier_snapshot_does_not_gain_managers_constructed_after_it(self) -> None:
        snapshot = live_managers()
        manager = JobManager(max_workers=1)

        assert manager not in snapshot

    def test_live_managers_includes_shut_down_managers(self) -> None:
        manager = JobManager(max_workers=1)
        manager.shutdown()

        assert manager in live_managers()


class TestRecoverStaleJobs:
    """Tests for recover_stale_jobs on startup."""

    def test_recover_marks_running_jobs_as_failed(self, tmp_path: Path) -> None:
        """Test that running jobs are marked as failed on recovery."""
        db_path = str(tmp_path / "stale.db")
        init_db(db_path)

        # Insert a run and job in 'running' state
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                ("run-1", "Stale Run", "home", "running"),
            )
            cursor.execute(
                "INSERT INTO jobs (id, run_id, status) VALUES (?, ?, ?)",
                ("job-1", "run-1", "running"),
            )

        recovered = recover_stale_jobs(db_path)
        assert recovered == 1

        # Verify job status
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, message FROM jobs WHERE id = ?", ("job-1",))
            row = cursor.fetchone()
            assert row["status"] == "failed"
            assert "server restart" in row["message"].lower()

    def test_recover_marks_queued_jobs_as_failed(self, tmp_path: Path) -> None:
        """Test that queued jobs are also recovered."""
        db_path = str(tmp_path / "stale2.db")
        init_db(db_path)

        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                ("run-1", "Queued Run", "home", "running"),
            )
            cursor.execute(
                "INSERT INTO jobs (id, run_id, status) VALUES (?, ?, ?)",
                ("job-1", "run-1", "queued"),
            )

        recovered = recover_stale_jobs(db_path)
        assert recovered == 1

    def test_recover_no_stale_jobs_returns_zero(self, tmp_path: Path) -> None:
        """Test that recovery returns 0 when no stale jobs exist."""
        db_path = str(tmp_path / "clean.db")
        init_db(db_path)

        recovered = recover_stale_jobs(db_path)
        assert recovered == 0

    def test_recovery_fails_the_run_of_a_job_dropped_when_its_manager_shut_down(
        self, blocking_simulation: _BlockingSimulation, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        dropped_job_id = _submit_home_job(manager, tmp_path)
        manager.shutdown()
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        assert _run_of_job(manager, dropped_job_id, storage).status == "running"

        recover_stale_jobs(storage.db_path)

        run = _run_of_job(manager, dropped_job_id, storage)
        assert (run.status, run.error_message) == ("failed", "Interrupted by server restart")
        assert run.completed_at is not None

    def test_recovery_leaves_a_completed_run_and_a_failed_run_as_they_were(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        completing = JobManager(max_workers=1, simulate_home=_RecordingSimulation())
        failing = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        jobs = [(completing, _submit_home_job(completing, tmp_path)), (failing, _submit_home_job(failing, tmp_path))]
        assert completing.wait_until_idle(timeout=30)
        assert failing.wait_until_idle(timeout=30)
        before = [_run_of_job(manager, job_id, storage) for manager, job_id in jobs]
        assert [run.status for run in before] == ["completed", "failed"]

        recover_stale_jobs(storage.db_path)

        assert [_run_of_job(manager, job_id, storage) for manager, job_id in jobs] == before

    def test_recovery_leaves_a_completed_job_and_a_failed_job_as_they_were(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        completing = JobManager(max_workers=1, simulate_home=_RecordingSimulation())
        failing = JobManager(max_workers=1, simulate_home=_a_failing_simulation)
        job_ids = [_submit_home_job(completing, tmp_path), _submit_home_job(failing, tmp_path)]
        assert completing.wait_until_idle(timeout=30)
        assert failing.wait_until_idle(timeout=30)
        before = [_job_row(storage, job_id) for job_id in job_ids]
        assert [row["status"] for row in before] == ["completed", "failed"]

        recover_stale_jobs(storage.db_path)

        assert [_job_row(storage, job_id) for job_id in job_ids] == before
