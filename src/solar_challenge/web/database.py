# SPDX-License-Identifier: AGPL-3.0-or-later
"""SQLite database module for Solar Challenge web dashboard persistence.

Provides schema initialization for storing simulation runs, chat messages,
and configuration presets, and Database, through which every connection to
the dashboard's database is opened.

Schema migration strategy:
    There is currently no automated migration framework.  When the schema
    changes (new columns, altered constraints, etc.), delete the database
    file (default ``~/.solar-challenge/solar-challenge.db``) and restart
    the application.  The ``init_db()`` function will recreate all tables
    from scratch using ``CREATE TABLE IF NOT EXISTS``.
"""

import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, get_args

RunType = Literal["home", "fleet"]  # the type of a run, held by the runs table's type column
RUN_TYPES: tuple[RunType, ...] = get_args(RunType)

RunStatus = Literal["running", "completed", "failed"]  # the status of a run, held by the runs table's status column
RUN_STATUSES: tuple[RunStatus, ...] = get_args(RunStatus)
UNFINISHED_RUN_STATUS: RunStatus = "running"

ChatRole = Literal["user", "assistant"]  # who wrote a chat message, held by the chat_messages table's role column
CHAT_ROLES: tuple[ChatRole, ...] = get_args(ChatRole)

PresetType = Literal["home", "fleet"]  # the type of a saved preset, held by the config_presets table's type column
PRESET_TYPES: tuple[PresetType, ...] = get_args(PresetType)


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
        the caller's error handling. journal_mode=WAL is a property of the file, which init_db
        sets when it creates the schema, so a connection to an initialised database reports
        wal. tests/unit/test_web_database_connections.py pins this policy.
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


def rebuild_table(conn: sqlite3.Connection, table: TableSchema, select: Mapping[str, str] | None = None) -> None:
    """Rebuild the table named *table*.name on *conn* to *table*'s schema, keeping each of its rows.

    Each column of a row is copied through the SQL expression *select* gives for it, which reads
    the old row, and every other column as itself. The old table is renamed away, *table* is
    created under its name, the rows are copied, the old table is dropped, and then *table*'s
    indexes are created. An index follows its table on a rename, so the indexes can only be
    created once the old table is dropped; the file then holds the schema a new database
    created from *table* holds. It runs inside its caller's transaction: it neither begins nor
    commits one.

    Raises:
        ValueError: Before anything is renamed, when a key of *select* is not one of *table*'s
            columns, or when another table's foreign key references the table: the rename would
            point that reference at the renamed table, whose drop would then delete the rows that
            reference it. The message names the keys and the columns, or the referencing tables
            and the table.
        sqlite3.Error: When the database refuses a statement, e.g. for a row *table* refuses.
    """
    expressions = {} if select is None else select
    unknown = sorted(set(expressions) - set(table.column_names))
    if unknown:
        raise ValueError(
            f"Cannot rebuild table {table.name!r}: select names {unknown}, "
            f"which are not among its columns {list(table.column_names)}"
        )
    referencing = [row[0] for row in conn.execute(_TABLES_REFERENCING, {"table": table.name})]
    if referencing:
        raise ValueError(
            f"Cannot rebuild table {table.name!r}: the foreign keys of {referencing} reference it, and renaming "
            "it away would point them at the renamed table, whose drop would delete the rows referencing it"
        )
    old_table = f"_{table.name}_before_rebuild"
    columns = ", ".join(table.column_names)
    values = ", ".join(expressions.get(column, column) for column in table.column_names)
    conn.execute(f"ALTER TABLE {table.name} RENAME TO {old_table}")
    conn.execute(table.create)
    conn.execute(f"INSERT INTO {table.name} ({columns}) SELECT {values} FROM {old_table}")
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


def init_db(db_path: str | Path) -> Database:
    """Initialize the SQLite database with the required schema, and return the Database for it.

    Creates tables for runs, chat_messages, and config_presets.
    The schema is created in one transaction, all or nothing.
    Safe to call multiple times - uses CREATE TABLE IF NOT EXISTS.

    Args:
        db_path: Path to the SQLite database file. Parent directory
            will be created if it doesn't exist.

    Returns:
        The Database for *db_path*, through which its caller opens every connection to it.
    """
    database = Database(Path(db_path))
    database.path.parent.mkdir(parents=True, exist_ok=True)

    with database.transaction() as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("BEGIN")
        _create_schema(conn.cursor())
    return database


def _create_schema(cursor: sqlite3.Cursor) -> None:
    """Create through *cursor* each of the dashboard's tables and indexes that is missing."""
    # Runs table - stores metadata for home/fleet simulations
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS runs (
            id TEXT PRIMARY KEY,
            name TEXT,
            type TEXT {check_one_of("type", RUN_TYPES)},
            config_json TEXT,
            summary_json TEXT,
            status TEXT DEFAULT {sql_string_literal(UNFINISHED_RUN_STATUS)} {check_one_of("status", RUN_STATUSES)},
            error_message TEXT,
            created_at TEXT,
            completed_at TEXT,
            duration_seconds REAL,
            n_homes INTEGER DEFAULT 1,
            notes TEXT
        )
    """)

    # Chat messages table - stores AI assistant conversation history
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            role TEXT {check_one_of("role", CHAT_ROLES)},
            content TEXT,
            created_at TEXT,
            metadata_json TEXT
        )
    """)

    # Config presets table - stores saved configuration templates
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS config_presets (
            id TEXT PRIMARY KEY,
            name TEXT UNIQUE,
            type TEXT {check_one_of("type", PRESET_TYPES)},
            config_json TEXT,
            created_at TEXT
        )
    """)

    # Create indexes for common queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_created_at
        ON runs(created_at DESC)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_runs_type
        ON runs(type)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_chat_messages_session_id
        ON chat_messages(session_id)
    """)


def save_chat_message(
    database: Database,
    session_id: str,
    role: ChatRole,
    content: str,
    metadata: dict[str, Any] | None = None,
) -> int:
    """Insert a chat message row and return the new row id.

    Args:
        database: The Database holding the chat_messages table.
        session_id: Browser-session identifier scoping the conversation.
        role: Who wrote the message, one of CHAT_ROLES.
        content: Message text.
        metadata: Optional dict serialised as JSON (e.g. usage/cache stats).

    Returns:
        The auto-incremented integer id of the newly inserted row.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    metadata_json: str | None = json.dumps(metadata) if metadata is not None else None
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO chat_messages (session_id, role, content, created_at, metadata_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, role, content, created_at, metadata_json),
        )
        return int(cursor.lastrowid or 0)


def get_chat_history(
    database: Database,
    session_id: str,
) -> list[dict[str, Any]]:
    """Return all chat messages for a session in insertion order.

    Args:
        database: The Database holding the chat_messages table.
        session_id: Browser-session identifier to filter by.

    Returns:
        List of dicts with keys: ``role``, ``content``, ``created_at``,
        ``metadata`` (dict or ``None``).
    """
    with database.transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT role, content, created_at, metadata_json
            FROM chat_messages
            WHERE session_id = ?
            ORDER BY id ASC
            """,
            (session_id,),
        )
        rows = cursor.fetchall()

    result: list[dict[str, Any]] = []
    for row in rows:
        meta_raw = row["metadata_json"]
        result.append(
            {
                "role": row["role"],
                "content": row["content"],
                "created_at": row["created_at"],
                "metadata": json.loads(meta_raw) if meta_raw is not None else None,
            }
        )
    return result
