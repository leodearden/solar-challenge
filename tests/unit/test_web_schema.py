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
schema is the one committed for its version as schema_v<N>.sql in tests/fixtures/databases, and
version 1's step leaves a legacy store at the one committed for version 1, so a change to a
table's schema cannot ship without its migration step (contract C10).

Each run-document step of the stored-run format is carried by the migration step of its
version, so the format cannot pass the schema (D-S19-2). Version 2's carries the first:
migrate_store brings each run of a store at version 1, the legacy fixtures of
tests/_stored_run_fixtures.py among them, to the stored-run format, in its files and its runs row
alike, so each then loads (D-S19-5). It rewrites only the documents the step changes, then
writes the run's format.json, and reports each value it drops that is not null. A run whose
documents it cannot migrate, or cannot read, is left as it was and reported by id, document and
field, and the rest of the store migrates. A step that cannot write a run's file, or whose
transaction fails once it has brought the run files forward, is refused, leaving the database
at the version before it, and the migration run again once the fault is gone completes it.
Version 1 names a legacy run after its home as the format reads the run's config once migrated.
A store at version 2, whose runs a solar-challenge at that version saved in format 2, is brought
forward by the steps after version 2 alone, version 3's reading each home's dispatch as it ran.
A run that store's migration left in format 1, with no format.json, has its files brought
forward by every step after format 1, so it is reported, if at all, by its own fault. After its
steps, migrate_store catches up: it brings forward each run an earlier migration left, also in a
store at SCHEMA_VERSION, which has no step to apply, once the run's documents are fixed, and
reports again each it still cannot migrate.
"""

import functools
import importlib.util
import json
import logging
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.dispatch import (
    DispatchStrategyConfig,
    GridChargeConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.home import HomeConfig
from solar_challenge.web.chat_messages import CHAT_ROLES, get_chat_history
from solar_challenge.web.database import Database, RowRefused
from solar_challenge.web.presets import PRESET_TYPES, home_presets
from solar_challenge.web.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    LaggingRunsRefused,
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
    RewrittenValue,
    RunType,
    StoredFleetRun,
    StoredHomeRun,
    UnmigratedRun,
    write_run_documents,
)
from tests._dashboard_databases import (
    FIXTURES_DIR,
    schema_of,
    write_database_a_newer_solar_challenge_wrote,
    write_database_at_schema_version,
    write_pre_548_database,
)
from tests._finance_builders import make_home_config, make_sim_results
from tests._run_storage_layout import stored_run_dir
from tests._run_stores import empty_run_storage, run_storage_over
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

    snapshot = write_database_at_schema_version(tmp_path / "snapshot.db", SCHEMA_VERSION)

    assert schema_of(snapshot) == schema_of(new_store), remedy


STORES_AT_AN_OLDER_VERSION = [
    pytest.param(write_pre_548_database, 0, id="legacy-store"),
    pytest.param(functools.partial(write_database_at_schema_version, version=2), 2, id="store-at-version-2"),
]
"""A writer of a store at a schema version below SCHEMA_VERSION, then that version; a legacy store, with no version, is at version 0."""


@pytest.mark.parametrize(("store_at_an_older_version", "version"), STORES_AT_AN_OLDER_VERSION)
def test_open_database_refuses_a_store_at_an_older_version_naming_it_both_versions_and_the_migrate_command(
    store_at_an_older_version: Callable[[Path], Path], version: int, tmp_path: Path
) -> None:
    path = store_at_an_older_version(tmp_path / "store.db")

    with pytest.raises(SchemaVersionMismatch) as refused:
        open_database(path)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (path, version, SCHEMA_VERSION)
    message = str(refused.value)
    assert str(path) in message
    assert f"schema version {version}" in message
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
    *STORES_AT_AN_OLDER_VERSION,
    pytest.param(write_database_a_newer_solar_challenge_wrote, SCHEMA_VERSION + 1, id="newer-store"),
]


@pytest.mark.parametrize(("store_at_another_version", "version"), STORES_AT_ANOTHER_VERSION)
def test_open_database_writes_nothing_to_a_store_it_refuses(
    store_at_another_version: Callable[[Path], Path], version: int, tmp_path: Path
) -> None:
    path = store_at_another_version(tmp_path / "store.db")
    bytes_before, schema_before = path.read_bytes(), schema_of(path)

    with pytest.raises(SchemaVersionMismatch):
        open_database(path)

    assert path.read_bytes() == bytes_before
    assert schema_of(path) == schema_before
    assert _user_version(path) == version


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


def test_schema_version_3_is_the_dispatch_as_it_ran_step_and_reports_its_description() -> None:
    """Version 3 changes no table: it brings every stored run to the stored-run format of version 3."""
    version_3 = MIGRATIONS[2]

    assert version_3.version == 3
    assert version_3.run_documents is RUN_DOCUMENT_STEPS[1]
    assert version_3.description == RUN_DOCUMENT_STEPS[1].description


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

    assert schema_of(legacy_store) == schema_of(write_database_at_schema_version(tmp_path / "schema_v1.db", 1))


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

    record = run_storage_over(open_database(legacy_store)).run_record(run_id)
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

    assert run_storage_over(open_database(legacy_store)).run_name("legacy-damaged") == RUN_KINDS[
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

    assert run_storage_over(open_database(legacy_store)).run_name("legacy-pre-union") == "North Roof"


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

    record = run_storage_over(open_database(legacy_store)).run_record("legacy-untyped-named")
    assert record is not None
    assert (record.name, record.type) == ("Untyped Run", None)


@pytest.fixture
def store_at_version_1(tmp_path: Path) -> Path:
    """The database file of a store a solar-challenge at schema version 1 left in tmp_path/store, the directory of its run files."""
    return write_database_at_schema_version(tmp_path / "store" / "solar-challenge.db", 1)


@pytest.fixture
def legacy_run_ids(store_at_version_1: Path) -> dict[str, str]:
    """The run id of each legacy stored-run fixture, by name, each installed in store_at_version_1: its runs row and its run directory."""
    database = Database(store_at_version_1)
    return {name: install_stored_run_fixture(name, database, store_at_version_1.parent) for name in STORED_RUN_FIXTURES}


_FIXTURES_IN_FORMAT_2 = ("pre_469_home", "legacy_fleet", "pre_787_dispatch_fleet")
"""The legacy stored-run fixtures whose documents version 2's step leaves as they are, so a store at schema version 2 holds them as committed.

