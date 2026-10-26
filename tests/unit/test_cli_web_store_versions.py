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
file that is not a database, naming it, and leave it as it is. migrate brings the runs of a store
at version 1 to the stored-run format too, reporting each value it drops that is not null and
each run it cannot migrate, and the dashboard then shows a run stored before runs carried a
format version (B5). It refuses a step that cannot write a run's file, exiting 1 with the
refusal naming the step and the fault.
"""

import json
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
from solar_challenge.web.storage import RunQuery
from solar_challenge.web.store_lock import acquire_store_lock
from solar_challenge.web.stored_runs import StoredHomeRun
from tests._dashboard_databases import (
    schema_of,
    write_database_a_newer_solar_challenge_wrote,
    write_database_at_schema_version_1,
    write_pre_548_database,
)
from tests._html_page import headings
from tests._run_storage_layout import stored_run_dir
from tests._run_stores import run_storage_over
from tests._stored_run_fixtures import STORED_RUN_FIXTURES, install_stored_run_fixture
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
    storage = run_storage_over(open_database(legacy_store))
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


@pytest.fixture
def legacy_run_ids(tmp_path: Path) -> dict[str, str]:
    """The run id of each legacy stored-run fixture, by name, each installed in the store under tmp_path/.solar-challenge, which a solar-challenge at schema version 1 left."""
    database = write_database_at_schema_version_1(_store_database(tmp_path))
    return {
        name: install_stored_run_fixture(name, Database(database), database.parent) for name in STORED_RUN_FIXTURES
    }


def _install_a_copy_editing_its_summary(tmp_path: Path, run_id: str, edit_summary: Any) -> str:
    """Install a copy of the pre_469_home fixture as run *run_id* in the store under tmp_path/.solar-challenge, its summary.json edited by *edit_summary*; return *run_id*."""
    database = _store_database(tmp_path)
    install_stored_run_fixture("pre_469_home", Database(database), database.parent, run_id=run_id)
    summary_path = stored_run_dir(run_storage_over(Database(database)), run_id) / "summary.json"
    summary = json.loads(summary_path.read_text())
    edit_summary(summary)
    summary_path.write_text(json.dumps(summary, indent=2))
    return run_id


def _a_line_naming(text: str, *parts: str) -> bool:
    """Whether a line of *text* names each of *parts*."""
    return any(all(part in line for part in parts) for line in text.splitlines())


def test_web_migrate_brings_the_runs_of_a_store_at_version_1_forward_reporting_each_value_dropped_and_each_run_left(
    legacy_run_ids: dict[str, str], tmp_path: Path
) -> None:
    """The report names the versions and version 2's step, each value it drops that is not null, and each run it cannot migrate."""
    retired = _install_a_copy_editing_its_summary(
        tmp_path, "retired-figure", lambda summary: summary.update(retired_figure=12.5)
    )
    lacking = _install_a_copy_editing_its_summary(
        tmp_path, "lacking-generation", lambda summary: summary.pop("total_generation_kwh")
    )

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 0, result.output
    for named in [str(_store_database(tmp_path)), "schema version 1", str(SCHEMA_VERSION), MIGRATIONS[1].description]:
        assert named in result.stdout, (named, result.stdout)
    assert _a_line_naming(result.stdout, retired, "summary.json", "retired_figure", "12.5"), result.stdout
    assert _a_line_naming(result.stdout, lacking, "summary.json", "total_generation_kwh"), result.stdout


def test_web_migrate_refuses_a_step_that_cannot_write_a_run_s_file_naming_the_step_and_the_fault(
    legacy_run_ids: dict[str, str], tmp_path: Path
) -> None:
    """A directory in the place of a run's format.json stands in for a file the step cannot write, e.g. on a full disk."""
    database = _store_database(tmp_path)
    marker = stored_run_dir(run_storage_over(Database(database)), legacy_run_ids["legacy_fleet"]) / "format.json"
    marker.mkdir()

    result = _web(tmp_path, "migrate")

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    assert "Traceback" not in result.output
    for named in [str(database), "schema version 2", "stays at version 1", str(marker)]:
        assert named in result.stderr, (named, result.stderr)


def test_after_web_migrate_the_dashboard_shows_a_run_stored_before_469_and_loads_it_with_no_grid_charge(
    legacy_run_ids: dict[str, str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B5's second half: before `web migrate` its page flashes format_version; after, it answers 200."""
    run_id = legacy_run_ids["pre_469_home"]
    assert _web(tmp_path, "migrate").exit_code == 0
    monkeypatch.setenv("HOME", str(tmp_path))

    dashboard = create_app()
    try:
        response = dashboard.test_client().get(f"/results/{run_id}")
        loaded = run_storage_of(dashboard).load_run(run_id)
    finally:
        release_store_lock(dashboard)

    assert response.status_code == 200
    assert headings(response.get_data(as_text=True))[0] == "Elm Street"
    assert isinstance(loaded, StoredHomeRun)
    assert loaded.summary.total_grid_charge_kwh == 0.0
