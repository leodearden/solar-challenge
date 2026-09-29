"""Tests for the background simulation API endpoints and job lifecycle."""

import collections
import json
import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest
pytest.importorskip("flask")
import pandas as pd
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.app import create_app
from solar_challenge.web.database import init_db
from solar_challenge.web.jobs import HomeSimulator, JobManager, live_managers, shutdown_all_managers
from solar_challenge.web.storage import RunStorage


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


class _BlockingSimulation:
    """Stands in for simulate_home: each job waits inside the simulation until release(), then gets an hour at its home's PV size."""

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


@pytest.fixture
def app(tmp_path) -> Flask:
    """Create a test Flask application with temporary database."""
    db_path = str(tmp_path / "test.db")
    data_dir = str(tmp_path / "data")
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": db_path,
            "DATA_DIR": data_dir,
        }
    )
    return test_app


def _client_whose_jobs_run(app: Flask, simulation: HomeSimulator) -> FlaskClient:
    """Make a JobManager that runs *simulation* the app's job manager, and return a client of the app."""
    app.extensions["job_manager"] = JobManager(simulate_home=simulation)
    return app.test_client()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A client whose jobs run a fake simulation that returns at once, so the teardown drain has nothing to wait for."""
    return _client_whose_jobs_run(app, _RecordingSimulation())


@pytest.fixture
def real_simulation_client(app: Flask) -> FlaskClient:
    """A client of the JobManager create_app built, whose jobs run the real simulate_home."""
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
        assert results_resp.get_json()["status"] == "running"

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
        from solar_challenge.web.jobs import JobManager
        assert isinstance(app.extensions["job_manager"], JobManager)

    def test_get_job_status_returns_none_for_unknown(self, app: Flask) -> None:
        """Test that get_job_status returns None for unknown job IDs."""
        jm = app.extensions["job_manager"]
        assert jm.get_job_status("nonexistent") is None


# ---------------------------------------------------------------------------
# Direct JobManager unit tests (no Flask required)
# ---------------------------------------------------------------------------


class TestJobManagerDirect:
    """Unit tests for JobManager exercised directly without Flask."""

    def test_thread_safety_concurrent_access(self, tmp_path: Path) -> None:
        """Test that concurrent get_job_status and get_events calls are thread-safe."""
        jm = JobManager(max_workers=1)

        # Manually inject some jobs into internal state
        with jm._lock:
            for i in range(10):
                jid = f"job-{i}"
                jm._jobs[jid] = {
                    "job_id": jid,
                    "run_id": f"run-{i}",
                    "status": "running",
                    "progress_pct": 50.0,
                    "current_step": "Testing",
                    "message": "In progress",
                    "created_at": time.monotonic(),
                }
                jm._event_queues[jid] = collections.deque(maxlen=100)
                jm._event_queues[jid].append({"event": "progress", "data": {"pct": 50}})

        errors: list[Exception] = []
        barrier = threading.Barrier(20)

        def worker(thread_id: int) -> None:
            try:
                barrier.wait()
                for i in range(10):
                    jid = f"job-{i}"
                    # Read job status
                    status = jm.get_job_status(jid)
                    assert status is None or isinstance(status, dict)
                    # Drain events
                    events = list(jm.get_events(jid))
                    assert isinstance(events, list)
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(t,)) for t in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            # Use a bounded timeout so a deadlocked thread surfaces as a clear
            # test failure rather than hanging the suite indefinitely.  60 s is
            # generous enough for any normal CI environment.  The barrier itself
            # has no timeout (barrier.wait()) so we can't get a BrokenBarrierError
            # from CPU contention; the only way join() times out is a real deadlock.
            t.join(timeout=60)
            assert not t.is_alive(), f"Thread did not finish within 60 s: {t}"

        assert len(errors) == 0, f"Thread safety errors: {errors}"

    def test_get_events_drains_queue(self) -> None:
        """Test that get_events yields events and clears the queue."""
        jm = JobManager(max_workers=1)

        job_id = "drain-test"
        with jm._lock:
            jm._jobs[job_id] = {
                "job_id": job_id,
                "run_id": "r1",
                "status": "running",
                "progress_pct": 0.0,
                "current_step": "test",
                "message": "test",
                "created_at": time.monotonic(),
            }
            jm._event_queues[job_id] = collections.deque(maxlen=100)

        # Add events
        with jm._lock:
            jm._event_queues[job_id].append({"event": "progress", "data": {"pct": 10}})
            jm._event_queues[job_id].append({"event": "progress", "data": {"pct": 20}})
            jm._event_queues[job_id].append({"event": "progress", "data": {"pct": 30}})

        # First call should yield all 3 events
        events = list(jm.get_events(job_id))
        assert len(events) == 3
        assert events[0]["data"]["pct"] == 10
        assert events[2]["data"]["pct"] == 30

        # Second call should yield nothing (queue was drained)
        events_again = list(jm.get_events(job_id))
        assert len(events_again) == 0

    def test_get_events_unknown_job_yields_nothing(self) -> None:
        """Test that get_events for an unknown job yields no events."""
        jm = JobManager(max_workers=1)
        events = list(jm.get_events("nonexistent-job-id"))
        assert events == []

    def test_ttl_cleanup_removes_old_jobs(self) -> None:
        """Test that _cleanup_old_jobs removes entries older than the TTL."""
        jm = JobManager(max_workers=1)

        # Insert a job with a created_at time in the distant past
        old_job_id = "old-job"
        new_job_id = "new-job"
        now = time.monotonic()

        with jm._lock:
            jm._jobs[old_job_id] = {
                "job_id": old_job_id,
                "run_id": "old-run",
                "status": "completed",
                "progress_pct": 100.0,
                "current_step": "Done",
                "message": "Done",
                "created_at": now - 7200,  # 2 hours ago
            }
            jm._event_queues[old_job_id] = collections.deque(maxlen=100)

            jm._jobs[new_job_id] = {
                "job_id": new_job_id,
                "run_id": "new-run",
                "status": "running",
                "progress_pct": 50.0,
                "current_step": "Running",
                "message": "Running",
                "created_at": now,  # just now
            }
            jm._event_queues[new_job_id] = collections.deque(maxlen=100)

        # Run cleanup with default 1-hour TTL
        jm._cleanup_old_jobs(max_age_seconds=3600.0)

        # Old job should be removed
        assert jm.get_job_status(old_job_id) is None
        assert old_job_id not in jm._event_queues

        # New job should still exist
        assert jm.get_job_status(new_job_id) is not None
        assert new_job_id in jm._event_queues

    def test_ttl_cleanup_preserves_all_when_young(self) -> None:
        """Test that _cleanup_old_jobs preserves jobs within the TTL."""
        jm = JobManager(max_workers=1)
        now = time.monotonic()

        with jm._lock:
            jm._jobs["young-job"] = {
                "job_id": "young-job",
                "run_id": "run",
                "status": "completed",
                "progress_pct": 100.0,
                "current_step": "Done",
                "message": "Done",
                "created_at": now - 60,  # 1 minute ago
            }
            jm._event_queues["young-job"] = collections.deque(maxlen=100)

        jm._cleanup_old_jobs(max_age_seconds=3600.0)

        # Should still be there
        assert jm.get_job_status("young-job") is not None


_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500))
_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")


def _run_storage(tmp_path: Path) -> RunStorage:
    storage = RunStorage(db_path=tmp_path / "jobs.db", data_dir=tmp_path / "data")
    init_db(storage.db_path)
    return storage


def _wait_until_finished(manager: JobManager, job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 30
    while True:
        status = manager.get_job_status(job_id)
        if status is None:
            pytest.fail(f"the manager has no status for job {job_id}")
        if status["status"] in ("completed", "failed"):
            return status
        if time.monotonic() > deadline:
            pytest.fail(f"job {job_id} did not finish within 30 s; its last status was {status}")
        time.sleep(0.01)


def _submit_home_job(manager: JobManager, tmp_path: Path) -> None:
    storage = _run_storage(tmp_path)
    manager.submit_home_job(
        config=_A_HOME,
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.db_path),
        data_dir=str(storage.data_dir),
    )


def _submit_fleet_job(manager: JobManager, tmp_path: Path) -> None:
    storage = _run_storage(tmp_path)
    manager.submit_fleet_job(
        configs=[_A_HOME],
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.db_path),
        data_dir=str(storage.data_dir),
    )


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

        status = _wait_until_finished(manager, job_id)
        assert status["status"] == "completed", status["message"]
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

        status = _wait_until_finished(manager, job_id)
        assert status["status"] == "completed", status["message"]
        assert simulation.calls == [(home, _JUNE_1, _JUNE_2) for home in homes]
        _, _, per_home_summaries = storage.load_fleet_run(run_id)
        assert [summary.total_generation_kwh for summary in per_home_summaries] == pytest.approx([4.0, 2.0])


class TestJobManagerShutdown:
    """Tests for JobManager shutdown."""

    def test_a_shut_down_manager_refuses_new_jobs(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1)

        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager, tmp_path)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_refused_job_leaves_no_run_in_the_history(
        self, submit_job: Callable[[JobManager, Path], None], tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1)
        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            submit_job(manager, tmp_path)

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
        from solar_challenge.web.database import init_db, get_db
        from solar_challenge.web.jobs import recover_stale_jobs

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
        from solar_challenge.web.database import init_db, get_db
        from solar_challenge.web.jobs import recover_stale_jobs

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
        from solar_challenge.web.database import init_db
        from solar_challenge.web.jobs import recover_stale_jobs

        db_path = str(tmp_path / "clean.db")
        init_db(db_path)

        recovered = recover_stale_jobs(db_path)
        assert recovered == 0
