# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.jobs: JobManager, live_managers, shutdown_all_managers and recover_stale_jobs."""

import logging
import sqlite3
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask import Flask

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import init_db
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
from tests.unit.web_jobs._app_client import A_HOME_JOB_REQUEST, client_using
from tests.unit.web_jobs._fakes import BlockingSimulation, CountingIds, RecordingSimulation, a_failing_simulation
from tests.unit.web_jobs._jobs_table import job_row, job_rows


_A_MESSAGE_SQLITE_CANNOT_STORE = "the simulation failed on " + chr(0xDCFF)


def _a_simulation_failing_with_a_message_sqlite_cannot_store(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> SimulationResults:
    """Stands in for simulate_home: every job it runs fails with a message holding a lone surrogate, which sqlite3 cannot bind."""
    raise RuntimeError(_A_MESSAGE_SQLITE_CANNOT_STORE)


def _a_simulation_that_exits(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
    """Stands in for simulate_home: every job it runs raises SystemExit, an error that is not an Exception."""
    raise SystemExit("the simulation exited")


class _AnErrorWhoseMessageCannotBeRead(BaseException):
    """An error that is not an Exception and whose message cannot be read, so a job that raised it cannot be reported failed."""

    def __str__(self) -> str:
        raise RuntimeError("the message of this error cannot be read")


def _a_simulation_raising_an_error_whose_message_cannot_be_read(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> SimulationResults:
    """Stands in for simulate_home: every job it runs raises an error whose message cannot be read."""
    raise _AnErrorWhoseMessageCannotBeRead()


class _AnInterruption(BaseException):
    """An error that is not an Exception."""


class _AnErrorWhoseMessageIsInterrupted(BaseException):
    """An error that is not an Exception, and reading whose message raises _AnInterruption, so failing a job that raised it raises an error that is not an Exception either."""

    def __str__(self) -> str:
        raise _AnInterruption("reading the message of this error was interrupted")


def _released_then_raising(blocking_simulation: BlockingSimulation, error: Callable[[], BaseException]) -> HomeSimulator:
    """Stands in for simulate_home: every job waits in *blocking_simulation* until it is released, then raises error()."""

    def simulate(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        blocking_simulation(config, start_date, end_date)
        raise error()

    return simulate


class _ManualClock:
    """Stands in for a JobManager's clock: time stands still until advance() moves it on."""

    def __init__(self) -> None:
        self._now = 0.0

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestJobManagerConstruction:
    """A JobManager is built with the home simulation its jobs run; it has none of its own."""

    def test_a_manager_is_given_its_home_simulator(self) -> None:
        with pytest.raises(TypeError, match="simulate_home"):
            JobManager()


class TestJobManagerDirect:
    """Tests for the events a JobManager queues for its jobs, read with get_events."""

    def test_thread_safety_concurrent_access(self, blocking_simulation: BlockingSimulation, tmp_path: Path) -> None:
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

    def test_get_events_drains_queue(self, blocking_simulation: BlockingSimulation, tmp_path: Path) -> None:
        """Test that get_events yields each queued event once."""
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        events = list(manager.get_events(job_id))

        assert [event.state.current_step for event in events] == ["Starting", "Simulating"]
        assert list(manager.get_events(job_id)) == []

    def test_each_progress_event_carries_the_state_the_job_reported_at_that_step(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
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
        [(RecordingSimulation(), "complete"), (a_failing_simulation, "error")],
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
        jm = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        events = list(jm.get_events("nonexistent-job-id"))
        assert events == []


_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500))
_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")


def _run_storage(tmp_path: Path) -> RunStorage:
    return RunStorage(init_db(tmp_path / "jobs.db"), tmp_path / "data")


def _refuse_new_rows(storage: RunStorage, table: str) -> None:
    """Make storage's database refuse every row inserted into *table*."""
    with storage.database.transaction() as conn:
        conn.execute(
            f"CREATE TRIGGER refuse_new_{table} BEFORE INSERT ON {table} "
            f"BEGIN SELECT RAISE(ABORT, 'the database refuses new {table} rows'); END"
        )


def _refuse_failed_rows(storage: RunStorage, table: str) -> None:
    """Make storage's database refuse every update that marks a row of *table* failed."""
    with storage.database.transaction() as conn:
        conn.execute(
            f"CREATE TRIGGER refuse_failed_{table} BEFORE UPDATE ON {table} WHEN NEW.status = 'failed' "
            f"BEGIN SELECT RAISE(ABORT, 'the database refuses failed {table} rows'); END"
        )


def _queue_a_job_whose_database_cannot_be_opened_when_it_starts(
    manager: JobManager, blocking_simulation: BlockingSimulation, tmp_path: Path
) -> str:
    """Queue a home job on *manager* behind one held in *blocking_simulation*, then turn its database file into a directory.

    Each job has a database of its own, so the held job completes once released, and the queued job cannot open its
    database when it starts. Returns the queued job's id.
    """
    _submit_home_job(manager, tmp_path / "held")
    blocking_simulation.wait_until_started()
    queued_storage = _run_storage(tmp_path / "queued")
    queued_job_id = _submit_home_job_to(manager, queued_storage)
    queued_storage.database.path.unlink()
    queued_storage.database.path.mkdir()
    return queued_job_id


_JOBS_LOGGER = "solar_challenge.web.jobs"


def _records_logged_by_jobs_py(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.name == _JOBS_LOGGER]


class _RecordKeeper(logging.Handler):
    """Keeps every record it handles, in order."""

    def __init__(self, level: int) -> None:
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@contextmanager
def _errors_logged_by_jobs_py_kept_out_of_the_report() -> Iterator[list[logging.LogRecord]]:
    """Collect the ERROR records jobs.py logs in the block, and pass none on to pytest, which would write them into the test's report.

    tests/unit/test_xdist_sendable_reports.py says why a report must not hold them.
    """
    jobs_logger = logging.getLogger(_JOBS_LOGGER)
    keeper = _RecordKeeper(logging.ERROR)
    propagated_before = jobs_logger.propagate
    jobs_logger.addHandler(keeper)
    jobs_logger.propagate = False
    try:
        yield keeper.records
    finally:
        jobs_logger.propagate = propagated_before
        jobs_logger.removeHandler(keeper)


def _ids_tracked_by(manager: JobManager, ids: list[str]) -> list[str]:
    return [job_id for job_id in ids if manager.job_state(job_id) is not None]


def _state_recorded_in_job_row(storage: RunStorage, job_id: str) -> JobState:
    """Return the state job *job_id*'s row in storage's jobs table records: its ids, status, progress, step, message and creation time."""
    row = job_row(storage, job_id)
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
    return _submit_home_job_to(manager, _run_storage(tmp_path))


def _submit_home_job_to(manager: JobManager, storage: RunStorage) -> str:
    job_id, _ = manager.submit_home_job(
        config=_A_HOME,
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.database.path),
        data_dir=str(storage.data_dir),
    )
    return job_id


def _submit_fleet_job(manager: JobManager, tmp_path: Path) -> str:
    storage = _run_storage(tmp_path)
    job_id, _ = manager.submit_fleet_job(
        configs=[_A_HOME],
        start_date=_JUNE_1,
        end_date=_JUNE_2,
        db_path=str(storage.database.path),
        data_dir=str(storage.data_dir),
    )
    return job_id


class TestJobManagerSimulation:
    """Tests for the simulation a JobManager runs."""

    def test_a_home_job_runs_the_simulation_the_manager_was_given(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        simulation = RecordingSimulation()
        manager = JobManager(max_workers=1, simulate_home=simulation)

        job_id, run_id = manager.submit_home_job(
            config=_A_HOME,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.database.path),
            data_dir=str(storage.data_dir),
        )

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        assert simulation.calls == [(_A_HOME, _JUNE_1, _JUNE_2)]
        _, _, summary = storage.load_home_run(run_id)
        assert summary.total_generation_kwh == pytest.approx(4.0)

    def test_a_fleet_job_runs_the_managers_simulation_once_per_home(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        simulation = RecordingSimulation()
        manager = JobManager(max_workers=1, simulate_home=simulation)
        homes = [
            _A_HOME,
            HomeConfig(pv_config=PVConfig(capacity_kw=2.0), load_config=LoadConfig(annual_consumption_kwh=3500)),
        ]

        job_id, run_id = manager.submit_fleet_job(
            configs=homes,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.database.path),
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
        ids = CountingIds()
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)

        job_id = submit_job(manager, tmp_path)

        state = manager.job_state(job_id)
        assert state is not None
        run_id = state.run_id
        assert {job_id, run_id} == set(ids.issued)
        storage = _run_storage(tmp_path)
        assert [run["id"] for run in storage.list_runs()] == [run_id]
        assert job_rows(storage) == [(job_id, run_id)]


class TestJobManagerState:
    """Tests for the state a JobManager reports for a job: only while it tracks the job in memory."""

    def test_a_jobs_state_holds_its_ids_its_progress_and_its_rows_creation_time(
        self, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())

        job_id, run_id = manager.submit_home_job(
            config=_A_HOME,
            start_date=_JUNE_1,
            end_date=_JUNE_2,
            db_path=str(storage.database.path),
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
            created_at=job_row(storage, job_id)["created_at"],
        )

    def test_a_state_the_manager_reported_stays_as_it_was_after_the_job_moves_on(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
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
        first = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        job_id = _submit_home_job(first, tmp_path)
        assert first.wait_until_idle(timeout=30)

        assert JobManager(max_workers=1, simulate_home=RecordingSimulation()).job_state(job_id) is None
        assert job_row(_run_storage(tmp_path), job_id)["status"] == "completed"


class TestRunLabelsEditedWhileItsJobRuns:
    """A run renamed or annotated in Run History while its job runs keeps those labels when the job finishes."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_run_edited_while_its_job_runs_keeps_its_labels_when_the_job_completes(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: BlockingSimulation,
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
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_MINUTE)

        _submit_home_job(manager, tmp_path)

        assert _status_of(manager, job_id) == "completed"

    def test_a_finished_job_is_not_tracked_after_a_submit_a_day_after_it_finished(self, tmp_path: Path) -> None:
        clock = _ManualClock()
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_DAY)

        _submit_home_job(manager, tmp_path)

        assert manager.job_state(job_id) is None

    def test_a_job_whose_failure_cannot_be_reported_is_not_tracked_after_a_submit_a_day_after_it_finished(
        self, tmp_path: Path
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(
            max_workers=1, simulate_home=_a_simulation_raising_an_error_whose_message_cannot_be_read, clock=clock
        )
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_DAY)

        _submit_home_job(manager, tmp_path)

        assert manager.job_state(job_id) is None

    def test_a_job_that_finished_a_minute_ago_is_still_tracked_though_it_was_submitted_a_day_before(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
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
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(simulate_home=blocking_simulation, clock=clock)
        client = client_using(app, manager)
        job_id = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()["job_id"]
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)

        assert client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).status_code == 201

        assert _status_of(manager, job_id) == "running"
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        assert response.get_json()["status"] == "running"

    def test_the_progress_stream_of_a_job_that_ran_past_a_later_submit_a_day_on_ends_with_its_completion(
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        clock = _ManualClock()
        manager = JobManager(simulate_home=blocking_simulation, clock=clock)
        client = client_using(app, manager)
        submitted = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)
        assert client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).status_code == 201

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
        blocking_simulation: BlockingSimulation,
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
        blocking_simulation: BlockingSimulation,
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
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
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
        blocking_simulation: BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        row = job_row(storage, job_id)

        assert (row["status"], row["completed_at"]) == ("running", None)
        assert row["started_at"] is not None

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_running_jobs_row_records_the_state_its_manager_reports(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        stored = _state_recorded_in_job_row(storage, job_id)

        assert stored.status == "running"
        assert manager.job_state(job_id) == stored

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failed_jobs_row_is_failed_with_the_jobs_error_its_traceback_and_a_completion_time(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        row = job_row(storage, job_id)

        assert (row["status"], row["message"]) == ("failed", "the simulation failed")
        assert "RuntimeError: the simulation failed" in row["error_traceback"]
        assert row["completed_at"] is not None

    @pytest.mark.parametrize(
        ("simulation", "status"),
        [(RecordingSimulation(), "completed"), (a_failing_simulation, "failed")],
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
        ids = CountingIds()
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)

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
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation, new_id=CountingIds())

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
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert job_row(storage, job_id)["status"] == "running"
        assert (run.status, run.error_message) == ("failed", "the simulation failed")
        assert run.completed_at is not None

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failure_the_runs_table_refuses_to_record_is_still_recorded_in_the_jobs_table(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        _refuse_failed_rows(storage, "runs")
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_id = submit_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        row = job_row(storage, job_id)

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
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_id = _submit_home_job(manager, tmp_path)
        assert manager.wait_until_idle(timeout=30)

        state = manager.job_state(job_id)

        assert state is not None
        assert (state.status, state.message) == ("failed", "the simulation failed")
        assert list(manager.get_events(job_id))[-1] == JobEvent("error", state)

    def test_a_failure_whose_message_sqlite_cannot_store_is_logged_for_each_table_and_still_reported(
        self, tmp_path: Path
    ) -> None:
        manager = JobManager(
            max_workers=1, simulate_home=_a_simulation_failing_with_a_message_sqlite_cannot_store, new_id=CountingIds()
        )

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            job_id = _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)

        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                f"Could not record in the {table} table that job id-1 of run id-2 failed with {_A_MESSAGE_SQLITE_CANNOT_STORE!r}",
            )
            for table in ("jobs", "runs")
        ]
        assert [type(record.exc_info[1]) for record in records if record.exc_info] == [UnicodeEncodeError] * 2
        assert _status_of(manager, job_id) == "failed"


class TestJobManagerEscapedErrors:
    """Tests for a job whose runner raises an error that the runner's own failure handling does not catch."""

    def test_a_job_whose_database_cannot_be_opened_when_it_starts_is_reported_failed_with_its_error_event(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_id = _queue_a_job_whose_database_cannot_be_opened_when_it_starts(manager, blocking_simulation, tmp_path)
        queued = manager.job_state(job_id)
        assert queued is not None

        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        failed = replace(queued, status="failed", message="unable to open database file")
        assert manager.job_state(job_id) == failed
        assert list(manager.get_events(job_id)) == [JobEvent("error", failed)]

    def test_a_job_whose_database_cannot_be_opened_when_it_starts_is_logged_with_its_error_and_with_the_failure_it_could_not_record(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation, new_id=CountingIds())
        _queue_a_job_whose_database_cannot_be_opened_when_it_starts(manager, blocking_simulation, tmp_path)

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                "Job id-3 of run id-4 failed with OperationalError('unable to open database file'),"
                " an error that escaped its failure handling",
            ),
            (
                logging.ERROR,
                "Could not open the database to record that job id-3 of run id-4 failed with 'unable to open database file'",
            ),
        ]
        assert [(type(record.exc_info[1]), str(record.exc_info[1])) for record in records if record.exc_info] == [
            (sqlite3.OperationalError, "unable to open database file")
        ] * 2

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_reported_failed_with_its_error_event(
        self, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=_a_simulation_that_exits)
        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            job_id = _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)
        row = job_row(storage, job_id)

        failed = JobState(
            job_id=job_id,
            run_id=row["run_id"],
            status="failed",
            progress_pct=20.0,
            current_step="Simulating",
            message="the simulation exited",
            created_at=row["created_at"],
        )
        assert manager.job_state(job_id) == failed
        assert list(manager.get_events(job_id)) == [
            JobEvent(
                "progress",
                replace(failed, status="running", progress_pct=5.0, current_step="Starting", message="Initializing..."),
            ),
            JobEvent("progress", replace(failed, status="running", message="Running home simulation...")),
            JobEvent("error", failed),
        ]

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_recorded_failed_in_its_rows(
        self, tmp_path: Path
    ) -> None:
        storage = _run_storage(tmp_path)
        manager = JobManager(max_workers=1, simulate_home=_a_simulation_that_exits)
        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            job_id = _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)

        row = job_row(storage, job_id)
        run = _run_of_job(manager, job_id, storage)

        assert (row["status"], row["message"]) == ("failed", "the simulation exited")
        assert "SystemExit: the simulation exited" in row["error_traceback"]
        assert row["completed_at"] is not None
        assert (run.status, run.error_message) == ("failed", "the simulation exited")
        assert run.completed_at is not None
        assert manager.job_state(job_id) == _state_recorded_in_job_row(storage, job_id)

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_logged_naming_the_job_and_its_run(
        self, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=_a_simulation_that_exits, new_id=CountingIds())

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            _submit_home_job(manager, tmp_path)
            assert manager.wait_until_idle(timeout=30)

        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                "Job id-1 of run id-2 failed with SystemExit('the simulation exited'),"
                " an error that escaped its failure handling",
            )
        ]
        assert records[0].exc_info is not None
        error = records[0].exc_info[1]
        assert (type(error), str(error)) == (SystemExit, "the simulation exited")


