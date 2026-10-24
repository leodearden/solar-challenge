# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage service for persisting simulation runs to disk and database.

Provides RunStorage class for saving and loading simulation results with:
- the files of each run, in the format solar_challenge.web.stored_runs writes and reads
- SQLite database for run metadata and indexing

Storage structure:
  {data_dir}/runs/{run_id}/   # the run's documents, as stored_runs lays them out for its kind
"""

import json
import logging
import math
import re
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict, TypeVar, assert_never, get_args

from solar_challenge.fleet import FleetResults, FleetSummary, aggregate_home_summaries, calculate_home_summaries
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.web.database import Database, TableSchema, check_one_of, rebuild_table, sql_string_literal
from solar_challenge.web.run_names import require_run_name
from solar_challenge.web.stored_runs import RUN_KINDS, RUN_TYPES, RunKind, RunType, StoredFleetRun, StoredHomeRun, StoredRun
from solar_challenge.web.text_options import one_of

logger = logging.getLogger(__name__)

RunStatus = Literal["running", "completed", "failed"]  # the status of a run, held by the runs table's status column
RUN_STATUSES: tuple[RunStatus, ...] = get_args(RunStatus)
UNFINISHED_RUN_STATUS: RunStatus = "running"

_COLUMN = "column"


def _runs_column(declaration: str) -> dict[str, str]:
    """Metadata of a RunRecord field: its runs column's *declaration*, the type and constraints CREATE TABLE states for it."""
    return {_COLUMN: declaration}


@dataclass(frozen=True)
class RunRecord:
    """One row of the runs table, each column in the field of the same name, whose metadata declares the column.

    config_json and summary_json are the JSON texts a save wrote; None while the run has none.
    type holds one of RUN_TYPES and status one of RUN_STATUSES, each None for NULL; a record
    given another value raises ValueError.
    """

    id: str = field(metadata=_runs_column("TEXT PRIMARY KEY"))
    name: str | None = field(metadata=_runs_column("TEXT"))
    type: RunType | None = field(metadata=_runs_column(f"TEXT {check_one_of('type', RUN_TYPES)}"))
    config_json: str | None = field(metadata=_runs_column("TEXT"))
    summary_json: str | None = field(metadata=_runs_column("TEXT"))
    status: RunStatus | None = field(
        metadata=_runs_column(
            f"TEXT DEFAULT {sql_string_literal(UNFINISHED_RUN_STATUS)} {check_one_of('status', RUN_STATUSES)}"
        )
    )
    error_message: str | None = field(metadata=_runs_column("TEXT"))
    created_at: str | None = field(metadata=_runs_column("TEXT"))
    completed_at: str | None = field(metadata=_runs_column("TEXT"))
    duration_seconds: float | None = field(metadata=_runs_column("REAL"))
    n_homes: int | None = field(metadata=_runs_column("INTEGER DEFAULT 1"))
    notes: str | None = field(metadata=_runs_column("TEXT"))

    def __post_init__(self) -> None:
        if self.type is not None:
            one_of(self.type, RUN_TYPES, "RunRecord.type")
        if self.status is not None:
            one_of(self.status, RUN_STATUSES, "RunRecord.status")

    @property
    def kind(self) -> RunKind:
        """The kind of run the record's type names: its entry in RUN_KINDS.

        Raises:
            ValueError: The record has no type, so it names no kind; the message names its run.
        """
        return _run_kind(self.id, self.type)

    def summary(self) -> SummaryStatistics | FleetSummary | None:
        """The run's summary, decoded from summary_json as its kind's summary_type; None while the run has none.

        Raises:
            ValueError: The record has no type, as RunRecord.kind refuses it, or summary_json does
                not decode as its kind's summary; then the message names the run and
                runs.summary_json, and the decoder's refusal is the cause.
        """
        return _run_summary(self.id, self.type, self.summary_json)

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