pre_787_dispatch_fleet is the one a solar-challenge at format 2 saved. pre_786_dispatch_home is
left out: its dispatch strategy holds the other variants' null keys, which v2 drops.
"""


@pytest.fixture
def store_at_version_2(tmp_path: Path) -> Path:
    """The database file of a store a solar-challenge at schema version 2 left in tmp_path/store, the directory of its run files."""
    return write_database_at_schema_version(tmp_path / "store" / "solar-challenge.db", 2)


@pytest.fixture
def format_2_run_ids(store_at_version_2: Path) -> dict[str, str]:
    """The run id of each of _FIXTURES_IN_FORMAT_2, by name, each installed in store_at_version_2 with the format.json naming 2 a save at format 2 left."""
    database = Database(store_at_version_2)
    run_ids = {name: install_stored_run_fixture(name, database, store_at_version_2.parent) for name in _FIXTURES_IN_FORMAT_2}
    for run_id in run_ids.values():
        write_run_documents(_run_dir(store_at_version_2, run_id), (), 2)
    return run_ids


@dataclass(frozen=True)
class _OlderStore:
    """A store a solar-challenge at schema *version*, below SCHEMA_VERSION, left at *path*, its run files in that file's directory.

    *run_ids* is the run id of each legacy stored-run fixture it holds, by the fixture's name.
    """

    path: Path
    version: int
    run_ids: Mapping[str, str]


@pytest.fixture(
    params=[
        pytest.param((1, "store_at_version_1", "legacy_run_ids"), id="store-at-version-1"),
        pytest.param((2, "store_at_version_2", "format_2_run_ids"), id="store-at-version-2"),
    ]
)
def older_store(request: pytest.FixtureRequest) -> _OlderStore:
    """store_at_version_1 holding legacy_run_ids, then store_at_version_2 holding format_2_run_ids."""
    version, path_fixture, run_ids_fixture = request.param
    return _OlderStore(request.getfixturevalue(path_fixture), version, request.getfixturevalue(run_ids_fixture))


def _run_dir(database_path: Path, run_id: str) -> Path:
    """The directory of run *run_id*'s files in the store whose database file is *database_path*, its run files in that file's directory."""
    return stored_run_dir(run_storage_over(Database(database_path)), run_id)


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
    return run_storage_over(open_database(database_path))


_PRE_787_FLEET_FIELDS_V3_CHANGES = (
    ("homes[0].battery_config.grid_charging", {"target_soc_fraction": 0.8}, None),
    ("homes[1].battery_config.grid_charging", {"target_soc_fraction": 0.8}, None),
    ("homes[2].dispatch_strategy", "tou_optimized", "greedy"),
    ("homes[2].battery_config.grid_charging", {"target_soc_fraction": 0.8}, None),
)
"""Each field of pre_787_dispatch_fleet's config that v3 sets to the dispatch its home ran by, the value it held and the one it holds now."""


