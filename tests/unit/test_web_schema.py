# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard store's schema version, held in its database file's PRAGMA user_version.

open_database creates a new store at schema.SCHEMA_VERSION, in one transaction, with one runs
column per RunRecord field (D27 invariant 7) and each table's constraints as its owner states
them. It refuses a store at any other version, a legacy store with no version being at version
0, with a SchemaVersionMismatch naming the file and both versions, and writes nothing to it.
migrate_store brings an older store to SCHEMA_VERSION, whose tables are then a new store's,
keeping its rows and naming each run that had no name after its kind (D27 invariant 7, part
2). MIGRATIONS' versions run from 1 without a gap, and SCHEMA_VERSION is the last of them
(contract C5).
"""

import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.web.database import CHAT_ROLES, Database, get_chat_history
from solar_challenge.web.presets import PRESET_TYPES, home_presets
from solar_challenge.web.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    MigrationReport,
    SchemaVersionMismatch,
    migrate_store,
    open_database,
)
from solar_challenge.web.storage import RUN_STATUSES, RunRecord, RunStorage
from solar_challenge.web.stored_runs import RUN_KINDS, RUN_TYPES, RunType
from tests._dashboard_databases import schema_of, write_pre_548_database


def _user_version(path: Path) -> int:
    """The schema version the database file at *path* records: its PRAGMA user_version."""
    with closing(Database(path).connect()) as conn:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])


def _names_in_sqlite_master(path: Path, object_type: str) -> set[str]:
    """The name of each *object_type* object, e.g. each table, the database file at *path* holds."""
    with closing(Database(path).connect()) as conn:
        return {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = ?", (object_type,))}


def _runs_column_names(path: Path) -> list[str]:
    """The name of each column of the runs table of the database file at *path*, in order."""
    with closing(Database(path).connect()) as conn:
        return [row["name"] for row in conn.execute("PRAGMA table_info(runs)")]


@pytest.fixture
def new_store(tmp_path: Path) -> Database:
    """A new store, which open_database created."""
    return open_database(tmp_path / "store.db")


def test_open_database_creates_a_new_store_at_the_schema_version_with_one_runs_column_per_run_record_field(
    tmp_path: Path,
) -> None:
    """D27 invariant 7, for a new store."""
    path = tmp_path / "nested" / "store.db"

    database = open_database(path)

    assert path.parent.is_dir() and path.is_file()
    assert database == Database(path)
    assert _user_version(path) == SCHEMA_VERSION
    assert _runs_column_names(path) == [field.name for field in fields(RunRecord)]


def test_a_new_store_holds_the_runs_chat_messages_and_config_presets_tables_and_their_indexes_in_wal_mode(
    new_store: Database,
) -> None:
    """There is no jobs table: a job's state lives in its JobManager, and its run's row is its outcome."""
    assert _names_in_sqlite_master(new_store.path, "table") == {
        "runs",
        "chat_messages",
        "config_presets",
        "sqlite_sequence",
    }
    assert {name for name in _names_in_sqlite_master(new_store.path, "index") if not name.startswith("sqlite_")} == {
        "idx_runs_created_at",
        "idx_runs_type",
        "idx_chat_messages_session_id",
    }
    with closing(new_store.connect()) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_open_database_opens_a_store_it_created_as_it_is(new_store: Database) -> None:
    schema_before = schema_of(new_store.path)

    assert open_database(new_store.path) == new_store

    assert schema_of(new_store.path) == schema_before
    assert _user_version(new_store.path) == SCHEMA_VERSION


def test_open_database_creates_a_store_all_or_nothing_so_a_statement_that_fails_leaves_no_table(
    tmp_path: Path,
) -> None:
    """A view named like the chat_messages index, the last statement of a creation, fails its CREATE INDEX."""
    path = tmp_path / "store.db"
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("CREATE VIEW idx_chat_messages_session_id AS SELECT 1")
        conn.commit()

    with pytest.raises(sqlite3.OperationalError, match="idx_chat_messages_session_id"):
        open_database(path)

    assert _names_in_sqlite_master(path, "table") == set(), "open_database must create a store in one transaction"
    assert _user_version(path) == 0


def _store_a_newer_solar_challenge_wrote(path: Path) -> Path:
    """A store open_database created at *path*, then recorded at SCHEMA_VERSION + 1, as a newer solar-challenge records it."""
    open_database(path)
    with closing(Database(path).connect()) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    return path


def test_open_database_refuses_a_legacy_store_naming_it_both_versions_and_the_migrate_command(tmp_path: Path) -> None:
    legacy = write_pre_548_database(tmp_path / "legacy.db")

    with pytest.raises(SchemaVersionMismatch) as refused:
        open_database(legacy)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (legacy, 0, SCHEMA_VERSION)
    message = str(refused.value)
    assert str(legacy) in message
    assert "schema version 0" in message
    assert f"version {SCHEMA_VERSION}" in message
    assert "Run `solar-challenge web migrate`" in message


def test_open_database_refuses_a_store_a_newer_solar_challenge_wrote_naming_both_versions(tmp_path: Path) -> None:
    newer = _store_a_newer_solar_challenge_wrote(tmp_path / "newer.db")

    with pytest.raises(SchemaVersionMismatch) as refused:
        open_database(newer)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (newer, SCHEMA_VERSION + 1, SCHEMA_VERSION)
    message = str(refused.value)
    assert f"schema version {SCHEMA_VERSION + 1}" in message
    assert f"version {SCHEMA_VERSION}." in message
    assert "This database was written by a newer solar-challenge" in message


STORES_AT_ANOTHER_VERSION = [
    pytest.param(write_pre_548_database, id="legacy-store"),
    pytest.param(_store_a_newer_solar_challenge_wrote, id="newer-store"),
]


@pytest.mark.parametrize("store_at_another_version", STORES_AT_ANOTHER_VERSION)
def test_open_database_writes_nothing_to_a_store_it_refuses(
    store_at_another_version: Callable[[Path], Path], tmp_path: Path
) -> None:
    path = store_at_another_version(tmp_path / "store.db")
    bytes_before, schema_before, version_before = path.read_bytes(), schema_of(path), _user_version(path)

    with pytest.raises(SchemaVersionMismatch):
        open_database(path)

    assert path.read_bytes() == bytes_before
    assert schema_of(path) == schema_before
    assert _user_version(path) == version_before


def test_a_schema_version_mismatch_is_not_a_value_error() -> None:
    """It is a start-up refusal, as StoreLockError is: no request causes it, so no request boundary answers it with a 400."""
    assert not issubclass(SchemaVersionMismatch, ValueError)


def test_the_migration_steps_versions_run_from_1_without_a_gap_and_the_schema_version_is_the_last() -> None:
    """Contract C5: each step brings a store at the version before it to its own version."""
    assert [step.version for step in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
    assert SCHEMA_VERSION == MIGRATIONS[-1].version
    assert all(step.description.strip() for step in MIGRATIONS)


@pytest.fixture
def legacy_store(tmp_path: Path) -> Path:
    """The pre-548 store, as an older solar-challenge left it: at version 0, with the jobs table and runs with no name."""
    return write_pre_548_database(tmp_path / "legacy.db")


def _runs_rows(path: Path) -> dict[str, dict[str, Any]]:
    """Each row of the runs table of the database file at *path*, as its columns by name, keyed by its id."""
    with closing(Database(path).connect()) as conn:
        return {row["id"]: dict(row) for row in conn.execute("SELECT * FROM runs")}


def _insert_run(path: Path, columns: dict[str, object]) -> None:
    """Insert into the runs table of the database file at *path* the row *columns* gives by column name."""
    names = ", ".join(columns)
    placeholders = ", ".join(f":{name}" for name in columns)
    with Database(path).transaction() as conn:
        conn.execute(f"INSERT INTO runs ({names}) VALUES ({placeholders})", columns)


def test_migrate_store_brings_a_legacy_store_to_the_schema_version_with_the_tables_of_a_new_store(
    legacy_store: Path, tmp_path: Path
) -> None:
    """D27 invariant 7, part 2: the migrated store holds one runs column per RunRecord field, and no jobs table."""
    report = migrate_store(legacy_store)

    assert report == MigrationReport(
        path=legacy_store, from_version=0, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS
    )
    assert _user_version(legacy_store) == SCHEMA_VERSION
    assert _runs_column_names(legacy_store) == [field.name for field in fields(RunRecord)]
    assert schema_of(legacy_store) == schema_of(open_database(tmp_path / "fresh.db").path)
    assert "jobs" not in _names_in_sqlite_master(legacy_store, "table")
    assert open_database(legacy_store) == Database(legacy_store)


@pytest.mark.parametrize(
    ("run_id", "name"),
    [
        pytest.param("legacy-named-home", "South Roof", id="a-named-run-keeps-its-name"),
        pytest.param("legacy-nameless-home", "North Roof", id="a-nameless-home-run-is-named-after-its-home"),
        pytest.param("legacy-blank-home", "Web Simulation", id="a-blank-named-run-of-a-nameless-home"),
        pytest.param("legacy-nameless-fleet", "Fleet Simulation", id="a-nameless-fleet-run"),
    ],
)
def test_migrate_store_names_each_run_with_no_name_as_a_job_given_none_names_it_and_keeps_its_other_columns(
    legacy_store: Path, tmp_path: Path, run_id: str, name: str
) -> None:
    """Contract C7: a migrated run's name is never NULL or blank; its kind's default_name names it after its homes."""
    row_before = _runs_rows(legacy_store)[run_id]

    migrate_store(legacy_store)

    record = RunStorage(open_database(legacy_store), tmp_path).run_record(run_id)
    assert record is not None
    assert asdict(record) == {**row_before, "name": name}


def test_migrate_store_keeps_every_run_chat_message_and_saved_preset(legacy_store: Path) -> None:
    run_ids_before = set(_runs_rows(legacy_store))

    migrate_store(legacy_store)

    database = open_database(legacy_store)
    assert set(_runs_rows(legacy_store)) == run_ids_before
    assert get_chat_history(database, "legacy-session") == [
        {
            "role": "user",
            "content": "How much did South Roof generate?",
            "created_at": "2025-06-01T09:05:00+00:00",
            "metadata": None,
        }
    ]
    assert [preset for preset in home_presets(database) if preset["source"] == "saved"] == [
        {
            "pv_kw": 3.5,
            "battery_kwh": 0,
            "consumption_kwh": 3000,
            "name": "Legacy Preset",
            "created_at": "2025-06-01T08:00:00+00:00",
            "source": "saved",
        }
    ]


@pytest.mark.parametrize("run_type", RUN_TYPES)
def test_migrate_store_names_a_nameless_run_whose_config_does_not_decode_as_its_kind_names_a_run_of_no_homes(
    legacy_store: Path, tmp_path: Path, caplog: pytest.LogCaptureFixture, run_type: RunType
) -> None:
    """A damaged config does not strand the store: its run is named, and a warning names the run."""
    _insert_run(legacy_store, {"id": "legacy-damaged", "name": None, "type": run_type, "config_json": "{not json"})
    caplog.set_level(logging.WARNING)

    migrate_store(legacy_store)

    assert RunStorage(open_database(legacy_store), tmp_path).run_name("legacy-damaged") == RUN_KINDS[
        run_type
    ].default_name(())
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any("legacy-damaged" in warning for warning in warnings), warnings


def test_migrate_store_applies_no_step_to_a_store_at_the_schema_version_and_writes_nothing_to_it(
    new_store: Database,
) -> None:
    bytes_before, schema_before = new_store.path.read_bytes(), schema_of(new_store.path)

    report = migrate_store(new_store.path)

    assert report == MigrationReport(
        path=new_store.path, from_version=SCHEMA_VERSION, to_version=SCHEMA_VERSION, applied_steps=()
    )
    assert new_store.path.read_bytes() == bytes_before
    assert schema_of(new_store.path) == schema_before


def test_migrate_store_refuses_a_store_a_newer_solar_challenge_wrote_and_writes_nothing_to_it(tmp_path: Path) -> None:
    newer = _store_a_newer_solar_challenge_wrote(tmp_path / "newer.db")
    bytes_before = newer.read_bytes()

    with pytest.raises(SchemaVersionMismatch) as refused:
        migrate_store(newer)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (newer, SCHEMA_VERSION + 1, SCHEMA_VERSION)
    assert "This database was written by a newer solar-challenge" in str(refused.value)
    assert newer.read_bytes() == bytes_before


def test_migrate_store_creates_a_new_store_at_the_schema_version_where_there_is_no_database(tmp_path: Path) -> None:
    path = tmp_path / "store.db"

    report = migrate_store(path)

    assert report == MigrationReport(path=path, from_version=SCHEMA_VERSION, to_version=SCHEMA_VERSION, applied_steps=())
    assert _user_version(path) == SCHEMA_VERSION
    assert schema_of(path) == schema_of(open_database(tmp_path / "fresh.db").path)


RUNS_COLUMN_VALUES = [
    *(pytest.param("type", run_type, id=f"type-{run_type}") for run_type in RUN_TYPES),
    pytest.param("type", None, id="type-null"),
    *(pytest.param("status", run_status, id=f"status-{run_status}") for run_status in RUN_STATUSES),
    pytest.param("status", None, id="status-null"),
]

VALUES_OUTSIDE_THE_RUNS_COLUMN_DEFINITIONS = [
    pytest.param("type", "hom", id="type-typo"),
    pytest.param("type", "Home", id="type-capitalised"),
    pytest.param("type", "sweep", id="type-sweep"),
    pytest.param("status", "complete", id="status-typo"),
    pytest.param("status", "queued", id="status-a-job-status"),
]

CHAT_MESSAGES_AND_CONFIG_PRESETS_COLUMN_VALUES = [
    *(pytest.param("chat_messages", "role", chat_role, id=f"chat_messages-role-{chat_role}") for chat_role in CHAT_ROLES),
    pytest.param("chat_messages", "role", None, id="chat_messages-role-null"),
    *(
        pytest.param("config_presets", "type", preset_type, id=f"config_presets-type-{preset_type}")
        for preset_type in PRESET_TYPES
    ),
    pytest.param("config_presets", "type", None, id="config_presets-type-null"),
]

VALUES_OUTSIDE_THE_CHAT_MESSAGES_AND_CONFIG_PRESETS_COLUMN_DEFINITIONS = [
    pytest.param("chat_messages", "role", "system", id="chat_messages-role-system"),
    pytest.param("chat_messages", "role", "User", id="chat_messages-role-capitalised"),
    pytest.param("config_presets", "type", "sweep", id="config_presets-type-sweep"),
    pytest.param("config_presets", "type", "Home", id="config_presets-type-capitalised"),
]


@pytest.mark.parametrize(("column", "value"), RUNS_COLUMN_VALUES)
def test_a_new_stores_runs_table_accepts_each_run_type_and_run_status_and_null(
    new_store: Database, column: str, value: str | None
) -> None:
    """The runs table stores each run type or NULL as a run's type, and each run status or NULL as its status."""
    with new_store.transaction() as conn:
        conn.execute(f"INSERT INTO runs (id, name, {column}) VALUES (?, ?, ?)", ("probe", "Probe", value))
        stored = conn.execute(f"SELECT {column} FROM runs WHERE id = 'probe'").fetchone()[0]

    assert stored == value


