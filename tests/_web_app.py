# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web dashboard's Flask app for tests, the job manager its jobs run on unless a test gives it another, its database and run files under one directory, the path of the database file it is given there, the Database it keeps its tables in, the RunStorage it keeps its runs in, and whether its store's lock is free.

build_test_app, jobs_in_this_process, database_of, run_storage_of and store_lock_is_free import
the web package when they are called, not when this module loads. So importing this module
needs no web extra, and a call made after a test drops solar_challenge.web.app from
sys.modules imports the factory anew.

An app holds its store's lock until dashboard_of(app).close(), which drops its queued jobs and
waits for its running ones first. A test that builds an app with build_test_app closes it
itself; app_builder(closes_at_teardown), which tests/unit/conftest.py's build_app fixture is,
builds apps that the test's teardown closes. No conftest above tests/unit holds that fixture:
the offline lane's jobs that install the dev extra alone load those conftests, and
tests/_declared_dependencies.py refuses them any import of the web package, at any scope.

Usage::

    from solar_challenge.web.dashboard import dashboard_of
    from tests._web_app import build_test_app, database_of, database_path_in, point_store_config_at_a_missing_directory, run_storage_of, store_lock_is_free
    from tests._web_job_runner import jobs_running

    app = build_test_app(tmp_path)
    database = database_of(app)
    assert database.path == database_path_in(tmp_path)
    storage = run_storage_of(app)
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")
    assert not store_lock_is_free(tmp_path)

    dashboard_of(app).close()
    assert store_lock_is_free(tmp_path)
    rebuilt = build_test_app(tmp_path, jobs=jobs_running(simulation))

    closed_at_teardown = app_builder(closes_at_teardown)(tmp_path / "other")
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from contextlib import ExitStack

    from flask import Flask

    from solar_challenge.web.dashboard import JobManagerFactory
    from solar_challenge.web.database import Database
    from solar_challenge.web.jobs import JobManager
    from solar_challenge.web.storage import RunStorage


class BuildApp(Protocol):
    """What app_builder returns, and so tests/unit/conftest.py's build_app fixture: build_test_app(*data_dir*, ...), whose app a closing stack closes."""

    def __call__(
        self, data_dir: Path, /, *, jobs: JobManagerFactory | None = ..., secret_key: str | None = ...
    ) -> Flask: ...


def app_builder(closes: ExitStack) -> BuildApp:
    """Return a BuildApp that builds each app as build_test_app does and registers its dashboard_of(app).close() on *closes*.

    A build that raises registers nothing. Given the closes_at_teardown fixture, each app closes
    at the test's teardown, after every gate the test's other fixtures hold is released.
    """

    def build(data_dir: Path, /, **options: Any) -> Flask:
        from solar_challenge.web.dashboard import dashboard_of

        app = build_test_app(data_dir, **options)
        closes.callback(dashboard_of(app).close)
        return app

    return build


def build_test_app(
    data_dir: Path, *, jobs: JobManagerFactory | None = None, secret_key: str | None = "test-secret-key"
) -> Flask:
    """Return the dashboard app in testing mode, keeping its database and run files under *data_dir*, its jobs run on the JobManager *jobs* builds over its RunStorage, else on jobs_in_this_process's.

    The test_config supplies *secret_key* as the app's SECRET_KEY. With
    secret_key=None it holds no SECRET_KEY, and create_app looks a key up itself.
    The app holds its store's lock until dashboard_of(app).close().
    """
    from solar_challenge.web.app import create_app

    secret_key_config = {} if secret_key is None else {"SECRET_KEY": secret_key}
    return create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(database_path_in(data_dir)),
            "DATA_DIR": str(data_dir),
            **secret_key_config,
        },
        jobs=jobs_in_this_process if jobs is None else jobs,
    )


def jobs_in_this_process(storage: RunStorage) -> JobManager:
    """The JobManager over *storage* whose jobs run through default_runner(), each fleet's homes in turn.

    So a test's jobs run in its own process, where its fixtures and monkeypatches reach them, on
    default_weather() as it stands when the app is built: a test's weather must be in place before
    it builds the app.
    """
    from dataclasses import replace

    from solar_challenge.fleet import default_runner
    from solar_challenge.web.jobs import JobManager

    return JobManager(storage, runner=replace(default_runner(), parallel=False))


def database_path_in(data_dir: Path) -> Path:
    """Return the database file build_test_app gives an app whose data is under *data_dir*."""
    return data_dir / "test.db"


def database_of(app: Flask) -> Database:
    """Return the Database *app* keeps its tables in: the one its views read, through the accessor they read it with."""
    from solar_challenge.web.dashboard import get_database

    with app.app_context():
        return get_database()


def run_storage_of(app: Flask) -> RunStorage:
    """Return the RunStorage *app* keeps its runs in: the one its pages read, through the accessor they read it with."""
    from solar_challenge.web.dashboard import get_storage

    with app.app_context():
        return get_storage()


def store_lock_is_free(data_dir: Path) -> bool:
    """Whether this process can take the lock on the store in *data_dir*, which it then releases at once: False while an app or a Dashboard holds it."""
    from solar_challenge.web.store_lock import StoreLocked, acquire_store_lock

    try:
        acquire_store_lock(data_dir).release()
    except StoreLocked:
        return False
    return True


def point_store_config_at_a_missing_directory(app: Flask, directory: Path) -> None:
    """Point *app*'s DATABASE and DATA_DIR config into *directory*, which must not exist.

    A request that still read the store's location from the config would fail to open
    its database, because sqlite3.connect does not create a missing directory. So a test
    that sends a request after this call shows that the request used the store
    create_app built.
    """
    assert not directory.exists(), (
        f"{directory} exists, so a request that read the store config could still open a database in it"
    )
    app.config["DATABASE"] = str(database_path_in(directory))
    app.config["DATA_DIR"] = str(directory)