def _run_kind(run_id: str, run_type: RunType | None) -> RunKind:
    """The kind of run that *run_type*, run *run_id*'s type, names: its entry in RUN_KINDS.

    Raises:
        ValueError: *run_type* is None, so it names no kind; the message names the run.
    """
    if run_type is None:
        raise ValueError(f"Run {run_id!r} is recorded with no type, so it is of no run kind")
    return RUN_KINDS[run_type]


def _run_summary(
    run_id: str, run_type: RunType | None, summary_json: str | None
) -> SummaryStatistics | FleetSummary | None:
    """Run *run_id*'s summary, decoded from its *summary_json* as the kind *run_type* names decodes it; None while it has none.

    Raises:
        ValueError: As RunRecord.summary() raises.
    """
    if summary_json is None:
        return None
    return _decoded_document(run_id, "summary_json", summary_json, _run_kind(run_id, run_type).summary)


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


def _record_of(row: sqlite3.Row) -> RunRecord:
    """The RunRecord of a runs row read with SELECT *."""
    return RunRecord(**dict(row))


def _record_of_row(row: sqlite3.Row | None) -> RunRecord | None:
    """The RunRecord of a runs row read with SELECT *, or None when no row was read."""
    return None if row is None else _record_of(row)


RUNS_TABLE = TableSchema(
    name="runs",
    columns=tuple((each.name, each.metadata[_COLUMN]) for each in fields(RunRecord)),
    indexes=("CREATE INDEX idx_runs_created_at ON runs(created_at DESC)", "CREATE INDEX idx_runs_type ON runs(type)"),
)
"""The runs table: one column per RunRecord field, in order, as its metadata declares it, and the indexes of the run list's default order and type filter."""


def migrate_runs_table_v1(conn: sqlite3.Connection) -> None:
    """Schema version 1's part for the runs table, run on *conn* inside its migration step's transaction: the table rebuilt to RUNS_TABLE."""
    rebuild_table(conn, RUNS_TABLE)


@dataclass(frozen=True)
class RunHeadline:
    """The figures a run list shows for a run: the energy it generated and the share of that it self-consumed.

    Raises:
        ValueError: A figure is not a finite number, e.g. None, a text, a bool, NaN or an
            infinity; the message names the figure and its value.
    """

    generation_kwh: float
    self_consumption_ratio: float

    def __post_init__(self) -> None:
        _require_finite_number("generation_kwh", self.generation_kwh)
        _require_finite_number("self_consumption_ratio", self.self_consumption_ratio)


def _require_finite_number(figure: str, value: object) -> None:
    """Raise ValueError naming RunHeadline's *figure* and *value* unless *value* is a finite int or float; a bool is neither."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"RunHeadline.{figure} is {value!r}, not a finite number")


def run_headline(summary: SummaryStatistics | FleetSummary) -> RunHeadline:
    """The headline of the run whose summary is *summary*, a home run's or a fleet run's.

    It is the one place the web maps a fleet summary's names, such as fleet_self_consumption_ratio,
    to a run list's (D-S19-8 in docs/prds/run-store-one-owner.md).

    Raises:
        ValueError: The summary's figure for the generation or the ratio is not a finite number,
            as RunHeadline refuses it.
    """
    match summary:
        case SummaryStatistics():
            return RunHeadline(
                generation_kwh=summary.total_generation_kwh, self_consumption_ratio=summary.self_consumption_ratio
            )
        case FleetSummary():
            return RunHeadline(
                generation_kwh=summary.total_generation_kwh, self_consumption_ratio=summary.fleet_self_consumption_ratio
            )
        case _:
            assert_never(summary)


def readable_headline(record: RunRecord) -> RunHeadline | None:
    """The headline a run list shows for *record*'s run; None while it has no summary, or when its summary is damaged.

    A summary is damaged when it does not decode, or run_headline refuses it for a figure that
    is not a finite number. A damaged summary is logged as a warning naming the run, which the
    run lists then show without figures and the dashboard's totals without its generation,
    rather than fail for one damaged run (the G7 waiver in docs/prds/run-store-one-owner.md §15,
    D-S19-9).
    """
    return _readable_headline(record.id, record.type, record.summary_json)


def _readable_headline(run_id: str, run_type: RunType | None, summary_json: str | None) -> RunHeadline | None:
    """readable_headline of run *run_id*, read from the only columns of its row it needs: its type and its summary_json."""
    try:
        summary = _run_summary(run_id, run_type, summary_json)
        return None if summary is None else run_headline(summary)
    except ValueError as damaged:
        logger.warning("Run %r shows no figures, as its summary is damaged: %s", run_id, damaged)
        return None


class HeadlineFigures(TypedDict):
    """The figures a run list's row shows for a run, under the names the History list and the assistant's run list give them; None where it has none."""

    total_generation_kwh: float | None
    self_consumption_ratio: float | None


def headline_figures(record: RunRecord) -> HeadlineFigures:
    """The figures a run list's row shows for *record*'s run: its readable_headline's figures, each None when it has no headline to read."""
    headline = readable_headline(record)
    if headline is None:
        return {"total_generation_kwh": None, "self_consumption_ratio": None}
    return {"total_generation_kwh": headline.generation_kwh, "self_consumption_ratio": headline.self_consumption_ratio}


