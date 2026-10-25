# SPDX-License-Identifier: AGPL-3.0-or-later
"""`solar-challenge web start` on a dashboard store at a schema version other than this solar-challenge's.

Each test runs the command in this process with typer's CliRunner, its HOME at the test's
tmp_path, so its store is the one under tmp_path/.solar-challenge. COLUMNS is wide, so Rich
prints each message on one line however long the store's path. A start whose store is at
another version exits 1 with the refusal on stderr, naming the store's database and both
versions, before the dashboard binds its port, and writes nothing to the store.
"""

import socket
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from flask import Flask
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.web.database import Database
from solar_challenge.web.schema import SCHEMA_VERSION, open_database
from tests._dashboard_databases import write_pre_548_database


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


def _store_a_newer_solar_challenge_wrote(path: Path) -> Path:
    """A store open_database created at *path*, then recorded at SCHEMA_VERSION + 1, as a newer solar-challenge records it."""
    open_database(path)
    with closing(Database(path).connect()) as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
    return path


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
    database = _store_a_newer_solar_challenge_wrote(_store_database(tmp_path))
    bytes_before = database.read_bytes()

    result = _web(tmp_path, "start", "--port", str(_free_port()))

    assert result.exit_code == 1, result.output
    assert isinstance(result.exception, SystemExit), "the refusal is reported, not raised"
    for named in ["newer", str(SCHEMA_VERSION + 1), str(SCHEMA_VERSION)]:
        assert named in result.stderr, (named, result.stderr)
    assert database.read_bytes() == bytes_before
