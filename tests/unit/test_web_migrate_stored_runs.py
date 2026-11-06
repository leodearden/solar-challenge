# SPDX-License-Identifier: AGPL-3.0-or-later
"""migrate_store's run-document steps: how it brings each run of a dashboard store to the stored-run format, in its files and its runs row.

Each run-document step of the stored-run format is carried by the migration step of its version
(D-S19-2), which tests/unit/test_web_schema.py checks beside the store's schema version.
Version 2's carries the first: migrate_store brings each run of a store at version 1, the legacy
fixtures of tests/_stored_run_fixtures.py among them, to the stored-run format, in its files and
its runs row alike, so each then loads (D-S19-5). It rewrites only the documents the step
changes, then writes the run's format.json, and reports each value it drops that is not null. A
run whose documents it cannot migrate, or cannot read, is left as it was and reported by id,
document and field, and the rest of the store migrates; so, once, is a run whose format.json
cannot be read, while a run whose format.json names a later format is left as it is. A step that
cannot write a run's file, or whose transaction fails once it has brought the run files forward,
is refused, leaving the database at the version before it, and the migration run again once the
fault is gone completes it. A step refused after an earlier step of the migration committed
leaves the store at the version that step brought it to, and the refusal carries the report of
the steps the migration applied.
A store at version 2, whose runs a solar-challenge at that version saved in format 2, is brought
forward by the steps after version 2 alone, version 3's reading each home's dispatch as it ran.
A run that store's migration left in format 1, with no format.json, has its files brought
forward by every step after format 1, so it is reported, if at all, by its own fault. After its
steps, migrate_store catches up: it brings forward each run an earlier migration left in its
files or its runs row, naming each, also in a store at SCHEMA_VERSION, which has no step to
apply, once the run's documents are fixed, and reports again each it still cannot migrate. It
goes by what a run's documents show, not by where they came from, so it catches up a run saved
in the current format the same way when its save did not finish or its runs row holds a key no
field has. A LaggingRunsRefused carries only the report of a migration that left the store at
SCHEMA_VERSION.
"""

import importlib.util
import json
import sqlite3
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from solar_challenge.dispatch import (
    DispatchStrategyConfig,
    GridChargeConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.home import HomeConfig, SummaryStatistics
from solar_challenge.web.database import Database
from solar_challenge.web.schema import (
    MIGRATIONS,
    SCHEMA_VERSION,
    LaggingRunsRefused,
    MigrationRefused,
    MigrationReport,
    migrate_store,
    open_database,
)
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.stored_runs import (
    RUN_FORMAT_VERSION,
    DroppedValue,
    RewrittenValue,
    StoredFleetRun,
    StoredHomeRun,
    StoredRunUnreadable,
    UnmigratedRun,
    write_run_documents,
)
from tests._dashboard_databases import (
    insert_runs_row,
    runs_rows_of,
    user_version_of,
    write_database_at_schema_version,
)
from tests._finance_builders import make_home_config, make_sim_results
from tests._refused_migration_steps import the_step_to_version_3_refused
from tests._run_storage_layout import stored_run_dir
from tests._run_stores import empty_run_storage, run_storage_over
from tests._stored_run_fixtures import FIXTURES_DIR as STORED_RUN_FIXTURES_DIR
from tests._stored_run_fixtures import STORED_RUN_FIXTURES, install_stored_run_fixture
from tests._web_runs import store_home_run

_NEEDS_PYARROW = pytest.mark.skipif(
    importlib.util.find_spec("pyarrow") is None,
    reason="a stored run's time series is written and read with pyarrow, from the web extra",
)


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
    document = json.loads(runs_rows_of(database_path)[run_id][column])
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
    assert user_version_of(older_store.path) == SCHEMA_VERSION


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

    config = json.loads(runs_rows_of(store_at_version_2)[left]["config_json"])
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
    row_before = runs_rows_of(store_at_version_2)[lacking]

    report = migrate_store(store_at_version_2, store_at_version_2.parent)

    assert len(report.unmigrated_runs) == 2
    assert {(each.run_id, each.document, each.field) for each in report.unmigrated_runs} == {
        (lacking, "summary.json", "total_generation_kwh"),
        (lacking, "runs.summary_json", "total_generation_kwh"),
    }
    assert runs_rows_of(store_at_version_2)[lacking] == row_before


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
        caught_up_runs=(lacking,),
    )
    marker = json.loads((_run_dir(store_at_version_1, lacking) / "format.json").read_text())
    assert marker == {"format_version": RUN_FORMAT_VERSION}
    storage = _storage_of(store_at_version_1)
    loaded = storage.load_run(lacking)
    record = storage.run_record(lacking)
    assert isinstance(loaded, StoredHomeRun)
    assert record is not None
    assert record.summary() == loaded.summary
    assert user_version_of(store_at_version_1) == SCHEMA_VERSION


