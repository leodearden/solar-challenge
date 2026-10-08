# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job manager for running simulations asynchronously.

Provides a JobManager class that uses a ThreadPoolExecutor to run
home and fleet simulations in background threads, with progress
tracking via SQLite and SSE event queues.
"""

import collections
import functools
import json
import sqlite3
import threading
import time
import traceback
import uuid
import weakref
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Any, Generator, TypeAlias

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.home import simulate_home as _default_simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import RunType, get_db
from solar_challenge.web.storage import RunStorage

HomeSimulator: TypeAlias = Callable[[HomeConfig, pd.Timestamp, pd.Timestamp], SimulationResults]

_QUEUED_JOB_STATE: Mapping[str, str | float] = MappingProxyType(
    {"status": "queued", "progress_pct": 0.0, "current_step": "Queued", "message": "Waiting to start..."}
)
_FINISHED_JOB_TTL_SECONDS = 3600.0

# Module-level weak registry of all live JobManager instances.
# WeakSet avoids keeping managers alive past their natural lifetime.
_active_managers: "weakref.WeakSet[JobManager]" = weakref.WeakSet()


def _random_id() -> str:
    """Return a new random UUID as a string."""
    return str(uuid.uuid4())


def live_managers() -> "frozenset[JobManager]":
    """Return a snapshot of every JobManager not yet garbage-collected, shut down or not."""
    return frozenset(_active_managers)


def shutdown_all_managers(wait: bool = False) -> None:
    """Shut down every live JobManager, as JobManager.shutdown does.

    A server whose requests submit jobs must call this when it stops, since
    nothing else drops the jobs still queued.  Shutting down an
    already-shut-down manager is a no-op, making this safe to call more than
    once (idempotent).

    Args:
        wait: If True, block until every manager's running jobs finish.
    """
    for manager in live_managers():
        manager.shutdown(wait=wait)


@dataclass(frozen=True)
class _NewJob:
    """A job just recorded: its id, its run's id, and the ISO 8601 UTC time its rows were created."""

    job_id: str
    run_id: str
    created_at: str


@dataclass
class _TrackedJob:
    """A job a JobManager tracks.

    The status get_job_status reports, the SSE events get_events has not yet yielded, and the manager's
    clock reading when the job finished (None while it is queued or running).
    """

    status: dict[str, Any]
    events: collections.deque[dict[str, Any]] = field(default_factory=lambda: collections.deque(maxlen=100))
    finished_at: float | None = None


