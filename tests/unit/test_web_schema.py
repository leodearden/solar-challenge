# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard store's schema version, held in its database file's PRAGMA user_version.

open_database creates a new store at schema.SCHEMA_VERSION, in one transaction, with one runs
column per RunRecord field (D27 invariant 7) and each table's constraints as its owner states
them. It refuses a store at any other version, a legacy store with no version being at version
0, with a SchemaVersionMismatch naming the file and both versions, and writes nothing to it.
migrate_store brings an older store to SCHEMA_VERSION, whose tables are then a new store's,
keeping its rows and naming each run that had no name after its kind (D27 invariant 7, part
2). A row a step's new constraints refuse makes migrate_store raise MigrationRefused, naming
the table, the row's id and the column, and leaves the store as it was; so do tables a step
cannot rebuild, naming the fault. Both refuse a file that is not a database with a
StoreUnreadable naming it, and leave it as it is. MIGRATIONS' versions
run from 1 without a gap, and SCHEMA_VERSION is the last of them (contract C5). A new store's
schema is the one committed for its version as tests/fixtures/databases/schema_v<N>.sql, and
version 1's step leaves a legacy store at the one committed for version 1, so a change to a
table's schema cannot ship without its migration step (contract C10).

Each run-document step of the stored-run format is carried by the migration step of its
version, so the format cannot pass the schema (D-S19-2). Version 2's carries the first:
migrate_store brings each run of a store at version 1, the legacy fixtures of
tests/_stored_run_fixtures among them, to the stored-run format, in its files and its runs row
alike, so each then loads (D-S19-5). It rewrites only the documents the step changes, then
writes the run's format.json, and reports each value it drops that is not null. A run whose
documents it cannot migrate, or cannot read, is left as it was and reported by id, document and
field, and the rest of the store migrates. A step that cannot write a run's file, or whose
transaction fails once it has brought the run files forward, is refused, leaving the database
at the version before it, and the migration run again once the fault is gone completes it.
Version 1 names a legacy run after its home as the format reads the run's config once migrated.
"""

import importlib.util
import json
import logging
import sqlite3
from collections.abc import Callable
from contextlib import closing
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.dispatch import TOUOptimizedStrategyConfig
from solar_challenge.web.chat_messages import CHAT_ROLES, get_chat_history
from solar_challenge.web.database import Database, RowRefused
from solar_challenge.web.presets import PRESET_TYPES, home_presets
from solar_challenge.web.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    MigrationRefused,
    MigrationReport,
    SchemaVersionMismatch,
    StoreUnreadable,
    migrate_store,
    open_database,
)
from solar_challenge.web.storage import RUN_STATUSES, RunRecord, RunStorage
from solar_challenge.web.stored_runs import (
    RUN_DOCUMENT_STEPS,
    RUN_FORMAT_VERSION,
    RUN_KINDS,
    RUN_TYPES,
    DroppedValue,
    RunType,
    StoredHomeRun,
    UnmigratedRun,
)
from tests._dashboard_databases import (
    FIXTURES_DIR,
    schema_of,
    write_database_a_newer_solar_challenge_wrote,
    write_database_at_schema_version_1,
    write_pre_548_database,
)
from tests._finance_builders import make_home_config, make_sim_results
from tests._run_storage_layout import stored_run_dir
from tests._stored_run_fixtures import FIXTURES_DIR as STORED_RUN_FIXTURES_DIR
from tests._stored_run_fixtures import STORED_RUN_FIXTURES, install_stored_run_fixture
from tests._web_runs import store_home_run

_NEEDS_PYARROW = pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None,
    reason="a stored run's time series is written and read with pyarrow, from the web extra",
)


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


def _create_statements(path: Path) -> str:
    """The statement creating each table and index of the database file at *path*, each ending ';', the tables first."""
    with closing(Database(path).connect()) as conn:
        rows = conn.execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
        ).fetchall()
    return "\n".join(f"{row['sql']};" for row in rows)


def _store_of_the_committed_schema(version: int, path: Path) -> Path:
    """A new database file at *path* holding the schema committed for *version*, tests/fixtures/databases/schema_v<version>.sql."""
    with closing(sqlite3.connect(path)) as conn:
        conn.executescript((FIXTURES_DIR / f"schema_v{version}.sql").read_text())
    return path


def test_a_new_store_has_the_committed_schema_of_its_version(tmp_path: Path) -> None:
    """Contract C10: a change to a table's schema changes a new store's, so it fails here until it ships as a new migration step, committed with its version's snapshot."""
    new_store = open_database(tmp_path / "new.db").path
    committed = FIXTURES_DIR / f"schema_v{SCHEMA_VERSION}.sql"
    remedy = (
        f"A new store's schema is not the schema of version {SCHEMA_VERSION} committed in {committed}. "
        "A change to a table's schema is a new migration step N, which brings a store at version N - 1 "
        f"to it, committed together with the schema of version N as {FIXTURES_DIR}/schema_v<N>.sql "
        f"(contract C10). A new store's schema is:\n{_create_statements(new_store)}"
    )
    assert committed.is_file(), remedy

    snapshot = _store_of_the_committed_schema(SCHEMA_VERSION, tmp_path / "snapshot.db")

    assert schema_of(snapshot) == schema_of(new_store), remedy


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
    newer = write_database_a_newer_solar_challenge_wrote(tmp_path / "newer.db")

    with pytest.raises(SchemaVersionMismatch) as refused:
        open_database(newer)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (newer, SCHEMA_VERSION + 1, SCHEMA_VERSION)
    message = str(refused.value)
    assert f"schema version {SCHEMA_VERSION + 1}" in message
    assert f"version {SCHEMA_VERSION}." in message
    assert "This database was written by a newer solar-challenge" in message