def test_migrate_store_reports_again_each_run_an_earlier_migration_left_that_still_cannot_be_migrated(
    store_at_version_1: Path,
) -> None:
    """Run again on the store, now at SCHEMA_VERSION, the migration applies no step but tries the run again, and reports each of its sources as the first migration did."""
    lacking = _install_a_run_lacking_generation(store_at_version_1)
    first = migrate_store(store_at_version_1, store_at_version_1.parent)
    assert [each.run_id for each in first.unmigrated_runs] == [lacking, lacking]
    files_after_first, rows_after_first = _files_of(_run_dir(store_at_version_1, lacking)), runs_rows_of(store_at_version_1)

    second = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (second.applied_steps, second.caught_up_runs) == ((), ())
    assert second.unmigrated_runs == first.unmigrated_runs
    assert _files_of(_run_dir(store_at_version_1, lacking)) == files_after_first
    assert runs_rows_of(store_at_version_1) == rows_after_first
    assert user_version_of(store_at_version_1) == SCHEMA_VERSION


def test_migrate_store_brings_forward_and_names_a_run_whose_runs_row_alone_an_earlier_migration_left_once_it_is_fixed(
    store_at_version_1: Path,
) -> None:
    """Only its runs.summary_json lacked the figure, so the first migration brought its files forward and left its row; the catch-up brings the fixed row forward and names the run."""
    lacking = _install_a_run_in_format_1(store_at_version_1, "lacking-generation")
    _edit_runs_document(store_at_version_1, lacking, "summary_json", _deleting("total_generation_kwh"))
    first = migrate_store(store_at_version_1, store_at_version_1.parent)
    assert [(each.run_id, each.document, each.field) for each in first.unmigrated_runs] == [
        (lacking, "runs.summary_json", "total_generation_kwh")
    ]
    committed = json.loads((STORED_RUN_FIXTURES_DIR / "pre_786_dispatch_home" / "run" / "summary.json").read_text())
    restore = _setting("total_generation_kwh", committed["total_generation_kwh"])
    _edit_runs_document(store_at_version_1, lacking, "summary_json", restore)
    files_after_first = _files_of(_run_dir(store_at_version_1, lacking))

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert report == MigrationReport(
        store_at_version_1,
        from_version=SCHEMA_VERSION,
        to_version=SCHEMA_VERSION,
        applied_steps=(),
        caught_up_runs=(lacking,),
    )
    assert "nothing to migrate" not in str(report)
    assert f"  run {lacking!r}" in str(report).splitlines()
    config = json.loads(runs_rows_of(store_at_version_1)[lacking]["config_json"])
    assert config["battery_config"]["dispatch_strategy"] == {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]}
    record = _storage_of(store_at_version_1).run_record(lacking)
    assert record is not None
    summary = record.summary()
    assert isinstance(summary, SummaryStatistics)
    assert summary.total_generation_kwh == committed["total_generation_kwh"]
    assert _files_of(_run_dir(store_at_version_1, lacking)) == files_after_first