class JobManager:
    """Manages background simulation jobs with progress tracking.

    Uses a ThreadPoolExecutor to run simulations in background threads.
    Each job has an in-memory event queue (collections.deque) for
    streaming progress events via SSE.

    Attributes:
        _executor: Thread pool for background job execution.
        _jobs: Each job the manager tracks, by id.
        _unfinished_job_count: Number of jobs queued or running; wait_until_idle waits for it to reach 0.
    """

    def __init__(
        self,
        max_workers: int = 2,
        *,
        simulate_home: HomeSimulator = _default_simulate_home,
        new_id: Callable[[], str] = _random_id,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the job manager.

        Args:
            max_workers: Maximum number of concurrent simulation threads.
            simulate_home: Simulates one home over a date range; defaults to
                solar_challenge.home.simulate_home.
            new_id: Returns a new, unique id on each call; each job and each run
                takes one. Defaults to a random UUID.
            clock: Returns the time in seconds on a clock that never goes
                backwards, which the manager reads to age the jobs it tracks.
                Defaults to time.monotonic.
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._simulate_home = simulate_home
        self._new_id = new_id
        self._clock = clock
        self._lock = threading.Lock()
        self._idle = threading.Condition(self._lock)
        self._unfinished_job_count = 0
        self._jobs: dict[str, _TrackedJob] = {}
        _active_managers.add(self)

    def shutdown(self, wait: bool = False) -> None:
        """Refuse new jobs and drop the jobs still queued.

        Running jobs cannot be interrupted, and the interpreter waits for them
        at exit.  Call this before the interpreter starts exiting: by the time
        atexit hooks run, concurrent.futures has already run every queued job.

        Args:
            wait: If True, block until the running jobs finish before returning.
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def wait_until_idle(self, timeout: float) -> bool:
        """Block until no job is queued or running, or until *timeout* seconds have passed.

        A job stops counting once it completes, fails, or is dropped by shutdown.

        Args:
            timeout: Longest wait in seconds; 0 only checks.

        Returns:
            True if the manager is idle, False if the timeout passed first.
        """
        with self._idle:
            return self._idle.wait_for(lambda: self._unfinished_job_count == 0, timeout)

    def submit_home_job(
        self,
        config: HomeConfig,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        db_path: str,
        data_dir: str,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Submit a home simulation job for background execution.

        Creates run and job entries in SQLite, then submits the simulation
        to the thread pool.

        Args:
            config: Home configuration for the simulation.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            db_path: Path to the SQLite database file.
            data_dir: Root directory for storing run data.
            name: Optional name for the simulation run.

        Returns:
            Tuple of (job_id, run_id).

        Raises:
            RuntimeError: If the manager has shut down; the refused job leaves no record.
            sqlite3.Error: If the database refuses the job's run or job row; the refused job leaves no record.
        """
        return self._submit_job(
            db_path,
            run_name=name or config.name or "Web Simulation",
            run_type="home",
            n_homes=1,
            run_simulation=lambda new_job: self._run_home_simulation(
                new_job.job_id,
                new_job.run_id,
                config,
                start_date,
                end_date,
                db_path,
                data_dir,
                name,
                new_job.created_at,
            ),
        )

    def submit_fleet_job(
        self,
        configs: list[HomeConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        db_path: str,
        data_dir: str,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Submit a fleet simulation job for background execution.

        Creates run and job entries in SQLite, then submits the fleet
        simulation to the thread pool.

        Args:
            configs: List of home configurations for the fleet.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            db_path: Path to the SQLite database file.
            data_dir: Root directory for storing run data.
            name: Optional name for the fleet simulation run.

        Returns:
            Tuple of (job_id, run_id).

        Raises:
            RuntimeError: If the manager has shut down; the refused job leaves no record.
            sqlite3.Error: If the database refuses the job's run or job row; the refused job leaves no record.
        """
        return self._submit_job(
            db_path,
            run_name=name or "Fleet Simulation",
            run_type="fleet",
            n_homes=len(configs),
            run_simulation=lambda new_job: self._run_fleet_simulation(
                new_job.job_id,
                new_job.run_id,
                configs,
                start_date,
                end_date,
                db_path,
                data_dir,
                name,
                new_job.created_at,
            ),
        )

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Return a copy of the in-memory status of a job this manager tracks.

        A manager tracks only the jobs submitted to it.  It tracks each one
        until the job finishes, and stops at the first submit made once the
        job has been finished for longer than _FINISHED_JOB_TTL_SECONDS.  It
        never reads the jobs table, so a job it does not track, such as one
        from before a restart, is unknown here although the job's rows remain
        in the database.

        Args:
            job_id: Unique job identifier.

        Returns:
            Dict with job_id, run_id, status, progress_pct, current_step,
            message and created_at, the ISO 8601 UTC time the job's rows were
            created.  None if this manager does not track the job.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else dict(job.status)

    def get_events(self, job_id: str) -> Generator[dict[str, Any], None, None]:
        """Yield SSE events from the job's event queue.

        Non-blocking: yields all currently queued events and returns.

        Args:
            job_id: Unique job identifier.

        Yields:
            Dict with event data (type, data fields).
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            # Copy and drain events under the lock to avoid TOCTOU
            events = list(job.events)
            job.events.clear()

        for event in events:
            yield event

    def _stop_tracking_jobs_finished_long_ago(self) -> None:
        """Stop tracking every job that finished more than _FINISHED_JOB_TTL_SECONDS ago; a queued or running job stays tracked."""
        now = self._clock()
        with self._lock:
            expired = [
                job_id
                for job_id, job in self._jobs.items()
                if job.finished_at is not None and now - job.finished_at > _FINISHED_JOB_TTL_SECONDS
            ]
            for job_id in expired:
                del self._jobs[job_id]

    def _submit_job(
        self,
        db_path: str,
        *,
        run_name: str,
        run_type: RunType,
        n_homes: int,
        run_simulation: Callable[[_NewJob], None],
    ) -> tuple[str, str]:
        """Record a new job, queue run_simulation(new_job) on the thread pool, and return (job_id, run_id)."""
        self._stop_tracking_jobs_finished_long_ago()
        new_job = self._record_new_job(db_path, run_name=run_name, run_type=run_type, n_homes=n_homes)
        self._schedule(new_job.job_id, new_job.run_id, db_path, functools.partial(run_simulation, new_job))
        return new_job.job_id, new_job.run_id

    def _record_new_job(self, db_path: str, run_name: str, run_type: RunType, n_homes: int) -> _NewJob:
        """Write a new queued job's run and job rows, then track the job in memory.

        The job is tracked only once both rows are written, so a database that refuses either leaves no record of it.
        """
        job_id = self._new_id()
        run_id = self._new_id()
        created_at = datetime.now(timezone.utc).isoformat()

        with get_db(db_path) as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    run_name,
                    run_type,
                    None,  # config_json filled on completion
                    None,  # summary_json filled on completion
                    "running",
                    None,
                    created_at,
                    None,
                    None,
                    n_homes,
                    None,
                ),
            )
            conn.execute(
                """
                INSERT INTO jobs (id, run_id, status, progress_pct, current_step, message, created_at)
                VALUES (:job_id, :run_id, :status, :progress_pct, :current_step, :message, :created_at)
                """,
                {"job_id": job_id, "run_id": run_id, "created_at": created_at, **_QUEUED_JOB_STATE},
            )

        with self._lock:
            self._jobs[job_id] = _TrackedJob(
                status={"job_id": job_id, "run_id": run_id, **_QUEUED_JOB_STATE, "created_at": created_at}
            )

        return _NewJob(job_id=job_id, run_id=run_id, created_at=created_at)

    def _schedule(self, job_id: str, run_id: str, db_path: str, job: Callable[[], None]) -> None:
        """Queue *job* on the thread pool, counting it as unfinished until it completes, fails or is dropped by shutdown.

        Raises:
            RuntimeError: If the manager has shut down; the refused job leaves no record.
        """
        with self._idle:
            self._unfinished_job_count += 1
        # Hold no lock from here on: the executor may run the done-callback, which takes self._lock,
        # under its own shutdown lock or at once in this thread.
        try:
            future = self._executor.submit(job)
        except RuntimeError:
            self._stop_counting_job()
            self._forget_job(job_id, run_id, db_path)
            raise
        future.add_done_callback(lambda _future: self._finish_job(job_id))

    def _finish_job(self, job_id: str) -> None:
        """Record the clock reading when the executor was done with a job, then stop counting it as unfinished."""
        try:
            finished_at = self._clock()
            with self._lock:
                job = self._jobs.get(job_id)
                if job is None:
                    raise RuntimeError(
                        f"job {job_id} finished, but its JobManager no longer tracked it; "
                        "a manager tracks each job until it finishes"
                    )
                job.finished_at = finished_at
        finally:
            self._stop_counting_job()

    def _stop_counting_job(self) -> None:
        """Stop counting one job as unfinished, waking every wait_until_idle caller once none is left."""
        with self._idle:
            self._unfinished_job_count -= 1
            if self._unfinished_job_count == 0:
                self._idle.notify_all()

    def _forget_job(self, job_id: str, run_id: str, db_path: str) -> None:
        """Erase every record of a job that the executor refused to schedule."""
        with self._lock:
            self._jobs.pop(job_id, None)
        with get_db(db_path) as conn:
            conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

    def _update_progress(
        self,
        job_id: str,
        pct: float,
        step: str,
        message: str,
        db_path: str,
        status: str = "running",
        conn: Any = None,
    ) -> None:
        """Update job progress in memory and SQLite, and append an SSE event.

        Args:
            job_id: Unique job identifier.
            pct: Progress percentage (0-100).
            step: Current step description.
            message: Human-readable progress message.
            db_path: Path to the SQLite database file.
            status: Job status string.
            conn: Optional existing SQLite connection. When provided, uses
                it directly instead of opening a new connection.
        """
        # Update in-memory state
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status.update(progress_pct=pct, current_step=step, message=message, status=status)

        # Update database
        if conn is not None:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE jobs SET
                    status = ?,
                    progress_pct = ?,
                    current_step = ?,
                    message = ?
                WHERE id = ?
                """,
                (status, pct, step, message, job_id),
            )
            conn.commit()
        else:
            with get_db(db_path) as fallback_conn:
                cursor = fallback_conn.cursor()
                cursor.execute(
                    """
                    UPDATE jobs SET
                        status = ?,
                        progress_pct = ?,
                        current_step = ?,
                        message = ?
                    WHERE id = ?
                    """,
                    (status, pct, step, message, job_id),
                )

        # Append SSE event
        event = {
            "event": "progress",
            "data": {
                "progress_pct": pct,
                "current_step": step,
                "message": message,
                "status": status,
            },
        }
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.events.append(event)

    def _emit_event(self, job_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Update in-memory job state and append an SSE event."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status.update(data)
                job.events.append({"event": event_type, "data": data})

    def _run_job(
        self,
        job_id: str,
        run_id: str,
        db_path: str,
        work_fn: Callable[[sqlite3.Connection, Callable[[float, str, str], None]], None],
        success_message: str = "Simulation completed successfully",
    ) -> None:
        """Common job lifecycle wrapper for DB, status, progress, SSE, and errors."""
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            self._update_progress(job_id, 5.0, "Starting", "Initializing...", db_path, "running", conn=conn)
            conn.execute("UPDATE jobs SET status='running', started_at=? WHERE id=?",
                         (datetime.now(timezone.utc).isoformat(), job_id))
            conn.commit()

            def progress(pct: float, step: str, msg: str) -> None:
                self._update_progress(job_id, pct, step, msg, db_path, conn=conn)

            work_fn(conn, progress)

            now = datetime.now(timezone.utc).isoformat()
            conn.execute("UPDATE jobs SET status='completed', progress_pct=100.0, "
                         "current_step='Done', message=?, completed_at=? WHERE id=?",
                         (success_message, now, job_id))
            conn.commit()
            self._emit_event(job_id, "complete", {
                "status": "completed", "progress_pct": 100.0,
                "current_step": "Done", "message": success_message, "run_id": run_id,
            })
        except Exception as exc:
            error_msg, now = str(exc), datetime.now(timezone.utc).isoformat()
            try:
                conn.execute("UPDATE jobs SET status='failed', message=?, error_traceback=?, completed_at=? WHERE id=?",
                             (error_msg, traceback.format_exc(), now, job_id))
                conn.execute("UPDATE runs SET status='failed', error_message=?, completed_at=? WHERE id=?",
                             (error_msg, now, run_id))
                conn.commit()
            except Exception:
                pass
            self._emit_event(job_id, "error", {"status": "failed", "message": error_msg})
        finally:
            conn.close()

    def _run_home_simulation(
        self,
        job_id: str,
        run_id: str,
        config: HomeConfig,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        db_path: str,
        data_dir: str,
        name: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Worker function that runs a home simulation in a background thread.

        Delegates lifecycle management to ``_run_job`` and focuses on the
        simulation-specific logic: running the simulation, calculating
        summary statistics, and persisting results via RunStorage.

        Args:
            job_id: Unique job identifier.
            run_id: Unique run identifier.
            config: Home configuration for the simulation.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            db_path: Path to the SQLite database file.
            data_dir: Root directory for storing run data.
            name: Optional name for the simulation run.
            created_at: Original creation timestamp from job submission.
        """
        start_ref = time.monotonic()

        def work(conn: sqlite3.Connection, progress: Callable[[float, str, str], None]) -> None:
            progress(20.0, "Simulating", "Running home simulation...")
            results = self._simulate_home(config, start_date, end_date)

            progress(80.0, "Summarizing", "Calculating summary statistics...")
            summary = calculate_summary(results)

            progress(90.0, "Saving", "Persisting results to storage...")
            storage = RunStorage(db_path=db_path, data_dir=data_dir)
            duration = time.monotonic() - start_ref
            storage.save_home_run(
                run_id=run_id,
                config=config,
                results=results,
                summary=summary,
                name=name or config.name or "Web Simulation",
                status="completed",
                duration_seconds=duration,
                created_at=created_at,
            )

        self._run_job(job_id, run_id, db_path, work, "Simulation completed successfully")

    def _run_fleet_simulation(
        self,
        job_id: str,
        run_id: str,
        configs: list[HomeConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        db_path: str,
        data_dir: str,
        name: str | None = None,
        created_at: str | None = None,
    ) -> None:
        """Worker function that runs a fleet simulation in a background thread.

        Delegates lifecycle management to ``_run_job`` and focuses on the
        fleet-specific logic: iterating homes, aggregating results, and
        persisting via RunStorage.

        Args:
            job_id: Unique job identifier.
            run_id: Unique run identifier.
            configs: List of home configurations for the fleet.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            db_path: Path to the SQLite database file.
            data_dir: Root directory for storing run data.
            name: Optional name for the fleet simulation run.
            created_at: Original creation timestamp from job submission.
        """
        start_ref = time.monotonic()

        def work(conn: sqlite3.Connection, progress: Callable[[float, str, str], None]) -> None:
            total = len(configs)
            per_home_results: list[SimulationResults] = []
            per_home_summaries: list[SummaryStatistics] = []

            for i, home_config in enumerate(configs):
                pct = (i / total) * 90.0 + 5.0  # 5% to 95%
                progress(pct, f"Home {i + 1}/{total}", f"Simulating home {i + 1} of {total}...")
                results = self._simulate_home(home_config, start_date, end_date)
                summary = calculate_summary(results)
                per_home_results.append(results)
                per_home_summaries.append(summary)

            progress(95.0, "Aggregating", "Aggregating fleet results...")
            fleet_results = FleetResults(
                per_home_results=per_home_results,
                home_configs=configs,
            )
            fleet_summary = calculate_fleet_summary(fleet_results)

            progress(97.0, "Saving", "Persisting fleet results...")
            storage = RunStorage(db_path=db_path, data_dir=data_dir)
            duration = time.monotonic() - start_ref
            storage.save_fleet_run(
                run_id=run_id,
                fleet_results=fleet_results,
                fleet_summary=fleet_summary,
                per_home_summaries=per_home_summaries,
                name=name or "Fleet Simulation",
                status="completed",
                duration_seconds=duration,
                created_at=created_at,
            )

        self._run_job(job_id, run_id, db_path, work, "Fleet simulation completed successfully")


def recover_stale_jobs(db_path: str | Path) -> int:
    """Mark any jobs stuck in 'running' or 'queued' status as failed.

    Called on startup to clean up jobs interrupted by a server restart.

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        Number of jobs recovered.
    """
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        now = datetime.now(timezone.utc).isoformat()
        cursor.execute(
            """
            UPDATE jobs SET
                status = 'failed',
                message = 'Interrupted by server restart',
                completed_at = ?
            WHERE status IN ('running', 'queued')
            """,
            (now,),
        )
        recovered_jobs = cursor.rowcount
        # Also mark corresponding runs as failed
        cursor.execute(
            """
            UPDATE runs SET
                status = 'failed',
                error_message = 'Interrupted by server restart',
                completed_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )
        return recovered_jobs
