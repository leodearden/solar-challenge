# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dashboard database files for tests: a store as an older solar-challenge left it, a store a newer one wrote, and the schema of any store.

write_pre_548_database writes the store tests/fixtures/databases/pre_548_store.sql holds: the
schema init_db created before task 548, whose runs table admits 'sweep' runs and nameless runs
and which keeps the retired jobs table, with a few rows and no schema version.
write_database_a_newer_solar_challenge_wrote writes a store at the schema version after
SCHEMA_VERSION. schema_of reads a database's schema as data, so a test can compare two stores'
schemas. FIXTURES_DIR is the directory holding the database fixtures.

Usage::

    from tests._dashboard_databases import schema_of, write_pre_548_database

    legacy = write_pre_548_database(tmp_path / "legacy.db")
    assert ("table", "jobs", "jobs") in [entry[:3] for entry in schema_of(legacy)]
"""

import sqlite3
from contextlib import closing
from pathlib import Path

from solar_challenge.web.database import Database
from solar_challenge.web.schema import SCHEMA_VERSION, open_database

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "databases"


def write_pre_548_database(path: Path) -> Path:
    """Write the store pre_548_store.sql holds as a new database file at *path*, creating its directory; return *path*.

    Raises:
        FileExistsError: A file is already at *path*, so the store would not be the fixture's alone.
    """
    if path.exists():
        raise FileExistsError(f"A file is already at {path}; the pre-548 store is written as a new file")
    path.parent.mkdir(parents=True, exist_ok=True)
    script = (FIXTURES_DIR / "pre_548_store.sql").read_text()
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript(script)
    return path


def write_database_a_newer_solar_challenge_wrote(path: Path) -> Path:
    """A store open_database created at *path*, then recorded at SCHEMA_VERSION + 1, as a newer solar-challenge records it; return *path*."""
    open_database(path)
    with closing(Database(path).connect()) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    return path


def schema_of(path: Path) -> list[tuple[str, str, str, str | None]]:
    """Every row of the sqlite_master of the database at *path*, as (type, name, tbl_name, sql), sorted.

    Its rootpage is left out: two databases of one schema can hold a table at different pages.

    Raises:
        FileNotFoundError: No file is at *path*; reading a schema never creates a database.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No database file is at {path}")
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
    return sorted((row[0], row[1], row[2], row[3]) for row in rows)
