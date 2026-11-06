# SPDX-License-Identifier: AGPL-3.0-or-later
"""Dashboard database files for tests: a store as an older solar-challenge left it, a store a newer one wrote, and the schema of any store.

write_pre_548_database writes the store tests/fixtures/databases/pre_548_store.sql holds: the
schema init_db created before task 548, whose runs table admits 'sweep' runs and nameless runs
and which keeps the retired jobs table, with a few rows and no schema version.
write_database_at_schema_version writes an empty store at a schema version N, whose schema
schema_v<N>.sql holds: the store a solar-challenge at that version created.
write_database_a_newer_solar_challenge_wrote writes a store at the schema version after
SCHEMA_VERSION. schema_of reads a database's schema as data, so a test can compare two stores'
schemas. user_version_of and runs_rows_of read a database's schema version and its runs rows,
and insert_runs_row writes a runs row with SQL, so a test can read or seed a store at any
schema version, which open_database would refuse. None of these four creates a database: each
refuses a path no file is at. FIXTURES_DIR is the directory holding the database fixtures.

Usage::

    from tests._dashboard_databases import schema_of, write_pre_548_database

    legacy = write_pre_548_database(tmp_path / "legacy.db")
    assert ("table", "jobs", "jobs") in [entry[:3] for entry in schema_of(legacy)]
"""

import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any

from solar_challenge.web.database import Database
from solar_challenge.web.schema import SCHEMA_VERSION, open_database

FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures" / "databases"


def write_pre_548_database(path: Path) -> Path:
    """Write the store pre_548_store.sql holds as a new database file at *path*, creating its directory; return *path*.

    Raises:
        FileExistsError: A file is already at *path*, so the store would not be the fixture's alone.
    """
    return _write_new_database(path, "the pre-548 store", (FIXTURES_DIR / "pre_548_store.sql").read_text())


def write_database_at_schema_version(path: Path, version: int) -> Path:
    """Write a store at schema version *version* as a new database file at *path*, creating its directory; return *path*.

    Its schema is the one schema_v<version>.sql holds, its tables hold no row, its user_version
    is *version* and it journals in WAL mode, as a store a solar-challenge at that schema version
    created does.

    Raises:
        FileNotFoundError: No schema_v<version>.sql is committed in FIXTURES_DIR, so no file is written.
        FileExistsError: A file is already at *path*, so the store would not be the fixture's alone.
    """
    script = (FIXTURES_DIR / f"schema_v{version}.sql").read_text()
    return _write_new_database(
        path,
        f"the store at schema version {version}",
        f"PRAGMA journal_mode=WAL;\n{script}\nPRAGMA user_version = {version};\n",
    )


def _write_new_database(path: Path, store: str, script: str) -> Path:
    """Run the SQL *script* on a new database file at *path*, creating its directory; return *path*.

    Raises:
        FileExistsError: A file is already at *path*; the message names it and *store*, what the
            file would have held.
    """
    if path.exists():
        raise FileExistsError(f"A file is already at {path}; {store} is written as a new file")
    path.parent.mkdir(parents=True, exist_ok=True)
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
    _refuse_a_missing_database(path)
    with closing(sqlite3.connect(path)) as conn:
        rows = conn.execute("SELECT type, name, tbl_name, sql FROM sqlite_master").fetchall()
    return sorted((row[0], row[1], row[2], row[3]) for row in rows)


def user_version_of(path: Path) -> int:
    """The schema version the database file at *path* records: its PRAGMA user_version.

    Raises:
        FileNotFoundError: No file is at *path*; reading a schema version never creates a database.
    """
    _refuse_a_missing_database(path)
    with closing(Database(path).connect()) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def runs_rows_of(path: Path) -> dict[str, dict[str, Any]]:
    """Each row of the runs table of the database file at *path*, as its columns by name, keyed by its id.

    Raises:
        FileNotFoundError: No file is at *path*; reading runs rows never creates a database.
    """
    _refuse_a_missing_database(path)
    with closing(Database(path).connect()) as conn:
        return {row["id"]: dict(row) for row in conn.execute("SELECT * FROM runs")}


def insert_runs_row(path: Path, columns: dict[str, object]) -> None:
    """Insert into the runs table of the database file at *path* the row *columns* gives by column name.

    Raises:
        FileNotFoundError: No file is at *path*; seeding a store never creates a database.
    """
    _refuse_a_missing_database(path)
    names = ", ".join(columns)
    placeholders = ", ".join(f":{name}" for name in columns)
    with Database(path).transaction() as conn:
        conn.execute(f"INSERT INTO runs ({names}) VALUES ({placeholders})", columns)


def _refuse_a_missing_database(path: Path) -> None:
    """Refuse *path* before anything opens it when no file is at it, since sqlite3.connect creates the file it is pointed at.

    Raises:
        FileNotFoundError: No file is at *path*; the message names it.
    """
    if not path.is_file():
        raise FileNotFoundError(f"No database file is at {path}")