STORES_AT_ANOTHER_VERSION = [
    pytest.param(write_pre_548_database, id="legacy-store"),
    pytest.param(write_database_a_newer_solar_challenge_wrote, id="newer-store"),
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


def test_every_run_document_step_is_carried_by_the_migration_step_of_its_version() -> None:
    """D-S19-2: a format bump without a schema step is impossible, so the format version is never past the schema version."""
    carried = {step.version: step.run_documents for step in MIGRATIONS if step.run_documents is not None}

    assert list(carried) == [step.version for step in RUN_DOCUMENT_STEPS]
    for document_step in RUN_DOCUMENT_STEPS:
        assert carried[document_step.version] is document_step
    assert RUN_FORMAT_VERSION <= SCHEMA_VERSION


def test_schema_version_2_is_the_first_run_document_step_and_reports_its_description() -> None:
    """Version 2 changes no table: it brings every stored run to the stored-run format of version 2."""
    version_2 = MIGRATIONS[1]

    assert version_2.version == 2
    assert version_2.run_documents is RUN_DOCUMENT_STEPS[0]
    assert version_2.description == RUN_DOCUMENT_STEPS[0].description


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
    report = migrate_store(legacy_store, legacy_store.parent)

    assert report == MigrationReport(
        path=legacy_store, from_version=0, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS
    )
    assert _user_version(legacy_store) == SCHEMA_VERSION
    assert _runs_column_names(legacy_store) == [field.name for field in fields(RunRecord)]
    assert schema_of(legacy_store) == schema_of(open_database(tmp_path / "fresh.db").path)
    assert "jobs" not in _names_in_sqlite_master(legacy_store, "table")
    assert open_database(legacy_store) == Database(legacy_store)


def test_version_1s_step_rebuilds_a_legacy_stores_tables_to_the_schema_committed_for_version_1(
    legacy_store: Path, tmp_path: Path
) -> None:
    """Each table is rebuilt to its schema at version 1, not to its owner's current schema, so a later step that changes a table changes nothing version 1's step does."""
    with Database(legacy_store).transaction() as conn:
        conn.execute("BEGIN IMMEDIATE")
        MIGRATIONS[0].migrate_database(conn)

    assert schema_of(legacy_store) == schema_of(_store_of_the_committed_schema(1, tmp_path / "schema_v1.db"))


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

    migrate_store(legacy_store, legacy_store.parent)

    record = RunStorage(open_database(legacy_store), tmp_path).run_record(run_id)
    assert record is not None
    assert asdict(record) == {**row_before, "name": name}


def test_migrate_store_keeps_every_run_chat_message_and_saved_preset(legacy_store: Path) -> None:
    run_ids_before = set(_runs_rows(legacy_store))

    migrate_store(legacy_store, legacy_store.parent)

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

    migrate_store(legacy_store, legacy_store.parent)

    assert RunStorage(open_database(legacy_store), tmp_path).run_name("legacy-damaged") == RUN_KINDS[
        run_type
    ].default_name(())
    warnings = [record.getMessage() for record in caplog.records if record.levelno == logging.WARNING]
    assert any("legacy-damaged" in warning for warning in warnings), warnings


def test_migrate_store_names_a_nameless_run_stored_before_the_dispatch_union_after_its_home(legacy_store: Path) -> None:
    """Version 1 reads a legacy config as the stored-run format reads it once migrated.

    Such a config holds the null keys of the other dispatch variants, which no field has, so read
    as it is stored it would be refused, and its run named as a run of no homes.
    """
    pre_union = json.loads((STORED_RUN_FIXTURES_DIR / "pre_dispatch_union_home_configs.json").read_text())
    config = {**pre_union["self_consumption"], "name": "North Roof"}
    _insert_run(legacy_store, {"id": "legacy-pre-union", "name": None, "type": "home", "config_json": json.dumps(config)})

    migrate_store(legacy_store, legacy_store.parent)

    assert RunStorage(open_database(legacy_store), legacy_store.parent).run_name("legacy-pre-union") == "North Roof"


def test_migrate_store_applies_no_step_to_a_store_at_the_schema_version_and_writes_nothing_to_it(
    new_store: Database,
) -> None:
    bytes_before, schema_before = new_store.path.read_bytes(), schema_of(new_store.path)

    report = migrate_store(new_store.path, new_store.path.parent)

    assert report == MigrationReport(
        path=new_store.path, from_version=SCHEMA_VERSION, to_version=SCHEMA_VERSION, applied_steps=()
    )
    assert new_store.path.read_bytes() == bytes_before
    assert schema_of(new_store.path) == schema_before


def test_migrate_store_refuses_a_store_a_newer_solar_challenge_wrote_and_writes_nothing_to_it(tmp_path: Path) -> None:
    newer = write_database_a_newer_solar_challenge_wrote(tmp_path / "newer.db")
    bytes_before = newer.read_bytes()

    with pytest.raises(SchemaVersionMismatch) as refused:
        migrate_store(newer, newer.parent)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (newer, SCHEMA_VERSION + 1, SCHEMA_VERSION)
    assert "This database was written by a newer solar-challenge" in str(refused.value)
    assert newer.read_bytes() == bytes_before


def test_a_migration_report_reads_as_the_store_both_versions_and_each_step_applied_in_order(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    report = MigrationReport(path, from_version=0, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS)

    assert str(report).splitlines() == [
        f"Migrated the dashboard database {path} from schema version 0 to {SCHEMA_VERSION}:",
        *(f"  {step.version}. {step.description}" for step in MIGRATIONS),
    ]


def test_a_migration_report_of_no_step_reads_as_nothing_to_migrate(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    report = MigrationReport(path, from_version=SCHEMA_VERSION, to_version=SCHEMA_VERSION, applied_steps=())

    assert str(report) == (
        f"The dashboard database {path} is at schema version {SCHEMA_VERSION}; there is nothing to migrate."
    )


def test_migrate_store_creates_a_new_store_at_the_schema_version_where_there_is_no_database(tmp_path: Path) -> None:
    path = tmp_path / "store.db"

    report = migrate_store(path, path.parent)

    assert report == MigrationReport(path=path, from_version=SCHEMA_VERSION, to_version=SCHEMA_VERSION, applied_steps=())
    assert _user_version(path) == SCHEMA_VERSION
    assert schema_of(path) == schema_of(open_database(tmp_path / "fresh.db").path)


ROWS_V1_REFUSES = [
    pytest.param(
        {"id": "legacy-sweep", "name": "Sweep Run", "type": "sweep"},
        "type",
        ["'sweep'", "['home', 'fleet']"],
        id="a-sweep-run",
    ),
    pytest.param({"id": "legacy-untyped", "name": None, "type": None}, "name", [], id="a-nameless-run-of-no-type"),
]


@pytest.mark.parametrize(("row", "column", "named_in_the_reason"), ROWS_V1_REFUSES)
def test_migrate_store_refuses_a_row_a_constraint_of_version_1_refuses_naming_it_and_changes_nothing(
    legacy_store: Path, row: dict[str, object], column: str, named_in_the_reason: list[str]
) -> None:
    """Version 1 refuses a run type other than RUN_TYPES and a nameless run with no type to name it after."""
    _insert_run(legacy_store, row)
    schema_before, rows_before = schema_of(legacy_store), _runs_rows(legacy_store)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(legacy_store, legacy_store.parent)

    assert (refused.value.path, refused.value.step) == (legacy_store, MIGRATIONS[0])
    message = str(refused.value)
    for named in [str(legacy_store), "schema version 1", "stays at version 0", "runs", repr(row["id"]), column]:
        assert named in message, (named, message)
    for named in named_in_the_reason:
        assert named in message, (named, message)
    cause = refused.value.__cause__
    assert isinstance(cause, RowRefused)
    assert (cause.table, cause.row_id, cause.column) == ("runs", row["id"], column)
    assert schema_of(legacy_store) == schema_before
    assert _user_version(legacy_store) == 0
    assert _runs_rows(legacy_store) == rows_before


def test_a_migration_refused_is_not_a_value_error() -> None:
    """No request causes it: the migration that meets the row refuses to run."""
    assert not issubclass(MigrationRefused, ValueError)


STORES_WHOSE_TABLES_VERSION_1_CANNOT_REBUILD = [
    pytest.param("DROP TABLE config_presets", sqlite3.OperationalError, "config_presets", id="no-config-presets-table"),
    pytest.param(
        "CREATE TABLE run_tags (id TEXT PRIMARY KEY, run_id TEXT REFERENCES runs(id))",
        ValueError,
        "run_tags",
        id="another-table-references-runs",
    ),
]


@pytest.mark.parametrize(("damage", "fault", "named"), STORES_WHOSE_TABLES_VERSION_1_CANNOT_REBUILD)
def test_migrate_store_refuses_a_store_whose_tables_version_1_cannot_rebuild_naming_the_fault_and_changes_nothing(
    legacy_store: Path, damage: str, fault: type[Exception], named: str
) -> None:
    """No solar-challenge left such a store: each created all four legacy tables, and only jobs referenced runs."""
    with Database(legacy_store).transaction() as conn:
        conn.execute(damage)
    schema_before, rows_before = schema_of(legacy_store), _runs_rows(legacy_store)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(legacy_store, legacy_store.parent)

    assert (refused.value.path, refused.value.step) == (legacy_store, MIGRATIONS[0])
    message = str(refused.value)
    for each in [str(legacy_store), "schema version 1", "stays at version 0", named]:
        assert each in message, (each, message)
    assert isinstance(refused.value.__cause__, fault)
    assert schema_of(legacy_store) == schema_before
    assert _user_version(legacy_store) == 0
    assert _runs_rows(legacy_store) == rows_before


def _migrate_store_in_its_directory(path: Path) -> MigrationReport:
    """migrate_store of the store whose database file is *path*, its run files in the directory of *path*."""
    return migrate_store(path, path.parent)


@pytest.mark.parametrize(
    "open_or_migrate",
    [pytest.param(open_database, id="open_database"), pytest.param(_migrate_store_in_its_directory, id="migrate_store")],
)
def test_a_file_that_is_not_a_database_is_refused_naming_it_and_left_as_it_is(
    open_or_migrate: Callable[[Path], object], tmp_path: Path
) -> None:
    path = tmp_path / "store.db"
    path.write_bytes(b"not a database")

    with pytest.raises(StoreUnreadable) as refused:
        open_or_migrate(path)

    assert refused.value.path == path
    message = str(refused.value)
    for named in [str(path), "cannot be read", "file is not a database"]:
        assert named in message, (named, message)
    assert isinstance(refused.value.__cause__, sqlite3.DatabaseError)
    assert path.read_bytes() == b"not a database"


def test_a_store_unreadable_is_not_a_value_error() -> None:
    """No request causes it, so it is a start-up refusal, as SchemaVersionMismatch is."""
    assert not issubclass(StoreUnreadable, ValueError)


def test_migrate_store_keeps_a_named_run_of_no_type_with_no_type(legacy_store: Path, tmp_path: Path) -> None:
    """Only a run with no name needs a kind to be named after, so a named run of no type migrates as it is."""
    _insert_run(legacy_store, {"id": "legacy-untyped-named", "name": "Untyped Run", "type": None})

    migrate_store(legacy_store, legacy_store.parent)

    record = RunStorage(open_database(legacy_store), tmp_path).run_record("legacy-untyped-named")
    assert record is not None
    assert (record.name, record.type) == ("Untyped Run", None)


@pytest.fixture
def store_at_version_1(tmp_path: Path) -> Path:
    """The database file of a store a solar-challenge at schema version 1 left in tmp_path/store, the directory of its run files."""
    return write_database_at_schema_version_1(tmp_path / "store" / "solar-challenge.db")


@pytest.fixture
def legacy_run_ids(store_at_version_1: Path) -> dict[str, str]:
    """The run id of each legacy stored-run fixture, by name, each installed in store_at_version_1: its runs row and its run directory."""
    database = Database(store_at_version_1)
    return {name: install_stored_run_fixture(name, database, store_at_version_1.parent) for name in STORED_RUN_FIXTURES}


def _run_dir(database_path: Path, run_id: str) -> Path:
    """The directory of run *run_id*'s files in the store whose database file is *database_path*, its run files in that file's directory."""
    return stored_run_dir(RunStorage(Database(database_path), database_path.parent), run_id)


def _files_of(run_dir: Path) -> dict[str, bytes]:
    """The bytes of each file in *run_dir* and its subdirectories, keyed by its POSIX path relative to *run_dir*."""
    return {path.relative_to(run_dir).as_posix(): path.read_bytes() for path in sorted(run_dir.rglob("*")) if path.is_file()}


Edit = Callable[[dict[str, Any]], None]


def _setting(key: str, value: object) -> Edit:
    """An edit setting a document's root key *key* to *value*."""

    def edit(document: dict[str, Any]) -> None:
        document[key] = value

    return edit


def _deleting(key: str) -> Edit:
    """An edit deleting a document's root key *key*."""

    def edit(document: dict[str, Any]) -> None:
        del document[key]

    return edit


def _edit_stored_document(path: Path, edit: Edit) -> None:
    """Rewrite the JSON document at *path*, a file of a run's directory, with *edit* applied to its content."""
    document = json.loads(path.read_text())
    edit(document)
    path.write_text(json.dumps(document, indent=2))


def _edit_runs_document(database_path: Path, run_id: str, column: str, edit: Edit) -> None:
    """Rewrite run *run_id*'s *column*, config_json or summary_json, with *edit* applied to the document it holds."""
    document = json.loads(_runs_rows(database_path)[run_id][column])
    edit(document)
    with Database(database_path).transaction() as conn:
        conn.execute(f"UPDATE runs SET {column} = ? WHERE id = ?", (json.dumps(document), run_id))


def _storage_of(database_path: Path) -> RunStorage:
    """The RunStorage of the store at SCHEMA_VERSION whose database file is *database_path*, its run files in that file's directory."""
    return RunStorage(open_database(database_path), database_path.parent)


def test_migrate_store_brings_a_store_at_version_1_to_the_schema_version_reporting_no_value_of_the_legacy_runs(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """The legacy runs hold no key v2 drops but the null keys of the other dispatch variants, a null value it drops unreported."""
    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert report == MigrationReport(
        path=store_at_version_1, from_version=1, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS[1:]
    )
    assert _user_version(store_at_version_1) == SCHEMA_VERSION


@_NEEDS_PYARROW
@pytest.mark.parametrize("name", STORED_RUN_FIXTURES)
def test_after_migrate_store_each_legacy_run_carries_the_format_version_and_loads(
    store_at_version_1: Path, legacy_run_ids: dict[str, str], name: str
) -> None:
    """B5's second half, at the store: a run stored before runs carried a format version loads once migrated."""
    run_id = legacy_run_ids[name]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    marker = json.loads((_run_dir(store_at_version_1, run_id) / "format.json").read_text())
    assert marker == {"format_version": RUN_FORMAT_VERSION}
    assert _storage_of(store_at_version_1).load_run(run_id).run_id == run_id


@_NEEDS_PYARROW
def test_after_migrate_store_a_run_stored_before_469_loads_with_no_grid_charge(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """Its summary has no total_grid_charge_kwh, so the field takes its default."""
    run_id = legacy_run_ids["pre_469_home"]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    loaded = _storage_of(store_at_version_1).load_run(run_id)
    assert isinstance(loaded, StoredHomeRun)
    assert loaded.summary.total_grid_charge_kwh == 0.0


@_NEEDS_PYARROW
def test_after_migrate_store_a_run_stored_before_786_reads_its_battery_dispatch_as_its_variant_from_its_files_and_its_row(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    run_id = legacy_run_ids["pre_786_dispatch_home"]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    storage = _storage_of(store_at_version_1)
    loaded = storage.load_run(run_id)
    record = storage.run_record(run_id)
    assert isinstance(loaded, StoredHomeRun)
    assert record is not None
    home_configs = record.home_configs()
    assert home_configs is not None
    for config in (loaded.config, *home_configs):
        assert config.battery_config is not None
        assert config.battery_config.dispatch_strategy == TOUOptimizedStrategyConfig(peak_hours=((16, 19),))


def test_migrate_store_drops_the_keys_v2_drops_from_a_run_s_files_and_its_runs_row_alike(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """The pre-786 run's dispatch strategy loses the other variants' null keys in config.json and runs.config_json."""
    run_id = legacy_run_ids["pre_786_dispatch_home"]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    configs = [
        json.loads((_run_dir(store_at_version_1, run_id) / "config.json").read_text()),
        json.loads(_runs_rows(store_at_version_1)[run_id]["config_json"]),
    ]
    assert [config["battery_config"]["dispatch_strategy"] for config in configs] == [
        {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]}
    ] * 2


def test_migrate_store_rewrites_only_the_documents_v2_changes_and_adds_each_run_s_format_marker_leaving_no_other_file(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """Every document and runs column v2 does not change is left byte for byte, and no temporary file is left behind."""
    files_before = {run_id: _files_of(_run_dir(store_at_version_1, run_id)) for run_id in legacy_run_ids.values()}
    rows_before = _runs_rows(store_at_version_1)
    pre_786 = legacy_run_ids["pre_786_dispatch_home"]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    rows_after = _runs_rows(store_at_version_1)
    for run_id, before in files_before.items():
        after = _files_of(_run_dir(store_at_version_1, run_id))
        assert set(after) == {*before, "format.json"}, run_id
        assert {path for path in before if after[path] != before[path]} == ({"config.json"} if run_id == pre_786 else set())
        assert {column for column, value in rows_before[run_id].items() if rows_after[run_id][column] != value} == (
            {"config_json"} if run_id == pre_786 else set()
        )


def test_migrate_store_reports_each_value_it_drops_that_is_not_null_naming_the_run_both_documents_and_the_field(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """A null value it drops, the retired setting's here and the other dispatch variants' keys of the pre-786 run, goes unreported."""
    run_id = install_stored_run_fixture(
        "pre_469_home", Database(store_at_version_1), store_at_version_1.parent, run_id="retired-keys"
    )
    run_dir = _run_dir(store_at_version_1, run_id)
    _edit_stored_document(run_dir / "summary.json", _setting("retired_figure", 12.5))
    _edit_runs_document(store_at_version_1, run_id, "summary_json", _setting("retired_figure", 12.5))
    _edit_stored_document(run_dir / "config.json", _setting("retired_setting", None))

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert len(report.dropped_values) == 2
    assert set(report.dropped_values) == {
        DroppedValue(run_id, "summary.json", "retired_figure", 12.5),
        DroppedValue(run_id, "runs.summary_json", "retired_figure", 12.5),
    }
    assert "retired_figure" not in json.loads((run_dir / "summary.json").read_text())
    assert "retired_figure" not in json.loads(_runs_rows(store_at_version_1)[run_id]["summary_json"])
    assert "retired_setting" not in json.loads((run_dir / "config.json").read_text())


@_NEEDS_PYARROW
def test_migrate_store_leaves_each_run_it_cannot_migrate_as_it_was_reports_it_and_migrates_every_other_run(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """D-S19-5: a run whose documents no step can make readable, which cannot be loaded today either, is reported by id, document and field."""
    lacking = install_stored_run_fixture(
        "pre_786_dispatch_home", Database(store_at_version_1), store_at_version_1.parent, run_id="lacking-generation"
    )
    _edit_stored_document(_run_dir(store_at_version_1, lacking) / "summary.json", _deleting("total_generation_kwh"))
    _edit_runs_document(store_at_version_1, lacking, "summary_json", _deleting("total_generation_kwh"))
    _insert_run(
        store_at_version_1,
        {"id": "garbled-config", "name": "Garbled", "type": "home", "config_json": "{not json", "status": "completed"},
    )
    files_before, rows_before = _files_of(_run_dir(store_at_version_1, lacking)), _runs_rows(store_at_version_1)

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert len(report.unmigrated_runs) == 3
    assert {(each.run_id, each.document, each.field) for each in report.unmigrated_runs} == {
        (lacking, "summary.json", "total_generation_kwh"),
        (lacking, "runs.summary_json", "total_generation_kwh"),
        ("garbled-config", "runs.config_json", None),
    }
    assert all(each.reason for each in report.unmigrated_runs)
    assert _files_of(_run_dir(store_at_version_1, lacking)) == files_before
    assert not (_run_dir(store_at_version_1, lacking) / "format.json").exists()
    rows_after = _runs_rows(store_at_version_1)
    assert [rows_after[run_id] for run_id in (lacking, "garbled-config")] == [
        rows_before[run_id] for run_id in (lacking, "garbled-config")
    ]
    assert _user_version(store_at_version_1) == SCHEMA_VERSION
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())


def test_migrate_store_reports_a_run_of_no_type_once_as_unmigrated_naming_its_type_and_leaves_it_as_it_was(
    store_at_version_1: Path,
) -> None:
    """A run of no type is of no kind, so no step can read its documents, whether its files or its row's copies."""
    run_id = install_stored_run_fixture(
        "pre_786_dispatch_home", Database(store_at_version_1), store_at_version_1.parent, run_id="untyped"
    )
    with Database(store_at_version_1).transaction() as conn:
        conn.execute("UPDATE runs SET type = NULL WHERE id = ?", (run_id,))
    files_before, row_before = _files_of(_run_dir(store_at_version_1, run_id)), _runs_rows(store_at_version_1)[run_id]

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document, each.field) for each in report.unmigrated_runs] == [(run_id, "runs.type", None)]
    assert _files_of(_run_dir(store_at_version_1, run_id)) == files_before
    assert _runs_rows(store_at_version_1)[run_id] == row_before


def _put_a_directory_in_place_of(path: Path) -> None:
    """Put a directory where the file at *path* is, or is to be written: no user can read or write it as a file, whereas a file's permissions do not bind a root user."""
    path.unlink(missing_ok=True)
    path.mkdir()


@_NEEDS_PYARROW
def test_migrate_store_reports_a_run_whose_document_cannot_be_read_as_unmigrated_and_migrates_every_other_run(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """A directory in the place of a run's summary.json stands in for a document that cannot be read, e.g. for its permissions."""
    unreadable = install_stored_run_fixture(
        "pre_469_home", Database(store_at_version_1), store_at_version_1.parent, run_id="unreadable-summary"
    )
    run_dir = _run_dir(store_at_version_1, unreadable)
    _put_a_directory_in_place_of(run_dir / "summary.json")
    files_before = _files_of(run_dir)

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document, each.field) for each in report.unmigrated_runs] == [
        (unreadable, "summary.json", None)
    ]
    assert "is unreadable" in report.unmigrated_runs[0].reason
    assert _files_of(run_dir) == files_before
    assert not (run_dir / "format.json").exists()
    assert _user_version(store_at_version_1) == SCHEMA_VERSION
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())


@_NEEDS_PYARROW
def test_migrate_store_refuses_a_step_that_cannot_write_a_run_s_file_and_run_again_once_it_can_migrates_the_store(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """A directory in the place of the legacy fleet run's format.json stands in for a file a step cannot write, e.g. on a full disk.

    The step stops there, leaving the database at version 1 and no temporary file in the run's
    directory; the runs it brought forward before the fault are brought forward again.
    """
    fleet_dir = _run_dir(store_at_version_1, legacy_run_ids["legacy_fleet"])
    _put_a_directory_in_place_of(fleet_dir / "format.json")
    fleet_files_before, rows_before = _files_of(fleet_dir), _runs_rows(store_at_version_1)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (refused.value.path, refused.value.step) == (store_at_version_1, MIGRATIONS[1])
    assert isinstance(refused.value.__cause__, OSError)
    message = str(refused.value)
    for named in [str(store_at_version_1), "schema version 2", "stays at version 1", str(fleet_dir / "format.json")]:
        assert named in message, (named, message)
    assert _user_version(store_at_version_1) == 1
    assert _runs_rows(store_at_version_1) == rows_before
    assert _files_of(fleet_dir) == fleet_files_before

    (fleet_dir / "format.json").rmdir()
    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert report == MigrationReport(
        path=store_at_version_1, from_version=1, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS[1:]
    )
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())


@_NEEDS_PYARROW
def test_a_migration_whose_transaction_fails_after_its_run_files_are_brought_forward_migrates_the_store_when_run_again(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """A trigger refusing each update of a runs row fails version 2's transaction, once its run-file part has given every run its format.json.

    Run again once the trigger is dropped, the migration brings those files forward again,
    changing nothing in them, and brings the runs rows forward.
    """
    with Database(store_at_version_1).transaction() as conn:
        conn.execute(
            "CREATE TRIGGER refuse_run_updates BEFORE UPDATE ON runs BEGIN SELECT RAISE(ABORT, 'no run may be updated'); END"
        )
    rows_before = _runs_rows(store_at_version_1)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(store_at_version_1, store_at_version_1.parent)

    assert refused.value.step == MIGRATIONS[1]
    assert isinstance(refused.value.__cause__, sqlite3.IntegrityError)
    assert "no run may be updated" in str(refused.value)
    assert _user_version(store_at_version_1) == 1
    assert _runs_rows(store_at_version_1) == rows_before
    files_brought_forward = {run_id: _files_of(_run_dir(store_at_version_1, run_id)) for run_id in legacy_run_ids.values()}
    markers = [json.loads(files["format.json"]) for files in files_brought_forward.values()]
    assert markers == [{"format_version": RUN_FORMAT_VERSION}] * len(legacy_run_ids)

    with Database(store_at_version_1).transaction() as conn:
        conn.execute("DROP TRIGGER refuse_run_updates")
    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert report == MigrationReport(
        path=store_at_version_1, from_version=1, to_version=SCHEMA_VERSION, applied_steps=MIGRATIONS[1:]
    )
    assert {run_id: _files_of(_run_dir(store_at_version_1, run_id)) for run_id in legacy_run_ids.values()} == (
        files_brought_forward
    )
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())
    record = storage.run_record(legacy_run_ids["pre_786_dispatch_home"])
    assert record is not None
    [config] = record.home_configs() or ()
    assert config.battery_config is not None
    assert config.battery_config.dispatch_strategy == TOUOptimizedStrategyConfig(peak_hours=((16, 19),))


@_NEEDS_PYARROW
def test_migrate_store_writes_nothing_to_a_store_at_the_schema_version_nor_to_its_runs_files(tmp_path: Path) -> None:
    """Every run of a store at SCHEMA_VERSION is in the current format, so no run-document step is pending."""
    database = open_database(tmp_path / "store.db")
    storage = RunStorage(database, tmp_path)
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
    files_before, bytes_before = _files_of(stored_run_dir(storage, "home-1")), database.path.read_bytes()

    report = migrate_store(database.path, tmp_path)

    assert report.applied_steps == ()
    assert database.path.read_bytes() == bytes_before
    assert _files_of(stored_run_dir(storage, "home-1")) == files_before


def test_a_migration_report_lists_each_value_dropped_and_each_run_left_unmigrated_after_the_steps(tmp_path: Path) -> None:
    path = tmp_path / "store.db"
    dropped = DroppedValue("run-1", "summary.json", "retired_figure", 12.5)
    unmigrated = UnmigratedRun(
        "run-2", "runs.summary_json", "total_generation_kwh", "is missing, and SummaryStatistics has no default for it"
    )
    report = MigrationReport(
        path,
        from_version=1,
        to_version=SCHEMA_VERSION,
        applied_steps=MIGRATIONS[1:],
        dropped_values=(dropped,),
        unmigrated_runs=(unmigrated,),
    )

    lines = str(report).splitlines()

    steps = [f"  {step.version}. {step.description}" for step in MIGRATIONS[1:]]
    assert lines[: 1 + len(steps)] == [
        f"Migrated the dashboard database {path} from schema version 1 to {SCHEMA_VERSION}:",
        *steps,
    ]
    [dropped_line] = [line for line in lines if "run-1" in line]
    [unmigrated_line] = [line for line in lines if "run-2" in line]
    for named in ["summary.json", "retired_figure", "12.5"]:
        assert named in dropped_line, (named, dropped_line)
    for named in ["runs.summary_json", "total_generation_kwh", unmigrated.reason]:
        assert named in unmigrated_line, (named, unmigrated_line)
    assert len(steps) < lines.index(dropped_line) < lines.index(unmigrated_line)


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