@_NEEDS_PYARROW
def test_migrate_store_catches_up_a_current_run_whose_runs_row_holds_a_key_no_field_has_by_dropping_the_key(
    tmp_path: Path,
) -> None:
    """A runs row records no format, so a row the current format refuses for a key no field has reads only from the first: the catch-up brings it forward from there, as it brings a row an earlier migration left, v2 dropping the key."""
    storage = empty_run_storage(tmp_path)
    config = make_home_config()
    store_home_run(storage, "home-1", config, make_sim_results(days=1))
    _edit_runs_document(storage.database.path, "home-1", "config_json", _setting("retired_setting", 1.5))
    files_before = _files_of(stored_run_dir(storage, "home-1"))

    report = migrate_store(storage.database.path, storage.data_dir)

    assert report == MigrationReport(
        storage.database.path,
        from_version=SCHEMA_VERSION,
        to_version=SCHEMA_VERSION,
        applied_steps=(),
        dropped_values=(DroppedValue("home-1", "runs.config_json", "retired_setting", 1.5),),
        caught_up_runs=("home-1",),
    )
    record = storage.run_record("home-1")
    assert record is not None
    assert record.home_configs() == (config,)
    assert _files_of(stored_run_dir(storage, "home-1")) == files_before


@_NEEDS_PYARROW
def test_migrate_store_catches_up_a_current_run_whose_save_did_not_finish_writing_only_its_format_json(
    tmp_path: Path,
) -> None:
    """A home run's save writes config.json, summary.json, data.parquet, then format.json; this run lost the last two, as a save stopped part way through leaves it.

    A run with no format.json reads as one saved before runs carried a format version, so the
    catch-up brings its documents forward from the first format, which changes none of them, and
    writes its format.json. Its load still refuses it, naming the time series it lacks.
    """
    storage = empty_run_storage(tmp_path)
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1))
    run_dir = stored_run_dir(storage, "home-1")
    saved = _files_of(run_dir)
    (run_dir / "format.json").unlink()
    (run_dir / "data.parquet").unlink()

    report = migrate_store(storage.database.path, storage.data_dir)

    assert report == MigrationReport(storage.database.path, SCHEMA_VERSION, SCHEMA_VERSION, (), caught_up_runs=("home-1",))
    assert _files_of(run_dir) == {name: content for name, content in saved.items() if name != "data.parquet"}
    with pytest.raises(StoredRunUnreadable) as refused:
        storage.load_run("home-1")
    assert (refused.value.document, refused.value.field) == ("data.parquet", None)


def test_migrate_store_drops_the_keys_v2_drops_from_a_run_s_files_and_its_runs_row_alike(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """The pre-786 run's dispatch strategy loses the other variants' null keys in config.json and runs.config_json."""
    run_id = legacy_run_ids["pre_786_dispatch_home"]

    migrate_store(store_at_version_1, store_at_version_1.parent)

    configs = [
        json.loads((_run_dir(store_at_version_1, run_id) / "config.json").read_text()),
        json.loads(runs_rows_of(store_at_version_1)[run_id]["config_json"]),
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
    rows_before = runs_rows_of(store)
    rewritten = {
        older_store.run_ids[name] for version, name in _CONFIG_EACH_RUN_DOCUMENT_STEP_REWRITES if version > older_store.version
    }

    migrate_store(store, store.parent)

    rows_after = runs_rows_of(store)
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
    assert "retired_figure" not in json.loads(runs_rows_of(store_at_version_1)[run_id]["summary_json"])
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
    insert_runs_row(
        store_at_version_1,
        {"id": "garbled-config", "name": "Garbled", "type": "home", "config_json": "{not json", "status": "completed"},
    )
    files_before, rows_before = _files_of(_run_dir(store_at_version_1, lacking)), runs_rows_of(store_at_version_1)

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
    rows_after = runs_rows_of(store_at_version_1)
    assert [rows_after[run_id] for run_id in (lacking, "garbled-config")] == [
        rows_before[run_id] for run_id in (lacking, "garbled-config")
    ]
    assert user_version_of(store_at_version_1) == SCHEMA_VERSION
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
    assert json.loads(runs_rows_of(store_at_version_1)[copy]["config_json"])["homes"][2]["dispatch_strategy"] == "greedy"


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
    files_before, row_before = _files_of(_run_dir(store_at_version_1, run_id)), runs_rows_of(store_at_version_1)[run_id]

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document, each.field) for each in report.unmigrated_runs] == [(run_id, "runs.type", None)]
    assert _files_of(_run_dir(store_at_version_1, run_id)) == files_before
    assert runs_rows_of(store_at_version_1)[run_id] == row_before


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
    assert user_version_of(store_at_version_1) == SCHEMA_VERSION
    storage = _storage_of(store_at_version_1)
    assert [storage.load_run(run_id).run_id for run_id in legacy_run_ids.values()] == list(legacy_run_ids.values())