def _values_v3_changes_in_the_pre_787_fleet(run_id: str) -> tuple[RewrittenValue, ...]:
    """The values migrate_store reports v3 rewrote in pre_787_dispatch_fleet, installed as run *run_id*: its config.json's, then its runs row's."""
    return tuple(
        RewrittenValue(run_id, document, field, was, now)
        for document in ("config.json", "runs.config_json")
        for field, was, now in _PRE_787_FLEET_FIELDS_V3_CHANGES
    )


def test_migrate_store_brings_an_older_store_to_the_schema_version_by_the_steps_after_its_own_reporting_only_the_values_v3_changes_in_the_pre_787_fleet(
    older_store: _OlderStore,
) -> None:
    """A store at version 2, each run's format.json naming 2, is migrated without version 2's step.

    The legacy runs hold no key v2 drops but the null keys of the other dispatch variants, a null value it drops unreported.
    """
    report = migrate_store(older_store.path, older_store.path.parent)

    assert report == MigrationReport(
        path=older_store.path,
        from_version=older_store.version,
        to_version=SCHEMA_VERSION,
        applied_steps=MIGRATIONS[older_store.version :],
        rewritten_values=_values_v3_changes_in_the_pre_787_fleet(older_store.run_ids["pre_787_dispatch_fleet"]),
    )
    assert _user_version(older_store.path) == SCHEMA_VERSION


@_NEEDS_PYARROW
def test_after_migrate_store_each_legacy_run_of_an_older_store_carries_the_format_version_and_loads(
    older_store: _OlderStore,
) -> None:
    """B5's second half, at the store: a run stored before runs carried a format version, or at format 2, loads once migrated."""
    run_ids = list(older_store.run_ids.values())

    migrate_store(older_store.path, older_store.path.parent)

    markers = [json.loads((_run_dir(older_store.path, run_id) / "format.json").read_text()) for run_id in run_ids]
    assert markers == [{"format_version": RUN_FORMAT_VERSION}] * len(run_ids)
    storage = _storage_of(older_store.path)
    assert [storage.load_run(run_id).run_id for run_id in run_ids] == run_ids


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


def _dispatch_settings(home: HomeConfig) -> tuple[str, str, DispatchStrategyConfig | None, GridChargeConfig | None]:
    """*home*'s name and dispatch_strategy, then its battery's dispatch_strategy and grid_charging; *home* has a battery."""
    battery = home.battery_config
    assert battery is not None, f"{home.name} has no battery"
    return (home.name, home.dispatch_strategy, battery.dispatch_strategy, battery.grid_charging)


