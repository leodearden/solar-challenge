# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard store's schema version, the ordered steps that bring an older store to it, and the opening of a store.

A store's schema version is its database file's PRAGMA user_version. The MigrationStep of
version N brings a store at version N - 1 to N, and SCHEMA_VERSION, the version this code
reads and writes, is the last step's. open_database creates a new store at SCHEMA_VERSION and
refuses a store at any other version with a SchemaVersionMismatch, and a file that cannot be
read as a database with a StoreUnreadable. migrate_store, which
`solar-challenge web migrate` runs, brings an older store to SCHEMA_VERSION and reports it in
a MigrationReport.

Each table's owner states the table's schema and its part of each step: storage.py the runs
table, presets.py config_presets and chat_messages.py chat_messages. This module states only the
steps' order, the version and the transaction (docs/prds/run-store-one-owner.md §3.1, §3.9).

A change to any table's schema is a new MigrationStep, committed with the schema of its version
as a snapshot in tests/fixtures/databases, version N's as schema_v<N>.sql. A step rebuilds a
table to the table's schema at the step's version, which the owner states apart from the
table's current schema, so a later step changes no earlier one.

A step may also carry a run-document step of the stored-run format (stored_runs.RUN_DOCUMENT_STEPS),
the step of the same version, as version 2 carries the first: migrate_store brings every stored
run's files forward by it before the step's transaction, and the runs rows' copies inside it.
Each run-document step is carried by the step of its version, so the format version is never
past the schema version (D-S19-2), and a store at SCHEMA_VERSION holds only runs in the current
format or runs its migration reported it could not migrate.
"""

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from solar_challenge.web.chat_messages import CHAT_MESSAGES_TABLE, migrate_chat_messages_table_v1
from solar_challenge.web.database import Database, RowRefused, create_table
from solar_challenge.web.presets import CONFIG_PRESETS_TABLE, migrate_config_presets_table_v1
from solar_challenge.web.storage import (
    RUNS_TABLE,
    RunDocumentsOutcome,
    migrate_runs_table_documents,
    migrate_runs_table_v1,
    migrate_stored_run_files,
)
from solar_challenge.web.stored_runs import RUN_DOCUMENT_STEPS, DroppedValue, RunDocumentStep, UnmigratedRun


class SchemaVersionMismatch(Exception):
    """A store at a schema version other than the one this code reads; the message names its file and both versions.

    It is not a ValueError: no request causes it, so it is a start-up refusal, as StoreLockError is.
    """

    def __init__(self, path: Path, found: int, expected: int) -> None:
        super().__init__(
            f"The dashboard database {path} is at schema version {found}; "
            f"this solar-challenge needs version {expected}.{_remedy(found, expected)}"
        )
        self.path = path
        self.found = found
        self.expected = expected


def _remedy(found: int, expected: int) -> str:
    """What brings a store at schema version *found* to *expected*, as a sentence SchemaVersionMismatch's message ends with."""
    if found < expected:
        return " Run `solar-challenge web migrate` to migrate it."
    if found > expected:
        return " This database was written by a newer solar-challenge."
    return ""


class StoreUnreadable(Exception):
    """A store whose database file cannot be read as a database, e.g. a file that is not one; the message names the file and the database's refusal.

    It is not a ValueError: no request causes it, so it is a start-up refusal, as SchemaVersionMismatch is.
    """

    def __init__(self, path: Path, refusal: sqlite3.Error) -> None:
        super().__init__(f"The dashboard database {path} cannot be read: {refusal}")
        self.path = path


@dataclass(frozen=True)
class MigrationStep:
    """The step of the store's schema to *version*: what brings a store at version - 1 to it.

    migrate_database is the step's database part, run on a connection inside the step's
    transaction, which also records *version* as the store's user_version. It raises RowRefused
    for a row a constraint the step adds refuses, and ValueError or sqlite3.Error for a table it
    cannot rebuild, e.g. one another table's foreign key references or one the store lacks.
    description says what the step does, for the report of a migration. run_documents is the
    run-document step of the same version that the step carries, if any: migrate_store brings
    each stored run's files forward by it first, then each runs row's copies inside the step's
    transaction.
    """

    version: int
    description: str
    migrate_database: Callable[[sqlite3.Connection], None]
    run_documents: RunDocumentStep | None = None


class MigrationRefused(Exception):
    """A migration step that cannot run on a store, as a constraint it adds refuses a row or a table is not one it can rebuild; the message names the store, the step's version, the version the store stays at, and the fault.

    It is not a ValueError: no request causes it, as SchemaVersionMismatch is not one.
    """

    def __init__(self, path: Path, step: MigrationStep, fault: RowRefused | ValueError | sqlite3.Error) -> None:
        super().__init__(
            f"{path} cannot be migrated to schema version {step.version}, so it stays at version "
            f"{step.version - 1}, and the step has changed nothing in it: {fault}"
        )
        self.path = path
        self.step = step


