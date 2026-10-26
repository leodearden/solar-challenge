# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.jobs: JobManager, live_managers and shutdown_all_managers."""

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
from solar_challenge.web.jobs import (
    HomeSimulator,
    JobManager,
    JobSnapshot,
    JobState,
    live_managers,
    shutdown_all_managers,
)
from solar_challenge.web.storage import RunQuery, RunRecord, RunStorage
from tests._manual_clock import ManualClock
from tests._run_storage_layout import stored_run_dir
from tests._run_stores import empty_run_storage
from tests._web_app import run_storage_of
from tests.unit.web_jobs._app_client import A_HOME_JOB_REQUEST, client_using
from tests.unit.web_jobs._fakes import (
    BlockingSimulation,
    CountingIds,
    RecordingSimulation,
    RunStorageWithGatedCompletion,
    RunStorageWithGatedHomeSaves,
    SaveGate,
    a_failing_simulation,
)


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
    """An error that is not an Exception and whose message cannot be read, so a job that raised it is reported failed naming the error's type."""

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


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """The store of no app that a test's JobManagers record their jobs' runs in."""
    return empty_run_storage(tmp_path)


class TestJobManagerConstruction:
    """A JobManager is built with the RunStorage and the home simulation its jobs use; it has neither of its own."""

    def test_a_manager_is_given_its_home_simulator(self, storage: RunStorage) -> None:
        with pytest.raises(TypeError, match="simulate_home"):
            JobManager(storage)


class TestJobManagerSnapshots:
    """Tests for the snapshot a JobManager keeps of each job: its state at that state's version, read with job_snapshot."""

    def test_thread_safety_concurrent_access(self, blocking_simulation: BlockingSimulation, storage: RunStorage) -> None:
        """Test that concurrent job_state and job_snapshot calls are thread-safe."""
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_ids = [_submit_home_job(manager) for _ in range(10)]
        blocking_simulation.wait_until_started()

        errors: list[Exception] = []
        barrier = threading.Barrier(20)

        def worker() -> None:
            try:
                barrier.wait()
                for job_id in job_ids:
                    assert manager.job_state(job_id) is not None
                    assert manager.job_snapshot(job_id) is not None
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

    def test_each_state_a_job_reports_takes_the_next_version(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        held = _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        queued = _submit_home_job(manager)

        assert manager.job_snapshot(queued) == JobSnapshot(version=1, state=manager.job_state(queued))
        simulating = manager.job_snapshot(held)
        assert simulating == JobSnapshot(version=3, state=manager.job_state(held))
        assert manager.job_snapshot(held) == simulating

        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        assert manager.job_snapshot(held) == JobSnapshot(version=5, state=manager.job_state(held))
        assert manager.job_snapshot(queued) == JobSnapshot(version=5, state=manager.job_state(queued))

    def test_a_job_the_manager_does_not_track_has_no_snapshot(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        assert manager.job_snapshot("nonexistent-job-id") is None


_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500))
_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")


def _refuse_new_runs_rows(storage: RunStorage) -> None:
    """Make storage's database refuse every row inserted into its runs table."""
    with storage.database.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER refuse_new_runs BEFORE INSERT ON runs "
            "BEGIN SELECT RAISE(ABORT, 'the database refuses new runs rows'); END"
        )


def _refuse_failed_runs_rows(storage: RunStorage) -> None:
    """Make storage's database refuse every update that marks a row of its runs table failed."""
    with storage.database.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER refuse_failed_runs BEFORE UPDATE ON runs WHEN NEW.status = 'failed' "
            "BEGIN SELECT RAISE(ABORT, 'the database refuses failed runs rows'); END"
        )


def _hold_a_job_whose_database_cannot_be_opened_when_it_saves_its_run(
    manager: JobManager, blocking_simulation: BlockingSimulation, storage: RunStorage
) -> str:
    """Submit a home job to *manager*, hold it in *blocking_simulation*, then turn *storage*'s database file into a directory.

    The job records its run in *storage* when it is submitted, so once released it cannot open the database to save
    its run. Returns the job's id.
    """
    job_id = _submit_home_job(manager)
    blocking_simulation.wait_until_started()
    storage.database.path.unlink()
    storage.database.path.mkdir()
    return job_id


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


