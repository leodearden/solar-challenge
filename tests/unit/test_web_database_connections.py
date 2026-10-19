# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every connection the dashboard opens to its database comes from a Database, which applies one policy.

Rows are read by column name, the schema's foreign keys are enforced, and nothing is read
from the file before the first statement. A database init_db created journals in WAL mode,
so every connection to it reports wal. A transaction commits a block that succeeds, rolls
back a block that raises, and closes its connection either way.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, closing, suppress
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import Database, init_db
from solar_challenge.web.jobs import JobManager


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
    """A dashboard database whose schema init_db has created."""
    return init_db(tmp_path / "dashboard.db")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_connection_to_a_database_init_db_created_reports_foreign_keys_on_and_wal_journal_mode(
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


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_a_dashboard_connection_refuses_a_job_whose_run_id_names_no_run(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY constraint failed"):
            conn.execute("INSERT INTO jobs (id, run_id) VALUES ('job-1', 'no-such-run')")


@pytest.mark.parametrize("open_connection", CONNECTION_OPENERS)
def test_deleting_a_run_on_a_dashboard_connection_deletes_its_jobs(
    open_connection: ConnectionOpener, dashboard_database: Database
) -> None:
    with open_connection(dashboard_database) as conn:
        conn.execute("INSERT INTO runs (id) VALUES ('run-1')")
        conn.execute("INSERT INTO jobs (id, run_id) VALUES ('job-1', 'run-1')")

        conn.execute("DELETE FROM runs WHERE id = 'run-1'")

        assert conn.execute("SELECT id FROM jobs").fetchall() == []


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
        conn.execute("INSERT INTO runs (id) VALUES ('run-1')")

    with closing(dashboard_database.connect()) as conn:
        assert [row["id"] for row in conn.execute("SELECT id FROM runs")] == ["run-1"]


def test_a_transaction_whose_block_raises_reraises_the_exception_and_keeps_none_of_its_writes(
    dashboard_database: Database,
) -> None:
    with pytest.raises(_BlockFailed):
        with dashboard_database.transaction() as conn:
            conn.execute("INSERT INTO runs (id) VALUES ('run-1')")
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


def _a_simulation_the_job_must_not_reach(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> SimulationResults:
    raise RuntimeError("the job reached its simulation")


def test_a_running_jobs_connection_refuses_a_write_that_would_leave_a_job_of_no_run(
    dashboard_database: Database, tmp_path: Path
) -> None:
    """A job's own connection enforces the schema's foreign keys too.

    A job whose start would insert a job of no run fails with the refusal, and leaves no such row.
    """
    with dashboard_database.transaction() as conn:
        conn.execute(
            "CREATE TRIGGER insert_a_job_of_no_run_when_a_job_starts_running AFTER UPDATE OF status ON jobs "
            "WHEN OLD.status = 'queued' AND NEW.status = 'running' "
            "BEGIN INSERT INTO jobs (id, run_id) VALUES ('job-of-no-run', 'no-such-run'); END"
        )
    manager = JobManager(max_workers=1, simulate_home=_a_simulation_the_job_must_not_reach)

    job_id, _ = manager.submit_home_job(
        config=HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500)),
        start_date=pd.Timestamp("2024-06-01", tz="UTC"),
        end_date=pd.Timestamp("2024-06-02", tz="UTC"),
        db_path=str(dashboard_database.path),
        data_dir=str(tmp_path / "data"),
    )
    assert manager.wait_until_idle(timeout=30)

    state = manager.job_state(job_id)
    assert state is not None
    assert (state.status, state.message) == ("failed", "FOREIGN KEY constraint failed")
    with dashboard_database.transaction() as conn:
        assert [row["id"] for row in conn.execute("SELECT id FROM jobs")] == [job_id]
