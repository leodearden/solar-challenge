# SPDX-License-Identifier: AGPL-3.0-or-later
"""Background job manager for running simulations asynchronously.

Provides a JobManager class that uses a ThreadPoolExecutor to run home and
fleet simulations in background threads. A job's progress is held in memory
and streamed through SSE event queues; its run is recorded through the
manager's RunStorage, running from its submit until the job completes it, once
its save has written the run's results, or its failure marks it failed. A job
reports completed only once its run reads completed. A job whose run is
deleted is cancelled and records nothing. A job's status moves only along
LEGAL_JOB_TRANSITIONS, through the manager's one writer of job state
(docs/prds/job-events-and-sse-framing.md §3.4).
"""

import collections
import functools
import logging
import threading
import time
import uuid
import weakref
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from collections.abc import Callable, Mapping
from types import MappingProxyType
from typing import Generator, Literal, TypeAlias

from concurrent.futures import Future, ThreadPoolExecutor

import pandas as pd

from solar_challenge.fleet import FleetResults
from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.web.run_names import is_run_name
from solar_challenge.web.storage import RunRecord, RunStorage
from solar_challenge.web.stored_runs import RUN_KINDS, RunType

logger = logging.getLogger(__name__)

HomeSimulator: TypeAlias = Callable[[HomeConfig, pd.Timestamp, pd.Timestamp], SimulationResults]

# Reports a running job's progress: its percentage, its step and its message.
_ProgressReport: TypeAlias = Callable[[float, str, str], None]

# Saves a finished job's run in the RunStorage.
_RunSave: TypeAlias = Callable[[], None]

JobStatus = Literal["queued", "running", "completed", "failed", "cancelled"]  # the status of a job a JobManager reports

_QUEUED_JOB_STATUS: JobStatus = "queued"
_RUNNING_JOB_STATUS: JobStatus = "running"
_COMPLETED_JOB_STATUS: JobStatus = "completed"
_FAILED_JOB_STATUS: JobStatus = "failed"
_CANCELLED_JOB_STATUS: JobStatus = "cancelled"
_CANCELLED_JOB_MESSAGE = "Cancelled: its run was deleted"
_FINISHED_JOB_TTL_SECONDS = 3600.0

LEGAL_JOB_TRANSITIONS: Mapping[JobStatus, frozenset[JobStatus]] = MappingProxyType(
    {
        "queued": frozenset({"running", "failed", "cancelled"}),
        "running": frozenset({"running", "completed", "failed", "cancelled"}),
        "completed": frozenset(),
        "failed": frozenset(),
        "cancelled": frozenset(),
    }
)
"""The statuses a job's status may move to from each status, the table of docs/prds/job-events-and-sse-framing.md §3.4.

running → running is a progress report. A status with no exits is terminal.
"""

TERMINAL_JOB_STATUSES: frozenset[JobStatus] = frozenset(
    status for status, exits in LEGAL_JOB_TRANSITIONS.items() if not exits
)
"""The statuses a job never moves on from: those LEGAL_JOB_TRANSITIONS gives no exits."""


class IllegalJobTransition(RuntimeError):
    """A move of a job's status that LEGAL_JOB_TRANSITIONS does not allow; the message names the job, its run, both statuses and the moves the table allows."""

    def __init__(self, job_id: str, run_id: str, from_status: JobStatus, to_status: JobStatus) -> None:
        exits = sorted(LEGAL_JOB_TRANSITIONS[from_status])
        allowed = f"only to {', '.join(repr(exit) for exit in exits)}" if exits else "to no status, as it is terminal"
        super().__init__(
            f"Job {job_id!r} of run {run_id!r} cannot move from {from_status!r} to {to_status!r}: "
            f"LEGAL_JOB_TRANSITIONS lets a job move from {from_status!r} {allowed}"
        )
        self.job_id = job_id
        self.run_id = run_id
        self.from_status = from_status
        self.to_status = to_status


def check_job_transition(job_id: str, run_id: str, from_status: JobStatus, to_status: JobStatus) -> None:
    """Check that job *job_id* of run *run_id* may move from *from_status* to *to_status*, as LEGAL_JOB_TRANSITIONS says.

    Raises:
        IllegalJobTransition: The table does not let *from_status* move to *to_status*.
    """
    if to_status not in LEGAL_JOB_TRANSITIONS[from_status]:
        raise IllegalJobTransition(job_id, run_id, from_status, to_status)

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
    """A job just recorded: its id, and the record of its run as its submit created it through the RunStorage."""

    job_id: str
    run: RunRecord


