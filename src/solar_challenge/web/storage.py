# SPDX-License-Identifier: AGPL-3.0-or-later
"""Storage service for persisting simulation runs to disk and database.

Provides RunStorage class for saving and loading simulation results with:
- the files of each run, in the format solar_challenge.web.stored_runs writes and reads
- SQLite database for run metadata and indexing

Storage structure:
  {data_dir}/runs/{run_id}/   # the run's documents, as stored_runs lays them out for its kind

A save writes the run's documents, then its format.json, then its runs row.

Only the lifecycle methods write a run's status: create_run records a run 'running', and
mark_run_completed, mark_run_failed and fail_interrupted_runs move it on, each from 'running'
only. mark_run_completed and mark_run_failed refuse a run in any other status with
RunStatusConflict, and fail_interrupted_runs leaves it as it was
(docs/prds/job-events-and-sse-framing.md §3.4).

The runs table's part of each schema step is here too: migrate_runs_table_v1 for version 1,
and for a step carrying a run-document step, migrate_stored_run_files, which brings every
stored run's files forward before the step's transaction, and migrate_runs_table_documents,
which brings the copies in each runs row forward inside it.
"""

import json
import logging
import math
import re
import shutil
import sqlite3
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, TypedDict, assert_never, get_args

from solar_challenge.fleet import FleetResults, FleetSummary, aggregate_home_summaries, calculate_home_summaries
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics, calculate_summary
from solar_challenge.web.database import Database, RowRefused, TableSchema, check_one_of, rebuild_table, sql_string_literal
from solar_challenge.web.run_names import is_run_name, require_run_name
from solar_challenge.web.stored_runs import (
    RUN_KINDS,
    RUN_TYPES,
    DroppedValue,
    RunDocumentStep,
    RunKind,
    RunType,
    StoredDocument,
    StoredFleetRun,
    StoredHomeRun,
    StoredRun,
    StoredRunDocuments,
    StoredRunUnreadable,
    UnmigratedRun,
    documents_in_current_format,
    read_run_documents,
    step_run_documents,
    write_run_documents,
)
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
    given another value raises ValueError. A run's name is never NULL or blank (contract C7):
    a record given a name require_run_name refuses raises its ValueError.
    """

    id: str = field(metadata=_runs_column("TEXT PRIMARY KEY"))
    name: str = field(metadata=_runs_column("TEXT NOT NULL"))
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
        require_run_name(self.name)
        if self.type is not None:
            one_of(self.type, RUN_TYPES, "RunRecord.type")
        if self.status is not None:
            one_of(self.status, RUN_STATUSES, "RunRecord.status")

    @property
    def kind(self) -> RunKind:
        """The kind of run the record's type names: its entry in RUN_KINDS.

        Raises:
            StoredRunUnreadable: The record has no type, so its run is of no run kind; the
                document is runs.type.
        """
        return _run_kind(self.id, self.type)

    def summary(self) -> SummaryStatistics | FleetSummary | None:
        """The run's summary, read from summary_json as its kind's summary_type; None while the run has none.

        Raises:
            StoredRunUnreadable: The record has no type, as RunRecord.kind refuses it, or
                summary_json is not the field tree of its kind's summary, as StoredDocument.read
                refuses it; the document is then runs.summary_json.
        """
        return _run_summary(self.id, self.type, self.summary_json)

    def home_configs(self) -> tuple[HomeConfig, ...] | None:
        """Each home's HomeConfig, in order, read from config_json as the run's kind reads it; None while the run has none.

        Raises:
            StoredRunUnreadable: The record has no type, as RunRecord.kind refuses it, or
                config_json is not the field tree of its kind's config, as StoredDocument.read
                refuses it; the document is then runs.config_json.
        """
        if self.config_json is None:
            return None
        return self.kind.home_configs(_row_document(self.id, "config_json", self.config_json))


def _run_kind(run_id: str, run_type: RunType | None) -> RunKind:
    """The kind of run that *run_type*, run *run_id*'s type, names: its entry in RUN_KINDS.

    Raises:
        StoredRunUnreadable: *run_type* is None, as _run_type refuses it.
    """
    return RUN_KINDS[_run_type(run_id, run_type)]


def _run_type(run_id: str, run_type: RunType | None) -> RunType:
    """*run_type*, run *run_id*'s type, which a stored run needs to be read as a run of a kind.

    Raises:
        StoredRunUnreadable: *run_type* is None, so the run is of no run kind; the document is runs.type.
    """
    if run_type is None:
        raise StoredRunUnreadable(run_id, "runs.type", None, "is NULL, so the run is of no run kind")
    return run_type


def _run_summary(
    run_id: str, run_type: RunType | None, summary_json: str | None
) -> SummaryStatistics | FleetSummary | None:
    """Run *run_id*'s summary, read from its *summary_json* as the kind *run_type* names reads it; None while it has none.

    Raises:
        StoredRunUnreadable: As RunRecord.summary() raises.
    """
    if summary_json is None:
        return None
    return _run_kind(run_id, run_type).summary(_row_document(run_id, "summary_json", summary_json))


_DocumentColumn = Literal["config_json", "summary_json"]  # a runs column holding the JSON text of a stored document


def _row_document(run_id: str, column: _DocumentColumn, text: str | None) -> StoredDocument:
    """The document runs.*column* of run *run_id*, whose JSON text is *text*; its content is None when *text* is.

    Raises:
        StoredRunUnreadable: *text* is not JSON; the document is runs.*column* and the field None.
    """
    name = f"runs.{column}"
    return StoredDocument(run_id, name, None) if text is None else StoredDocument.decoded(run_id, name, text)


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
"""The runs table this code reads and writes, which a new store creates: one column per RunRecord field, in order, as its metadata declares it, and the indexes of the run list's default order and type filter."""