def _schema_v1(conn: sqlite3.Connection) -> None:
    """Version 1's database part: the retired jobs table dropped, then runs, config_presets and chat_messages rebuilt to their schema at version 1.

    jobs goes first: its run_id references runs, and rebuild_table refuses a table another
    table's foreign key references. Only the runs part can refuse a row: the constraints of
    config_presets and chat_messages at version 1 are a legacy table's.
    """
    conn.execute("DROP TABLE IF EXISTS jobs")
    migrate_runs_table_v1(conn)
    migrate_config_presets_table_v1(conn)
    migrate_chat_messages_table_v1(conn)


def _no_table_changes(conn: sqlite3.Connection) -> None:
    """The database part of a step that changes no table, as version 2's: its run-document step brings the runs rows' copies forward."""


def _carrying(version: int) -> MigrationStep:
    """The step to *version* that carries the run-document step of *version*, under that step's description, and changes no table.

    Raises:
        ValueError: RUN_DOCUMENT_STEPS holds no step of *version*; the message names it.
    """
    document_step = next((step for step in RUN_DOCUMENT_STEPS if step.version == version), None)
    if document_step is None:
        raise ValueError(f"No run-document step is of version {version}")
    return MigrationStep(version, document_step.description, _no_table_changes, run_documents=document_step)


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(
        1,
        "Drop the retired jobs table and rebuild runs, config_presets and chat_messages to version 1's schema, "
        "naming each run that has no name after its kind",
        _schema_v1,
    ),
    _carrying(2),
)
"""Every step of the store's schema, in order: MIGRATIONS[N - 1] is the step to version N."""


def _last_version(steps: Sequence[MigrationStep]) -> int:
    """The version of the last of *steps*, whose versions run from 1 without a gap.

    Raises:
        ValueError: There are no steps, or their versions are not 1 to N in order; the message
            names the versions.
    """
    versions = [step.version for step in steps]
    if not versions or versions != list(range(1, len(versions) + 1)):
        raise ValueError(f"The migration steps' versions are {versions}, not 1 to {len(versions)} in order")
    return versions[-1]


def _require_each_run_document_step_carried(steps: Sequence[MigrationStep]) -> None:
    """Check that each of RUN_DOCUMENT_STEPS is carried by the one of *steps* of its version, and that *steps* carry no other.

    Raises:
        ValueError: A run-document step no step of its version carries, or a step carrying one
            of another version or not in RUN_DOCUMENT_STEPS; the message names both sets of versions.
    """
    carried = {step.version: step.run_documents for step in steps if step.run_documents is not None}
    expected = {step.version: step for step in RUN_DOCUMENT_STEPS}
    if carried.keys() != expected.keys() or any(carried[version] is not expected[version] for version in expected):
        raise ValueError(
            f"The run-document steps are of versions {sorted(expected)}, and the migration steps of versions "
            f"{sorted(carried)} carry one: each run-document step must be carried by the migration step of its version"
        )


SCHEMA_VERSION = _last_version(MIGRATIONS)
"""The schema version this code reads and writes: the last migration step's."""

_require_each_run_document_step_carried(MIGRATIONS)

_CURRENT_TABLES = (RUNS_TABLE, CONFIG_PRESETS_TABLE, CHAT_MESSAGES_TABLE)
"""Every table of a store at SCHEMA_VERSION, in the order a new store creates them, so chat_messages' index is a creation's last statement."""


def open_database(path: Path) -> Database:
    """The Database of the store at *path* at SCHEMA_VERSION, which is created when the file holds no table.

    The directory of *path* is created if need be. The store's version is read before anything
    is written. A new store is created all or nothing, in one transaction: every table at its
    owner's current schema, with its indexes, and the user_version SCHEMA_VERSION; its file
    journals in WAL mode. A store at SCHEMA_VERSION is opened as it is. Every connection is
    opened through Database.connect().

    Raises:
        SchemaVersionMismatch: The store is at another schema version, a legacy store that
            records none being at version 0; nothing is written to it.
        StoreUnreadable: The file cannot be read as a database; nothing is written to it.
        sqlite3.Error: The new store cannot be created; the file then holds none of its tables.
    """
    database = Database(path)
    found = _version_of_existing_or_new_store(database)
    if found != SCHEMA_VERSION:
        raise SchemaVersionMismatch(path, found, SCHEMA_VERSION)
    return database


@dataclass(frozen=True)
class MigrationReport:
    """What migrate_store did to the store at *path*: the schema version it found it at, the one it left it at, and each step it applied, in order.

    dropped_values are the values its run-document steps dropped that are not null, and
    unmigrated_runs the stored runs they left as they were, each once.
    """

    path: Path
    from_version: int
    to_version: int
    applied_steps: tuple[MigrationStep, ...]
    dropped_values: tuple[DroppedValue, ...] = ()
    unmigrated_runs: tuple[UnmigratedRun, ...] = ()

    def __str__(self) -> str:
        """The report as `solar-challenge web migrate` prints it.

        That is the store's database, both versions and each step applied, then each value
        dropped and each run left unmigrated; or that there was nothing to migrate.
        """
        if not self.applied_steps:
            return f"The dashboard database {self.path} is at schema version {self.to_version}; there is nothing to migrate."
        return "\n".join([
            f"Migrated the dashboard database {self.path} from schema version {self.from_version} to {self.to_version}:",
            *(f"  {step.version}. {step.description}" for step in self.applied_steps),
            *_listed("Dropped each value below, which no field of its document holds:", self.dropped_values),
            *_listed(
                "Left each run below as it was, as its documents cannot be read; it cannot be loaded until they are fixed:",
                self.unmigrated_runs,
            ),
        ])