def _submit_home_job(manager: JobManager) -> str:
    job_id, _ = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)
    return job_id


def _submit_fleet_job(manager: JobManager) -> str:
    job_id, _ = manager.submit_fleet_job(configs=[_A_HOME], start_date=_JUNE_1, end_date=_JUNE_2)
    return job_id


class TestJobManagerSimulation:
    """Tests for the simulation a JobManager runs."""

    def test_a_home_job_runs_the_simulation_the_manager_was_given(self, storage: RunStorage) -> None:
        simulation = RecordingSimulation()
        manager = JobManager(storage, max_workers=1, simulate_home=simulation)

        job_id, run_id = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        assert simulation.calls == [(_A_HOME, _JUNE_1, _JUNE_2)]
        summary = storage.load_run(run_id).summary
        assert summary.total_generation_kwh == pytest.approx(4.0)

    def test_a_fleet_job_runs_the_managers_simulation_once_per_home(self, storage: RunStorage) -> None:
        simulation = RecordingSimulation()
        manager = JobManager(storage, max_workers=1, simulate_home=simulation)
        homes = [
            _A_HOME,
            HomeConfig(pv_config=PVConfig(capacity_kw=2.0), load_config=LoadConfig(annual_consumption_kwh=3500)),
        ]

        job_id, run_id = manager.submit_fleet_job(configs=homes, start_date=_JUNE_1, end_date=_JUNE_2)

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        assert simulation.calls == [(home, _JUNE_1, _JUNE_2) for home in homes]
        per_home_summaries = storage.load_run(run_id).home_summaries
        assert [summary.total_generation_kwh for summary in per_home_summaries] == pytest.approx([4.0, 2.0])


class TestJobManagerIds:
    """Tests for the ids a JobManager gives its jobs and their runs."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_job_and_its_run_take_their_ids_from_the_managers_id_source(
        self, submit_job: Callable[[JobManager], str], storage: RunStorage
    ) -> None:
        ids = CountingIds()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)

        job_id = submit_job(manager)

        state = manager.job_state(job_id)
        assert state is not None
        run_id = state.run_id
        assert {job_id, run_id} == set(ids.issued)
        assert [record.id for record in storage.page_runs(RunQuery()).records] == [run_id]


class TestJobManagerState:
    """Tests for the state a JobManager reports for a job: only while it tracks the job in memory."""

    def test_a_jobs_state_holds_its_ids_its_progress_and_its_runs_creation_time(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        job_id, run_id = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)
        assert manager.wait_until_idle(timeout=30)

        assert manager.job_state(job_id) == JobState(
            job_id=job_id,
            run_id=run_id,
            status="completed",
            progress_pct=100.0,
            current_step="Done",
            message="Simulation completed successfully",
            created_at=_run_of_job(manager, job_id, storage).created_at,
        )

    def test_a_state_the_manager_reported_stays_as_it_was_after_the_job_moves_on(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = _submit_home_job(manager)
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

    def test_a_manager_does_not_know_a_job_another_manager_ran_although_its_run_remains(
        self, storage: RunStorage
    ) -> None:
        first = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())
        job_id = _submit_home_job(first)
        assert first.wait_until_idle(timeout=30)

        assert JobManager(storage, max_workers=1, simulate_home=RecordingSimulation()).job_state(job_id) is None
        assert _run_of_job(first, job_id, storage).status == "completed"


class TestRunLabelsEditedWhileItsJobRuns:
    """A run renamed or annotated in Run History while its job runs keeps those labels when the job finishes."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_run_edited_while_its_job_runs_keeps_its_labels_when_the_job_completes(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager)
        blocking_simulation.wait_until_started()
        run_id = _run_of_job(manager, job_id, storage).id
        storage.update_run_labels(run_id, {"name": "Renamed by user", "notes": "my note"})

        blocking_simulation.release()

        state = _wait_until_finished(manager, job_id)
        assert state.status == "completed", state.message
        run = storage.run_record(run_id)
        assert run is not None
        assert (run.status, run.name, run.notes) == ("completed", "Renamed by user", "my note")