@dataclass(frozen=True)
class JobState:
    """What a JobManager reports about a job it tracks: its ids, status and progress, and its run's created_at.

    created_at is the ISO 8601 UTC time the job's submit created its run.
    """

    job_id: str
    run_id: str
    status: JobStatus
    progress_pct: float
    current_step: str
    message: str
    created_at: str


# The event a job's progress stream names: the job progressed, completed or failed. A cancelled job's stream ends
# with the error event too, as docs/prds/run-store-one-owner.md §3.7 records.
JobEventType = Literal["progress", "complete", "error"]


@dataclass(frozen=True)
class JobEvent:
    """An event a JobManager queues for a job's progress stream: its type, and the state the job reported with it."""

    type: JobEventType
    state: JobState


_EVENT_TYPE_OF_STATUS: Mapping[JobStatus, JobEventType] = MappingProxyType(
    {"queued": "progress", "running": "progress", "completed": "complete", "failed": "error", "cancelled": "error"}
)
"""The type of the event a job's move into each status queues for its progress stream."""


class _JobCancelled(BaseException):
    """Raised at a runner's checkpoint once its job is cancelled.

    It is not an Exception, as asyncio.CancelledError is not, so it passes through the generic error handlers
    between a checkpoint and JobManager._run_job, which reports the job cancelled.
    """


