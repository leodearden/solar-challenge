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
import threading
import time
import weakref
from collections.abc import Callable
from contextlib import ExitStack, closing
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")

from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.weather import WeatherCache
from solar_challenge.web.app import create_app, default_jobs
from solar_challenge.web.dashboard import dashboard_of
from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.schema import SCHEMA_VERSION, SchemaVersionMismatch, StoreUnreadable
from solar_challenge.web.shared import get_database, get_job_manager, get_job_stream_policy, get_storage
from solar_challenge.web.sse import JobStreamPolicy
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.store_lock import StoreLocked, acquire_store_lock
from tests._dashboard_databases import write_pre_548_database
from tests._web_app import BuildApp, build_test_app, database_path_in, jobs_in_this_process, run_storage_of, store_lock_is_free
from tests._web_job_runner import jobs_running
from tests.unit.web_jobs._app_client import A_HOME_JOB_DAYS, A_HOME_JOB_REQUEST
from tests.unit.web_jobs._fakes import BlockingSimulation


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
    build_app: BuildApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Building the app and serving the assistant page never import the anthropic SDK: the assistant imports it only to answer a chat."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    _uncache_module(monkeypatch, "solar_challenge.web.assistant")
    _uncache_module(monkeypatch, "solar_challenge.web.app")

    app = build_app(tmp_path)

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
    build_app: BuildApp, home: Path, tmp_path: Path
) -> None:
    """A SECRET_KEY supplied in test_config becomes the app's key, and the build never touches the key persisted under the home directory."""
    app = build_app(tmp_path / "data", secret_key="a-key-from-test-config")

    assert app.secret_key == "a-key-from-test-config"
    assert [path.name for path in home.iterdir()] == []


def test_without_a_supplied_secret_key_the_app_keeps_one_under_the_home_directory(
    build_app: BuildApp, home: Path, tmp_path: Path
) -> None:
    """With no SECRET_KEY in test_config or the environment, the app persists a generated key under the home directory and the next build reuses it."""
    first = build_app(tmp_path / "data", secret_key=None)
    dashboard_of(first).close()
    second = build_app(tmp_path / "data", secret_key=None)

    key_file = home / ".solar-challenge" / ".secret_key"
    assert first.secret_key
    assert first.secret_key == second.secret_key == key_file.read_text()


def test_a_build_whose_persisted_secret_key_cannot_be_read_fails_with_the_lookups_error_and_releases_its_store(
    home: Path, tmp_path: Path
) -> None:
    """A key file of bytes no UTF-8 decoder reads makes the key lookup raise UnicodeDecodeError, which it does not catch."""
    key_file = home / ".solar-challenge" / ".secret_key"
    key_file.parent.mkdir()
    key_file.write_bytes(b"\xff\xfe not a key")

    with pytest.raises(UnicodeDecodeError):
        build_test_app(tmp_path / "data", secret_key=None)

    assert store_lock_is_free(tmp_path / "data")