@_NEEDS_PYARROW
def test_after_migrate_store_the_pre_787_fleet_of_a_store_at_version_2_reads_each_home_s_dispatch_as_it_ran_from_its_files_and_its_row(
    store_at_version_2: Path, format_2_run_ids: dict[str, str]
) -> None:
    """Before the migration, its documents hold the three shapes HomeConfig has refused since task 787.

    They are grid_charging under self-consumption, grid_charging with no tariff, and home
    tou_optimized with no tariff. Each now reads as the dispatch its run ran by.
    """
    run_id = format_2_run_ids["pre_787_dispatch_fleet"]

    migrate_store(store_at_version_2, store_at_version_2.parent)

    storage = _storage_of(store_at_version_2)
    loaded = storage.load_run(run_id)
    record = storage.run_record(run_id)
    assert isinstance(loaded, StoredFleetRun)
    assert record is not None
    for homes in (tuple(loaded.fleet_results.home_configs), record.home_configs()):
        assert homes is not None
        assert [_dispatch_settings(home) for home in homes] == [
            ("Elm Row 1", "greedy", SelfConsumptionStrategyConfig(), None),
            ("Elm Row 2", "greedy", TOUOptimizedStrategyConfig(peak_hours=((16, 19),)), None),
            ("Elm Row 3", "greedy", None, None),
        ]


def _install_a_run_in_format_1(database_path: Path, run_id: str) -> str:
    """Install pre_786_dispatch_home as run *run_id* in the store whose database file is *database_path*, its run files in that file's directory; return the id.

    The run has no format.json, so its documents are in format 1. In a store at version 2 that
    is a run the migration to version 2 left as it was. Its config holds the other dispatch
    variants' null keys, which v2 drops and v3 alone would refuse.
    """
    return install_stored_run_fixture("pre_786_dispatch_home", Database(database_path), database_path.parent, run_id=run_id)


@_NEEDS_PYARROW
def test_migrate_store_brings_the_files_of_a_run_an_earlier_migration_left_in_format_1_forward_by_every_step_after_it(
    store_at_version_2: Path,
) -> None:
    """The run stands for one the migration to version 2 left, whose documents have since been fixed: v2, then v3, bring it forward."""
    left = _install_a_run_in_format_1(store_at_version_2, "left-by-v2")

    report = migrate_store(store_at_version_2, store_at_version_2.parent)

    run_dir = _run_dir(store_at_version_2, left)
    assert json.loads((run_dir / "format.json").read_text()) == {"format_version": RUN_FORMAT_VERSION}
    config = json.loads((run_dir / "config.json").read_text())
    assert config["battery_config"]["dispatch_strategy"] == {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]}
    assert [
        each for each in report.unmigrated_runs if each.run_id == left and each.document in ("config.json", "summary.json")
    ] == []
    assert _storage_of(store_at_version_2).load_run(left).run_id == left


def test_migrate_store_reports_the_files_of_a_run_an_earlier_migration_left_by_their_own_fault_not_by_a_key_the_skipped_step_drops(
    store_at_version_2: Path,
) -> None:
    """Its summary.json lacks a figure SummaryStatistics requires; its config.json's import_limit_kw, which v2 drops, is no fault of it.

    Only its files' report is checked here; its runs row's is checked apart.
    """
    lacking = _install_a_run_in_format_1(store_at_version_2, "lacking-generation")
    run_dir = _run_dir(store_at_version_2, lacking)
    _edit_stored_document(run_dir / "summary.json", _deleting("total_generation_kwh"))
    files_before = _files_of(run_dir)

    report = migrate_store(store_at_version_2, store_at_version_2.parent)

    reported = {(each.run_id, each.document, each.field) for each in report.unmigrated_runs}
    assert (lacking, "summary.json", "total_generation_kwh") in reported
    assert (lacking, "config.json", "battery_config.dispatch_strategy.import_limit_kw") not in reported
    assert _files_of(run_dir) == files_before
    assert not (run_dir / "format.json").exists()


