# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard store's schema version, the ordered steps that bring an older store to it, and the opening of a store.

A store's schema version is its database file's PRAGMA user_version. The MigrationStep of
version N brings a store at version N - 1 to N, and SCHEMA_VERSION, the version this code
reads and writes, is the last step's. open_database creates a new store at SCHEMA_VERSION and
refuses a store at any other version with a SchemaVersionMismatch.

Each table's owner states the table's schema and its part of each step: storage.py the runs
table, presets.py config_presets and database.py chat_messages. This module states only the
steps' order, the version and the transaction (docs/prds/run-store-one-owner.md §3.1, §3.9).
"""

import sqlite3
from collections.abc import Callable, Sequence
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from solar_challenge.web.database import CHAT_MESSAGES_TABLE, Database, create_table, migrate_chat_messages_table_v1
from solar_challenge.web.presets import CONFIG_PRESETS_TABLE, migrate_config_presets_table_v1
from solar_challenge.web.storage import RUNS_TABLE, migrate_runs_table_v1


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


@dataclass(frozen=True)
class MigrationStep:
    """The step of the store's schema to *version*: what brings a store at version - 1 to it.

    migrate_database is the step's database part, run on a connection inside the step's
    transaction, which also records *version* as the store's user_version. description says
    what the step does, for the report of a migration.
    """

    version: int
    description: str
    migrate_database: Callable[[sqlite3.Connection], None]


def _schema_v1(conn: sqlite3.Connection) -> None:
    """Version 1's database part: the retired jobs table dropped, then runs, config_presets and chat_messages rebuilt to their current schema.

    jobs goes first: its run_id references runs, and rebuild_table refuses a table another
    table's foreign key references.
    """
    conn.execute("DROP TABLE IF EXISTS jobs")
    migrate_runs_table_v1(conn)
    migrate_config_presets_table_v1(conn)
    migrate_chat_messages_table_v1(conn)


MIGRATIONS: tuple[MigrationStep, ...] = (
    MigrationStep(
        1,
        "Drop the retired jobs table and rebuild runs, config_presets and chat_messages to their current schema, "
        "naming each run that has no name after its kind",
        _schema_v1,
    ),
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


SCHEMA_VERSION = _last_version(MIGRATIONS)
"""The schema version this code reads and writes: the last migration step's."""

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
        sqlite3.Error: The new store cannot be created; the file then holds none of its tables.
    """
    database = Database(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    found = _found_version(database)
    if found is None:
        _create_store(database)
    elif found != SCHEMA_VERSION:
        raise SchemaVersionMismatch(path, found, SCHEMA_VERSION)
    return database


def _found_version(database: Database) -> int | None:
    """The schema version *database*'s file records, read without writing to it: None when it holds no table, else its user_version."""
    with closing(database.connect()) as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' LIMIT 1").fetchone() is None:
            return None
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _create_store(database: Database) -> None:
    """Create a new store at SCHEMA_VERSION in *database*'s file, which holds no table, in one transaction."""
    with database.transaction() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN IMMEDIATE")
        for table in _CURRENT_TABLES:
            create_table(conn, table)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