_RUN_TYPES_V1: tuple[RunType, ...] = ("home", "fleet")
"""The run types the runs table admits at schema version 1."""

_RUNS_TABLE_V1 = TableSchema(
    name="runs",
    columns=(
        ("id", "TEXT PRIMARY KEY"),
        ("name", "TEXT NOT NULL"),
        ("type", f"TEXT {check_one_of('type', _RUN_TYPES_V1)}"),
        ("config_json", "TEXT"),
        ("summary_json", "TEXT"),
        ("status", "TEXT DEFAULT 'running' CHECK(status IN ('running', 'completed', 'failed'))"),
        ("error_message", "TEXT"),
        ("created_at", "TEXT"),
        ("completed_at", "TEXT"),
        ("duration_seconds", "REAL"),
        ("n_homes", "INTEGER DEFAULT 1"),
        ("notes", "TEXT"),
    ),
    indexes=("CREATE INDEX idx_runs_created_at ON runs(created_at DESC)", "CREATE INDEX idx_runs_type ON runs(type)"),
)
"""The runs table at schema version 1, as tests/fixtures/databases/schema_v1.sql holds it, whatever RunRecord declares since."""


def migrate_runs_table_v1(conn: sqlite3.Connection) -> None:
    """Schema version 1's part for the runs table, run on *conn* inside its migration step's transaction.

    Every row is first checked against the two constraints version 1 adds to the table, since
    the database's own refusal would name no row. Each run whose name cannot name a run, NULL
    or blank, is then named as a job given no name creates its run (contract C7): its kind's
    default_name of the homes its config holds. The table is then rebuilt to its schema at
    version 1, whose name column is NOT NULL. A legacy runs table already held every other
    constraint of that schema, so no other row can be refused.

    Raises:
        RowRefused: Before anything is written, for a run whose type is neither NULL nor one of
            the run types version 1 admits, as 'sweep' was once, or whose name cannot name a run
            while it has no type to take a default name from.
    """
    rows = conn.execute("SELECT id, name, type, config_json FROM runs").fetchall()
    for row in rows:
        _require_version_1_keeps(row["id"], row["type"], row["name"])
    for row in rows:
        if not is_run_name(row["name"]):
            name = _name_of_a_run_given_none(row["id"], row["type"], row["config_json"])
            conn.execute("UPDATE runs SET name = ? WHERE id = ?", (name, row["id"]))
    rebuild_table(conn, _RUNS_TABLE_V1)


def _require_version_1_keeps(run_id: str, run_type: object, name: object) -> None:
    """Check that schema version 1's runs table can keep run *run_id* of *run_type* named *name*, once each nameless run of a type is named.

    Raises:
        RowRefused: *run_type* is neither None nor one of the run types version 1 admits, the
            reason being one_of's refusal, from which it is raised; or *name* cannot name a run
            and *run_type* is None.
    """
    if run_type is not None:
        try:
            one_of(run_type, _RUN_TYPES_V1, "value")
        except ValueError as refusal:
            raise RowRefused("runs", run_id, "type", str(refusal)) from refusal
    elif not is_run_name(name):
        raise RowRefused("runs", run_id, "name", "is NULL or blank, and the run has no type to take a default name from")


