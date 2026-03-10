"""Flask application factory for the Solar Challenge web dashboard."""

import logging
import os
from pathlib import Path

from flask import Flask, render_template

from solar_challenge.web.database import init_db

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


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the Flask web dashboard application.

    Uses the application factory pattern to allow multiple instances
    and easy testing with different configurations.

    Args:
        test_config: Optional configuration dict to override defaults.
            Useful for testing.

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

    # Default configuration
    app.config.from_mapping(
        SECRET_KEY=_get_secret_key(default_data_dir),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        DATA_DIR=str(default_data_dir),
        DATABASE=str(default_db_path),
    )

    if test_config is not None:
        # Override with test-specific configuration when provided
        app.config.from_mapping(test_config)

    # Secure session cookie when not in debug mode
    if "SESSION_COOKIE_SECURE" not in app.config:
        app.config["SESSION_COOKIE_SECURE"] = not app.debug

    # Ensure template and static directories exist
    for folder in (template_folder, static_folder):
        os.makedirs(folder, exist_ok=True)

    # Initialize database with configured path
    db_path = app.config["DATABASE"]
    init_db(db_path)

    # Initialize RunStorage singleton
    from solar_challenge.web.storage import RunStorage
    storage = RunStorage(db_path=db_path, data_dir=app.config["DATA_DIR"])
    app.extensions["storage"] = storage

    # Initialize JobManager for background simulation execution
    try:
        from solar_challenge.web.jobs import JobManager, recover_stale_jobs
        job_manager = JobManager()
        app.extensions["job_manager"] = job_manager

        # Recover jobs stuck from previous server shutdown
        recovered = recover_stale_jobs(db_path)
        if recovered:
            logger.info("Recovered %d stale jobs on startup", recovered)

        # Register shutdown handler
        import atexit
        atexit.register(job_manager.shutdown)
    except ImportError as e:
        logger.warning("JobManager not available: %s", e)

    # Register blueprints (deferred to allow routes to exist independently)
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
    """Register application blueprints.

    Attempts to register multiple blueprints for different feature areas:
    - simulation: Main simulation interface (routes.py for now)
    - history: Simulation run history and comparison
    - scenarios: Saved configuration presets and templates
    - assistant: AI chat assistant for simulation help

    Args:
        app: The Flask application instance.
    """
    # Register main routes blueprint (simulation interface)
    try:
        from solar_challenge.web.routes import bp
        app.register_blueprint(bp)
    except ImportError as e:
        logger.warning("Routes blueprint not available: %s", e)

    # Register history blueprint
    try:
        from solar_challenge.web.history import bp as history_bp
        app.register_blueprint(history_bp, url_prefix="/history")
    except ImportError as e:
        logger.warning("History blueprint not available: %s", e)

    # Register scenarios blueprint
    try:
        from solar_challenge.web.scenarios import bp as scenarios_bp
        app.register_blueprint(scenarios_bp, url_prefix="/scenarios")
    except ImportError as e:
        logger.warning("Scenarios blueprint not available: %s", e)

    # Register API blueprint (background simulation endpoints)
    try:
        from solar_challenge.web.api import api_bp
        app.register_blueprint(api_bp)
    except ImportError as e:
        logger.warning("API blueprint not available: %s", e)

    # Register assistant blueprint
    try:
        from solar_challenge.web.assistant import bp as assistant_bp
        app.register_blueprint(assistant_bp, url_prefix="/assistant")
    except ImportError as e:
        logger.warning("Assistant blueprint not available: %s", e)


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