def test_migrate_store_brings_the_runs_row_of_a_run_an_earlier_migration_left_in_format_1_forward_by_every_step_after_it(
    store_at_version_2: Path,
) -> None:
    """A runs row records no format: one that v3 alone cannot bring forward from format 2 is brought forward from format 1, by v2 then v3."""
    left = _install_a_run_in_format_1(store_at_version_2, "left-by-v2")

    report = migrate_store(store_at_version_2, store_at_version_2.parent)

    config = json.loads(_runs_rows(store_at_version_2)[left]["config_json"])
    assert config["battery_config"]["dispatch_strategy"] == {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]}
    record = _storage_of(store_at_version_2).run_record(left)
    assert record is not None
    [home] = record.home_configs() or ()
    assert home.battery_config is not None
    assert home.battery_config.dispatch_strategy == TOUOptimizedStrategyConfig(peak_hours=((16, 19),))
    assert [each for each in report.unmigrated_runs if each.run_id == left] == []


def _install_a_run_lacking_generation(database_path: Path) -> str:
    """Install _install_a_run_in_format_1's run as 'lacking-generation', without total_generation_kwh, which SummaryStatistics requires, in its summary.json and its runs.summary_json; return the id."""
    lacking = _install_a_run_in_format_1(database_path, "lacking-generation")
    _edit_stored_document(_run_dir(database_path, lacking) / "summary.json", _deleting("total_generation_kwh"))
    _edit_runs_document(database_path, lacking, "summary_json", _deleting("total_generation_kwh"))
    return lacking


def test_migrate_store_reports_each_source_of_a_run_an_earlier_migration_left_once_by_its_own_fault(
    store_at_version_2: Path,
) -> None:
    """Its files and its runs row are each reported by the figure their summary lacks, not by the import_limit_kw v2 drops from their config."""
    lacking = _install_a_run_lacking_generation(store_at_version_2)
    row_before = _runs_rows(store_at_version_2)[lacking]

    report = migrate_store(store_at_version_2, store_at_version_2.parent)

    assert len(report.unmigrated_runs) == 2
    assert {(each.run_id, each.document, each.field) for each in report.unmigrated_runs} == {
        (lacking, "summary.json", "total_generation_kwh"),
        (lacking, "runs.summary_json", "total_generation_kwh"),
    }
    assert _runs_rows(store_at_version_2)[lacking] == row_before


@_NEEDS_PYARROW
def test_migrate_store_brings_forward_a_run_an_earlier_migration_left_once_its_documents_are_fixed(
    store_at_version_1: Path,
) -> None:
    """The store is at SCHEMA_VERSION by the time the run's summaries hold the figure they lacked, so no step is pending; the run is brought forward even so."""
    lacking = _install_a_run_lacking_generation(store_at_version_1)
    first = migrate_store(store_at_version_1, store_at_version_1.parent)
    assert [each.run_id for each in first.unmigrated_runs] == [lacking, lacking]
    committed = json.loads((STORED_RUN_FIXTURES_DIR / "pre_786_dispatch_home" / "run" / "summary.json").read_text())
    restore = _setting("total_generation_kwh", committed["total_generation_kwh"])
    _edit_stored_document(_run_dir(store_at_version_1, lacking) / "summary.json", restore)
    _edit_runs_document(store_at_version_1, lacking, "summary_json", restore)

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert report == MigrationReport(
        store_at_version_1,
        from_version=SCHEMA_VERSION,
        to_version=SCHEMA_VERSION,
        applied_steps=(),
        brought_forward_runs=(lacking,),
    )
    marker = json.loads((_run_dir(store_at_version_1, lacking) / "format.json").read_text())
    assert marker == {"format_version": RUN_FORMAT_VERSION}
    storage = _storage_of(store_at_version_1)
    loaded = storage.load_run(lacking)
    record = storage.run_record(lacking)
    assert isinstance(loaded, StoredHomeRun)
    assert record is not None
    assert record.summary() == loaded.summary
    assert _user_version(store_at_version_1) == SCHEMA_VERSION