def _name_of_a_run_given_none(run_id: str, run_type: RunType, config_json: str | None) -> str:
    """The name a job given none would have created run *run_id* under: the default_name of *run_type*'s kind for the homes *config_json* holds.

    The legacy config is read as the stored-run format reads it once migrated, every
    run-document step brought to bear on it in memory first. A run with no config is named as a
    run of no homes, and so is one whose config cannot be read as its kind's even so, with a
    logged warning naming the run and the refusal: the name is a label its user can rename, so a
    damaged config does not keep the store from migrating.
    """
    kind = RUN_KINDS[run_type]
    homes: tuple[HomeConfig, ...] = ()
    if config_json is not None:
        try:
            legacy = StoredRunDocuments(
                config=_row_document(run_id, "config_json", config_json),
                summary=_row_document(run_id, "summary_json", None),
            )
            homes = kind.home_configs(documents_in_current_format(run_type, legacy).config)
        except StoredRunUnreadable as refusal:
            logger.warning("Run %r is named as a run of no homes, as its config cannot be read: %s", run_id, refusal)
    return kind.default_name(homes)


def _run_dir(data_dir: Path, run_id: str) -> Path:
    """The directory of the files of run *run_id* in the store whose data directory is *data_dir*: {data_dir}/runs/{run_id}.

    Raises:
        ValueError: No run can be stored under *run_id*, to keep a path from leaving the runs
            directory: it holds a character other than a letter, digit, hyphen or underscore, or
            resolves outside the runs directory.
    """
    if not re.fullmatch(r"[a-zA-Z0-9_-]+", run_id):
        raise ValueError(
            f"Invalid run_id: {run_id!r}. Only alphanumeric characters, hyphens, and underscores are allowed."
        )
    runs_dir = (data_dir / "runs").resolve()
    if (runs_dir / run_id).resolve().parent != runs_dir:
        raise ValueError(f"Invalid run_id: {run_id!r}. Resolved path is outside the runs directory.")
    return data_dir / "runs" / run_id


@dataclass(frozen=True)
class RunDocumentsOutcome:
    """What a run-document step did to a store's runs: each value it dropped that is not null, and each run it left unmigrated, in order."""

    dropped: tuple[DroppedValue, ...] = ()
    unmigrated: tuple[UnmigratedRun, ...] = ()

    def __add__(self, later: "RunDocumentsOutcome") -> "RunDocumentsOutcome":
        """This outcome followed by *later*'s."""
        return RunDocumentsOutcome(self.dropped + later.dropped, self.unmigrated + later.unmigrated)


def migrate_stored_run_files(database: Database, data_dir: Path, step: RunDocumentStep) -> RunDocumentsOutcome:
    """Bring the files of each run the runs table of *database* records forward by *step*, the run-file part of the schema step carrying it.

    A run with no directory under *data_dir* is skipped, and so is a directory no row records.
    Each run's JSON documents are read as its kind lays them out and brought forward as
    step_run_documents brings them; then only the documents the step changed are rewritten, and
    format.json naming step.version last. A run whose documents cannot be read or brought
    forward, or whose row has no type, is left as it was and reported as unmigrated. A run's
    time series are not read: they have no format version, so a run whose time series is
    damaged is brought forward as any other is, and refused naming it when it is loaded. The
    writes are idempotent, so a migration stopped part way through runs again from the start.

    Raises:
        sqlite3.Error: The runs table cannot be read; nothing has been written.
        OSError: A run's file cannot be written, e.g. on a full disk, or its directory cannot
            be looked for; the runs before it have been brought forward, and so may some of its
            documents have been, each whole.
    """
    with database.transaction() as conn:
        rows = conn.execute("SELECT id, type FROM runs ORDER BY id").fetchall()
    outcome = RunDocumentsOutcome()
    for row in rows:
        run_dir = _existing_run_dir(data_dir, row["id"])
        if run_dir is not None:
            outcome += _migrate_run_files(run_dir, row["id"], row["type"], step)
    return outcome


