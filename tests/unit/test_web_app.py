# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the web dashboard's application factory."""

import gc
import importlib
import importlib.util
import os
import re
import shutil
import sqlite3
import sys
import weakref
from contextlib import closing
from pathlib import Path

import pytest

pytest.importorskip("flask")

from solar_challenge.web.database import Database
from solar_challenge.web.jobs import live_managers
from solar_challenge.web.schema import SCHEMA_VERSION, SchemaVersionMismatch, StoreUnreadable
from solar_challenge.web.shared import get_database, get_storage
from solar_challenge.web.store_lock import StoreLocked, acquire_store_lock
from tests._dashboard_databases import write_pre_548_database
from tests._web_app import build_test_app, release_store_lock, run_storage_of


def _uncache_module(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Make the next import of *module* run it afresh; the cached module comes back after the test.

    A fresh import that succeeds also rebinds the module's attribute on its parent package,
    so that attribute is restored along with the sys.modules entry.
    """
    package, _, name = module.rpartition(".")
    monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.delattr(importlib.import_module(package), name, raising=False)


_DASHBOARD_FOLDERS = ("templates", "static")


def _import_app_from_a_web_package_lacking(
    missing: str, web_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Make the next import of solar_challenge.web.app load a copy of app.py from *web_dir*, which holds every dashboard folder but *missing*, as from an install whose web package lacks that folder; the real module, imported here if need be, comes back after the test."""
    web_package = importlib.import_module("solar_challenge.web")
    importlib.import_module("solar_challenge.web.app")
    web_dir.mkdir()
    shutil.copy(Path(web_package.__file__).parent / "app.py", web_dir / "app.py")
    for folder in set(_DASHBOARD_FOLDERS) - {missing}:
        (web_dir / folder).mkdir()
    monkeypatch.setattr(web_package, "__path__", [str(web_dir), *web_package.__path__])
    _uncache_module(monkeypatch, "solar_challenge.web.app")


@pytest.mark.parametrize(
    "module",
    [
        "solar_challenge.web.jobs",
        "solar_challenge.web.routes",
        "solar_challenge.web.history",
        "solar_challenge.web.scenarios",
        "solar_challenge.web.api",
        "solar_challenge.web.assistant",
        "solar_challenge.web.plotly_js",
    ],
    ids=lambda module: module.rpartition(".")[2],
)
def test_building_the_app_fails_when_a_module_it_wires_in_cannot_import(
    module: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A job-manager or blueprint module that cannot import fails the app build instead of vanishing from the app."""
    # A None entry makes any import of the module raise ModuleNotFoundError naming it.
    monkeypatch.setitem(sys.modules, module, None)
    _uncache_module(monkeypatch, "solar_challenge.web.app")
    with pytest.raises(ImportError, match=re.escape(module)):
        build_test_app(tmp_path)


@pytest.mark.parametrize("missing", _DASHBOARD_FOLDERS)
def test_building_the_app_fails_naming_a_dashboard_folder_the_installed_package_lacks(
    missing: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installed web package that lacks templates/ or static/ fails the app build with a FileNotFoundError naming the folder's path, and the build writes nothing into the package."""
    web_dir = tmp_path / "web"
    _import_app_from_a_web_package_lacking(missing, web_dir, monkeypatch)
    with pytest.raises(FileNotFoundError, match=re.escape(str(web_dir / missing))):
        build_test_app(tmp_path / "data")
    assert not (web_dir / missing).exists()


def test_building_the_app_fails_naming_the_plotly_js_the_installed_plotly_package_lacks(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An installed plotly package that lacks the plotly.js it bundles fails the app build with a FileNotFoundError naming the file's path, instead of each chart page's request for the script."""
    importlib.import_module("solar_challenge.web.app")
    plotly_dir = tmp_path / "plotly"
    plotly_dir.mkdir()
    (plotly_dir / "__init__.py").touch()
    plotly_spec = importlib.util.spec_from_file_location("plotly", plotly_dir / "__init__.py")
    monkeypatch.setitem(sys.modules, "plotly", importlib.util.module_from_spec(plotly_spec))
    _uncache_module(monkeypatch, "solar_challenge.web.plotly_js")
    _uncache_module(monkeypatch, "solar_challenge.web.app")

    bundled = plotly_dir / "package_data" / "plotly.min.js"
    with pytest.raises(FileNotFoundError, match=re.escape(str(bundled))):
        build_test_app(tmp_path / "data")


def test_building_the_app_does_not_import_the_anthropic_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Building the app and serving the assistant page never import the anthropic SDK: the assistant imports it only to answer a chat."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    _uncache_module(monkeypatch, "solar_challenge.web.assistant")
    _uncache_module(monkeypatch, "solar_challenge.web.app")

    app = build_test_app(tmp_path)

    assert app.test_client().get("/assistant").status_code == 200


@pytest.fixture
def home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """An empty home directory with no SECRET_KEY exported, so only a key persisted under it can supply one."""
    home_dir = tmp_path / "home"
    home_dir.mkdir()
    monkeypatch.setenv("HOME", str(home_dir))
    monkeypatch.delenv("SECRET_KEY", raising=False)
    return home_dir


def test_a_secret_key_in_test_config_leaves_the_home_directory_untouched(
    home: Path, tmp_path: Path
) -> None:
    """A SECRET_KEY supplied in test_config becomes the app's key, and the build never touches the key persisted under the home directory."""
    app = build_test_app(tmp_path / "data", secret_key="a-key-from-test-config")

    assert app.secret_key == "a-key-from-test-config"
    assert [path.name for path in home.iterdir()] == []


def test_without_a_supplied_secret_key_the_app_keeps_one_under_the_home_directory(
    home: Path, tmp_path: Path
) -> None:
    """With no SECRET_KEY in test_config or the environment, the app persists a generated key under the home directory and the next build reuses it."""
    first = build_test_app(tmp_path / "data", secret_key=None)
    release_store_lock(first)
    second = build_test_app(tmp_path / "data", secret_key=None)

    key_file = home / ".solar-challenge" / ".secret_key"
    assert first.secret_key
    assert first.secret_key == second.secret_key == key_file.read_text()


@pytest.mark.parametrize("flask_debug", ["0", "1"], ids=["debug_off", "debug_on"])
def test_the_session_cookie_is_not_marked_secure(
    flask_debug: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The session cookie is not Secure, in debug mode or out of it: `solar-challenge web start` serves plain HTTP, also to the LAN with --host 0.0.0.0, and browsers withhold a Secure cookie from a non-localhost plain-HTTP origin, so the assistant would lose its chat session on every request."""
    monkeypatch.setenv("FLASK_DEBUG", flask_debug)
    app = build_test_app(tmp_path)
    client = app.test_client()

    assert client.get("/assistant/history").status_code == 200
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    assert cookie is not None
    assert not cookie.secure


def test_the_app_serves_the_database_its_config_names_and_its_connections_enforce_the_schema(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)

    with app.app_context():
        database = get_database()

    assert database == Database(Path(app.config["DATABASE"]))
    with closing(database.connect()) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_apps_run_store_keeps_its_runs_in_the_apps_database(tmp_path: Path) -> None:
    """The app's Database is the one owner of the store's file; its RunStorage borrows it for the runs.

    So the chat rows and presets the app keeps in its Database, and the runs its
    RunStorage keeps, are one file.
    """
    app = build_test_app(tmp_path)

    with app.app_context():
        assert get_storage().database == get_database()


def test_dropping_the_app_frees_its_job_manager(tmp_path: Path) -> None:
    """Nothing outside the app keeps its job manager alive, so the manager is freed along with the app."""
    app = build_test_app(tmp_path)
    job_manager_ref = weakref.ref(app.extensions["job_manager"])

    del app
    gc.collect()

    assert job_manager_ref() is None


def test_a_live_apps_job_manager_is_among_the_live_managers(tmp_path: Path) -> None:
    """While the app lives, live_managers() reports its job manager, so shutdown code that walks that registry reaches it."""
    app = build_test_app(tmp_path)

    assert app.extensions["job_manager"] in live_managers()


def test_an_app_on_a_store_another_app_holds_is_refused_naming_this_process_and_the_holders_running_run_stays_running(
    tmp_path: Path,
) -> None:
    """B12: the refused build never reaches the recovery that would fail the run the holder's job is running."""
    first = build_test_app(tmp_path)
    run_storage_of(first).create_run(
        "r-1", run_type="home", name="North Roof", n_homes=1, created_at="2026-10-22T09:00:00"
    )

    with pytest.raises(StoreLocked) as refused:
        build_test_app(tmp_path)

    assert refused.value.holder_pid == os.getpid()
    assert refused.value.path == tmp_path / "dashboard.lock"
    record = run_storage_of(first).run_record("r-1")
    assert record is not None
    assert record.status == "running"


def test_an_app_refused_its_store_opens_no_database(tmp_path: Path) -> None:
    held = acquire_store_lock(tmp_path)
    try:
        with pytest.raises(StoreLocked):
            build_test_app(tmp_path)

        assert not (tmp_path / "test.db").exists()
    finally:
        held.release()


def test_a_build_that_fails_after_taking_its_store_lock_releases_it(tmp_path: Path) -> None:
    """A directory where the database file belongs fails the build when it opens the database."""
    (tmp_path / "test.db").mkdir()

    with pytest.raises(StoreUnreadable) as refused:
        build_test_app(tmp_path)

    assert isinstance(refused.value.__cause__, sqlite3.OperationalError)
    acquire_store_lock(tmp_path).release()


def test_an_app_on_a_legacy_store_refuses_to_build_naming_it_and_both_versions_and_releases_the_store(tmp_path: Path) -> None:
    """B2: the store keeps its bytes, and the refused build has released its lock."""
    legacy = write_pre_548_database(tmp_path / "test.db")
    bytes_before = legacy.read_bytes()

    with pytest.raises(SchemaVersionMismatch) as refused:
        build_test_app(tmp_path)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (legacy, 0, SCHEMA_VERSION)
    acquire_store_lock(tmp_path).release()
    assert legacy.read_bytes() == bytes_before
