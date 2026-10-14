# SPDX-License-Identifier: AGPL-3.0-or-later
"""Reads of the jobs table, where a JobManager records the jobs it is given."""

from typing import Any

from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage


def job_rows(storage: RunStorage) -> list[tuple[str, str]]:
    """Return (id, run_id) of every row in storage's jobs table."""
    with get_db(storage.db_path) as conn:
        return [(row["id"], row["run_id"]) for row in conn.execute("SELECT id, run_id FROM jobs")]


def job_row(storage: RunStorage, job_id: str) -> dict[str, Any]:
    """Return every column of job *job_id*'s row in storage's jobs table, by name."""
    with get_db(storage.db_path) as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None, f"storage's jobs table has no row for job {job_id}"
    return dict(row)