def test_migrate_store_reports_again_each_run_an_earlier_migration_left_that_still_cannot_be_migrated(
    store_at_version_1: Path,
) -> None:
    """Run again on the store, now at SCHEMA_VERSION, the migration applies no step but tries the run again, and reports each of its sources as the first migration did."""
    lacking = _install_a_run_lacking_generation(store_at_version_1)
    first = migrate_store(store_at_version_1, store_at_version_1.parent)
    assert [each.run_id for each in first.unmigrated_runs] == [lacking, lacking]
    files_after_first, rows_after_first = _files_of(_run_dir(store_at_version_1, lacking)), _runs_rows(store_at_version_1)

    second = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (second.applied_steps, second.brought_forward_runs) == ((), ())
    assert second.unmigrated_runs == first.unmigrated_runs
    assert _files_of(_run_dir(store_at_version_1, lacking)) == files_after_first
    assert _runs_rows(store_at_version_1) == rows_after_first
    assert _user_version(store_at_version_1) == SCHEMA_VERSION


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


_CONFIG_EACH_RUN_DOCUMENT_STEP_REWRITES = (
    (2, "pre_786_dispatch_home"),
    (3, "pre_787_dispatch_fleet"),
)
"""Each run-document step's version and the legacy stored-run fixture whose config it rewrites.

v2 drops the pre-786 run's null dispatch keys, and v3 sets the pre-787 fleet's dispatch to the one each home ran by.
"""


def test_migrate_store_rewrites_only_the_documents_the_steps_change_and_writes_each_run_s_format_marker_leaving_no_other_file(
    older_store: _OlderStore,
) -> None:
    """Every document and runs column no step changes is left byte for byte, and no temporary file is left behind.

    Each run's format.json is added, or rewritten where a save at format 2 left one.
    """
    store = older_store.path
    files_before = {run_id: _files_of(_run_dir(store, run_id)) for run_id in older_store.run_ids.values()}
    rows_before = _runs_rows(store)
    rewritten = {
        older_store.run_ids[name] for version, name in _CONFIG_EACH_RUN_DOCUMENT_STEP_REWRITES if version > older_store.version
    }

    migrate_store(store, store.parent)

    rows_after = _runs_rows(store)
    for run_id, before in files_before.items():
        after = _files_of(_run_dir(store, run_id))
        assert set(after) == {*before, "format.json"}, run_id
        assert {path for path in after if after[path] != before.get(path)} == (
            {"config.json", "format.json"} if run_id in rewritten else {"format.json"}
        ), run_id
        assert {column for column, value in rows_before[run_id].items() if rows_after[run_id][column] != value} == (
            {"config_json"} if run_id in rewritten else set()
        ), run_id


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

    dropped = [each for each in report.dropped_values if each.run_id == run_id]
    assert len(dropped) == 2
    assert set(dropped) == {
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
    """D-S19-5: a run whose documents no step can make readable, which cannot be loaded today either, is reported by id, document and field.

    Each run is reported once per document source, by the fault that keeps it from the step that
    left it, because no later step of the migration is given it.
    """
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


def test_migrate_store_still_brings_forward_the_runs_row_of_a_run_whose_files_a_step_left_unmigrated(
    store_at_version_1: Path,
) -> None:
    """A fleet run missing a home's summary file is left unmigrated in its files alone, so v3 still rewrites its runs row."""
    copy = install_stored_run_fixture(
        "pre_787_dispatch_fleet", Database(store_at_version_1), store_at_version_1.parent, run_id="missing-home-summary"
    )
    (_run_dir(store_at_version_1, copy) / "homes" / "home_0_summary.json").unlink()

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document) for each in report.unmigrated_runs] == [(copy, "homes/home_0_summary.json")]
    assert tuple(each for each in report.rewritten_values if each.run_id == copy) == tuple(
        RewrittenValue(copy, "runs.config_json", field, was, now) for field, was, now in _PRE_787_FLEET_FIELDS_V3_CHANGES
    )
    assert json.loads(_runs_rows(store_at_version_1)[copy]["config_json"])["homes"][2]["dispatch_strategy"] == "greedy"


