# SPDX-License-Identifier: AGPL-3.0-or-later
"""The web dashboard's Flask app for tests, its database and run files under one directory, the Database it keeps its tables in, the RunStorage it keeps its runs in, and the release of the store lock it holds.

build_test_app, database_of, run_storage_of and release_store_lock import the web package
when they are called, not when this module loads. So importing this module needs no web
extra, and a call made after a test drops solar_challenge.web.app from sys.modules imports
the factory anew.

Usage::

    from tests._web_app import build_test_app, database_of, point_store_config_at_a_missing_directory, release_store_lock, run_storage_of

    app = build_test_app(tmp_path)
    database = database_of(app)
    storage = run_storage_of(app)
    point_store_config_at_a_missing_directory(app, tmp_path / "missing")

    release_store_lock(app)
    rebuilt = build_test_app(tmp_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask

    from solar_challenge.web.database import Database
    from solar_challenge.web.storage import RunStorage


def build_test_app(
    data_dir: Path, *, secret_key: str | None = "test-secret-key"
) -> Flask:
    """Return the dashboard app in testing mode, keeping its database and run files under *data_dir*.

    The test_config supplies *secret_key* as the app's SECRET_KEY. With
    secret_key=None it holds no SECRET_KEY, and create_app looks a key up itself.
    The app's jobs simulate on default_weather() as it is when the app is built,
    so a test's weather must be in place before it builds the app.
    """
    from solar_challenge.web.app import create_app

    secret_key_config = {} if secret_key is None else {"SECRET_KEY": secret_key}
    return create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(data_dir / "test.db"),
            "DATA_DIR": str(data_dir),
            **secret_key_config,
        }
    )


def database_of(app: Flask) -> Database:
    """Return the Database *app* keeps its tables in: the one its views read, through the accessor they read it with."""
    from solar_challenge.web.shared import get_database

    with app.app_context():
        return get_database()


def run_storage_of(app: Flask) -> RunStorage:
    """Return the RunStorage *app* keeps its runs in: the one its pages read, through the accessor they read it with."""
    from solar_challenge.web.shared import get_storage

    with app.app_context():
        return get_storage()


def release_store_lock(app: Flask) -> None:
    """Release the store lock *app* took on its data directory, as the end of a server's process does, so the test can build another app on that directory.

    Releasing twice is harmless.
    """
    from solar_challenge.web.store_lock import StoreLock

    store_lock = app.extensions.get("store_lock")
    assert isinstance(store_lock, StoreLock), (
        f"app.extensions['store_lock'] is a {type(store_lock).__name__}, not the StoreLock create_app keeps there"
    )
    store_lock.release()


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
    app.config["DATABASE"] = str(directory / "test.db")
    app.config["DATA_DIR"] = str(directory)
