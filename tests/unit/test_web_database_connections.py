# SPDX-License-Identifier: AGPL-3.0-or-later
"""Every connection the dashboard opens to its database applies one policy, whichever opener it came from.

Rows are read by column name, the schema's foreign keys are enforced, and nothing is read
from the file before the first statement.
"""

import sqlite3
from collections.abc import Callable
from contextlib import AbstractContextManager, closing
from pathlib import Path

import pandas as pd
import pytest

from solar_challenge.home import HomeConfig, SimulationResults
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import connect, get_db, init_db
from solar_challenge.web.jobs import JobManager


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


def _a_simulation_the_job_must_not_reach(
    config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp
) -> SimulationResults:
    raise RuntimeError("the job reached its simulation")


def test_a_running_jobs_connection_refuses_a_write_that_would_leave_a_job_of_no_run(
    dashboard_db: Path, tmp_path: Path
) -> None:
    """A job's own connection enforces the schema's foreign keys too.

    A job whose start would insert a job of no run fails with the refusal, and leaves no such row.
    """
    with get_db(dashboard_db) as conn:
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
        db_path=str(dashboard_db),
        data_dir=str(tmp_path / "data"),
    )
    assert manager.wait_until_idle(timeout=30)

    state = manager.job_state(job_id)
    assert state is not None
    assert (state.status, state.message) == ("failed", "FOREIGN KEY constraint failed")
    with get_db(dashboard_db) as conn:
        assert [row["id"] for row in conn.execute("SELECT id FROM jobs")] == [job_id]
