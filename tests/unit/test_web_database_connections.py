# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every connection the dashboard opens to its database comes from a Database, which applies one policy.

Rows are read by column name, the foreign keys of any table on the database are enforced, and nothing is read
from the file before the first statement. A store open_database created journals in WAL mode,
so every connection to it reports wal. A transaction commits a block that succeeds, rolls
back a block that raises, and closes its connection either way.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, closing, suppress
from pathlib import Path

import pytest

from solar_challenge.web.database import Database
from solar_challenge.web.schema import open_database


def _connected(database: Database) -> AbstractContextManager[sqlite3.Connection]:
    """A connection from database.connect() that is closed when the block exits."""
    return closing(database.connect())


def _in_a_transaction(database: Database) -> AbstractContextManager[sqlite3.Connection]:
    """The connection of a transaction on *database*."""
    return database.transaction()


ConnectionOpener = Callable[[Database], AbstractContextManager[sqlite3.Connection]]

CONNECTION_OPENERS = [
    pytest.param(_connected, id="connect"),
    pytest.param(_in_a_transaction, id="transaction"),
]


@pytest.fixture
def dashboard_database(tmp_path: Path) -> Database:
    """A dashboard database, a new store open_database created."""
    return open_database(tmp_path / "dashboard.db")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_connection_to_a_store_open_database_created_reports_foreign_keys_on_and_wal_journal_mode(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_reads_rows_by_column_name(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        assert conn.execute("SELECT 1 AS value").fetchone()["value"] == 1


def _create_a_table_whose_rows_reference_a_run(conn: sqlite3.Connection) -> None:
    """Create, on *conn*, the table run_notes, whose run_id references a run and whose rows are deleted with it."""
    conn.execute("CREATE TABLE run_notes (id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(id) ON DELETE CASCADE)")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_refuses_a_row_whose_run_id_names_no_run(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        _create_a_table_whose_rows_reference_a_run(conn)
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute("INSERT INTO run_notes (id, run_id) VALUES ('note-1', 'no-such-run')")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_deleting_a_run_on_a_dashboard_connection_deletes_the_rows_that_reference_it(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        _create_a_table_whose_rows_reference_a_run(conn)
        conn.execute("INSERT INTO runs (id, name) VALUES ('run-1', 'Run 1')")
        conn.execute("INSERT INTO run_notes (id, run_id) VALUES ('note-1', 'run-1')")

        conn.execute("DELETE FROM runs WHERE id = 'run-1'")

        assert conn.execute("SELECT id FROM run_notes").fetchall() == []


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_opens_a_file_that_is_not_a_database_and_its_first_read_raises(
    open_connection: ConnectionOpener, tmp_path: Path
) -> None:
    """Opening reads nothing from the file, so an unreadable database raises at the first
    statement that reads it, inside the caller's own error handling."""
    not_a_database = tmp_path / "not-a-database.db"
    not_a_database.write_bytes(b"not a database")

    with open_connection(Database(not_a_database)) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="file is not a database"):
            conn.execute("SELECT id FROM runs")


class _BlockFailed(Exception):
    """The exception a test's transaction block raises."""


def _succeed() -> None:
    """End a transaction's block without raising."""


def _fail() -> None:
    """End a transaction's block by raising _BlockFailed."""
    raise _BlockFailed


BLOCK_ENDINGS = [pytest.param(_succeed, id="block-succeeds"), pytest.param(_fail, id="block-raises")]


def test_a_run_inserted_in_a_transaction_whose_block_succeeds_is_read_back_on_a_new_connection(
    dashboard_database: Database,
) -> None:
    with dashboard_database.transaction() as conn:
        conn.execute("INSERT INTO runs (id, name) VALUES ('run-1', 'Run 1')")

    with closing(dashboard_database.connect()) as conn:
        assert [row["id"] for row in conn.execute("SELECT id FROM runs")] == ["run-1"]


def test_a_transaction_whose_block_raises_reraises_the_exception_and_keeps_none_of_its_writes(
    dashboard_database: Database,
) -> None:
    with pytest.raises(_BlockFailed):
        with dashboard_database.transaction() as conn:
            conn.execute("INSERT INTO runs (id, name) VALUES ('run-1', 'Run 1')")
            _fail()

    with closing(dashboard_database.connect()) as conn:
        assert conn.execute("SELECT id FROM runs").fetchall() == []


@pytest.mark.parametrize("end_the_block", BLOCK_ENDINGS)
def test_a_transaction_closes_its_connection_when_its_block_exits(
    end_the_block: Callable[[], None], dashboard_database: Database
) -> None:
    with suppress(_BlockFailed):
        with dashboard_database.transaction() as conn:
            end_the_block()

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        conn.execute("SELECT 1")