def _existing_run_dir(data_dir: Path, run_id: str) -> Path | None:
    """The directory of run *run_id*'s files under *data_dir*; None when no directory holds them, or no run can be stored under the id."""
    try:
        run_dir = _run_dir(data_dir, run_id)
    except ValueError:
        return None
    return run_dir if run_dir.is_dir() else None


def _migrate_run_files(run_dir: Path, run_id: str, run_type: RunType | None, step: RunDocumentStep) -> RunDocumentsOutcome:
    """Bring the files of run *run_id* of *run_type*, which *run_dir* holds, forward by *step*, as migrate_stored_run_files does for each run."""
    try:
        typed = _run_type(run_id, run_type)
        documents = read_run_documents(run_dir, run_id, typed)
        result = step_run_documents(step, typed, documents)
    except StoredRunUnreadable as refusal:
        return RunDocumentsOutcome(unmigrated=(UnmigratedRun.of(refusal),))
    write_run_documents(run_dir, result.documents.changed_from(documents), step.version)
    return RunDocumentsOutcome(dropped=result.dropped)


_DOCUMENT_COLUMNS: tuple[_DocumentColumn, ...] = ("config_json", "summary_json")


def migrate_runs_table_documents(conn: sqlite3.Connection, step: RunDocumentStep) -> RunDocumentsOutcome:
    """The runs table's part of the schema step carrying *step*, run on *conn* inside that step's transaction.

    Each run's runs.config_json and runs.summary_json are brought forward as
    step_run_documents brings them, and only a column the step changed is rewritten, as the
    JSON text a save writes. A row that holds neither document is skipped. A row whose
    documents cannot be brought forward, or that has no type, is left as it was and reported as
    unmigrated.
    """
    rows = conn.execute("SELECT id, type, config_json, summary_json FROM runs ORDER BY id").fetchall()
    outcome = RunDocumentsOutcome()
    for row in rows:
        if row["config_json"] is not None or row["summary_json"] is not None:
            outcome += _migrate_runs_row(conn, row, step)
    return outcome


def _migrate_runs_row(conn: sqlite3.Connection, row: sqlite3.Row, step: RunDocumentStep) -> RunDocumentsOutcome:
    """Bring the documents of *row*, a runs row read with its id, type, config_json and summary_json, forward by *step*, as migrate_runs_table_documents does for each row."""
    run_id = row["id"]
    try:
        typed = _run_type(run_id, row["type"])
        documents = StoredRunDocuments(
            config=_row_document(run_id, "config_json", row["config_json"]),
            summary=_row_document(run_id, "summary_json", row["summary_json"]),
        )
        result = step_run_documents(step, typed, documents)
    except StoredRunUnreadable as refusal:
        return RunDocumentsOutcome(unmigrated=(UnmigratedRun.of(refusal),))
    stepped = (result.documents.config, result.documents.summary)
    for column, was, document in zip(_DOCUMENT_COLUMNS, (documents.config, documents.summary), stepped, strict=True):
        if document.content != was.content:
            conn.execute(f"UPDATE runs SET {column} = ? WHERE id = ?", (json.dumps(document.content), run_id))
    return RunDocumentsOutcome(dropped=result.dropped)


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


def _read_headline(
    run_id: str, run_type: RunType | None, summary_json: str | None
) -> RunHeadline | StoredRunUnreadable | None:
    """What a run list reads of run *run_id* from the only columns of its row it needs, its type and its summary_json.

    That is the run's headline; the refusal of its summary, when that cannot be read; or None,
    while it has no summary, or when run_headline refuses it for a figure that is not a finite
    number. A summary that cannot be read or that run_headline refuses is damaged, and is logged
    as a warning naming the run, which the run lists then show without figures and the
    dashboard's totals without its generation, rather than fail for one damaged run (the G7
    waiver in docs/prds/run-store-one-owner.md §15, D-S19-9).
    """
    try:
        summary = _run_summary(run_id, run_type, summary_json)
    except StoredRunUnreadable as unreadable:
        logger.warning("Run %r shows no figures, as its summary cannot be read: %s", run_id, unreadable)
        return unreadable
    if summary is None:
        return None
    try:
        return run_headline(summary)
    except ValueError as refusal:
        logger.warning("Run %r shows no figures, as its summary's headline is damaged: %s", run_id, refusal)
        return None


