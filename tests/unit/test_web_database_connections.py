# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every connection the dashboard opens to its database applies one policy, whichever opener it came from.

Rows are read by column name, the schema's foreign keys are enforced, and nothing is read
from the file before the first statement.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from pathlib import Path

import pytest

from solar_challenge.web.database import connect, get_db, init_db


def _connected(db_path: Path) -> AbstractContextManager[sqlite3.Connection]:
    """A connection from connect that is closed when the block exits."""
    return closing(connect(db_path))


CONNECTION_OPENERS = [pytest.param(_connected, id="connect"), pytest.param(get_db, id="get_db")]


@pytest.fixture
def dashboard_db(tmp_path: Path) -> Path:
    """The path of a dashboard database whose schema init_db has created."""
    db_path = tmp_path / "dashboard.db"
    init_db(db_path)
    return db_path


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_reads_rows_by_column_name(
    open_connection: Callable[[Path], AbstractContextManager[sqlite3.Connection]], dashboard_db: Path
) -> None:
    with open_connection(dashboard_db) as conn:
        assert conn.execute("SELECT 1 AS value").fetchone()["value"] == 1


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_refuses_a_job_whose_run_id_names_no_run(
    open_connection: Callable[[Path], AbstractContextManager[sqlite3.Connection]], dashboard_db: Path
) -> None:
    with open_connection(dashboard_db) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute("INSERT INTO jobs (id, run_id) VALUES ('job-1', 'no-such-run')")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_deleting_a_run_on_a_dashboard_connection_deletes_its_jobs(
    open_connection: Callable[[Path], AbstractContextManager[sqlite3.Connection]], dashboard_db: Path
) -> None:
    with open_connection(dashboard_db) as conn:
        conn.execute("INSERT INTO runs (id) VALUES ('run-1')")
        conn.execute("INSERT INTO jobs (id, run_id) VALUES ('job-1', 'run-1')")

        conn.execute("DELETE FROM runs WHERE id = 'run-1'")

        assert conn.execute("SELECT id FROM jobs").fetchall() == []


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_opens_a_file_that_is_not_a_database_and_its_first_read_raises(
    open_connection: Callable[[Path], AbstractContextManager[sqlite3.Connection]], tmp_path: Path
) -> None:
    """Opening reads nothing from the file, so an unreadable database raises at the first
    statement that reads it, inside the caller's own error handling."""
    not_a_database = tmp_path / "not-a-database.db"
    not_a_database.write_bytes(b"not a database")

    with open_connection(not_a_database) as conn:
        with pytest.raises(sqlite3.DatabaseError, match="file is not a database"):
            conn.execute("SELECT id FROM runs")