_FORMAT_MARKERS_THAT_NAME_NO_FORMAT = [
    pytest.param("not json", None, id="not-json"),
    pytest.param(json.dumps({"format_version": "x"}), "format_version", id="format-version-not-a-number"),
]
"""The text of a format.json that names no format, and the field of it the refusal names, None for the document as a whole."""


@pytest.mark.parametrize(("marker", "field"), _FORMAT_MARKERS_THAT_NAME_NO_FORMAT)
def test_migrate_store_reports_a_run_whose_format_json_cannot_be_read_once_by_it_and_leaves_its_files_and_runs_row_as_they_were(
    store_at_version_1: Path, marker: str, field: str | None
) -> None:
    """A run's files are in the format their format.json names, so one that cannot be read leaves no format to bring them forward from.

    No later step of the migration, nor its catch-up, is given the files, so they are reported
    once. pre_469_home's runs row is one no step changes, so it is as it was too.
    """
    run_id = install_stored_run_fixture(
        "pre_469_home", Database(store_at_version_1), store_at_version_1.parent, run_id="unreadable-marker"
    )
    run_dir = _run_dir(store_at_version_1, run_id)
    (run_dir / "format.json").write_text(marker)
    files_before, row_before = _files_of(run_dir), runs_rows_of(store_at_version_1)[run_id]

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert [(each.run_id, each.document, each.field) for each in report.unmigrated_runs] == [
        (run_id, "format.json", field)
    ]
    assert _files_of(run_dir) == files_before
    assert runs_rows_of(store_at_version_1)[run_id] == row_before


def test_migrate_store_leaves_the_files_of_a_run_whose_format_json_names_a_later_format_as_they_are_and_reports_nothing_of_them(
    store_at_version_1: Path,
) -> None:
    """A run a newer solar-challenge saved is in a format past every step's, so no step brings its files forward or reports them; its load refuses it, naming the newer solar-challenge."""
    run_id = install_stored_run_fixture(
        "pre_469_home", Database(store_at_version_1), store_at_version_1.parent, run_id="saved-by-a-newer-solar-challenge"
    )
    run_dir = _run_dir(store_at_version_1, run_id)
    write_run_documents(run_dir, (), RUN_FORMAT_VERSION + 1)
    files_before = _files_of(run_dir)

    report = migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (report.unmigrated_runs, report.caught_up_runs) == ((), ())
    assert _files_of(run_dir) == files_before
    with pytest.raises(StoredRunUnreadable) as refused:
        _storage_of(store_at_version_1).load_run(run_id)
    assert (refused.value.document, refused.value.field) == ("format.json", "format_version")
    assert "a newer solar-challenge saved it" in refused.value.reason


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
    fleet_files_before, rows_before = _files_of(fleet_dir), runs_rows_of(store_at_version_1)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (refused.value.path, refused.value.step) == (store_at_version_1, MIGRATIONS[1])
    assert isinstance(refused.value.__cause__, OSError)
    message = str(refused.value)
    for named in [str(store_at_version_1), "schema version 2", "stays at version 1", str(fleet_dir / "format.json")]:
        assert named in message, (named, message)
    assert refused.value.migrated == MigrationReport(store_at_version_1, 1, 1, ())
    assert user_version_of(store_at_version_1) == 1
    assert runs_rows_of(store_at_version_1) == rows_before
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
    rows_before = runs_rows_of(store_at_version_1)

    with pytest.raises(MigrationRefused) as refused:
        migrate_store(store_at_version_1, store_at_version_1.parent)

    assert refused.value.step == MIGRATIONS[1]
    assert isinstance(refused.value.__cause__, sqlite3.IntegrityError)
    assert "no run may be updated" in str(refused.value)
    assert user_version_of(store_at_version_1) == 1
    assert runs_rows_of(store_at_version_1) == rows_before
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


