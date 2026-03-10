"""Background job manager for running simulations asynchronously.

Provides a JobManager class that uses a ThreadPoolExecutor to run
home and fleet simulations in background threads, with progress
tracking via SQLite and SSE event queues.
"""

import collections
import json
import threading
import time
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
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

    def shutdown(self) -> None:
        """Shut down the thread pool executor."""
        self._executor.shutdown(wait=False)

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
    ) -> None:
        """Update job progress in memory and SQLite, and append an SSE event.

        Args:
            job_id: Unique job identifier.
            pct: Progress percentage (0-100).
            step: Current step description.
            message: Human-readable progress message.
            db_path: Path to the SQLite database file.
            status: Job status string.
        """
        # Update in-memory state
        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["progress_pct"] = pct
                self._jobs[job_id]["current_step"] = step
                self._jobs[job_id]["message"] = message
                self._jobs[job_id]["status"] = status

        # Update database
        with get_db(db_path) as conn:
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

        Steps:
        1. Update job status to 'running'
        2. Call simulate_home()
        3. Call calculate_summary()
        4. Save via RunStorage.save_home_run() (upserts the placeholder row)
        5. Update job status to 'completed'

        On exception: update status to 'failed' and capture traceback.

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
        start_time = time.monotonic()
        try:
            # Step 1: Update to running
            self._update_progress(job_id, 5.0, "Starting", "Initializing simulation...", db_path, "running")

            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), job_id),
                )

            # Step 2: Run simulation
            self._update_progress(job_id, 20.0, "Simulating", "Running home simulation...", db_path)
            results = simulate_home(config, start_date, end_date)

            # Step 3: Calculate summary
            self._update_progress(job_id, 80.0, "Summarizing", "Calculating summary statistics...", db_path)
            summary = calculate_summary(results)

            # Step 4: Save results (upserts the placeholder run row)
            self._update_progress(job_id, 90.0, "Saving", "Persisting results to storage...", db_path)
            storage = RunStorage(db_path=db_path, data_dir=data_dir)

            duration = time.monotonic() - start_time
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

            # Step 5: Update job to completed
            completed_at = datetime.now(timezone.utc).isoformat()
            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE jobs SET
                        status = 'completed',
                        progress_pct = 100.0,
                        current_step = 'Done',
                        message = 'Simulation completed successfully',
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (completed_at, job_id),
                )

            # Update in-memory state
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["progress_pct"] = 100.0
                    self._jobs[job_id]["current_step"] = "Done"
                    self._jobs[job_id]["message"] = "Simulation completed successfully"

                # Append completion SSE event
                if job_id in self._event_queues:
                    self._event_queues[job_id].append({
                        "event": "complete",
                        "data": {
                            "status": "completed",
                            "run_id": run_id,
                        },
                    })

        except Exception as exc:
            # Update job and run to failed
            error_tb = traceback.format_exc()
            error_msg = str(exc)
            completed_at = datetime.now(timezone.utc).isoformat()

            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE jobs SET
                        status = 'failed',
                        message = ?,
                        error_traceback = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (error_msg, error_tb, completed_at, job_id),
                )
                cursor.execute(
                    """
                    UPDATE runs SET
                        status = 'failed',
                        error_message = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (error_msg, completed_at, run_id),
                )

            # Update in-memory state
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "failed"
                    self._jobs[job_id]["message"] = error_msg

                # Append failure SSE event
                if job_id in self._event_queues:
                    self._event_queues[job_id].append({
                        "event": "error",
                        "data": {
                            "status": "failed",
                            "message": error_msg,
                        },
                    })

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

        Iterates through home configs, simulates each one, reports progress,
        and saves aggregated results.

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

        start_time = time.monotonic()
        try:
            # Update to running
            self._update_progress(job_id, 5.0, "Starting", "Initializing fleet simulation...", db_path, "running")

            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE jobs SET status = 'running', started_at = ? WHERE id = ?",
                    (datetime.now(timezone.utc).isoformat(), job_id),
                )

            # Simulate each home
            total = len(configs)
            per_home_results: list[SimulationResults] = []
            per_home_summaries: list[SummaryStatistics] = []

            for i, home_config in enumerate(configs):
                pct = (i / total) * 90.0 + 5.0  # 5% to 95%
                self._update_progress(
                    job_id, pct,
                    f"Home {i + 1}/{total}",
                    f"Simulating home {i + 1} of {total}...",
                    db_path,
                )

                results = simulate_home(home_config, start_date, end_date)
                summary = calculate_summary(results)
                per_home_results.append(results)
                per_home_summaries.append(summary)

            # Aggregate results
            self._update_progress(job_id, 95.0, "Aggregating", "Aggregating fleet results...", db_path)

            fleet_results = FleetResults(
                per_home_results=per_home_results,
                home_configs=configs,
            )

            # Calculate fleet summary using the proper function
            fleet_summary = calculate_fleet_summary(fleet_results)

            # Save results (upserts the placeholder run row)
            self._update_progress(job_id, 97.0, "Saving", "Persisting fleet results...", db_path)
            storage = RunStorage(db_path=db_path, data_dir=data_dir)

            duration = time.monotonic() - start_time
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

            # Update job to completed
            completed_at = datetime.now(timezone.utc).isoformat()
            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE jobs SET
                        status = 'completed',
                        progress_pct = 100.0,
                        current_step = 'Done',
                        message = 'Fleet simulation completed successfully',
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (completed_at, job_id),
                )

            # Update in-memory state
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "completed"
                    self._jobs[job_id]["progress_pct"] = 100.0
                    self._jobs[job_id]["current_step"] = "Done"
                    self._jobs[job_id]["message"] = "Fleet simulation completed successfully"

                # Append completion SSE event
                if job_id in self._event_queues:
                    self._event_queues[job_id].append({
                        "event": "complete",
                        "data": {
                            "status": "completed",
                            "run_id": run_id,
                        },
                    })

        except Exception as exc:
            error_tb = traceback.format_exc()
            error_msg = str(exc)
            completed_at = datetime.now(timezone.utc).isoformat()

            with get_db(db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE jobs SET
                        status = 'failed',
                        message = ?,
                        error_traceback = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (error_msg, error_tb, completed_at, job_id),
                )
                cursor.execute(
                    """
                    UPDATE runs SET
                        status = 'failed',
                        error_message = ?,
                        completed_at = ?
                    WHERE id = ?
                    """,
                    (error_msg, completed_at, run_id),
                )

            # Update in-memory state
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["status"] = "failed"
                    self._jobs[job_id]["message"] = error_msg

                # Append failure SSE event
                if job_id in self._event_queues:
                    self._event_queues[job_id].append({
                        "event": "error",
                        "data": {
                            "status": "failed",
                            "message": error_msg,
                        },
                    })


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