def _listed(heading: str, items: Sequence[DroppedValue] | Sequence[UnmigratedRun]) -> list[str]:
    """*heading*, then each of *items* on a line of its own; no line at all when there is no item."""
    return [heading, *(f"  {item}" for item in items)] if items else []


def migrate_store(database_path: Path, data_dir: Path) -> MigrationReport:
    """Bring the store at *database_path*, whose run files are under *data_dir*, to SCHEMA_VERSION, applying each step of MIGRATIONS after its version, in order.

    The store's version is read before anything is written. A file that holds no table is
    created as open_database creates a new store, at SCHEMA_VERSION, so no step is applied to
    it, and a store at SCHEMA_VERSION is left as it is. A step carrying a run-document step
    first brings each stored run's files forward by it, as migrate_stored_run_files does, which
    can be run again should the step then fail. Each step is then applied in a transaction of
    its own, which writes the step's database part, brings each runs row's documents forward
    by its run-document step, and records the step's version as the store's user_version
    together: a step that fails leaves the store at the version before it, as the steps before
    it left it. A run whose documents a run-document step cannot bring forward is left as it
    was and reported, and the migration goes on. Every connection is opened through
    Database.connect().

    Raises:
        SchemaVersionMismatch: The store is at a version above SCHEMA_VERSION, which a newer
            solar-challenge wrote; nothing is written to it.
        StoreUnreadable: The file cannot be read as a database; nothing is written to it.
        MigrationRefused: A step's database part fails, the cause: a constraint the step adds
            refuses a row (RowRefused), or a table is not one it can rebuild (ValueError or
            sqlite3.Error). The step has changed nothing, so the store stays at the version
            before it.
        sqlite3.Error: A new store cannot be created.
    """
    database = Database(database_path)
    found = _version_of_existing_or_new_store(database)
    if found > SCHEMA_VERSION:
        raise SchemaVersionMismatch(database_path, found, SCHEMA_VERSION)
    pending = tuple(step for step in MIGRATIONS if step.version > found)
    outcome = RunDocumentsOutcome()
    for step in pending:
        try:
            outcome += _apply_step(database, data_dir, step)
        except (RowRefused, ValueError, sqlite3.Error) as fault:
            raise MigrationRefused(database_path, step, fault) from fault
    return MigrationReport(
        database_path,
        from_version=found,
        to_version=SCHEMA_VERSION,
        applied_steps=pending,
        dropped_values=outcome.dropped,
        unmigrated_runs=tuple(dict.fromkeys(outcome.unmigrated)),
    )


def _apply_step(database: Database, data_dir: Path, step: MigrationStep) -> RunDocumentsOutcome:
    """Apply *step* to the store of *database* and *data_dir*, which is at the version before it, and return what its run-document step did.

    The run-document step, if the step carries one, first brings the stored runs' files
    forward. Then one transaction writes the step's database part, brings the runs rows'
    documents forward by the same run-document step, and records the step's version as the
    store's user_version.
    """
    document_step = step.run_documents
    outcome = RunDocumentsOutcome() if document_step is None else migrate_stored_run_files(database, data_dir, document_step)
    with database.transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        step.migrate_database(conn)
        if document_step is not None:
            outcome += migrate_runs_table_documents(conn, document_step)
        conn.execute(f"PRAGMA user_version = {step.version}")
    return outcome


def _version_of_existing_or_new_store(database: Database) -> int:
    """The schema version of *database*'s store, read before anything is written to it.

    A file that holds no table is first created as a new store at SCHEMA_VERSION, with the
    directory it is in if need be.
    """
    database.path.parent.mkdir(parents=True, exist_ok=True)
    found = _found_version(database)
    if found is None:
        _create_store(database)
        return SCHEMA_VERSION
    return found


def _found_version(database: Database) -> int | None:
    """The schema version *database*'s file records, read without writing to it: None when it holds no table, else its user_version.

    Raises:
        StoreUnreadable: The file cannot be read as a database, the database's refusal being the cause.
    """
    try:
        with closing(database.connect()) as conn:
            if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone() is None:
                return None
            return int(conn.execute("PRAGMA user_version").fetchone()[0])
    except sqlite3.Error as refusal:
        raise StoreUnreadable(database.path, refusal) from refusal


def _create_store(database: Database) -> None:
    """Create a new store at SCHEMA_VERSION in *database*'s file, which holds no table, in one transaction."""
    with database.transaction() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        for table in _CURRENT_TABLES:
            create_table(conn, table)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
