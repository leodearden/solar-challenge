# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's SQLite database: the policy every connection to it applies, and the mechanism with which each table's owner states and migrates its table.

Database opens every connection to the database file. TableSchema states a table as its
owner declares it, create_table creates one, and rebuild_table rebuilds an existing table to
a schema, keeping its rows; RowRefused names a row a migration cannot keep. Each table's
owner states its own schema, the one a new store creates and the one of each schema version
a migration step rebuilds the table to: storage.py the runs table, presets.py config_presets
and chat_messages.py chat_messages (docs/prds/run-store-one-owner.md §3.1, the persistence
stratum).

A store's schema version is its database file's PRAGMA user_version. web/schema.py creates a
new store at the current version and refuses a store at any other, and
`solar-challenge web migrate` brings an older store forward to it
(docs/prds/run-store-one-owner.md §3.9).
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


def sql_string_literal(text: str) -> str:
    """*text* as an SQL string literal, each single quote in it doubled."""
    return "'" + text.replace("'", "''") + "'"


def check_one_of(column: str, values: tuple[str, ...]) -> str:
    """The CHECK constraint that refuses a value of *column* other than one of *values*; NULL passes, as in any CHECK."""
    return f"CHECK({column} IN ({', '.join(sql_string_literal(value) for value in values)}))"


@dataclass(frozen=True)
class Database:
    """The dashboard's SQLite database file at *path*, through which every connection to it is opened."""

    path: Path

    def connect(self) -> sqlite3.Connection:
        """Open a connection to this database under the policy every dashboard connection applies; the caller closes it.

        Rows are read by column name and the schema's foreign keys are enforced. Opening reads
        nothing from the file, so an unreadable database raises at the first statement, inside
        the caller's error handling. journal_mode=WAL is a property of the file, which
        web/schema.py's open_database sets when it creates a store, so a connection to a store
        it created reports wal. tests/unit/test_web_database_connections.py pins this policy.
        """
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Open a connection through connect() for one block of work.

        Commits when the block succeeds, rolls back and re-raises when the block raises, and
        closes the connection either way.
        """
        conn = self.connect()

        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


@dataclass(frozen=True)
class TableSchema:
    """A table of the dashboard's database as its owner states it: its name, its columns in order and its indexes.

    Each column is a (name, declaration) pair, the declaration being the column's type and
    constraints as CREATE TABLE states them, and each index a CREATE INDEX statement.
    """

    name: str
    columns: tuple[tuple[str, str], ...]
    indexes: tuple[str, ...] = ()

    @property
    def column_names(self) -> tuple[str, ...]:
        """The name of each column, in order."""
        return tuple(name for name, _ in self.columns)

    @property
    def create(self) -> str:
        """The CREATE TABLE statement of the table: the exact text a database stores for the table it creates."""
        column_lines = ",\n".join(f"    {name} {declaration}" for name, declaration in self.columns)
        return f"CREATE TABLE {self.name} (\n{column_lines}\n)"


def create_table(conn: sqlite3.Connection, table: TableSchema) -> None:
    """Create *table* on *conn*: its CREATE TABLE statement, then each of its indexes."""
    conn.execute(table.create)
    for index in table.indexes:
        conn.execute(index)


_TABLES_REFERENCING = (
    "SELECT DISTINCT m.name FROM sqlite_master AS m, pragma_foreign_key_list(m.name) AS fk"
    " WHERE m.type = 'table' AND fk.\"table\" = :table COLLATE NOCASE AND m.name != :table COLLATE NOCASE"
    " ORDER BY m.name"
)
"""The other tables whose foreign keys reference the table :table; SQLite names a table in any ASCII case."""


def rebuild_table(conn: sqlite3.Connection, table: TableSchema) -> None:
    """Rebuild the table named *table*.name on *conn* to *table*'s schema, keeping each of its rows, each column as it is.

    The old table is renamed away, *table* is created under its name, the rows are copied, the
    old table is dropped, and then *table*'s indexes are created. An index follows its table on
    a rename, so the indexes can only be created once the old table is dropped; the file then
    holds the schema a new database created from *table* holds. It runs inside its caller's
    transaction: it neither begins nor commits one.

    Raises:
        ValueError: Before anything is renamed, when another table's foreign key references the
            table: the rename would point that reference at the renamed table, whose drop would
            then delete the rows that reference it. The message names the referencing tables
            and the table.
        sqlite3.Error: When the database refuses a statement, e.g. for a row *table* refuses.
    """
    referencing = [row[0] for row in conn.execute(_TABLES_REFERENCING, {"table": table.name})]
    if referencing:
        raise ValueError(
            f"Cannot rebuild table {table.name!r}: the foreign keys of {referencing} reference it, and renaming "
            "it away would point them at the renamed table, whose drop would delete the rows referencing it"
        )
    old_table = f"_{table.name}_before_rebuild"
    columns = ", ".join(table.column_names)
    conn.execute(f"ALTER TABLE {table.name} RENAME TO {old_table}")
    conn.execute(table.create)
    conn.execute(f"INSERT INTO {table.name} ({columns}) SELECT {columns} FROM {old_table}")
    conn.execute(f"DROP TABLE {old_table}")
    for index in table.indexes:
        conn.execute(index)


class RowRefused(Exception):
    """A row a migration cannot keep, as a constraint its table gains refuses it; the message names the table, the row's id and the column.

    It is not a ValueError: no request causes it; the migration that meets the row refuses to run.
    """

    def __init__(self, table: str, row_id: object, column: str, reason: str) -> None:
        super().__init__(f"The {table} row {row_id!r} cannot be migrated: its {column} {reason}")
        self.table = table
        self.row_id = row_id
        self.column = column
        self.reason = reason
