# SPDX-License-Identifier: AGPL-3.0-or-later
"""`solar-challenge web start` and `solar-challenge web migrate` on a dashboard store at a schema version other than this solar-challenge's.

Each test runs a command in this process with typer's CliRunner, its HOME at the test's
tmp_path, so its store is the one under tmp_path/.solar-challenge. COLUMNS is wide, so Rich
prints each message on one line however long the store's path. A start whose store is at
another version exits 1 with the refusal on stderr, naming the store's database and both
versions, before the dashboard binds its port, and writes nothing to the store. migrate
brings an older store to SCHEMA_VERSION, reporting on stdout each step it applied, and the
dashboard then builds on the store. It refuses, exiting 1 with the refusal on stderr and
changing nothing, a store a newer solar-challenge wrote, a store holding a row version 1
cannot keep, naming the row, a store whose tables version 1 cannot rebuild, naming the fault,
and a store another dashboard holds, naming its lock file. Both commands refuse a database
file that is not a database, naming it, and leave it as it is.
"""

import socket
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.web.app import create_app
from solar_challenge.web.database import Database
from solar_challenge.web.schema import MIGRATIONS, SCHEMA_VERSION, open_database
from solar_challenge.web.storage import RunQuery, RunStorage
from solar_challenge.web.store_lock import acquire_store_lock
from tests._dashboard_databases import schema_of, write_database_a_newer_solar_challenge_wrote, write_pre_548_database
from tests._web_app import release_store_lock, run_storage_of


