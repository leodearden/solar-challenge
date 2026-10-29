# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask application factory for the Solar Challenge web dashboard."""

import functools
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from flask import Flask, render_template

from solar_challenge.home import simulate_home
from solar_challenge.weather import default_weather
from solar_challenge.web.api import api_bp
from solar_challenge.web.assistant import bp as assistant_bp
from solar_challenge.web.history import bp as history_bp
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.plotly_js import bp as plotly_js_bp
from solar_challenge.web.routes import bp as routes_bp
from solar_challenge.web.schema import open_database
from solar_challenge.web.scenarios import bp as scenarios_bp
from solar_challenge.web.sse import JobStreamPolicy
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.store_lock import acquire_store_lock

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoreLocation:
    """Where a dashboard store is: its data directory, which holds its run files and its lock, and its database file."""

    data_dir: Path
    database: Path


def default_store_location() -> StoreLocation:
    """The store create_app opens unless its config names another, which `solar-challenge web start` serves and `solar-challenge web migrate` migrates: ~/.solar-challenge, and the solar-challenge.db in it."""
    data_dir = Path.home() / ".solar-challenge"
    return StoreLocation(data_dir=data_dir, database=data_dir / "solar-challenge.db")


def _get_secret_key(data_dir: Path) -> str:
    """Return a stable SECRET_KEY, persisting it across restarts.

    Priority: SECRET_KEY env var > persisted file > generate new key.
    """
    env_key = os.environ.get("SECRET_KEY")
    if env_key:
        return env_key

    key_file = data_dir / ".secret_key"
    try:
        if key_file.exists():
            return key_file.read_text().strip()
    except OSError:
        pass

    # Generate and persist a new key
    new_key = os.urandom(24).hex()
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        key_file.write_text(new_key)
        key_file.chmod(0o600)
    except OSError:
        logger.warning("Could not persist SECRET_KEY to %s", key_file)
    return new_key


def _packaged_folder(name: str) -> Path:
    """Return the *name* folder shipped beside this module; raise FileNotFoundError when the installed package lacks it."""
    folder = Path(__file__).parent / name
    if not folder.is_dir():
        raise FileNotFoundError(
            "The web dashboard cannot start: the installed solar_challenge package "
            f"has no {name} folder at {folder}. Reinstall a build of solar-challenge "
            f"that ships solar_challenge/web/{name}."
        )
    return folder


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask web dashboard application.

    Uses the application factory pattern to allow multiple instances
    and easy testing with different configurations.

    .. note::
        One process per store: create_app takes the lock on DATA_DIR's
        dashboard.lock before it opens the database or fails interrupted
        runs, and keeps it on ``app.extensions['store_lock']`` until
        ``StoreLock.release()`` or the end of the process. A second
        create_app on the store, in this process or another, raises
        StoreLocked naming the lock file and the holder's pid.
        The server must still run single-worker: a process forked after
        create_app shares its lock, so a host that forks workers from one
        built app (e.g. ``gunicorn --preload -w 2``) gets past it, and a
        job, whose state is in memory, goes missing from the workers that
        did not create it.
        A host other than ``solar-challenge web start`` must call
        ``solar_challenge.web.jobs.shutdown_all_managers()`` when it stops.

    .. note::
        Its jobs simulate on ``default_weather()`` as resolved when create_app
        runs, so a weather cache installed, or SOLAR_CHALLENGE_WEATHER_CACHE_DIR
        set, after it does not reach them. The dashboard's fleet job still
        reads that provider once per home; S16 brings it prefetch.

    Args:
        test_config: Optional configuration dict to override defaults.
            Useful for testing.  A ``SECRET_KEY`` given here is used as is,
            and the key persisted under ``~/.solar-challenge`` is then
            neither read nor written.

    Returns:
        Flask: The configured Flask application instance.

    Raises:
        FileNotFoundError: If the installed package lacks the dashboard's
            templates or static folder.
        StoreLocked: If another app, in this process or another, holds
            the store's lock.
        StoreLockUnsupported: If this platform has no POSIX flock.
        SchemaVersionMismatch: If the store's database is at a schema
            version other than this solar-challenge's, naming the file and
            both versions; the store is left as it was, and its lock is
            released.
        StoreUnreadable: If the store's database file cannot be read as a
            database, naming it; the file is left as it was, and the
            store's lock is released.
    """
    app = Flask(
        __name__,
        template_folder=_packaged_folder("templates"),
        static_folder=_packaged_folder("static"),
    )

    default_location = default_store_location()

    # Default configuration.  Why the session cookie is not Secure:
    # tests/unit/test_web_app.py::test_the_session_cookie_is_not_marked_secure
    app.config.from_mapping(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        DATA_DIR=str(default_location.data_dir),
        DATABASE=str(default_location.database),
    )

    if test_config is not None:
        # Override with test-specific configuration when provided
        app.config.from_mapping(test_config)

    _register_blueprints(app)

    # Register custom error handlers
    @app.errorhandler(404)
    def page_not_found(e: Exception) -> tuple[str, int]:
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e: Exception) -> tuple[str, int]:
        return render_template("errors/500.html"), 500

    app.extensions["job_stream_policy"] = JobStreamPolicy()

    store_lock = acquire_store_lock(Path(app.config["DATA_DIR"]))
    try:
        _open_store(app, default_location.data_dir)
    except BaseException:
        store_lock.release()
        raise
    app.extensions["store_lock"] = store_lock
    return app


def _open_store(app: Flask, default_data_dir: Path) -> None:
    """Set *app* up on its store, which this process holds the lock on: the secret key, which may be persisted under *default_data_dir*, the database, the RunStorage and JobManager over it, and the failure of the runs an earlier server left running."""
    # Consult the persisted key only when no config source supplied one
    if app.secret_key is None:
        app.secret_key = _get_secret_key(default_data_dir)

    database = open_database(Path(app.config["DATABASE"]))
    app.extensions["database"] = database

    # Initialize RunStorage singleton
    storage = RunStorage(database, app.config["DATA_DIR"])
    app.extensions["storage"] = storage

    # Initialize JobManager for background simulation execution, recording its jobs' runs in the app's storage
    job_manager = JobManager(storage, simulate_home=functools.partial(simulate_home, weather=default_weather()))
    app.extensions["job_manager"] = job_manager

    # Fail the runs whose jobs an earlier server left running when it stopped
    interrupted = storage.fail_interrupted_runs()
    if interrupted:
        logger.info("Marked %d runs interrupted by a server restart failed on startup", interrupted)


def _register_blueprints(app: Flask) -> None:
    """Register each of the dashboard's blueprints on *app*."""
    app.register_blueprint(routes_bp)
    app.register_blueprint(history_bp, url_prefix="/history")
    app.register_blueprint(scenarios_bp, url_prefix="/scenarios")
    app.register_blueprint(api_bp)
    app.register_blueprint(assistant_bp, url_prefix="/assistant")
    app.register_blueprint(plotly_js_bp)
