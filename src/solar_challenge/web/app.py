# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask application factory for the Solar Challenge web dashboard."""

import atexit
import logging
import os
from pathlib import Path
from typing import Any

from flask import Flask, render_template

from solar_challenge.web.api import api_bp
from solar_challenge.web.assistant import bp as assistant_bp
from solar_challenge.web.database import init_db
from solar_challenge.web.history import bp as history_bp
from solar_challenge.web.jobs import JobManager, recover_stale_jobs
from solar_challenge.web.routes import bp as routes_bp
from solar_challenge.web.scenarios import bp as scenarios_bp
from solar_challenge.web.storage import RunStorage

logger = logging.getLogger(__name__)


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


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    """Create and configure the Flask web dashboard application.

    Uses the application factory pattern to allow multiple instances
    and easy testing with different configurations.

    .. note::
        This application requires single-worker deployment because the
        JobManager uses in-memory state (job tracking dicts and SSE event
        queues) that is not shared across processes.  Multi-worker
        deployment (e.g. ``gunicorn -w 2+``) will cause jobs to appear
        missing from workers that did not create them.

    Args:
        test_config: Optional configuration dict to override defaults.
            Useful for testing.  A ``SECRET_KEY`` given here is used as is,
            and the key persisted under ``~/.solar-challenge`` is then
            neither read nor written.

    Returns:
        Flask: The configured Flask application instance.
    """
    # Resolve template and static folder paths relative to this file
    web_dir = Path(__file__).parent
    template_folder = str(web_dir / "templates")
    static_folder = str(web_dir / "static")

    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )

    # Default data directory configuration
    default_data_dir = Path.home() / ".solar-challenge"
    default_db_path = default_data_dir / "solar-challenge.db"

    # Default configuration.  Why the session cookie is not Secure:
    # tests/unit/test_web_app.py::test_the_session_cookie_is_not_marked_secure
    app.config.from_mapping(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=False,
        DATA_DIR=str(default_data_dir),
        DATABASE=str(default_db_path),
    )

    if test_config is not None:
        # Override with test-specific configuration when provided
        app.config.from_mapping(test_config)

    # Consult the persisted key only when no config source supplied one
    if app.secret_key is None:
        app.secret_key = _get_secret_key(default_data_dir)

    # Ensure template and static directories exist
    for folder in (template_folder, static_folder):
        os.makedirs(folder, exist_ok=True)

    # Initialize database with configured path
    db_path = app.config["DATABASE"]
    init_db(db_path)

    # Initialize RunStorage singleton
    storage = RunStorage(db_path=db_path, data_dir=app.config["DATA_DIR"])
    app.extensions["storage"] = storage

    # Initialize JobManager for background simulation execution
    job_manager = JobManager()
    app.extensions["job_manager"] = job_manager

    # Recover jobs stuck from previous server shutdown
    recovered = recover_stale_jobs(db_path)
    if recovered:
        logger.info("Recovered %d stale jobs on startup", recovered)

    # Register shutdown handler
    atexit.register(job_manager.shutdown)

    _register_blueprints(app)

    # Register custom error handlers
    @app.errorhandler(404)
    def page_not_found(e: Exception) -> tuple[str, int]:
        return render_template("errors/404.html", page="error"), 404

    @app.errorhandler(500)
    def internal_server_error(e: Exception) -> tuple[str, int]:
        return render_template("errors/500.html", page="error"), 500

    return app


def _register_blueprints(app: Flask) -> None:
    """Register the blueprint of each feature area on *app*."""
    app.register_blueprint(routes_bp)
    app.register_blueprint(history_bp, url_prefix="/history")
    app.register_blueprint(scenarios_bp, url_prefix="/scenarios")
    app.register_blueprint(api_bp)
    app.register_blueprint(assistant_bp, url_prefix="/assistant")


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