class TestJobManagerShutdown:
    """Tests for JobManager shutdown."""

    def test_a_shut_down_manager_refuses_new_jobs(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())

        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager, tmp_path)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_refused_job_leaves_no_record(
        self, submit_job: Callable[[JobManager, Path], str], tmp_path: Path
    ) -> None:
        ids = CountingIds()
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)
        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            submit_job(manager, tmp_path)

        assert ids.issued
        assert _ids_tracked_by(manager, ids.issued) == []
        assert _run_storage(tmp_path).list_runs() == []

    def test_a_job_dropped_by_shutdown_keeps_the_state_it_was_queued_in_and_logs_no_error(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()
        dropped_job_id = _submit_home_job(manager, tmp_path)
        queued = manager.job_state(dropped_job_id)
        assert queued is not None
        assert queued.status == "queued"

        with caplog.at_level(logging.ERROR):
            manager.shutdown()
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        assert manager.job_state(dropped_job_id) == queued
        assert [(record.name, record.getMessage()) for record in caplog.records if record.levelno >= logging.ERROR] == []

    def test_shutdown_all_managers_shuts_down_every_live_manager(self, tmp_path: Path) -> None:
        managers = [JobManager(max_workers=1, simulate_home=RecordingSimulation()) for _ in range(2)]

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
        jm = JobManager(max_workers=1, simulate_home=RecordingSimulation())

        shutdown_all_managers()
        shutdown_all_managers()  # must not raise

        # Suppress "local variable 'jm' assigned but never used" lint; the
        # strong reference is the point — it keeps jm alive through both calls.
        del jm


class TestJobManagerWaitUntilIdle:
    """Tests for JobManager.wait_until_idle, which blocks until no job is queued or running."""

    def test_a_manager_never_given_a_job_is_idle(self) -> None:
        assert JobManager(max_workers=1, simulate_home=RecordingSimulation()).wait_until_idle(timeout=0) is True

    def test_waiting_returns_false_when_the_timeout_passes_while_a_job_runs(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        assert manager.wait_until_idle(timeout=0.05) is False

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_waiting_returns_true_once_every_submitted_job_has_finished(
        self,
        submit_job: Callable[[JobManager, Path], str],
        blocking_simulation: BlockingSimulation,
        tmp_path: Path,
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        job_ids = [submit_job(manager, tmp_path), submit_job(manager, tmp_path)]
        blocking_simulation.wait_until_started()

        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True
        assert [_status_of(manager, job_id) for job_id in job_ids] == ["completed", "completed"]

    def test_a_failed_job_counts_as_finished(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_id = _submit_home_job(manager, tmp_path)

        assert manager.wait_until_idle(timeout=30) is True
        assert _status_of(manager, job_id) == "failed"

    def test_a_job_whose_failure_report_is_stopped_by_an_error_that_is_not_an_exception_counts_as_finished(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(
            max_workers=1,
            simulate_home=_released_then_raising(blocking_simulation, _AnErrorWhoseMessageIsInterrupted),
        )
        _submit_home_job(manager, tmp_path)

        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

    def test_a_job_dropped_by_shutdown_does_not_keep_the_manager_busy(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
    ) -> None:
        manager = JobManager(max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager, tmp_path)
        _submit_home_job(manager, tmp_path)
        blocking_simulation.wait_until_started()

        manager.shutdown()
        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True

    def test_a_job_the_manager_refused_does_not_keep_it_busy(self, tmp_path: Path) -> None:
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        manager.shutdown()
        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager, tmp_path)

        assert manager.wait_until_idle(timeout=0) is True


class TestLiveManagers:
    """Tests for live_managers(), the snapshot of every JobManager not yet garbage-collected."""

    def test_live_managers_reports_a_newly_constructed_manager(self) -> None:
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())

        assert manager in live_managers()

    def test_an_earlier_snapshot_does_not_gain_managers_constructed_after_it(self) -> None:
        snapshot = live_managers()
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())

        assert manager not in snapshot

    def test_live_managers_includes_shut_down_managers(self) -> None:
        manager = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        manager.shutdown()

        assert manager in live_managers()


class TestRecoverStaleJobs:
    """Tests for recover_stale_jobs on startup."""

    def test_recover_marks_running_jobs_as_failed(self, tmp_path: Path) -> None:
        """Test that running jobs are marked as failed on recovery."""
        database = init_db(tmp_path / "stale.db")

        # Insert a run and job in 'running' state
        with database.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                ("run-1", "Stale Run", "home", "running"),
            )
            cursor.execute(
                "INSERT INTO jobs (id, run_id, status) VALUES (?, ?, ?)",
                ("job-1", "run-1", "running"),
            )

        recovered = recover_stale_jobs(database)
        assert recovered == 1

        # Verify job status
        with database.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT status, message FROM jobs WHERE id = ?", ("job-1",))
            row = cursor.fetchone()
            assert row["status"] == "failed"
            assert "server restart" in row["message"].lower()

    def test_recover_marks_queued_jobs_as_failed(self, tmp_path: Path) -> None:
        """Test that queued jobs are also recovered."""
        database = init_db(tmp_path / "stale2.db")

        with database.transaction() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO runs (id, name, type, status) VALUES (?, ?, ?, ?)",
                ("run-1", "Queued Run", "home", "running"),
            )
            cursor.execute(
                "INSERT INTO jobs (id, run_id, status) VALUES (?, ?, ?)",
                ("job-1", "run-1", "queued"),
            )

        recovered = recover_stale_jobs(database)
        assert recovered == 1

    def test_recover_no_stale_jobs_returns_zero(self, tmp_path: Path) -> None:
        """Test that recovery returns 0 when no stale jobs exist."""
        database = init_db(tmp_path / "clean.db")

        recovered = recover_stale_jobs(database)
        assert recovered == 0

    def test_recovery_fails_the_run_of_a_job_dropped_when_its_manager_shut_down(
        self, blocking_simulation: BlockingSimulation, tmp_path: Path
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

        recover_stale_jobs(storage.database)

        run = _run_of_job(manager, dropped_job_id, storage)
        assert (run.status, run.error_message) == ("failed", "Interrupted by server restart")
        assert run.completed_at is not None

    def test_recovery_leaves_a_completed_run_and_a_failed_run_as_they_were(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        completing = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        failing = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        jobs = [(completing, _submit_home_job(completing, tmp_path)), (failing, _submit_home_job(failing, tmp_path))]
        assert completing.wait_until_idle(timeout=30)
        assert failing.wait_until_idle(timeout=30)
        before = [_run_of_job(manager, job_id, storage) for manager, job_id in jobs]
        assert [run.status for run in before] == ["completed", "failed"]

        recover_stale_jobs(storage.database)

        assert [_run_of_job(manager, job_id, storage) for manager, job_id in jobs] == before

    def test_recovery_leaves_a_completed_job_and_a_failed_job_as_they_were(self, tmp_path: Path) -> None:
        storage = _run_storage(tmp_path)
        completing = JobManager(max_workers=1, simulate_home=RecordingSimulation())
        failing = JobManager(max_workers=1, simulate_home=a_failing_simulation)
        job_ids = [_submit_home_job(completing, tmp_path), _submit_home_job(failing, tmp_path)]
        assert completing.wait_until_idle(timeout=30)
        assert failing.wait_until_idle(timeout=30)
        before = [job_row(storage, job_id) for job_id in job_ids]
        assert [row["status"] for row in before] == ["completed", "failed"]

        recover_stale_jobs(storage.database)

        assert [job_row(storage, job_id) for job_id in job_ids] == before