@pytest.fixture(autouse=True)
def _the_dashboard_never_serves(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail a test whose command would serve the dashboard, which it would do until stopped, rather than let it hang."""

    def serve(self: Flask, *args: Any, **kwargs: Any) -> None:
        pytest.fail("`solar-challenge web start` served the dashboard rather than refusing its store")

    monkeypatch.setattr(Flask, "run", serve)


def _store_database(home: Path) -> Path:
    """The database of the dashboard store of a user whose HOME is *home*."""
    return home / ".solar-challenge" / "solar-challenge.db"


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
        return port


def _web(home: Path, *args: str) -> Result:
    """Run `solar-challenge web <args>` in this process, its HOME at *home*, on a console wide enough to print each message on one line."""
    return CliRunner().invoke(app, ["web", *args], env={"HOME": str(home), "COLUMNS": "1000"})


def test_web_start_refuses_a_legacy_store_naming_its_database_both_versions_and_the_migrate_command(
    tmp_path: Path,
) -> None:
    """B2: a store an older solar-challenge left, with no schema version, is at version 0."""
    database = write_pre_548_database(_store_database(tmp_path))
    bytes_before = database.read_bytes()

    result = _web(tmp_path, "start", "--port", str(_free_port()))

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    assert "Traceback" not in result.output
    for named in [str(database), "schema version 0", str(SCHEMA_VERSION), "solar-challenge web migrate"]:
        assert named in result.stderr, (named, result.stderr)
    assert database.read_bytes() == bytes_before


def test_web_start_refuses_a_store_a_newer_solar_challenge_wrote_naming_both_versions(tmp_path: Path) -> None:
    """B4, for start."""
    database = write_database_a_newer_solar_challenge_wrote(_store_database(tmp_path))
    bytes_before = database.read_bytes()

    result = _web(tmp_path, "start", "--port", str(_free_port()))

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in ["newer", str(SCHEMA_VERSION + 1), str(SCHEMA_VERSION)]:
        assert named in result.stderr, (named, result.stderr)
    assert database.read_bytes() == bytes_before


@pytest.fixture
def legacy_store(tmp_path: Path) -> Path:
    """The database of the store under tmp_path/.solar-challenge, the pre-548 store an older solar-challenge left: at version 0, with the jobs table and runs with no name."""
    return write_pre_548_database(_store_database(tmp_path))


def test_web_migrate_brings_a_legacy_store_to_the_schema_version_reporting_each_step_it_applied(
    legacy_store: Path, tmp_path: Path
) -> None:
    """B3: the migrated store's schema is a new store's, with no jobs table, and each run with no name is named after its kind."""
    result = _web(tmp_path, "migrate")

    assert result.exit_code == 0, result.output
    for named in [str(legacy_store), "schema version 0", str(SCHEMA_VERSION), MIGRATIONS[0].description]:
        assert named in result.stdout, (named, result.stdout)
    assert schema_of(legacy_store) == schema_of(open_database(tmp_path / "fresh.db").path)
    assert "jobs" not in {name for object_type, name, _, _ in schema_of(legacy_store) if object_type == "table"}
    storage = RunStorage(open_database(legacy_store), legacy_store.parent)
    assert storage.run_name("legacy-nameless-home") == "North Roof"
    assert storage.run_name("legacy-nameless-fleet") == "Fleet Simulation"


def test_the_dashboard_builds_on_a_store_web_migrate_migrated_and_lists_its_runs(
    legacy_store: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B3: create_app, with no test_config, opens the store under ~/.solar-challenge once it is at the schema version."""
    assert _web(tmp_path, "migrate").exit_code == 0
    monkeypatch.setenv("HOME", str(tmp_path))

    dashboard = create_app()
    try:
        listed = run_storage_of(dashboard).page_runs(RunQuery()).records
    finally:
        release_store_lock(dashboard)

    assert {record.id for record in listed} == {
        "legacy-named-home",
        "legacy-nameless-home",
        "legacy-blank-home",
        "legacy-nameless-fleet",
    }


def test_web_migrate_says_there_is_nothing_to_migrate_on_a_store_at_the_schema_version(
    legacy_store: Path, tmp_path: Path
) -> None:
    assert _web(tmp_path, "migrate").exit_code == 0

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 0, result.output
    assert f"schema version {SCHEMA_VERSION}" in result.stdout
    assert "nothing to migrate" in result.stdout


def test_web_migrate_refuses_a_store_a_newer_solar_challenge_wrote_naming_both_versions_and_changes_nothing(
    tmp_path: Path,
) -> None:
    """B4, for migrate."""
    database = write_database_a_newer_solar_challenge_wrote(_store_database(tmp_path))
    bytes_before = database.read_bytes()

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in ["newer", str(SCHEMA_VERSION + 1), str(SCHEMA_VERSION)]:
        assert named in result.stderr, (named, result.stderr)
    assert database.read_bytes() == bytes_before


def test_web_migrate_refuses_a_store_holding_a_run_version_1_cannot_keep_naming_the_row_and_changes_nothing(
    legacy_store: Path, tmp_path: Path
) -> None:
    """Version 1 no longer admits a 'sweep' run."""
    with Database(legacy_store).transaction() as conn:
        conn.execute("INSERT INTO runs (id, name, type) VALUES ('legacy-sweep', 'Sweep Run', 'sweep')")
    bytes_before = legacy_store.read_bytes()

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in ["runs", "'legacy-sweep'", "type"]:
        assert named in result.stderr, (named, result.stderr)
    assert legacy_store.read_bytes() == bytes_before


def test_web_migrate_refuses_a_store_whose_tables_version_1_cannot_rebuild_naming_the_fault_and_changes_nothing(
    legacy_store: Path, tmp_path: Path
) -> None:
    """A store with no config_presets table, which no solar-challenge left."""
    with Database(legacy_store).transaction() as conn:
        conn.execute("DROP TABLE config_presets")
    bytes_before = legacy_store.read_bytes()

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in [str(legacy_store), "schema version 1", "stays at version 0", "config_presets"]:
        assert named in result.stderr, (named, result.stderr)
    assert legacy_store.read_bytes() == bytes_before


@pytest.mark.parametrize("command", ["start", "migrate"])
def test_web_start_and_web_migrate_refuse_a_file_that_is_not_a_database_naming_it_and_leave_it_as_it_is(
    command: str, tmp_path: Path
) -> None:
    database = _store_database(tmp_path)
    database.parent.mkdir()
    database.write_bytes(b"not a database")
    options = ["--port", str(_free_port())] if command == "start" else []

    result = _web(tmp_path, command, *options)

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in [str(database), "file is not a database"]:
        assert named in result.stderr, (named, result.stderr)
    assert database.read_bytes() == b"not a database"


def test_web_migrate_refuses_a_store_another_dashboard_holds_naming_its_lock_file_and_changes_nothing(
    legacy_store: Path, tmp_path: Path
) -> None:
    bytes_before = legacy_store.read_bytes()
    held = acquire_store_lock(legacy_store.parent)
    try:
        result = _web(tmp_path, "migrate")
    finally:
        held.release()

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    assert str(held.path) in result.stderr, result.stderr
    assert legacy_store.read_bytes() == bytes_before


def test_web_migrate_releases_the_store_lock_once_it_has_migrated_the_store(legacy_store: Path, tmp_path: Path) -> None:
    assert _web(tmp_path, "migrate").exit_code == 0

    acquire_store_lock(legacy_store.parent).release()