def _names_while_running_and_once_completed(
    manager: JobManager, job_id: str, blocking_simulation: BlockingSimulation, storage: RunStorage
) -> list[tuple[str | None, str | None]]:
    """The status and name of job *job_id*'s run, held in *blocking_simulation*, before and after it is released to complete."""
    running = _run_of_job(manager, job_id, storage)
    blocking_simulation.release()
    assert manager.wait_until_idle(timeout=30)
    completed = _run_of_job(manager, job_id, storage)
    return [(running.status, running.name), (completed.status, completed.name)]


class TestRunNames:
    """A JobManager names a job's run once, when its submit creates it: the submit's name, or the run kind's default name when the submit gives none or a blank one."""

    @pytest.mark.parametrize(
        ("name", "home_name", "run_name"),
        [
            (None, "North Roof", "North Roof"),
            (None, "", "Web Simulation"),
            ("", "", "Web Simulation"),
            ("   ", "", "Web Simulation"),
            (None, "   ", "Web Simulation"),
            ("Street", "North Roof", "Street"),
        ],
        ids=[
            "no-name-a-named-home",
            "no-name-an-unnamed-home",
            "an-empty-name",
            "a-blank-name",
            "no-name-a-home-of-a-blank-name",
            "a-name-a-named-home",
        ],
    )
    def test_a_home_jobs_run_is_named_at_its_submit_and_keeps_that_name_once_completed(
        self,
        name: str | None,
        home_name: str,
        run_name: str,
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)

        job_id, _ = manager.submit_home_job(
            config=replace(_A_HOME, name=home_name), start_date=_JUNE_1, end_date=_JUNE_2, name=name
        )

        assert _names_while_running_and_once_completed(manager, job_id, blocking_simulation, storage) == [
            ("running", run_name),
            ("completed", run_name),
        ]

    @pytest.mark.parametrize(
        ("name", "run_name"),
        [(None, "Fleet Simulation"), ("   ", "Fleet Simulation"), ("Street", "Street")],
        ids=["no-name", "a-blank-name", "a-name"],
    )
    def test_a_fleet_jobs_run_is_named_at_its_submit_and_keeps_that_name_once_completed(
        self, name: str | None, run_name: str, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        homes = [replace(_A_HOME, name="Home 1"), replace(_A_HOME, name="Home 2")]

        job_id, _ = manager.submit_fleet_job(configs=homes, start_date=_JUNE_1, end_date=_JUNE_2, name=name)

        assert _names_while_running_and_once_completed(manager, job_id, blocking_simulation, storage) == [
            ("running", run_name),
            ("completed", run_name),
        ]


_A_MINUTE = 60.0
_A_DAY = 24 * 60 * 60.0


class TestJobManagerAgeLimit:
    """Tests for how long a JobManager tracks a job: until it finishes, and for a while after."""

    def test_a_finished_job_is_still_tracked_at_a_submit_a_minute_after_it_finished(self, storage: RunStorage) -> None:
        clock = ManualClock()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_MINUTE)

        _submit_home_job(manager)

        assert _status_of(manager, job_id) == "completed"

    def test_a_finished_job_is_not_tracked_after_a_submit_a_day_after_it_finished(self, storage: RunStorage) -> None:
        clock = ManualClock()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation(), clock=clock)
        job_id = _submit_home_job(manager)
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_DAY)

        _submit_home_job(manager)

        assert manager.job_state(job_id) is None

    def test_a_job_that_failed_with_an_error_whose_message_cannot_be_read_is_not_tracked_after_a_submit_a_day_after_it_finished(
        self, storage: RunStorage
    ) -> None:
        clock = ManualClock()
        manager = JobManager(
            storage,
            max_workers=1,
            simulate_home=_a_simulation_raising_an_error_whose_message_cannot_be_read,
            clock=clock,
        )
        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            job_id = _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)
            clock.advance(_A_DAY)

            _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)

        assert manager.job_state(job_id) is None

    def test_a_job_that_finished_a_minute_ago_is_still_tracked_though_it_was_submitted_a_day_before(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        clock = ManualClock()
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation, clock=clock)
        job_id = _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        clock.advance(_A_DAY)
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        clock.advance(_A_MINUTE)

        _submit_home_job(manager)

        assert _status_of(manager, job_id) == "completed"

    def test_a_job_still_running_a_day_after_it_was_submitted_is_still_reported_after_a_later_submit(
        self, app: Flask, blocking_simulation: BlockingSimulation
    ) -> None:
        clock = ManualClock()
        manager = JobManager(run_storage_of(app), simulate_home=blocking_simulation, clock=clock)
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
        clock = ManualClock()
        manager = JobManager(run_storage_of(app), simulate_home=blocking_simulation, clock=clock)
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
    def test_a_queued_job_reports_its_queued_state_while_its_run_is_already_running(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()

        queued_job_id = submit_job(manager)

        queued = manager.job_state(queued_job_id)
        assert queued is not None
        assert (queued.status, queued.progress_pct, queued.current_step, queued.message) == (
            "queued",
            0.0,
            "Queued",
            "Waiting to start...",
        )
        run = _run_of_job(manager, queued_job_id, storage)
        assert (run.status, run.error_message, run.completed_at) == ("running", None, None)


class TestJobManagerRuns:
    """Tests for the row a JobManager writes for each job's run, as RunStorage reads it."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_jobs_run_is_running_while_its_simulation_runs(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager)
        blocking_simulation.wait_until_started()

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message, run.completed_at) == ("running", None, None)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_completed_jobs_run_is_completed_with_a_completion_time_and_no_error(
        self, submit_job: Callable[[JobManager], str], storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())
        job_id = submit_job(manager)
        assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message) == ("completed", None)
        assert run.completed_at is not None

    def test_a_job_reports_completed_only_once_its_run_reads_completed(
        self, storage: RunStorage, save_gate: SaveGate
    ) -> None:
        gated = RunStorageWithGatedCompletion(storage.database, storage.data_dir, save_gate)
        manager = JobManager(gated, max_workers=1, simulate_home=RecordingSimulation())
        job_id = _submit_home_job(manager)
        save_gate.wait_until_a_save_waits()

        assert _run_of_job(manager, job_id, storage).status == "completed"
        assert _status_of(manager, job_id) == "running"
        save_gate.open()
        assert manager.wait_until_idle(timeout=30)
        assert _status_of(manager, job_id) == "completed"

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_failed_jobs_run_is_failed_with_the_jobs_error_and_a_completion_time(
        self, submit_job: Callable[[JobManager], str], storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=a_failing_simulation)
        job_id = submit_job(manager)
        assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message) == ("failed", "the simulation failed")
        assert run.completed_at is not None


class TestJobManagerRefusedRows:
    """Tests for a submit whose run's row the database refuses."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_job_whose_runs_row_the_database_refuses_leaves_no_record(
        self, submit_job: Callable[[JobManager], str], storage: RunStorage
    ) -> None:
        _refuse_new_runs_rows(storage)
        ids = CountingIds()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)

        with pytest.raises(sqlite3.IntegrityError, match="refuses new runs rows"):
            submit_job(manager)

        assert ids.issued
        assert _ids_tracked_by(manager, ids.issued) == []
        assert storage.page_runs(RunQuery()).total == 0