def test_migrate_store_refused_at_v3_after_it_applied_v2_carries_the_report_of_v2_and_leaves_the_store_at_version_2(
    store_at_version_1: Path, legacy_run_ids: dict[str, str]
) -> None:
    """Version 3's step is refused once version 2's has committed, so the value v2 dropped from the copy of pre_469_home is in the report the refusal carries."""
    run_id = install_stored_run_fixture(
        "pre_469_home", Database(store_at_version_1), store_at_version_1.parent, run_id="retired-figure"
    )
    _edit_stored_document(_run_dir(store_at_version_1, run_id) / "summary.json", _setting("retired_figure", 12.5))
    _edit_runs_document(store_at_version_1, run_id, "summary_json", _setting("retired_figure", 12.5))

    with (
        the_step_to_version_3_refused(store_at_version_1, legacy_run_ids["pre_787_dispatch_fleet"]),
        pytest.raises(MigrationRefused) as refused,
    ):
        migrate_store(store_at_version_1, store_at_version_1.parent)

    assert (refused.value.path, refused.value.step) == (store_at_version_1, MIGRATIONS[2])
    assert isinstance(refused.value.__cause__, sqlite3.IntegrityError)
    assert "stays at version 2" in str(refused.value)
    assert user_version_of(store_at_version_1) == 2
    assert refused.value.migrated == MigrationReport(
        path=store_at_version_1,
        from_version=1,
        to_version=2,
        applied_steps=(MIGRATIONS[1],),
        dropped_values=(
            DroppedValue(run_id, "summary.json", "retired_figure", 12.5),
            DroppedValue(run_id, "runs.summary_json", "retired_figure", 12.5),
        ),
    )


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
    for named in [str(store), f"schema version {SCHEMA_VERSION}, as it was", str(RUN_FORMAT_VERSION), str(marker)]:
        assert named in message, (named, message)
    assert refused.value.path == store
    assert refused.value.migrated == MigrationReport(store, SCHEMA_VERSION, SCHEMA_VERSION, ())
    assert user_version_of(store) == SCHEMA_VERSION
    assert _files_of(_run_dir(store, run_id)) == files_before

    marker.rmdir()
    report = migrate_store(store, store.parent)

    assert report.caught_up_runs == (run_id,)
    assert _storage_of(store).load_run(run_id).run_id == run_id


def test_a_lagging_runs_refused_is_not_a_value_error() -> None:
    """No request causes it: the migration that meets the fault refuses to go on."""
    assert not issubclass(LaggingRunsRefused, ValueError)


def test_a_lagging_runs_refused_after_its_migration_s_steps_names_the_version_they_brought_the_store_from(
    tmp_path: Path,
) -> None:
    """The catch-up runs after the steps its migration applied, which stay applied, so a store it refuses then was not at SCHEMA_VERSION before.

    No store makes the catch-up fail right after steps, as once they have run it has nothing left
    to write, so the refusal is built here from the report such a migration carries.
    """
    path = tmp_path / "store.db"
    fault = sqlite3.OperationalError("disk I/O error")
    migrated = MigrationReport(path, 1, SCHEMA_VERSION, MIGRATIONS[1:])

    refused = LaggingRunsRefused(migrated, fault)

    message = str(refused)
    for named in [str(path), f"schema version {SCHEMA_VERSION}", "brought it from version 1", str(fault)]:
        assert named in message, (named, message)
    assert "as it was" not in message
    assert refused.migrated is migrated
    assert refused.path == path


def test_a_lagging_runs_refused_refuses_the_report_of_a_migration_that_left_the_store_below_the_schema_version(
    tmp_path: Path,
) -> None:
    """The catch-up runs once the store is at SCHEMA_VERSION, the version the refusal says it stays at."""
    left_at_version_2 = MigrationReport(tmp_path / "store.db", 1, 2, (MIGRATIONS[1],))

    with pytest.raises(ValueError) as refused:
        LaggingRunsRefused(left_at_version_2, sqlite3.OperationalError("disk I/O error"))

    for named in [f"store at schema version {SCHEMA_VERSION}", "left the store at version 2"]:
        assert named in str(refused.value), (named, str(refused.value))


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
        path, SCHEMA_VERSION, SCHEMA_VERSION, (), caught_up_runs=("run-4",), unmigrated_runs=(unmigrated,)
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