RunSort =Literal["created_at", "name", "type", "status", "duration_seconds", "n_homes"]  # a runs column a run list sorts by
RUN_SORTS: tuple[RunSort, ...] = get_args(RunSort)

_MAX_RUNS_PER_PAGE = 100


@dataclass(frozen=True)
class RunQuery:
    """A page of the run list: the runs it keeps, the order it sorts them in, and which page of them it is.

    run_type keeps the runs of that type; text the runs whose name or notes hold it, in any ASCII
    case; created_from and created_to the runs created on or after the one date and on or before
    the other. A filter that is None keeps every run. The runs are sorted by the sort column, then
    by id, descending or not, and page numbers from 1 the pages of per_page runs.

    Raises:
        ValueError: sort is not one of RUN_SORTS, run_type is not one of RUN_TYPES, page is below
            1, or per_page is not from 1 to 100; the message names the field and its value.
    """

    run_type: RunType | None = None
    text: str | None = None
    created_from: date | None = None
    created_to: date | None = None
    sort: RunSort = "created_at"
    descending: bool = True
    page: int = 1
    per_page: int = 20

    def __post_init__(self) -> None:
        one_of(self.sort, RUN_SORTS, "sort")
        if self.run_type is not None:
            one_of(self.run_type, RUN_TYPES, "run_type")
        if self.page < 1:
            raise ValueError(f"page is {self.page!r}, not a page number: pages are numbered from 1")
        if not 1 <= self.per_page <= _MAX_RUNS_PER_PAGE:
            raise ValueError(f"per_page is {self.per_page!r}, not from 1 to {_MAX_RUNS_PER_PAGE} runs a page")


@dataclass(frozen=True)
class RunPage:
    """A page of the run list: the records of its runs, in order, and the count of every run the list's query keeps."""

    records: tuple[RunRecord, ...]
    total: int


@dataclass(frozen=True)
class RunTotals:
    """The dashboard's totals: the count of the completed runs, of their homes, and the energy they generated."""

    run_count: int
    home_count: int
    generation_kwh: float


_RUN_QUERY_CONDITION = (
    "(:run_type IS NULL OR type = :run_type)"
    " AND (:text IS NULL OR instr(lower(name), lower(:text)) > 0 OR instr(lower(notes), lower(:text)) > 0)"
    " AND (:created_from IS NULL OR created_at >= :created_from)"
    " AND (:created_before IS NULL OR created_at < :created_before)"
)


def _run_query_values(query: RunQuery) -> dict[str, str | None]:
    """The values _RUN_QUERY_CONDITION binds to keep the runs *query* keeps; None where it keeps every run.

    A run created on created_to is created before the next day starts. The text is found
    anywhere in a name or notes, each character as itself (no % or _ is a wildcard), in any
    ASCII case: SQLite's lower() folds ASCII letters only, as LIKE does.
    """
    return {
        "run_type": query.run_type,
        "text": query.text,
        "created_from": None if query.created_from is None else query.created_from.isoformat(),
        "created_before": None if query.created_to is None else (query.created_to + timedelta(days=1)).isoformat(),
    }


