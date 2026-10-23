# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage service for persisting simulation runs to disk and database.

Provides RunStorage class for saving and loading simulation results with:
- the files of each run, in the format solar_challenge.web.stored_runs writes and reads
- SQLite database for run metadata and indexing

Storage structure:
  {data_dir}/runs/{run_id}/   # the run's documents, as stored_runs lays them out for its kind
"""

import json
import re
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, TypeVar, get_args

from solar_challenge.fleet import FleetResults, FleetSummary, aggregate_home_summaries, calculate_home_summaries
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.web.database import RUN_STATUSES, RUN_TYPES, UNFINISHED_RUN_STATUS, Database, RunStatus, RunType
from solar_challenge.web.stored_runs import RUN_KINDS, RunKind, StoredFleetRun, StoredHomeRun, StoredRun


@dataclass(frozen=True)
class RunRecord:
    """One row of the runs table, each column in the field of the same name.

    config_json and summary_json are the JSON texts a save wrote; None while the run has none.
    type holds one of RUN_TYPES and status one of RUN_STATUSES, each None for NULL; a record
    given another value raises ValueError.
    """

    id: str
    name: str | None
    type: RunType | None
    config_json: str | None
    summary_json: str | None
    status: RunStatus | None
    error_message: str | None
    created_at: str | None
    completed_at: str | None
    duration_seconds: float | None
    n_homes: int | None
    notes: str | None

    def __post_init__(self) -> None:
        _require_one_of("type", self.type, RUN_TYPES)
        _require_one_of("status", self.status, RUN_STATUSES)

    @property
    def kind(self) -> RunKind:
        """The kind of run the record's type names: its entry in RUN_KINDS.

        Raises:
            ValueError: The record has no type, so it names no kind; the message names its run.
        """
        if self.type is None:
            raise ValueError(f"Run {self.id!r} is recorded with no type, so it is of no run kind")
        return RUN_KINDS[self.type]

    def summary(self) -> SummaryStatistics | FleetSummary | None:
        """The run's summary, decoded from summary_json as its kind's summary_type; None while the run has none.

        Raises:
            ValueError: The record has no type, as RunRecord.kind refuses it, or summary_json does
                not decode as its kind's summary; then the message names the run and
                runs.summary_json, and the decoder's refusal is the cause.
        """
        if self.summary_json is None:
            return None
        return _decoded_document(self.id, "summary_json", self.summary_json, self.kind.summary)

    def home_configs(self) -> tuple[HomeConfig, ...] | None:
        """Each home's HomeConfig, in order, decoded from config_json as the run's kind decodes it; None while the run has none.

        Raises:
            ValueError: The record has no type, as RunRecord.kind refuses it, or config_json does
                not decode as its kind's config; then the message names the run and
                runs.config_json, and the decoder's refusal is the cause.
        """
        if self.config_json is None:
            return None
        return _decoded_document(self.id, "config_json", self.config_json, self.kind.home_configs)

    def decoded_config(self) -> Any:
        """The value config_json encodes; {} when the run has no config text or it is not JSON."""
        return _decoded_or_empty(self.config_json)

    def decoded_summary(self) -> Any:
        """The value summary_json encodes; {} when the run has no summary text or it is not JSON."""
        return _decoded_or_empty(self.summary_json)


def _require_one_of(field_name: str, value: str | None, allowed: tuple[str, ...]) -> None:
    """Raise ValueError naming RunRecord's field *field_name* unless *value* is None or one of *allowed*."""
    if value is not None and value not in allowed:
        raise ValueError(f"RunRecord.{field_name} is {value!r}, not one of {list(allowed)} or None")


_DocumentColumn = Literal["config_json", "summary_json"]  # a runs column holding the JSON text of a stored document
_Decoded = TypeVar("_Decoded")


def _decoded_document(
    run_id: str, column: _DocumentColumn, text: str, decode: Callable[[Mapping[str, Any]], _Decoded]
) -> _Decoded:
    """What *decode* reads from the document JSON *text* holds, run *run_id*'s runs.*column*.

    Raises:
        ValueError: *text* is not JSON, or *decode* refuses the document it holds; the message
            names the run and the column, and the refusal is the cause.
    """
    try:
        return decode(json.loads(text))
    except (ValueError, TypeError, KeyError, AttributeError) as refusal:
        raise ValueError(
            f"The runs.{column} of run {run_id!r} is not a document its kind decodes: {type(refusal).__name__}: {refusal}"
        ) from refusal