@_NEEDS_PYARROW
def test_migrate_store_still_brings_forward_the_files_of_a_run_whose_runs_row_a_step_left_unmigrated(
    store_at_version_1: Path,
) -> None:
    """A fleet run whose runs.config_json is not JSON is left unmigrated in its runs row alone, so v3 still rewrites its files."""
    copy = install_stored_run_fixture(
        "pre_787_dispatch_fleet", Database(store_at_version_1), store_at_version_1.parent, run_id="garbled-row-config"
    )
    with Database(store_at_version_1).transaction() as conn:
        conn.execute("UPDATE runs SET config_json = '{not json' WHERE id = ?", (copy,))

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document, each.field) for each in report.unmigrated_runs] == [(copy, "runs.config_json", None)]
    assert tuple(each for each in report.rewritten_values if each.run_id == copy) == tuple(
        RewrittenValue(copy, "config.json", field, was, now) for field, was, now in _PRE_787_FLEET_FIELDS_V3_CHANGES
    )
    marker = json.loads((_run_dir(store_at_version_1, copy) / "format.json").read_text())
    assert marker == {"format_version": RUN_FORMAT_VERSION}
    assert _storage_of(store_at_version_1).load_run(copy).run_id == copy


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
    directory; the runs it brought forward before the fault keep their format.json naming 2, so
    the migration run again brings them on by v3 alone.
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
        path=store_at_version_1,
        from_version=1,
        to_version=SCHEMA_VERSION,
        applied_steps=MIGRATIONS[1:],
        rewritten_values=_values_v3_changes_in_the_pre_787_fleet(legacy_run_ids["pre_787_dispatch_fleet"]),
    )
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())