class TestJobManagerUnrecordedFailures:
    """Tests for a failed job whose failure the database does not record in its run's row."""

    def test_a_failure_the_runs_table_refuses_to_record_is_logged_naming_the_job_its_run_and_the_refusal(
        self, storage: RunStorage, caplog: pytest.LogCaptureFixture
    ) -> None:
        _refuse_failed_runs_rows(storage)
        manager = JobManager(storage, max_workers=1, simulate_home=a_failing_simulation, new_id=CountingIds())

        with caplog.at_level(logging.ERROR, logger=_JOBS_LOGGER):
            _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)

        records = _records_logged_by_jobs_py(caplog)
        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                "Could not record in the run store that job id-1 of run id-2 failed with 'the simulation failed'",
            )
        ]
        assert records[0].exc_info is not None
        refusal = records[0].exc_info[1]
        assert (type(refusal), str(refusal)) == (sqlite3.IntegrityError, "the database refuses failed runs rows")
        assert (type(refusal.__context__), str(refusal.__context__)) == (RuntimeError, "the simulation failed")

    def test_a_job_whose_failure_the_runs_table_refuses_to_record_is_still_reported_failed(
        self, storage: RunStorage
    ) -> None:
        _refuse_failed_runs_rows(storage)
        manager = JobManager(storage, max_workers=1, simulate_home=a_failing_simulation)
        job_id = _submit_home_job(manager)
        assert manager.wait_until_idle(timeout=30)

        state = manager.job_state(job_id)

        assert state is not None
        assert (state.status, state.message) == ("failed", "the simulation failed")

    def test_a_failure_whose_message_sqlite_cannot_store_is_logged_and_still_reported(self, storage: RunStorage) -> None:
        manager = JobManager(
            storage,
            max_workers=1,
            simulate_home=_a_simulation_failing_with_a_message_sqlite_cannot_store,
            new_id=CountingIds(),
        )

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            job_id = _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)

        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                "Could not record in the run store that job id-1 of run id-2 failed with"
                f" {_A_MESSAGE_SQLITE_CANNOT_STORE!r}",
            )
        ]
        assert [type(record.exc_info[1]) for record in records if record.exc_info] == [UnicodeEncodeError]
        assert _status_of(manager, job_id) == "failed"

    def test_a_job_whose_database_cannot_be_opened_when_it_saves_its_run_is_reported_failed_at_its_save_with_the_databases_error(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = _hold_a_job_whose_database_cannot_be_opened_when_it_saves_its_run(
            manager, blocking_simulation, storage
        )

        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        failed = manager.job_state(job_id)
        assert failed is not None
        assert (failed.status, failed.current_step, failed.message) == (
            "failed",
            "Saving",
            "unable to open database file",
        )

    def test_a_job_whose_database_cannot_be_opened_when_it_saves_its_run_is_logged_with_the_failure_it_could_not_record(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation, new_id=CountingIds())
        _hold_a_job_whose_database_cannot_be_opened_when_it_saves_its_run(manager, blocking_simulation, storage)

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        assert [(record.levelno, record.getMessage()) for record in records] == [
            (
                logging.ERROR,
                "Could not record in the run store that job id-1 of run id-2 failed with 'unable to open database file'",
            )
        ]
        assert [type(record.exc_info[1]) for record in records if record.exc_info] == [sqlite3.OperationalError]


class TestJobManagerEscapedErrors:
    """Tests for a job whose runner raises an error that the runner's own failure handling does not catch."""

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_reported_failed_at_the_progress_it_had_reached_as_its_next_state(
        self, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=_a_simulation_that_exits)
        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            job_id, run_id = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)
            assert manager.wait_until_idle(timeout=30)
        run = storage.run_record(run_id)
        assert run is not None

        failed = JobState(
            job_id=job_id,
            run_id=run_id,
            status="failed",
            progress_pct=20.0,
            current_step="Simulating",
            message="the simulation exited",
            created_at=run.created_at,
        )
        assert manager.job_state(job_id) == failed
        assert manager.job_snapshot(job_id) == JobSnapshot(4, failed)

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_recorded_failed_in_its_runs_row(
        self, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=_a_simulation_that_exits)
        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            job_id = _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)

        run = _run_of_job(manager, job_id, storage)

        assert (run.status, run.error_message) == ("failed", "the simulation exited")
        assert run.completed_at is not None

    def test_a_job_whose_simulation_raises_an_error_that_is_not_an_exception_is_logged_naming_the_job_and_its_run(
        self, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=_a_simulation_that_exits, new_id=CountingIds())

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            _submit_home_job(manager)
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

    def test_a_job_whose_error_has_a_message_that_cannot_be_read_is_reported_failed_naming_the_errors_type(
        self, storage: RunStorage
    ) -> None:
        manager = JobManager(
            storage,
            max_workers=1,
            simulate_home=_a_simulation_raising_an_error_whose_message_cannot_be_read,
            new_id=CountingIds(),
        )

        with _errors_logged_by_jobs_py_kept_out_of_the_report() as records:
            job_id = _submit_home_job(manager)
            assert manager.wait_until_idle(timeout=30)

        message = "_AnErrorWhoseMessageCannotBeRead, whose message could not be read"
        state = manager.job_state(job_id)
        assert state is not None
        assert (state.status, state.message) == ("failed", message)
        run = _run_of_job(manager, job_id, storage)
        assert (run.status, run.error_message) == ("failed", message)
        assert [(record.levelno, "id-1" in record.getMessage(), "id-2" in record.getMessage()) for record in records] == [
            (logging.ERROR, True, True)
        ]
        assert records[0].exc_info is not None
        assert type(records[0].exc_info[1]) is _AnErrorWhoseMessageCannotBeRead