class _Cancellation:
    """Whether a job is cancelled, which its run's delete does through JobManager.cancel_run, under a lock of the job's own.

    The job's completion is made under the same lock: the save of its run, its run marked completed, then the job
    reported completed. That is how contract C8 holds (docs/prds/run-store-one-owner.md §3.7), and how a job reports
    completed only once its run reads completed (J3, docs/prds/job-events-and-sse-framing.md §3.4). Lock order: a
    job's cancellation lock may be held while its JobManager's _lock is taken, never the reverse.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cancelled = False
        self._completing = False

    def cancel(self) -> bool:
        """Cancel the job, which stops at its runner's next checkpoint, unless its completion has started.

        A cancel that comes while the completion runs waits for it to end.

        Returns:
            Whether the job is cancelled: False once its completion has started.
        """
        with self._lock:
            if not self._completing:
                self._cancelled = True
            return self._cancelled

    @property
    def is_cancelled(self) -> bool:
        """Whether the job is cancelled."""
        with self._lock:
            return self._cancelled

    def checkpoint(self) -> None:
        """Raise _JobCancelled once the job is cancelled."""
        if self.is_cancelled:
            raise _JobCancelled()

    def complete_unless_cancelled(self, complete: Callable[[], None]) -> None:
        """Make the job's completion, holding the lock across the check that the job is not cancelled and the completion.

        Raises:
            _JobCancelled: The job is cancelled; the completion never started then.
        """
        with self._lock:
            if self._cancelled:
                raise _JobCancelled()
            self._completing = True
            complete()


@dataclass
class _TrackedJob:
    """A job a JobManager tracks.

    The state job_state reports, which only JobManager._move_job writes, the SSE events get_events has not yet
    yielded, the manager's
    clock reading when the job finished (None while it is queued or running), the job's
    cancellation, which cancel_run sets when the job's run is deleted, and the executor's future
    of the job once it is queued (None until then), which cancel_run cancels to drop the job
    from the queue.
    """

    state: JobState
    events: collections.deque[JobEvent] = field(default_factory=lambda: collections.deque(maxlen=100))
    finished_at: float | None = None
    cancellation: _Cancellation = field(default_factory=_Cancellation)
    future: Future[None] | None = None


class JobManager:
    """Manages background simulation jobs with progress tracking.

    Uses a ThreadPoolExecutor to run simulations in background threads.
    Each job has an in-memory event queue (collections.deque) for
    streaming progress events via SSE, and a run the manager records
    through its RunStorage. A job's status moves only along
    LEGAL_JOB_TRANSITIONS (docs/prds/job-events-and-sse-framing.md §3.4),
    through one writer, _move_job, which refuses any other move with
    IllegalJobTransition.

    Attributes:
        _storage: The RunStorage each job's run is recorded in.
        _executor: Thread pool for background job execution.
        _jobs: Each job the manager tracks, by id.
        _unfinished_job_count: Number of jobs queued or running; wait_until_idle waits for it to reach 0.
    """

    def __init__(
        self,
        storage: RunStorage,
        max_workers: int = 2,
        *,
        simulate_home: HomeSimulator,
        new_id: Callable[[], str] = _random_id,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize the job manager.

        Args:
            storage: The RunStorage each job's run is recorded in, from the
                job's submit to its outcome; create_app passes the app's.
            max_workers: Maximum number of concurrent simulation threads.
            simulate_home: Simulates one home over a date range, on the weather
                it is bound to; create_app binds solar_challenge.home.simulate_home
                to default_weather().
            new_id: Returns a new, unique id on each call; each job and each run
                takes one. Defaults to a random UUID.
            clock: Returns the time in seconds on a clock that never goes
                backwards, which the manager reads to age the jobs it tracks.
                Defaults to time.monotonic.
        """
        self._storage = storage
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

        A job stops counting once it completes, fails, is cancelled, or is dropped by shutdown.

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
        name: str | None = None,
    ) -> tuple[str, str]:
        """Submit a home simulation job for background execution.

        Records the job's run, running, through the manager's RunStorage before
        the simulation is queued on the thread pool.

        Args:
            config: Home configuration for the simulation.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            name: The run's name; when None or blank, its run kind's default name of the
                job's homes (RunKind.default_name).

        Returns:
            Tuple of (job_id, run_id).

        Raises:
            RuntimeError: If the manager has shut down.
            ValueError: If the store refuses the run id.
            sqlite3.Error: If the database refuses the run's row.
            A refused job leaves no record.
        """
        return self._submit_job(
            name=name,
            run_type="home",
            home_configs=(config,),
            run_simulation=lambda new_job: self._run_home_simulation(
                new_job.job_id, new_job.run, config, start_date, end_date
            ),
        )

    def submit_fleet_job(
        self,
        configs: list[HomeConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Submit a fleet simulation job for background execution.

        Records the job's run, running, through the manager's RunStorage before
        the fleet simulation is queued on the thread pool.

        Args:
            configs: List of home configurations for the fleet.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
            name: The run's name; when None or blank, its run kind's default name of the
                job's homes (RunKind.default_name).

        Returns:
            Tuple of (job_id, run_id).

        Raises:
            RuntimeError: If the manager has shut down.
            ValueError: If the store refuses the run id.
            sqlite3.Error: If the database refuses the run's row.
            A refused job leaves no record.
        """
        return self._submit_job(
            name=name,
            run_type="fleet",
            home_configs=tuple(configs),
            run_simulation=lambda new_job: self._run_fleet_simulation(
                new_job.job_id, new_job.run, configs, start_date, end_date
            ),
        )

    def job_state(self, job_id: str) -> JobState | None:
        """Return the in-memory state of a job this manager tracks.

        A manager tracks only the jobs submitted to it.  It tracks each one
        until the job finishes, and stops at the first submit made once the
        job has been finished for longer than _FINISHED_JOB_TTL_SECONDS.  It
        never reads the RunStorage, so a job it does not track, such as one
        from before a restart, is unknown here although the job's run remains
        there.

        Args:
            job_id: Unique job identifier.

        Returns:
            The job's frozen JobState: its job_id, run_id, status,
            progress_pct, current_step, message and created_at, its run's
            created_at.  None if this manager does not track the job.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            return None if job is None else job.state

    def get_events(self, job_id: str) -> Generator[JobEvent, None, None]:
        """Yield the events queued for the job's progress stream since the last call, oldest first.

        Non-blocking: yields all currently queued events and returns.

        Args:
            job_id: Unique job identifier.

        Yields:
            Each queued JobEvent: its type, and the state the job reported with it.
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

    def cancel_run(self, run_id: str) -> bool:
        """Cancel the queued or running job of run *run_id*, as the run's delete does before it removes the run.

        The job reports 'cancelled' and writes nothing to the RunStorage (contract C8, docs/prds/run-store-one-owner.md
        §3.7). A queued job is dropped from the queue and reports cancelled before cancel_run returns. A running job
        stops at its runner's next progress report: a home job once its current simulation returns, a fleet job before
        its next home. Once the job's completion has started, cancel_run waits for it to end.

        Args:
            run_id: The id of the run whose job to cancel.

        Returns:
            True if the run's job will save nothing; False if this manager has no queued or running job of the run,
            or the job's completion had already started.
        """
        job = self._unfinished_job_of_run(run_id)
        if job is None or not job.cancellation.cancel():
            return False
        with self._lock:
            future = job.future
        # A future _schedule has not stored yet is not cancelled here: the flag stops its job at the 'Starting'
        # checkpoint. Cancelling a queued future runs its done-callback, which takes self._lock, before cancel()
        # returns, so no lock is held here.
        if future is not None:
            future.cancel()
        return True

    def _unfinished_job_of_run(self, run_id: str) -> _TrackedJob | None:
        """Return the job of run *run_id* this manager tracks whose status is not terminal, or None if it has none."""
        with self._lock:
            return next(
                (
                    job
                    for job in self._jobs.values()
                    if job.state.run_id == run_id and job.state.status not in TERMINAL_JOB_STATUSES
                ),
                None,
            )

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
        *,
        name: str | None,
        run_type: RunType,
        home_configs: tuple[HomeConfig, ...],
        run_simulation: Callable[[_NewJob], None],
    ) -> tuple[str, str]:
        """Record a new job, queue run_simulation(new_job) on the thread pool, and return (job_id, run_id)."""
        self._stop_tracking_jobs_finished_long_ago()
        new_job = self._record_new_job(name=name, run_type=run_type, home_configs=home_configs)
        self._schedule(new_job.job_id, new_job.run.id, functools.partial(run_simulation, new_job))
        return new_job.job_id, new_job.run.id

    def _record_new_job(self, name: str | None, run_type: RunType, home_configs: tuple[HomeConfig, ...]) -> _NewJob:
        """Create a new queued job's run of *home_configs*, running, through the RunStorage, then track the job in memory.

        This is the one place a run's name is decided (contract C7, docs/prds/run-store-one-owner.md
        §3.6): *name* when it can name a run, else its run kind's default name of *home_configs*.
        The job is tracked only once its run is created, so a store that refuses the run leaves no record of it.
        The job's created_at is its run's.
        """
        job_id = self._new_id()
        run_id = self._new_id()
        created_at = datetime.now(timezone.utc).isoformat()
        run = self._storage.create_run(
            run_id,
            run_type=run_type,
            name=name if is_run_name(name) else RUN_KINDS[run_type].default_name(home_configs),
            n_homes=len(home_configs),
            created_at=created_at,
        )
        queued = JobState(
            job_id=job_id,
            run_id=run_id,
            status=_QUEUED_JOB_STATUS,
            progress_pct=0.0,
            current_step="Queued",
            message="Waiting to start...",
            created_at=created_at,
        )

        with self._lock:
            self._jobs[job_id] = _TrackedJob(state=queued)

        return _NewJob(job_id=job_id, run=run)

    def _schedule(self, job_id: str, run_id: str, job: Callable[[], None]) -> None:
        """Queue *job* on the thread pool, counting it as unfinished until it completes, fails, is cancelled or is dropped from the queue.

        Raises:
            RuntimeError: If the manager has shut down; the refused job leaves no record.
        """
        with self._idle:
            self._unfinished_job_count += 1
        # No lock is held while the executor may run the done-callback, which takes self._lock: under its own
        # shutdown lock, or at once in this thread once the callback is added.
        try:
            future = self._executor.submit(job)
        except RuntimeError:
            self._stop_counting_job()
            self._forget_job(job_id, run_id)
            raise
        with self._lock:
            self._jobs[job_id].future = future
        future.add_done_callback(functools.partial(self._on_job_done, job_id))

    def _on_job_done(self, job_id: str, future: Future[None]) -> None:
        """Report job *job_id* cancelled if its run's delete dropped it from the queue, or failed if its runner raised, then finish it, even if reporting it raised.

        The job therefore reports cancelled or failed before it stops counting as unfinished. Both steps stay in this
        one callback: the executor runs a callback added after the job finished at once, in the thread that adds it,
        so two callbacks could run out of order.
        """
        try:
            if future.cancelled():
                self._report_job_dropped_from_the_queue(job_id)
            else:
                self._fail_job_if_its_runner_raised(job_id, future)
        finally:
            self._finish_job(job_id)

    def _report_job_dropped_from_the_queue(self, job_id: str) -> None:
        """Report job *job_id*, which the executor dropped from its queue before it ran, cancelled if its run's delete cancelled it.

        A job shutdown dropped never ran, so it is not failed: it keeps the state it was queued in.
        """
        if self._cancellation_of(job_id).is_cancelled:
            self._report_cancelled_job(job_id)

    def _fail_job_if_its_runner_raised(self, job_id: str, future: Future[None]) -> None:
        """Fail job *job_id* with the error its runner raised, if it raised one."""
        error = future.exception()
        if error is not None:
            self._fail_job_whose_runner_raised(job_id, error)

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

    def _forget_job(self, job_id: str, run_id: str) -> None:
        """Erase every record of a job that the executor refused to schedule: stop tracking it, and delete its run."""
        with self._lock:
            self._jobs.pop(job_id, None)
        self._storage.delete_run(run_id)

    def _cancellation_of(self, job_id: str) -> _Cancellation:
        """Return the cancellation of job *job_id*, which this manager tracks."""
        with self._lock:
            return self._jobs[job_id].cancellation

    def _move_job(
        self,
        job_id: str,
        to_status: JobStatus,
        message: str,
        *,
        progress_pct: float | None = None,
        current_step: str | None = None,
    ) -> JobState:
        """Move job *job_id* to *to_status* with *message*, as the one writer of a job's state does; return the new state.

        The job keeps its progress unless *progress_pct* and *current_step* are given. Under one hold of the lock the
        move is checked against LEGAL_JOB_TRANSITIONS, the new state is stored, finished_at is stamped when the new
        status is terminal, and the new state's event is queued, so a reader who sees the new state finds its event
        queued.

        Raises:
            RuntimeError: The manager no longer tracks the job, though it tracks each job until it finishes.
            IllegalJobTransition: LEGAL_JOB_TRANSITIONS does not let the job's status move to *to_status*; nothing
                has changed then.
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise RuntimeError(
                    f"job {job_id} moves to {to_status!r}, but its JobManager no longer tracks it; "
                    "a manager tracks each job until it finishes"
                )
            check_job_transition(job_id, job.state.run_id, job.state.status, to_status)
            job.state = replace(
                job.state,
                status=to_status,
                message=message,
                progress_pct=job.state.progress_pct if progress_pct is None else progress_pct,
                current_step=job.state.current_step if current_step is None else current_step,
            )
            if to_status in TERMINAL_JOB_STATUSES:
                job.finished_at = self._clock()
            job.events.append(JobEvent(_EVENT_TYPE_OF_STATUS[to_status], job.state))
            return job.state

    def _report_cancelled_job(self, job_id: str) -> None:
        """Report job *job_id* cancelled because its run was deleted, at its last progress.

        It records nothing through the RunStorage: the run's delete removes the run's row.
        """
        self._move_job(job_id, _CANCELLED_JOB_STATUS, _CANCELLED_JOB_MESSAGE)

    def _fail_job(self, job_id: str, message: str) -> None:
        """Report job *job_id* failed with *message*, at its last progress, then record its run failed.

        The job is reported failed first, so nothing its run's row write raises keeps the failure from being
        reported; the row write is best-effort, as _record_failed_run makes it (docs/prds/job-events-and-sse-framing.md
        §3.4, and the G7 waiver of §15).
        """
        self._record_failed_run(self._move_job(job_id, _FAILED_JOB_STATUS, message))

    def _record_failed_run(self, state: JobState) -> None:
        """Mark the run of *state*'s job failed with the job's message, through the RunStorage.

        An Exception that stops it is logged, naming the job, its run and its failure, and not raised: the job is
        already reported failed. A run it cannot record failed stays running, and RunStorage.fail_interrupted_runs
        marks it failed when the next server starts.
        """
        try:
            self._storage.mark_run_failed(state.run_id, state.message)
        except Exception:
            logger.exception(
                "Could not record in the run store that job %s of run %s failed with %r",
                state.job_id,
                state.run_id,
                state.message,
            )

    def _fail_job_whose_runner_raised(self, job_id: str, error: BaseException) -> None:
        """Fail job *job_id* with *error*, which its runner raised and the runner's own failure handling did not catch.

        Report the job failed, log *error* naming the job and its run, then record the failure in the job's run, as
        _fail_job records it.
        """
        failed = self._move_job(job_id, _FAILED_JOB_STATUS, str(error))
        logger.error(
            "Job %s of run %s failed with %r, an error that escaped its failure handling",
            failed.job_id,
            failed.run_id,
            error,
            exc_info=error,
        )
        self._record_failed_run(failed)

    def _run_job(
        self,
        job_id: str,
        run_id: str,
        simulate: Callable[[_ProgressReport], _RunSave],
        success_message: str = "Simulation completed successfully",
    ) -> None:
        """Run a job's simulation, reporting its progress, then complete the job; or report its cancellation or its failure.

        Each progress report, the 'Starting' one included, is a checkpoint at which a cancelled job stops. The
        completion is made through _Cancellation.complete_unless_cancelled, the one place a job's run is saved: the
        save the simulation returns writes the results of run *run_id*, the run is marked completed, and only then
        is the job reported completed. A cancelled job reports cancelled even if its simulation then raises an
        Exception. Otherwise an Exception the simulation or the completion raises fails the job, and its run is
        recorded failed. An error that is not an Exception, other than _JobCancelled, escapes to
        _fail_job_if_its_runner_raised, which fails the job.
        """
        cancellation = self._cancellation_of(job_id)

        def progress(pct: float, step: str, msg: str) -> None:
            cancellation.checkpoint()
            self._move_job(job_id, _RUNNING_JOB_STATUS, msg, progress_pct=pct, current_step=step)

        def complete(save: _RunSave) -> None:
            save()
            self._storage.mark_run_completed(run_id)
            self._move_job(job_id, _COMPLETED_JOB_STATUS, success_message, progress_pct=100.0, current_step="Done")

        try:
            progress(5.0, "Starting", "Initializing...")
            cancellation.complete_unless_cancelled(functools.partial(complete, simulate(progress)))
        except _JobCancelled:
            self._report_cancelled_job(job_id)
        except Exception as exc:
            if cancellation.is_cancelled:
                self._report_cancelled_job(job_id)
            else:
                self._fail_job(job_id, str(exc))

    def _run_home_simulation(
        self,
        job_id: str,
        run: RunRecord,
        config: HomeConfig,
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> None:
        """Worker function that runs a home simulation in a background thread.

        Delegates lifecycle management to ``_run_job`` and focuses on the
        simulation-specific logic: running the simulation, then returning the
        save of the run from its results through
        RunStorage.save_home_run_from_results, under the name and creation
        time its submit recorded, which _run_job makes, then completes the
        run, under the job's lock.

        Args:
            job_id: Unique job identifier.
            run: The record of the job's run, as its submit created it.
            config: Home configuration for the simulation.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
        """
        start_ref = time.monotonic()

        def simulate(progress: _ProgressReport) -> _RunSave:
            progress(20.0, "Simulating", "Running home simulation...")
            results = self._simulate_home(config, start_date, end_date)

            progress(90.0, "Saving", "Persisting results to storage...")

            def save() -> None:
                self._storage.save_home_run_from_results(
                    run_id=run.id,
                    config=config,
                    results=results,
                    name=run.name,
                    duration_seconds=time.monotonic() - start_ref,
                    created_at=run.created_at,
                )

            return save

        self._run_job(job_id, run.id, simulate, "Simulation completed successfully")

    def _run_fleet_simulation(
        self,
        job_id: str,
        run: RunRecord,
        configs: list[HomeConfig],
        start_date: pd.Timestamp,
        end_date: pd.Timestamp,
    ) -> None:
        """Worker function that runs a fleet simulation in a background thread.

        Delegates lifecycle management to ``_run_job`` and focuses on the
        fleet-specific logic: simulating each home, then returning the save of
        the run from the fleet's results through
        RunStorage.save_fleet_run_from_results, under the name and creation
        time its submit recorded, which _run_job makes, then completes the
        run, under the job's lock.

        Args:
            job_id: Unique job identifier.
            run: The record of the job's run, as its submit created it.
            configs: List of home configurations for the fleet.
            start_date: Start date for the simulation period.
            end_date: End date for the simulation period.
        """
        start_ref = time.monotonic()

        def simulate(progress: _ProgressReport) -> _RunSave:
            total = len(configs)
            per_home_results: list[SimulationResults] = []

            for i, home_config in enumerate(configs):
                pct = (i / total) * 90.0 + 5.0  # 5% to 95%
                progress(pct, f"Home {i + 1}/{total}", f"Simulating home {i + 1} of {total}...")
                per_home_results.append(self._simulate_home(home_config, start_date, end_date))

            progress(97.0, "Saving", "Persisting fleet results...")

            def save() -> None:
                self._storage.save_fleet_run_from_results(
                    run_id=run.id,
                    fleet_results=FleetResults(per_home_results=per_home_results, home_configs=configs),
                    name=run.name,
                    duration_seconds=time.monotonic() - start_ref,
                    created_at=run.created_at,
                )

            return save

        self._run_job(job_id, run.id, simulate, "Fleet simulation completed successfully")