class HeadlineFigures(TypedDict):
    """The figures a run list's row shows for a run, under the names the History list and the assistant's run list give them; None where it has none.

    unreadable is the message of the StoredRunUnreadable refusing the run's summary, naming the
    run, the document and the field, when the summary cannot be read; None when it can be, or
    the run has none.
    """

    total_generation_kwh: float | None
    self_consumption_ratio: float | None
    unreadable: str | None


def headline_figures(record: RunRecord) -> HeadlineFigures:
    """The figures a run list's row shows for *record*'s run: its headline's figures, each None when _read_headline reads it no headline, and why its summary cannot be read, if it cannot."""
    headline = _read_headline(record.id, record.type, record.summary_json)
    match headline:
        case RunHeadline():
            return {
                "total_generation_kwh": headline.generation_kwh,
                "self_consumption_ratio": headline.self_consumption_ratio,
                "unreadable": None,
            }
        case StoredRunUnreadable():
            return {"total_generation_kwh": None, "self_consumption_ratio": None, "unreadable": str(headline)}
        case None:
            return {"total_generation_kwh": None, "self_consumption_ratio": None, "unreadable": None}
        case _:
            assert_never(headline)


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


_COMPLETED_RUN_STATUS: RunStatus = "completed"
_FAILED_RUN_STATUS: RunStatus = "failed"
_INTERRUPTED_BY_RESTART_MESSAGE = "Interrupted by server restart"


class RunStatusConflict(Exception):
    """A run a lifecycle method of RunStorage cannot move to *wanted*, as a run's status moves only from 'running'.

    found is the status the run's row holds, or None when no run is recorded under run_id. The
    message names the run, the status found and the status wanted.
    """

    def __init__(self, run_id: str, found: RunStatus | None, wanted: RunStatus) -> None:
        held = "no run is recorded under that id" if found is None else f"the run is {found!r}"
        super().__init__(
            f"Run {run_id!r} cannot be marked {wanted!r}: a run's status moves only from "
            f"{UNFINISHED_RUN_STATUS!r}, and {held}"
        )
        self.run_id = run_id
        self.found = found
        self.wanted = wanted


def _now() -> str:
    """The time now, as the ISO 8601 UTC text a runs row records its times in."""
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class _RunEnding:
    """How a run that stops running ends, as its runs row records it: the status it ends in, its error message, None unless it failed, and when it ended."""

    status: RunStatus
    error_message: str | None
    completed_at: str


def _completed_now() -> _RunEnding:
    """The ending of a run that completes now."""
    return _RunEnding(status=_COMPLETED_RUN_STATUS, error_message=None, completed_at=_now())


def _failed_now(message: str) -> _RunEnding:
    """The ending of a run that fails now, with *message* as its error."""
    return _RunEnding(status=_FAILED_RUN_STATUS, error_message=message, completed_at=_now())


_END_RUNNING_RUNS = (
    "UPDATE runs SET status = :status, error_message = :error_message, completed_at = :completed_at "
    "WHERE status = :running"
)
"""The statement writing a _RunEnding, bound by field name, to every running run, the only status a run moves from; a condition joined with AND narrows the runs it ends."""


def _ending_values(ending: _RunEnding) -> dict[str, str | None]:
    """The values _END_RUNNING_RUNS binds to end the running runs as *ending* says."""
    return {**asdict(ending), "running": UNFINISHED_RUN_STATUS}


_COLUMNS_A_RESAVE_KEEPS = ("id", "created_at", *RUN_LABELS, *(column.name for column in fields(_RunEnding)))
"""The columns of a runs row a save leaves as they are: the run's id and creation time, the labels a user edits in Run History, and the columns a run's ending writes, which only the lifecycle methods write."""


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