class TestJobManagerCancelRun:
    """JobManager.cancel_run, which a run's delete calls first: the run's queued or running job is cancelled and saves nothing."""

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_running_job_whose_run_is_cancelled_reports_cancelled_at_the_progress_it_had_reached(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager)
        blocking_simulation.wait_until_started()
        running = manager.job_state(job_id)
        assert running is not None

        assert manager.cancel_run(running.run_id) is True
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        cancelled = replace(running, status="cancelled", message="Cancelled: its run was deleted")
        assert manager.job_state(job_id) == cancelled

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_cancelled_job_writes_nothing_to_the_run_store(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_id = submit_job(manager)
        blocking_simulation.wait_until_started()
        created = _run_of_job(manager, job_id, storage)

        manager.cancel_run(created.id)
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        assert storage.run_record(created.id) == created
        assert not stored_run_dir(storage, created.id).exists()

    def test_a_job_whose_simulation_raises_once_its_run_is_cancelled_reports_cancelled_and_writes_nothing_to_the_run_store(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(
            storage,
            max_workers=1,
            simulate_home=_released_then_raising(blocking_simulation, lambda: RuntimeError("the simulation failed")),
        )
        job_id = _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        running = manager.job_state(job_id)
        assert running is not None
        created = _run_of_job(manager, job_id, storage)

        assert manager.cancel_run(created.id) is True
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)

        cancelled = replace(running, status="cancelled", message="Cancelled: its run was deleted")
        assert manager.job_state(job_id) == cancelled
        assert storage.run_record(created.id) == created

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_queued_job_whose_run_is_cancelled_is_dropped_at_once_and_never_runs(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        queued_job_id = submit_job(manager)
        queued = manager.job_state(queued_job_id)
        assert queued is not None
        created = _run_of_job(manager, queued_job_id, storage)

        assert manager.cancel_run(queued.run_id) is True

        cancelled = replace(queued, status="cancelled", message="Cancelled: its run was deleted")
        assert manager.job_state(queued_job_id) == cancelled
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        assert len(blocking_simulation.calls) == 1
        assert manager.job_state(queued_job_id) == cancelled
        assert storage.run_record(queued.run_id) == created

    def test_a_cancel_that_comes_while_the_jobs_final_save_runs_waits_for_the_save_and_leaves_the_job_completed(
        self, storage: RunStorage, save_gate: SaveGate
    ) -> None:
        gated_storage = RunStorageWithGatedHomeSaves(storage.database, storage.data_dir, save_gate)
        manager = JobManager(gated_storage, max_workers=1, simulate_home=RecordingSimulation())
        job_id, run_id = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)
        save_gate.wait_until_a_save_waits()
        answers: list[bool] = []
        cancel = threading.Thread(target=lambda: answers.append(manager.cancel_run(run_id)), daemon=True)

        cancel.start()
        cancel.join(timeout=0.2)
        assert cancel.is_alive(), "cancel_run returned while the job's final save still ran"
        save_gate.open()
        cancel.join(timeout=30)

        assert answers == [False]
        assert manager.wait_until_idle(timeout=30)
        assert _status_of(manager, job_id) == "completed"
        run = storage.run_record(run_id)
        assert run is not None
        assert run.status == "completed"

    @pytest.mark.parametrize(
        ("simulation", "status"),
        [(RecordingSimulation(), "completed"), (a_failing_simulation, "failed")],
        ids=["completed", "failed"],
    )
    def test_cancelling_the_run_of_a_finished_job_returns_false_and_leaves_the_job_as_it_ended(
        self, simulation: HomeSimulator, status: str, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=simulation)
        job_id, run_id = manager.submit_home_job(config=_A_HOME, start_date=_JUNE_1, end_date=_JUNE_2)
        assert manager.wait_until_idle(timeout=30)
        ended = manager.job_state(job_id)
        assert ended is not None
        assert ended.status == status

        assert manager.cancel_run(run_id) is False
        assert manager.job_state(job_id) == ended

    def test_cancelling_a_run_no_job_of_the_manager_runs_returns_false(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        assert manager.cancel_run("no-such-run") is False


class TestJobManagerShutdown:
    """Tests for JobManager shutdown."""

    def test_a_shut_down_manager_refuses_new_jobs(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager)

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_a_refused_job_leaves_no_record(
        self, submit_job: Callable[[JobManager], str], storage: RunStorage
    ) -> None:
        ids = CountingIds()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation(), new_id=ids)
        manager.shutdown()

        with pytest.raises(RuntimeError, match="after shutdown"):
            submit_job(manager)

        assert ids.issued
        assert _ids_tracked_by(manager, ids.issued) == []
        assert storage.page_runs(RunQuery()).total == 0

    def test_a_job_dropped_by_shutdown_reports_failed_naming_the_shutdown_and_logs_no_error(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage, caplog: pytest.LogCaptureFixture
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        dropped_job_id = _submit_home_job(manager)
        queued = manager.job_state(dropped_job_id)
        assert queued is not None
        assert queued.status == "queued"

        with caplog.at_level(logging.ERROR):
            manager.shutdown()
            dropped = replace(queued, status="failed", message="Dropped: the server shut down before the job ran")
            assert manager.job_state(dropped_job_id) == dropped
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

        assert [(record.name, record.getMessage()) for record in caplog.records if record.levelno >= logging.ERROR] == []

    def test_shutdown_all_managers_shuts_down_every_live_manager(self, storage: RunStorage) -> None:
        managers = [JobManager(storage, max_workers=1, simulate_home=RecordingSimulation()) for _ in range(2)]

        shutdown_all_managers()

        for manager in managers:
            with pytest.raises(RuntimeError, match="after shutdown"):
                _submit_home_job(manager)

    def test_shutdown_all_managers_is_idempotent(self, storage: RunStorage) -> None:
        """Test that calling shutdown_all_managers() twice does not raise."""
        # Bind to a local variable so the manager has a strong reference and
        # is not garbage-collected from the WeakSet before the first shutdown
        # call — without this the WeakSet could be empty and the test would
        # pass trivially without exercising the double-shutdown path.
        jm = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        shutdown_all_managers()
        shutdown_all_managers()  # must not raise

        # Suppress "local variable 'jm' assigned but never used" lint; the
        # strong reference is the point — it keeps jm alive through both calls.
        del jm


class TestJobManagerWaitUntilIdle:
    """Tests for JobManager.wait_until_idle, which blocks until no job is queued or running."""

    def test_a_manager_never_given_a_job_is_idle(self, storage: RunStorage) -> None:
        assert JobManager(storage, max_workers=1, simulate_home=RecordingSimulation()).wait_until_idle(timeout=0) is True

    def test_waiting_returns_false_when_the_timeout_passes_while_a_job_runs(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()

        assert manager.wait_until_idle(timeout=0.05) is False

    @pytest.mark.parametrize("submit_job", [_submit_home_job, _submit_fleet_job], ids=["home", "fleet"])
    def test_waiting_returns_true_once_every_submitted_job_has_finished(
        self,
        submit_job: Callable[[JobManager], str],
        blocking_simulation: BlockingSimulation,
        storage: RunStorage,
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        job_ids = [submit_job(manager), submit_job(manager)]
        blocking_simulation.wait_until_started()

        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True
        assert [_status_of(manager, job_id) for job_id in job_ids] == ["completed", "completed"]

    def test_a_failed_job_counts_as_finished(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=a_failing_simulation)
        job_id = _submit_home_job(manager)

        assert manager.wait_until_idle(timeout=30) is True
        assert _status_of(manager, job_id) == "failed"

    def test_a_job_whose_failure_report_is_stopped_by_an_error_that_is_not_an_exception_counts_as_finished(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(
            storage,
            max_workers=1,
            simulate_home=_released_then_raising(blocking_simulation, _AnErrorWhoseMessageIsInterrupted),
        )
        _submit_home_job(manager)

        with _errors_logged_by_jobs_py_kept_out_of_the_report():
            blocking_simulation.release()
            assert manager.wait_until_idle(timeout=30)

    def test_a_job_dropped_by_shutdown_does_not_keep_the_manager_busy(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()

        manager.shutdown()
        blocking_simulation.release()

        assert manager.wait_until_idle(timeout=30) is True

    def test_a_job_the_manager_refused_does_not_keep_it_busy(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())
        manager.shutdown()
        with pytest.raises(RuntimeError, match="after shutdown"):
            _submit_home_job(manager)

        assert manager.wait_until_idle(timeout=0) is True


class TestLiveManagers:
    """Tests for live_managers(), the snapshot of every JobManager not yet garbage-collected."""

    def test_live_managers_reports_a_newly_constructed_manager(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        assert manager in live_managers()

    def test_an_earlier_snapshot_does_not_gain_managers_constructed_after_it(self, storage: RunStorage) -> None:
        snapshot = live_managers()
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())

        assert manager not in snapshot

    def test_live_managers_includes_shut_down_managers(self, storage: RunStorage) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=RecordingSimulation())
        manager.shutdown()

        assert manager in live_managers()


class TestRecoveryOfInterruptedRuns:
    """Tests for RunStorage.fail_interrupted_runs, which a server start calls, on the runs a JobManager's jobs left."""

    def test_the_run_of_a_job_dropped_when_its_manager_shut_down_is_failed_naming_the_drop_and_recovery_leaves_it_as_it_was(
        self, blocking_simulation: BlockingSimulation, storage: RunStorage
    ) -> None:
        manager = JobManager(storage, max_workers=1, simulate_home=blocking_simulation)
        _submit_home_job(manager)
        blocking_simulation.wait_until_started()
        dropped_job_id = _submit_home_job(manager)
        manager.shutdown()
        blocking_simulation.release()
        assert manager.wait_until_idle(timeout=30)
        dropped = _run_of_job(manager, dropped_job_id, storage)
        assert (dropped.status, dropped.error_message) == ("failed", "Dropped: the server shut down before the job ran")
        assert dropped.completed_at is not None

        assert storage.fail_interrupted_runs() == 0

        assert _run_of_job(manager, dropped_job_id, storage) == dropped