@_NEEDS_PYARROW
def test_a_migration_whose_transaction_fails_after_its_run_files_are_brought_forward_migrates_the_store_when_run_again(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """A trigger refusing each update of a runs row fails version 2's transaction, once its run-file part has given every run its format.json.

    Run again once the trigger is dropped, the migration leaves those files as they are until
    v3, as they are in format 2 already, then brings them forward by v3, and brings the runs
    rows forward.
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
    assert markers == [{"format_version": 2}] * len(legacy_run_ids)

    with Database(store_at_version_1).transaction() as conn:
        conn.execute("DROP TRIGGER refuse_run_updates")
    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    pre_787 = legacy_run_ids["pre_787_dispatch_fleet"]
    assert report == MigrationReport(
        path=store_at_version_1,
        from_version=1,
        to_version=SCHEMA_VERSION,
        applied_steps=MIGRATIONS[1:],
        rewritten_values=_values_v3_changes_in_the_pre_787_fleet(pre_787),
    )
    for run_id, before in files_brought_forward.items():
        after = _files_of(_run_dir(store_at_version_1, run_id))
        assert {path for path in before if after[path] != before[path]} == (
            {"format.json", "config.json"} if run_id == pre_787 else {"format.json"}
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
    storage = empty_run_storage(tmp_path)
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
    files_before, bytes_before = _files_of(stored_run_dir(storage, "home-1")), storage.database.path.read_bytes()

    report = migrate_store(storage.database.path, storage.data_dir)

    assert report.applied_steps == ()
    assert storage.database.path.read_bytes() == bytes_before
    assert _files_of(stored_run_dir(storage, "home-1")) == files_before


@_NEEDS_PYARROW
def test_migrate_store_refuses_a_lagging_run_s_file_it_cannot_write_and_run_again_once_it_can_brings_the_run_forward(
    tmp_path: Path,
) -> None:
    """A directory in the place of the format.json of a run in format 1, in a store at SCHEMA_VERSION, stands in for a file the catch-up cannot write, e.g. on a full disk."""
    store = open_database(tmp_path / "store" / "solar-challenge.db").path
    run_id = install_stored_run_fixture("pre_469_home", Database(store), store.parent)
    marker = _run_dir(store, run_id) / "format.json"
    _put_a_directory_in_place_of(marker)
    files_before = _files_of(_run_dir(store, run_id))

    with pytest.raises(LaggingRunsRefused) as refused:
        migrate_store(store, store.parent)

    assert isinstance(refused.value.__cause__, OSError)
    message = str(refused.value)
    for named in [str(store), f"schema version {SCHEMA_VERSION}", str(RUN_FORMAT_VERSION), str(marker)]:
        assert named in message, (named, message)
    assert _user_version(store) == SCHEMA_VERSION
    assert _files_of(_run_dir(store, run_id)) == files_before

    marker.rmdir()
    report = migrate_store(store, store.parent)

    assert report.brought_forward_runs == (run_id,)
    assert _storage_of(store).load_run(run_id).run_id == run_id


def test_a_lagging_runs_refused_is_not_a_value_error() -> None:
    """No request causes it: the migration that meets the fault refuses to go on."""
    assert not issubclass(LaggingRunsRefused, ValueError)


def test_a_migration_report_lists_each_value_dropped_each_value_rewritten_and_each_run_left_unmigrated_after_the_steps(
    tmp_path: Path,
) -> None:
    path = tmp_path / "store.db"
    dropped = DroppedValue("run-1", "summary.json", "retired_figure", 12.5)
    rewritten = RewrittenValue("run-3", "config.json", "homes[2].dispatch_strategy", "tou_optimized", "greedy")
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
        rewritten_values=(rewritten,),
    )

    lines = str(report).splitlines()

    steps = [f"  {step.version}. {step.description}" for step in MIGRATIONS[1:]]
    assert lines[: 1 + len(steps)] == [
        f"Migrated the dashboard database {path} from schema version 1 to {SCHEMA_VERSION}:",
        *steps,
    ]
    [dropped_line] = [line for line in lines if "run-1" in line]
    [unmigrated_line] = [line for line in lines if "run-2" in line]
    [rewritten_line] = [line for line in lines if "run-3" in line]
    for named in ["summary.json", "retired_figure", "12.5"]:
        assert named in dropped_line, (named, dropped_line)
    assert rewritten_line == '  run \'run-3\': config.json\'s homes[2].dispatch_strategy was "tou_optimized", now "greedy"'
    assert lines[lines.index(rewritten_line) - 1].startswith("Rewrote each value below"), lines
    for named in ["runs.summary_json", "total_generation_kwh", unmigrated.reason]:
        assert named in unmigrated_line, (named, unmigrated_line)
    assert len(steps) < lines.index(dropped_line) < lines.index(rewritten_line) < lines.index(unmigrated_line)


def test_a_migration_report_of_no_step_lists_each_run_brought_forward_and_each_run_left(tmp_path: Path) -> None:
    """A store at SCHEMA_VERSION has no step to apply, but a migration of it still brings forward, or leaves, the runs an earlier migration left."""
    path = tmp_path / "store.db"
    unmigrated = UnmigratedRun(
        "run-2", "summary.json", "total_generation_kwh", "is missing, and SummaryStatistics has no default for it"
    )
    report = MigrationReport(
        path, SCHEMA_VERSION, SCHEMA_VERSION, (), brought_forward_runs=("run-4",), unmigrated_runs=(unmigrated,)
    )
    leaving_only = MigrationReport(path, SCHEMA_VERSION, SCHEMA_VERSION, (), unmigrated_runs=(unmigrated,))

    lines = str(report).splitlines()

    assert str(path) in lines[0]
    assert f"schema version {SCHEMA_VERSION}" in lines[0]
    assert "nothing to migrate" not in str(report)
    assert lines[lines.index("  run 'run-4'") - 1].startswith("Brought forward"), lines
    [unmigrated_line] = [line for line in lines if "run-2" in line]
    assert lines[lines.index(unmigrated_line) - 1].startswith("Left each run below"), lines
    assert "nothing to migrate" not in str(leaving_only)
    assert f"  {unmigrated}" in str(leaving_only).splitlines()


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
