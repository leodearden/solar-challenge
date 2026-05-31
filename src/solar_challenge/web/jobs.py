# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job manager for running simulations asynchronously.

Provides a JobManager class that uses a ThreadPoolExecutor to run
home and fleet simulations in background threads, with progress
tracking via SQLite and SSE event queues.
"""

import atexit
import collections
import json
import sqlite3
import threading
import time
import traceback
import uuid
import weakref
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Callable
from typing import Any, Generator

from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage

# Module-level weak registry of all live JobManager instances.
# WeakSet avoids keeping managers alive past their natural lifetime.
_active_managers: "weakref.WeakSet[JobManager]" = weakref.WeakSet()


def shutdown_all_managers(wait: bool = False) -> None:
    """Shut down every live JobManager registered in _active_managers.

    Iterates a snapshot of the registry so that managers garbage-collected
    between registration and this call are silently skipped.  Shutting down
    an already-shut-down executor is a no-op, making this safe to call more
    than once (idempotent).

    Args:
        wait: If True, block until all running workers finish.  Defaults to
            False so the atexit hook does not stall interpreter shutdown.
    """
    for manager in list(_active_managers):
        manager.shutdown(wait=wait)


atexit.register(shutdown_all_managers)


class JobManager:
    """Manages background simulation jobs with progress tracking.

    Uses a ThreadPoolExecutor to run simulations in background threads.
    Each job has an in-memory event queue (collections.deque) for
    streaming progress events via SSE.

    Attributes:
        _executor: Thread pool for background job execution.
        _jobs: In-memory dict tracking job metadata.
        _event_queues: Per-job deques of SSE event dicts.
    """

    def __init__(self, max_workers: int = 2) -> None:
        """Initialize the job manager.

        Args:
            max_workers: Maximum number of concurrent simulation threads.
        """
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}
        self._event_queues: dict[str, collections.deque[dict[str, Any]]] = {}
        _active_managers.add(self)

    def shutdown(self, wait: bool = False) -> None:
        """Shut down the thread pool executor.

        Args:
            wait: If True, block until all running workers finish before
                returning.  Defaults to False so deployed-server teardown
                (and the module-level atexit hook) exits promptly.
                cancel_futures=True drops any queued-but-unstarted jobs so
                they do not block process exit.
        """
        self._executor.shutdown(wait=wait, cancel_futures=True)

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
        """
        self._cleanup_old_jobs()

        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # Initialize in-memory tracking
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "run_id": run_id,
                "status": "queued",
                "progress_pct": 0.0,
                "current_step": "Queued",
                "message": "Waiting to start...",
                "created_at": time.monotonic(),
            }
            self._event_queues[job_id] = collections.deque(maxlen=100)

        # Create run record in database
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    name or config.name or "Web Simulation",
                    "home",
                    None,  # config_json filled on completion
                    None,  # summary_json filled on completion
                    "running",
                    None,
                    created_at,
                    None,
                    None,
                    1,
                    None,
                ),
            )

            # Create job record in database
            cursor.execute(
                """
                INSERT INTO jobs (
                    id, run_id, status, progress_pct, current_step,
                    message, created_at, started_at, completed_at,
                    error_traceback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    "queued",
                    0.0,
                    "Queued",
                    "Waiting to start...",
                    created_at,
                    None,
                    None,
                    None,
                ),
            )

        # Submit to thread pool
        self._executor.submit(
            self._run_home_simulation,
            job_id,
            run_id,
            config,
            start_date,
            end_date,
            db_path,
            data_dir,
            name,
            created_at,
        )

        return job_id, run_id

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
        """
        self._cleanup_old_jobs()

        job_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        created_at = datetime.now(timezone.utc).isoformat()

        # Initialize in-memory tracking
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "run_id": run_id,
                "status": "queued",
                "progress_pct": 0.0,
                "current_step": "Queued",
                "message": "Waiting to start...",
                "created_at": time.monotonic(),
            }
            self._event_queues[job_id] = collections.deque(maxlen=100)

        # Create run record in database
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO runs (
                    id, name, type, config_json, summary_json,
                    status, error_message, created_at, completed_at,
                    duration_seconds, n_homes, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    name or "Fleet Simulation",
                    "fleet",
                    None,
                    None,
                    "running",
                    None,
                    created_at,
                    None,
                    None,
                    len(configs),
                    None,
                ),
            )

            # Create job record in database
            cursor.execute(
                """
                INSERT INTO jobs (
                    id, run_id, status, progress_pct, current_step,
                    message, created_at, started_at, completed_at,
                    error_traceback
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    run_id,
                    "queued",
                    0.0,
                    "Queued",
                    "Waiting to start...",
                    created_at,
                    None,
                    None,
                    None,
                ),
            )

        # Submit to thread pool
        self._executor.submit(
            self._run_fleet_simulation,
            job_id,
            run_id,
            configs,
            start_date,
            end_date,
            db_path,
            data_dir,
            name,
            created_at,
        )

        return job_id, run_id

    def get_job_status(self, job_id: str) -> dict[str, Any] | None:
        """Get the current status of a job.

        Checks in-memory cache first, then falls back to database.

        Args:
            job_id: Unique job identifier.

        Returns:
            Dict with job_id, status, progress_pct, current_step, message,
            and run_id. Returns None if job not found.
        """
        with self._lock:
            if job_id in self._jobs:
                return dict(self._jobs[job_id])
            return None

    def get_events(self, job_id: str) -> Generator[dict[str, Any], None, None]:
        """Yield SSE events from the job's event queue.

        Non-blocking: yields all currently queued events and returns.

        Args:
            job_id: Unique job identifier.

        Yields:
            Dict with event data (type, data fields).
        """
        with self._lock:
            queue = self._event_queues.get(job_id)
            if queue is None:
                return
            # Copy and drain events under the lock to avoid TOCTOU
            events = list(queue)
            queue.clear()

        for event in events:
            yield event

    def _cleanup_old_jobs(self, max_age_seconds: float = 3600.0) -> None:
        """Remove jobs older than max_age_seconds from in-memory tracking.

        Compares each job's ``created_at`` monotonic timestamp against the
        current time and removes entries that exceed the threshold.

        Args:
            max_age_seconds: Maximum age in seconds before a job is removed.
                Defaults to 3600 (1 hour).
        """
        now = time.monotonic()
        with self._lock:
            expired = [
                jid
                for jid, job in self._jobs.items()
                if now - job.get("created_at", now) > max_age_seconds
            ]
            for jid in expired:
                del self._jobs[jid]
                self._event_queues.pop(jid, None)

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
            if job_id in self._jobs:
                self._jobs[job_id]["progress_pct"] = pct
                self._jobs[job_id]["current_step"] = step
                self._jobs[job_id]["message"] = message
                self._jobs[job_id]["status"] = status

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
            if job_id in self._event_queues:
                self._event_queues[job_id].append(event)

    def _emit_event(self, job_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Update in-memory job state and append an SSE event."""
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id].update(data)
            if job_id in self._event_queues:
                self._event_queues[job_id].append({"event": event_type, "data": data})

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
            results = simulate_home(config, start_date, end_date)

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
        from solar_challenge.fleet import FleetResults, calculate_fleet_summary

        start_ref = time.monotonic()

        def work(conn: sqlite3.Connection, progress: Callable[[float, str, str], None]) -> None:
            total = len(configs)
            per_home_results: list[SimulationResults] = []
            per_home_summaries: list[SummaryStatistics] = []

            for i, home_config in enumerate(configs):
                pct = (i / total) * 90.0 + 5.0  # 5% to 95%
                progress(pct, f"Home {i + 1}/{total}", f"Simulating home {i + 1} of {total}...")
                results = simulate_home(home_config, start_date, end_date)
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
    from pathlib import Path

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