def _decoded_or_empty(text: str | None) -> Any:
    """The value JSON *text* encodes; {} when *text* is None, empty or not JSON."""
    if not text:
        return {}
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {}


def _record_of_row(row: sqlite3.Row | None) -> RunRecord | None:
    """The RunRecord of a runs row read with SELECT *, or None when no row was read."""
    return None if row is None else RunRecord(**dict(row))


RunLabel = Literal["name", "notes"]  # a label of a run that Run History lets a user edit
RUN_LABELS: tuple[RunLabel, ...] = get_args(RunLabel)


_COLUMNS_A_RESAVE_KEEPS = ("id", "created_at", *RUN_LABELS)

_FAILED_RUN_STATUS: RunStatus = "failed"
_INTERRUPTED_BY_RESTART_MESSAGE = "Interrupted by server restart"


def _run_row_insert() -> str:
    """The statement inserting a RunRecord, bound by field name, as a new runs row; an id a run already has fails it."""
    columns = [field.name for field in fields(RunRecord)]
    column_list = ", ".join(columns)
    placeholders = ", ".join(f":{column}" for column in columns)
    return f"INSERT INTO runs ({column_list}) VALUES ({placeholders})"


def _run_row_upsert() -> str:
    """The statement writing a RunRecord, bound by field name, as the runs row under its id.

    It inserts as _run_row_insert's statement does, except that a row already under that id
    keeps the columns _COLUMNS_A_RESAVE_KEEPS names and takes every other column from the record.
    """
    rewritten = [field.name for field in fields(RunRecord) if field.name not in _COLUMNS_A_RESAVE_KEEPS]
    assignments = ", ".join(f"{column} = excluded.{column}" for column in rewritten)
    return f"{_run_row_insert()} ON CONFLICT(id) DO UPDATE SET {assignments}"


_RUN_ROW_INSERT = _run_row_insert()
_RUN_ROW_UPSERT = _run_row_upsert()


def _now() -> str:
    """The time now, as the ISO 8601 UTC text a runs row records its times in."""
    return datetime.now(timezone.utc).isoformat()


def _saved_run_row(
    *,
    run_id: str,
    name: str,
    run_type: RunType,
    config: dict[str, Any],
    summary: dict[str, Any],
    status: RunStatus,
    error_message: str | None,
    created_at: str | None,
    duration_seconds: float | None,
    n_homes: int,
) -> RunRecord:
    """The runs row a save writes for the run it stored under *run_id*, its config and summary as JSON text.

    The run is created now unless *created_at* is given, is completed now if its *status* is
    completed, and has no notes. Now is one time, read once: a run created and completed by the
    same save has the same time for both.

    Raises:
        ValueError: *status* is not one of RUN_STATUSES, as RunRecord refuses it.
    """
    now = _now()
    return RunRecord(
        id=run_id,
        name=name,
        type=run_type,
        config_json=json.dumps(config),
        summary_json=json.dumps(summary),
        status=status,
        error_message=error_message,
        created_at=now if created_at is None else created_at,
        completed_at=now if status == "completed" else None,
        duration_seconds=duration_seconds,
        n_homes=n_homes,
        notes=None,
    )