RunLabel = Literal["name", "notes"]  # a label of a run that Run History lets a user edit
RUN_LABELS: tuple[RunLabel, ...] = get_args(RunLabel)


_COLUMNS_A_RESAVE_KEEPS = ("id", "created_at", *RUN_LABELS)

_COMPLETED_RUN_STATUS: RunStatus = "completed"
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
    name: str | None,
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
        completed_at=now if status == _COMPLETED_RUN_STATUS else None,
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
            ValueError: The store refuses *run_id*, *run_type* is not one of RUN_TYPES, or
                *name* cannot name a run, as require_run_name refuses it.
            sqlite3.Error: The database refuses the row, e.g. for an id a run already has.
            Neither leaves anything written.
        """
        self._validate_run_id(run_id)
        record = RunRecord(
            id=run_id,
            name=require_run_name(name),
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
            name: The name the save records a run it records for the first time under, None
                for none. A run already recorded, as a job's submit records it through
                create_run, keeps its name, as a re-save keeps a run's labels.
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
            name=name,
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
            name: The name the save records a run it records for the first time under, None
                for none. A run already recorded, as a job's submit records it through
                create_run, keeps its name, as a re-save keeps a run's labels.
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
            name=name,
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

        A run's name is never NULL or blank, so a name given must be one require_run_name
        returns; notes may be None.

        Returns:
            The run's record as written, or None when no run has that id.

        Raises:
            ValueError: Writing no label, when a key of *labels* is not one of RUN_LABELS, or
                the name given cannot name a run, as require_run_name refuses it.
        """
        unknown = sorted(set(labels) - set(RUN_LABELS))
        if unknown:
            raise ValueError(f"Not run labels: {unknown}; the run labels are {list(RUN_LABELS)}")
        if "name" in labels:
            require_run_name(labels["name"])
        with self.database.transaction() as conn:
            for label, value in labels.items():
                conn.execute(f"UPDATE runs SET {label} = ? WHERE id = ?", (value, run_id))
        return self.run_record(run_id)

    def page_runs(self, query: RunQuery) -> RunPage:
        """The records of the runs on *query*'s page of the run list, in its order, and the count of every run *query* keeps.

        A page past the last lists no runs.
        """
        values = _run_query_values(query)
        direction = "DESC" if query.descending else "ASC"
        order = f"{one_of(query.sort, RUN_SORTS, 'sort')} {direction}, id {direction}"
        with self.database.transaction() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM runs WHERE {_RUN_QUERY_CONDITION}", values).fetchone()[0]
            rows = conn.execute(
                f"SELECT * FROM runs WHERE {_RUN_QUERY_CONDITION} ORDER BY {order} LIMIT :limit OFFSET :offset",
                {**values, "limit": query.per_page, "offset": (query.page - 1) * query.per_page},
            ).fetchall()
        return RunPage(records=tuple(_record_of(row) for row in rows), total=total)

    def totals(self) -> RunTotals:
        """The count of the completed runs and of their homes, and the generation of those whose readable_headline reads.

        A run whose row records no count of homes counts as one home. A run whose summary is
        damaged still counts, with its homes, but adds no generation; readable_headline logs it.
        The generation is read from each run's type and summary alone, never its config.
        """
        completed = {"completed": _COMPLETED_RUN_STATUS}
        with self.database.transaction() as conn:
            run_count, home_count = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(CASE WHEN n_homes > 0 THEN n_homes ELSE 1 END), 0) "
                "FROM runs WHERE status = :completed",
                completed,
            ).fetchone()
            rows = conn.execute(
                "SELECT id, type, summary_json FROM runs WHERE status = :completed AND summary_json IS NOT NULL",
                completed,
            ).fetchall()
        headlines = (_readable_headline(row["id"], row["type"], row["summary_json"]) for row in rows)
        generation_kwh = sum((headline.generation_kwh for headline in headlines if headline is not None), 0.0)
        return RunTotals(run_count=run_count, home_count=home_count, generation_kwh=generation_kwh)

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