@pytest.mark.parametrize("flask_debug", ["0", "1"], ids=["debug_off", "debug_on"])
def test_the_session_cookie_is_not_marked_secure(
    flask_debug: str, build_app: BuildApp, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The session cookie is not Secure, in debug mode or out of it: `solar-challenge web start` serves plain HTTP, also to the LAN with --host 0.0.0.0, and browsers withhold a Secure cookie from a non-localhost plain-HTTP origin, so the assistant would lose its chat session on every request."""
    monkeypatch.setenv("FLASK_DEBUG", flask_debug)
    app = build_app(tmp_path)
    client = app.test_client()

    assert client.get("/assistant/history").status_code == 200
    cookie = client.get_cookie(app.config["SESSION_COOKIE_NAME"])
    assert cookie is not None
    assert not cookie.secure


def test_the_app_serves_the_database_its_config_names_and_its_connections_enforce_the_schema(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path)

    with app.app_context():
        database = get_database()

    assert database == Database(Path(app.config["DATABASE"]))
    with closing(database.connect()) as conn:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_the_apps_run_store_keeps_its_runs_in_the_apps_database(build_app: BuildApp, tmp_path: Path) -> None:
    """The app's Database is the one owner of the store's file; its RunStorage borrows it for the runs.

    So the chat rows and presets the app keeps in its Database, and the runs its
    RunStorage keeps, are one file.
    """
    app = build_app(tmp_path)

    with app.app_context():
        assert get_storage().database == get_database()


def test_the_app_serves_its_job_progress_streams_under_the_default_policy(build_app: BuildApp, tmp_path: Path) -> None:
    """Two default policies compare equal: each one's clock is the same builtin, time.monotonic."""
    app = build_app(tmp_path)

    with app.app_context():
        assert get_job_stream_policy() == JobStreamPolicy()


def test_a_job_stream_policy_extension_that_is_not_a_policy_is_refused_naming_its_type(
    build_app: BuildApp, tmp_path: Path
) -> None:
    app = build_app(tmp_path)
    app.extensions["job_stream_policy"] = object()

    with app.app_context(), pytest.raises(TypeError, match=r"\bobject\b"):
        get_job_stream_policy()


def test_dropping_a_closed_app_frees_its_job_manager(tmp_path: Path) -> None:
    """Nothing outside the app keeps its job manager alive, no registry of managers included, so the manager is freed along with the app."""
    app = build_test_app(tmp_path)
    job_manager_ref = weakref.ref(dashboard_of(app).jobs)
    dashboard_of(app).close()

    del app
    gc.collect()

    assert job_manager_ref() is None


def test_an_app_on_a_store_another_app_holds_is_refused_naming_this_process_and_the_holders_running_run_stays_running(
    build_app: BuildApp, tmp_path: Path
) -> None:
    """B12: the refused build never reaches the recovery that would fail the run the holder's job is running."""
    first = build_app(tmp_path)
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
    """The refused build leaves the store's directory holding only the lock file its holder took, so it wrote no database file there."""
    held = acquire_store_lock(tmp_path)
    try:
        with pytest.raises(StoreLocked):
            build_test_app(tmp_path)

        assert sorted(tmp_path.iterdir()) == [held.path]
    finally:
        held.release()


def test_a_build_that_fails_after_taking_its_store_lock_releases_it(tmp_path: Path) -> None:
    """A directory where the database file belongs fails the build when it opens the database."""
    database_path_in(tmp_path).mkdir()

    with pytest.raises(StoreUnreadable) as refused:
        build_test_app(tmp_path)

    assert isinstance(refused.value.__cause__, sqlite3.OperationalError)
    acquire_store_lock(tmp_path).release()


def test_an_app_on_a_legacy_store_refuses_to_build_naming_it_and_both_versions_and_releases_the_store(tmp_path: Path) -> None:
    """B2: the store keeps its bytes, and the refused build has released its lock."""
    legacy = write_pre_548_database(database_path_in(tmp_path))
    bytes_before = legacy.read_bytes()

    with pytest.raises(SchemaVersionMismatch) as refused:
        build_test_app(tmp_path)

    assert (refused.value.path, refused.value.found, refused.value.expected) == (legacy, 0, SCHEMA_VERSION)
    acquire_store_lock(tmp_path).release()
    assert legacy.read_bytes() == bytes_before


_DROPPED = "Dropped: the server shut down before the job ran"


def _seed_a_running_run(directory: Path, run_id: str) -> RunStorage:
    """Leave run *run_id* running in the store in *directory*, as a server stopped mid-job leaves it, through an app closed once it has; return that app's RunStorage, which still reads the store."""
    seeding = build_test_app(directory)
    storage = run_storage_of(seeding)
    storage.create_run(run_id, run_type="home", name="North Roof", n_homes=1, created_at="2026-10-22T09:00:00")
    dashboard_of(seeding).close()
    return storage


def _json_once(client: FlaskClient, url: str, reached: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    """The JSON GET *url* answers as soon as *reached* holds for it; the test fails after 30 s without it."""
    deadline = time.monotonic() + 30
    while not reached(answer := client.get(url).get_json()):
        if time.monotonic() > deadline:
            pytest.fail(f"GET {url} did not answer as awaited within 30 s; it last answered {answer}")
        time.sleep(0.01)
    return answer


def test_create_app_called_without_a_jobs_factory_is_refused_naming_it(tmp_path: Path) -> None:
    store_config = {"TESTING": True, "DATA_DIR": str(tmp_path), "DATABASE": str(database_path_in(tmp_path))}

    with pytest.raises(TypeError, match=r"\bjobs\b"):
        create_app(test_config=store_config)  # type: ignore[call-arg]


def test_the_apps_job_manager_is_the_one_its_factory_built_once_over_the_apps_run_storage(
    build_app: BuildApp, tmp_path: Path
) -> None:
    built: list[tuple[RunStorage, JobManager]] = []

    def jobs(storage: RunStorage) -> JobManager:
        built.append((storage, jobs_in_this_process(storage)))
        return built[-1][1]

    app = build_app(tmp_path, jobs=jobs)

    [(storage, manager)] = built
    with app.app_context():
        assert get_storage() is storage
        assert get_job_manager() is manager


def test_the_apps_accessors_read_its_dashboard(app: Flask) -> None:
    dashboard = dashboard_of(app)

    with app.app_context():
        assert get_storage() is dashboard.storage
        assert get_job_manager() is dashboard.jobs
        assert get_database() is dashboard.database


def test_the_jobs_factory_runs_once_the_store_is_locked_and_open_and_before_the_runs_an_earlier_server_left_running_are_failed(
    build_app: BuildApp, tmp_path: Path
) -> None:
    _seed_a_running_run(tmp_path, "r-1")
    seen_at_the_call: list[tuple[bool, str | None]] = []

    def jobs(storage: RunStorage) -> JobManager:
        record = storage.run_record("r-1")
        seen_at_the_call.append((store_lock_is_free(tmp_path), None if record is None else record.status))
        return jobs_in_this_process(storage)

    app = build_app(tmp_path, jobs=jobs)

    assert seen_at_the_call == [(False, "running")]
    record = run_storage_of(app).run_record("r-1")
    assert record is not None
    assert record.status == "failed"


class _FactoryFailed(Exception):
    """What a jobs factory that cannot build its manager raises."""


def test_a_jobs_factory_that_raises_fails_the_build_with_its_error_and_the_store_is_released_with_its_running_run_left_running(
    tmp_path: Path,
) -> None:
    seeded = _seed_a_running_run(tmp_path, "r-1")

    def jobs(storage: RunStorage) -> JobManager:
        raise _FactoryFailed("no job manager")

    with pytest.raises(_FactoryFailed, match="no job manager"):
        build_test_app(tmp_path, jobs=jobs)

    assert store_lock_is_free(tmp_path)
    record = seeded.run_record("r-1")
    assert record is not None
    assert record.status == "running"


def test_a_closed_app_refuses_a_job_and_its_store_is_free_for_the_next_app(build_app: BuildApp, tmp_path: Path) -> None:
    """B13: a job submitted to a closed app's endpoint raises the manager's RuntimeError naming its shutdown, which an app in testing mode propagates."""
    app = build_app(tmp_path)

    dashboard_of(app).close()

    with pytest.raises(RuntimeError, match="shutdown"):
        app.test_client().post("/api/simulate/home", json=A_HOME_JOB_REQUEST)
    build_app(tmp_path)


def test_closing_an_app_drops_its_queued_job_and_keeps_its_store_until_its_running_job_has_finished(
    build_app: BuildApp, closes_at_teardown: ExitStack, tmp_path: Path
) -> None:
    """B13: while the running job simulates, the closing app's store refuses another app and its run still reads running."""
    blocking_simulation = BlockingSimulation()
    app = build_app(tmp_path, jobs=jobs_running(blocking_simulation, max_workers=1))
    closes_at_teardown.callback(blocking_simulation.release)
    client = app.test_client()
    running = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()
    blocking_simulation.wait_until_started()
    queued = client.post("/api/simulate/home", json=A_HOME_JOB_REQUEST).get_json()
    closing = threading.Thread(target=dashboard_of(app).close, daemon=True)
    closing.start()

    _json_once(client, f"/api/jobs/{queued['job_id']}", lambda job: (job["status"], job["message"]) == ("failed", _DROPPED))

    with pytest.raises(StoreLocked):
        build_test_app(tmp_path)
    assert client.get(f"/api/history/runs/{running['run_id']}").get_json()["status"] == "running"
    assert closing.is_alive()
    blocking_simulation.release()
    closing.join(timeout=30)
    assert not closing.is_alive()
    build_app(tmp_path)


def test_an_app_on_default_jobs_runs_a_fleet_job_to_completed_through_the_parallel_default_runner(
    build_app: BuildApp, tmp_path: Path, weather_cache: WeatherCache
) -> None:
    """Its homes run in a pool of worker processes on the weather default_runner() bound as the app was built: the test's own cache, where Bristol's TMY is a clear day on the first day of the job's window."""
    A_HOME_JOB_DAYS.seed_as_bristol_tmy(weather_cache)
    app = build_app(tmp_path, jobs=default_jobs)
    client = app.test_client()

    submitted = client.post("/api/simulate/fleet", json={"homes": [A_HOME_JOB_REQUEST, {**A_HOME_JOB_REQUEST, "pv_kw": 3.0}]})
    assert submitted.status_code == 201
    assert dashboard_of(app).jobs.wait_until_idle(timeout=120)

    job = client.get(f"/api/jobs/{submitted.get_json()['job_id']}").get_json()
    assert job["status"] == "completed", job
    results = client.get(f"/api/jobs/{submitted.get_json()['job_id']}/results").get_json()
    assert results["summary"]["n_homes"] == 2
    assert results["summary"]["per_home_generation_min_kwh"] > 0


def test_the_package_facade_builds_an_app_whose_jobs_run_on_a_job_manager(
    home: Path, closes_at_teardown: ExitStack
) -> None:
    from solar_challenge.web import create_app as facade_create_app

    app = facade_create_app()
    closes_at_teardown.callback(dashboard_of(app).close)

    assert isinstance(dashboard_of(app).jobs, JobManager)
    assert Path(app.config["DATA_DIR"]) == home / ".solar-challenge"