@pytest.mark.parametrize(("column", "value"), VALUES_OUTSIDE_THE_RUNS_COLUMN_DEFINITIONS)
def test_a_new_stores_runs_table_refuses_a_type_or_status_outside_its_definition(
    new_store: Database, column: str, value: str
) -> None:
    """The runs table refuses a type that is not a run type, and a status that is not a run status."""
    with new_store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(f"INSERT INTO runs (id, name, {column}) VALUES (?, ?, ?)", ("probe", "Probe", value))


def test_a_new_store_gives_a_run_inserted_without_a_status_the_status_running(new_store: Database) -> None:
    with new_store.transaction() as conn:
        conn.execute("INSERT INTO runs (id, name) VALUES ('no-status', 'No Status')")
        status = conn.execute("SELECT status FROM runs WHERE id = 'no-status'").fetchone()[0]

    assert status == "running"


def test_a_new_stores_runs_table_refuses_a_run_with_no_name(new_store: Database) -> None:
    """Contract C7: a run's name is never NULL."""
    with new_store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL constraint failed: runs.name"):
            conn.execute("INSERT INTO runs (id) VALUES ('r')")


@pytest.mark.parametrize(("table", "column", "value"), CHAT_MESSAGES_AND_CONFIG_PRESETS_COLUMN_VALUES)
def test_a_new_stores_chat_messages_and_config_presets_tables_accept_each_defined_value_and_null(
    new_store: Database, table: str, column: str, value: str | None
) -> None:
    """chat_messages stores each chat role or NULL as a message's role, and config_presets each preset type or NULL as a preset's type."""
    with new_store.transaction() as conn:
        rowid = conn.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,)).lastrowid
        stored = conn.execute(f"SELECT {column} FROM {table} WHERE rowid = ?", (rowid,)).fetchone()[0]

    assert stored == value


@pytest.mark.parametrize(("table", "column", "value"), VALUES_OUTSIDE_THE_CHAT_MESSAGES_AND_CONFIG_PRESETS_COLUMN_DEFINITIONS)
def test_a_new_stores_chat_messages_and_config_presets_tables_refuse_a_value_outside_its_definition(
    new_store: Database, table: str, column: str, value: str
) -> None:
    """chat_messages refuses a role that is not a chat role, and config_presets a type that is not a preset type."""
    with new_store.transaction() as conn:
        with pytest.raises(sqlite3.IntegrityError, match="CHECK constraint failed"):
            conn.execute(f"INSERT INTO {table} ({column}) VALUES (?)", (value,))