class RunStorage:
    """Storage service for simulation runs.

    Manages persistence of simulation results to filesystem and SQLite database.

    Attributes:
        database: The Database holding the runs table
        data_dir: Root directory for run data files
    """

    def __init__(self, database: Database, data_dir: str | Path):
        """Initialize storage service.

        Args:
            database: The Database holding the runs table
            data_dir: Root directory for storing run data
        """
        self.database = database
        self.data_dir = Path(data_dir)

    def _validate_run_id(self, run_id: str) -> None:
        """Validate run_id to prevent path traversal attacks.

        Args:
            run_id: Run identifier to validate

        Raises:
            ValueError: If run_id contains invalid characters or resolves
                outside the runs directory
        """
        if not re.fullmatch(r"[a-zA-Z0-9_-]+", run_id):
            raise ValueError(
                f"Invalid run_id: {run_id!r}. "
                "Only alphanumeric characters, hyphens, and underscores are allowed."
            )
        runs_dir = (self.data_dir / "runs").resolve()
        resolved = (runs_dir / run_id).resolve()
        if not resolved.parent == runs_dir:
            raise ValueError(
                f"Invalid run_id: {run_id!r}. "
                "Resolved path is outside the runs directory."
            )

    def _get_run_dir(self, run_id: str) -> Path:
        """Get the directory path for a run's data files.

        Args:
            run_id: Unique run identifier

        Returns:
            Path to run directory

        Raises:
            ValueError: If run_id is invalid or would escape the runs directory
        """
        self._validate_run_id(run_id)
        return self.data_dir / "runs" / run_id

    def _stored_run_dir(self, run_id: str) -> Path:
        """The directory holding the files of the run stored under *run_id*.

        Raises:
            FileNotFoundError: No run is stored under *run_id*: the store refuses the id, so
                no save can have written one (the refusal is the cause), or no directory holds it.
        """
        try:
            run_dir = self._get_run_dir(run_id)
        except ValueError as refusal:
            raise FileNotFoundError(f"No run is stored under {run_id!r}: {refusal}") from refusal
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir

    def _upsert_run_row(self, row: RunRecord) -> None:
        """Write *row* as the runs row under row.id.

        A row already under that id keeps the columns _COLUMNS_A_RESAVE_KEEPS names, among
        them RUN_LABELS, the labels a user edits in Run History: a run renamed while its job
        runs keeps the new name when the job's save rewrites its row.
        """
        with self.database.transaction() as conn:
            conn.execute(_RUN_ROW_UPSERT, asdict(row))

    def create_run(self, run_id: str, *, run_type: RunType, name: str, n_homes: int, created_at: str) -> RunRecord:
        """Record a new run under *run_id*, running, as a job's submit records it before its simulation is queued.

        The run has the *run_type*, *name*, *n_homes* and *created_at* given and no other column:
        no config, summary, error, completion time, duration or notes. It writes no file; the save
        of the job's results writes the run's files and completes its row.

        Returns:
            The run's record as written.

        Raises:
            ValueError: The store refuses *run_id*, or *run_type* is not one of RUN_TYPES.
            sqlite3.Error: The database refuses the row, e.g. for an id a run already has.
            Neither leaves anything written.
        """
        self._validate_run_id(run_id)
        record = RunRecord(
            id=run_id,
            name=name,
            type=run_type,
            config_json=None,
            summary_json=None,
            status=UNFINISHED_RUN_STATUS,
            error_message=None,
            created_at=created_at,
            completed_at=None,
            duration_seconds=None,
            n_homes=n_homes,
            notes=None,
        )
        with self.database.transaction() as conn:
            conn.execute(_RUN_ROW_INSERT, asdict(record))
        return record

    def mark_run_failed(self, run_id: str, message: str) -> None:
        """Record that run *run_id* failed with *message*: failed, with *message* as its error, completed now.

        The run is marked failed whatever its status. When no run has that id, nothing is written.
        """
        self._fail_runs("id = :run_id", {"run_id": run_id}, message)

    def fail_interrupted_runs(self) -> int:
        """Mark every running run failed, as mark_run_failed marks one, with the message "Interrupted by server restart".

        A server calls it when it starts, before it runs any job, so each running run is one whose
        job an earlier server was running when it stopped.

        Returns:
            The number of runs it marked failed.
        """
        return self._fail_runs(
            "status = :unfinished_status", {"unfinished_status": UNFINISHED_RUN_STATUS}, _INTERRUPTED_BY_RESTART_MESSAGE
        )

    def _fail_runs(self, condition: str, condition_values: Mapping[str, str], message: str) -> int:
        """Mark failed, with *message* as its error and completed now, each run whose row matches the SQL *condition*.

        *condition* binds by name the values *condition_values* holds.

        Returns:
            The number of runs it marked failed.
        """
        with self.database.transaction() as conn:
            cursor = conn.execute(
                "UPDATE runs SET status = :failed_status, error_message = :message, completed_at = :completed_at "
                f"WHERE {condition}",
                {**condition_values, "failed_status": _FAILED_RUN_STATUS, "message": message, "completed_at": _now()},
            )
            return cursor.rowcount

    def save_home_run(
        self,
        run_id: str,
        config: HomeConfig,
        results: SimulationResults,
        summary: SummaryStatistics,
        name: str | None = None,
        status: RunStatus = "completed",
        error_message: str | None = None,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a home simulation run to storage.

        Creates directory structure, serializes config and summary to JSON,
        saves time series to parquet, and upserts metadata into database. A run
        already stored under run_id keeps the columns of its runs row that
        _upsert_run_row keeps.

        Args:
            run_id: Unique run identifier
            config: Home configuration
            results: Simulation results with time series
            summary: Summary statistics
            name: Optional run name (defaults to config.name)
            status: Run status
            error_message: Optional error message for failed runs
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.

        Raises:
            ValueError: If the store refuses run_id, or status is not one of RUN_STATUSES.
                The save has written nothing then.
        """
        run_dir = self._get_run_dir(run_id)
        stored = StoredHomeRun(run_id=run_id, config=config, results=results, summary=summary)
        config_document = stored.config_document()
        summary_document = stored.summary_document()
        # Build the row first, so a save RunRecord refuses has written no file.
        row = _saved_run_row(
            run_id=run_id,
            name=name or config.name or "Unnamed Run",
            run_type="home",
            config=config_document,
            summary=summary_document,
            status=status,
            error_message=error_message,
            created_at=created_at,
            duration_seconds=duration_seconds,
            n_homes=1,
        )
        stored.write(run_dir, config_document, summary_document)
        self._upsert_run_row(row)

    def save_home_run_from_results(
        self,
        run_id: str,
        config: HomeConfig,
        results: SimulationResults,
        *,
        name: str | None = None,
        status: RunStatus = "completed",
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a home run as save_home_run does, with the summary calculate_summary derives from *results*.

        This is the save a finished home job makes. It raises as save_home_run raises.
        """
        self.save_home_run(
            run_id,
            config,
            results,
            calculate_summary(results),
            name=name,
            status=status,
            duration_seconds=duration_seconds,
            created_at=created_at,
        )

    def save_fleet_run(
        self,
        run_id: str,
        fleet_results: FleetResults,
        fleet_summary: FleetSummary,
        per_home_summaries: list[SummaryStatistics],
        name: str | None = None,
        status: RunStatus = "completed",
        error_message: str | None = None,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a fleet simulation run to storage.

        Creates directory structure with homes/ subdirectory, saves per-home
        parquet files, fleet summary JSON, and fleet config JSON. A run already
        stored under run_id keeps the columns of its runs row that _upsert_run_row
        keeps.

        Args:
            run_id: Unique run identifier
            fleet_results: Fleet simulation results with per-home data
            fleet_summary: Fleet-level summary statistics
            per_home_summaries: List of SummaryStatistics for each home
            name: Optional run name
            status: Run status
            error_message: Optional error message for failed runs
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.

        Raises:
            ValueError: If the store refuses run_id, per_home_summaries does not hold one
                summary per home's results, or status is not one of RUN_STATUSES. The save
                has written nothing then.
        """
        run_dir = self._get_run_dir(run_id)
        stored = StoredFleetRun(
            run_id=run_id,
            fleet_results=fleet_results,
            summary=fleet_summary,
            home_summaries=tuple(per_home_summaries),
        )
        config_document = stored.config_document()
        summary_document = stored.summary_document()
        # Build the row first, so a save RunRecord refuses has written no file.
        row = _saved_run_row(
            run_id=run_id,
            name=name or "Unnamed Fleet Run",
            run_type="fleet",
            config=config_document,
            summary=summary_document,
            status=status,
            error_message=error_message,
            created_at=created_at,
            duration_seconds=duration_seconds,
            n_homes=len(fleet_results.home_configs),
        )
        stored.write(run_dir, config_document, summary_document)
        self._upsert_run_row(row)

    def save_fleet_run_from_results(
        self,
        run_id: str,
        fleet_results: FleetResults,
        *,
        name: str | None = None,
        status: RunStatus = "completed",
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a fleet run as save_fleet_run does, with each home's summary and the fleet summary aggregated from them.

        Each summary is derived once from *fleet_results*. This is the save a finished
        fleet job makes.

        Raises:
            ValueError: If fleet_results has no homes, or its home_configs does not hold one
                HomeConfig per home's results; the save has written nothing then. Otherwise
                as save_fleet_run raises.
        """
        home_summaries = calculate_home_summaries(fleet_results)
        self.save_fleet_run(
            run_id,
            fleet_results,
            aggregate_home_summaries(home_summaries),
            home_summaries,
            name=name,
            status=status,
            duration_seconds=duration_seconds,
            created_at=created_at,
        )

    def load_run(self, run_id: str) -> StoredRun:
        """The run stored under *run_id*, read from its directory as its record's kind reads it.

        Raises:
            FileNotFoundError: No run is stored under *run_id*: the store refuses the id (the
                refusal is the cause), no directory holds it, no run is recorded under it, its
                record names no run kind (RunRecord.kind's refusal is the cause), or a document
                its kind reads is missing. The message names the id.
            ValueError: A stored document is corrupted or incomplete.
        """
        run_dir = self._stored_run_dir(run_id)
        record = self.run_record(run_id)
        if record is None:
            raise FileNotFoundError(f"No run is recorded under {run_id!r}")
        try:
            kind = record.kind
        except ValueError as no_kind:
            raise FileNotFoundError(f"No run kind reads the files of run {run_id!r}: {no_kind}") from no_kind
        return kind.read(run_dir, run_id)

    def run_record(self, run_id: str) -> RunRecord | None:
        """The record of run *run_id*: its row in the runs table. None when no run has that id."""
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _record_of_row(row)

    def run_name(self, run_id: str) -> str | None:
        """The name run *run_id* is saved under, the one Run History lists and renames.

        None when no run has that id, or its name is NULL.
        """
        record = self.run_record(run_id)
        return None if record is None else record.name

    def latest_run_named(self, name: str) -> RunRecord | None:
        """The run named *name* that was created last. None when no run has that name."""
        with self.database.transaction() as conn:
            row = conn.execute(
                "SELECT * FROM runs WHERE name = ? ORDER BY created_at DESC LIMIT 1", (name,)
            ).fetchone()
        return _record_of_row(row)

    def update_run_labels(
        self, run_id: str, labels: Mapping[RunLabel, str | None]
    ) -> RunRecord | None:
        """Write each of *labels* to run *run_id*, None as NULL; a label not in *labels* keeps its value.

        Returns:
            The run's record as written, or None when no run has that id.

        Raises:
            ValueError: Writing nothing, when a key of *labels* is not one of RUN_LABELS.
        """
        unknown = sorted(set(labels) - set(RUN_LABELS))
        if unknown:
            raise ValueError(f"Not run labels: {unknown}; the run labels are {list(RUN_LABELS)}")
        with self.database.transaction() as conn:
            for label, value in labels.items():
                conn.execute(f"UPDATE runs SET {label} = ? WHERE id = ?", (value, run_id))
        return self.run_record(run_id)

    def list_runs(
        self,
        run_type: RunType | None = None,
        status: RunStatus | None = None,
        limit: int | None = None,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List simulation runs with optional filtering.

        Queries SQLite database for run metadata with optional filters.

        Args:
            run_type: Filter by run type, None for all
            status: Filter by status, None for all
            limit: Maximum number of results to return, None for all
            offset: Number of results to skip (for pagination)

        Returns:
            List of run metadata dictionaries with keys matching the database schema
        """
        with self.database.transaction() as conn:
            cursor = conn.cursor()

            # Build query with optional filters
            query = "SELECT * FROM runs WHERE 1=1"
            params: list[Any] = []

            if run_type is not None:
                query += " AND type = ?"
                params.append(run_type)

            if status is not None:
                query += " AND status = ?"
                params.append(status)

            # Order by created_at descending (most recent first)
            query += " ORDER BY created_at DESC"

            # Add limit and offset
            if limit is not None:
                query += " LIMIT ?"
                params.append(limit)

            if offset > 0:
                if limit is None:
                    query += " LIMIT -1"
                query += " OFFSET ?"
                params.append(offset)

            cursor.execute(query, params)
            rows = cursor.fetchall()

            # Convert Row objects to dictionaries
            return [dict(row) for row in rows]

    def delete_run(self, run_id: str) -> None:
        """Delete a simulation run from storage.

        Removes the database row and all associated files, whichever exist: a delete
        of an id that has neither changes nothing.

        Args:
            run_id: Unique run identifier

        Raises:
            ValueError: If the store refuses run_id. No run can be saved under a refused
                id, so a delete under one is a caller bug.
        """
        run_dir = self._get_run_dir(run_id)

        # Delete from database first
        with self.database.transaction() as conn:
            conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))

        # Delete run directory and all files
        if run_dir.exists():
            shutil.rmtree(run_dir)