def _saved_run_row(
    *,
    run_id: str,
    name: str,
    run_type: RunType,
    config: dict[str, Any],
    summary: dict[str, Any],
    created_at: str | None,
    duration_seconds: float | None,
    n_homes: int,
) -> RunRecord:
    """The runs row a save writes for the run it stored under *run_id*, its config and summary as JSON text.

    The run is running, with no error and no completion time, as create_run records a run: a
    save writes no status, which only the lifecycle methods move on. The run is created now
    unless *created_at* is given, and has no notes.

    Raises:
        ValueError: *name* cannot name a run, as require_run_name refuses it; RunRecord refuses it.
    """
    return RunRecord(
        id=run_id,
        name=name,
        type=run_type,
        config_json=json.dumps(config),
        summary_json=json.dumps(summary),
        status=UNFINISHED_RUN_STATUS,
        error_message=None,
        created_at=_now() if created_at is None else created_at,
        completed_at=None,
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

    def _get_run_dir(self, run_id: str) -> Path:
        """The directory of the files of run *run_id*, as _run_dir names it in this store's data directory.

        Raises:
            ValueError: The store refuses *run_id*, as _run_dir refuses it.
        """
        return _run_dir(self.data_dir, run_id)

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
        runs keeps the new name when the job's save rewrites its row. It also keeps the status,
        error and completion time the lifecycle methods wrote.
        """
        with self.database.transaction() as conn:
            conn.execute(_RUN_ROW_UPSERT, asdict(row))

    def create_run(self, run_id: str, *, run_type: RunType, name: str, n_homes: int, created_at: str) -> RunRecord:
        """Record a new run under *run_id*, running, as a job's submit records it before its simulation is queued.

        The run has the *run_type*, *name*, *n_homes* and *created_at* given and no other column:
        no config, summary, error, completion time, duration or notes. It writes no file; the save
        of the job's results writes the run's files and documents, and mark_run_completed then
        completes the run.

        Returns:
            The run's record as written.

        Raises:
            ValueError: The store refuses *run_id*, *run_type* is not one of RUN_TYPES, or
                *name* cannot name a run, as require_run_name refuses it.
            sqlite3.Error: The database refuses the row, e.g. for an id a run already has.
            Neither leaves anything written.
        """
        self._get_run_dir(run_id)
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

    def mark_run_completed(self, run_id: str) -> None:
        """Record that run *run_id* completed: completed now, with no error.

        Raises:
            RunStatusConflict: The run is not running, or no run is recorded under *run_id*,
                found None then, as a job never completes a run deleted while it ran (contract
                C8, docs/prds/run-store-one-owner.md §3.7). Nothing is written then.
        """
        ending = _completed_now()
        found = self._end_running_run(run_id, ending)
        if found != UNFINISHED_RUN_STATUS:
            raise RunStatusConflict(run_id, found, ending.status)

    def mark_run_failed(self, run_id: str, message: str) -> None:
        """Record that run *run_id* failed with *message*: failed, with *message* as its error, completed now.

        When no run has that id, nothing is written: a run deleted while its job ran stays deleted.

        Raises:
            RunStatusConflict: The run is not running, e.g. it completed; it is left as it was.
        """
        ending = _failed_now(message)
        found = self._end_running_run(run_id, ending)
        if found is not None and found != UNFINISHED_RUN_STATUS:
            raise RunStatusConflict(run_id, found, ending.status)

    def fail_interrupted_runs(self) -> int:
        """Mark every running run failed, as mark_run_failed marks one, with the message "Interrupted by server restart".

        A server calls it when it starts, before it runs any job, so each running run is one whose
        job an earlier server was running when it stopped. A run in any other status is left as it was.

        Returns:
            The number of runs it marked failed.
        """
        ending = _failed_now(_INTERRUPTED_BY_RESTART_MESSAGE)
        with self.database.transaction() as conn:
            return conn.execute(_END_RUNNING_RUNS, _ending_values(ending)).rowcount

    def _end_running_run(self, run_id: str, ending: _RunEnding) -> RunStatus | None:
        """End run *run_id* as *ending* says if it is running, in one transaction; return the status its row held.

        Returns:
            UNFINISHED_RUN_STATUS when the run was running and has ended. Otherwise the status
            its row holds, or None when no run is recorded under *run_id*; nothing has been
            written then.
        """
        with self.database.transaction() as conn:
            ended = conn.execute(f"{_END_RUNNING_RUNS} AND id = :run_id", {**_ending_values(ending), "run_id": run_id})
            if ended.rowcount == 1:
                return UNFINISHED_RUN_STATUS
            record = _record_of_row(conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone())
        return None if record is None else record.status

    def save_home_run(
        self,
        run_id: str,
        config: HomeConfig,
        results: SimulationResults,
        summary: SummaryStatistics,
        name: str,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a home simulation run to storage.

        Creates directory structure, serializes config and summary to JSON,
        saves time series to parquet, and upserts metadata into database. A new
        runs row is recorded running; a run already stored under run_id keeps the
        columns of its runs row that _upsert_run_row keeps, among them the status,
        error and completion time the lifecycle methods wrote.

        Args:
            run_id: Unique run identifier
            config: Home configuration
            results: Simulation results with time series
            summary: Summary statistics
            name: The name of the run when the save records it for the first time. A run
                already recorded, as a job's submit records it through create_run, keeps its
                own name, as a re-save keeps a run's labels.
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.

        Raises:
            ValueError: If the store refuses run_id, or name cannot name a run, as
                require_run_name refuses it. The save has written nothing then.
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
        name: str,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a home run as save_home_run does, with the summary calculate_summary derives from *results*.

        *name* is the name of the run when the save records it for the first time; a run
        already recorded keeps its own. This is the save a finished home job makes. It raises
        as save_home_run raises.
        """
        self.save_home_run(
            run_id,
            config,
            results,
            calculate_summary(results),
            name=name,
            duration_seconds=duration_seconds,
            created_at=created_at,
        )

    def save_fleet_run(
        self,
        run_id: str,
        fleet_results: FleetResults,
        fleet_summary: FleetSummary,
        per_home_summaries: list[SummaryStatistics],
        name: str,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a fleet simulation run to storage.

        Creates directory structure with homes/ subdirectory, saves per-home
        parquet files, fleet summary JSON, and fleet config JSON. A new runs row
        is recorded running; a run already stored under run_id keeps the columns
        of its runs row that _upsert_run_row keeps, among them the status, error
        and completion time the lifecycle methods wrote.

        Args:
            run_id: Unique run identifier
            fleet_results: Fleet simulation results with per-home data
            fleet_summary: Fleet-level summary statistics
            per_home_summaries: List of SummaryStatistics for each home
            name: The name of the run when the save records it for the first time. A run
                already recorded, as a job's submit records it through create_run, keeps its
                own name, as a re-save keeps a run's labels.
            duration_seconds: Optional simulation duration
            created_at: Optional ISO timestamp; if provided, preserves the
                original creation time from job submission.

        Raises:
            ValueError: If the store refuses run_id, per_home_summaries does not hold one
                summary per home's results, or name cannot name a run, as require_run_name
                refuses it. The save has written nothing then.
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
        name: str,
        duration_seconds: float | None = None,
        created_at: str | None = None,
    ) -> None:
        """Save a fleet run as save_fleet_run does, with each home's summary and the fleet summary aggregated from them.

        *name* is the name of the run when the save records it for the first time; a run
        already recorded keeps its own. Each summary is derived once from *fleet_results*.
        This is the save a finished fleet job makes.

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
            duration_seconds=duration_seconds,
            created_at=created_at,
        )

    def load_run(self, run_id: str) -> StoredRun:
        """The run stored under *run_id*, read from its directory as its record's kind reads it.

        Raises:
            FileNotFoundError: No run is stored under *run_id*: the store refuses the id (the
                refusal is the cause), no directory holds it, or no run is recorded under it. The
                message names the id.
            StoredRunUnreadable: The run is stored but cannot be read: its record has no type,
                as RunRecord.kind refuses it, naming runs.type, or a document its kind reads is
                missing or cannot be read, as the kind's read refuses it, naming the run, the
                document and the field.
        """
        run_dir = self._stored_run_dir(run_id)
        record = self.run_record(run_id)
        if record is None:
            raise FileNotFoundError(f"No run is recorded under {run_id!r}")
        return record.kind.read(run_dir, run_id)

    def run_record(self, run_id: str) -> RunRecord | None:
        """The record of run *run_id*: its row in the runs table. None when no run has that id."""
        with self.database.transaction() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return _record_of_row(row)

    def run_name(self, run_id: str) -> str | None:
        """The name run *run_id* is saved under, the one Run History lists and renames.

        None when no run has that id.
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
        """The count of the completed runs and of their homes, and the generation of those whose headline _read_headline reads.

        A run whose row records no count of homes counts as one home. A run whose summary is
        damaged, as _read_headline says, still counts, with its homes, but adds no
        generation, and a warning names it. The generation is read from each run's type and
        summary alone, never its config.
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
        headlines = (_read_headline(row["id"], row["type"], row["summary_json"]) for row in rows)
        generation_kwh = sum(
            (headline.generation_kwh for headline in headlines if isinstance(headline, RunHeadline)), 0.0
        )
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
