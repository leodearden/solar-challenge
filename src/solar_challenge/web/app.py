"""Flask application factory for the Solar Challenge web dashboard."""

import os
from pathlib import Path

from flask import Flask, render_template

from solar_challenge.web.database import close_db, init_db


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
        SECRET_KEY=os.environ.get("SECRET_KEY", os.urandom(24).hex()),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        DATA_DIR=str(default_data_dir),
        DATABASE=str(default_db_path),
    )

    if test_config is not None:
        # Override with test-specific configuration when provided
        app.config.from_mapping(test_config)

    # Ensure template and static directories exist
    for folder in (template_folder, static_folder):
        os.makedirs(folder, exist_ok=True)

    # Initialize database with configured path
    db_path = app.config["DATABASE"]
    init_db(db_path)

    # Register database cleanup on app context teardown
    @app.teardown_appcontext
    def teardown_db(exception: Exception | None = None) -> None:
        """Close database connection on app context teardown.

        Args:
            exception: Exception that caused teardown, if any.
        """
        close_db(db_path)

    # Initialize JobManager for background simulation execution
    try:
        from solar_challenge.web.jobs import JobManager
        app.extensions["job_manager"] = JobManager()
    except ImportError:
        # jobs.py not yet implemented
        pass

    # Register blueprints (deferred to allow routes to exist independently)
    _register_blueprints(app)

    # Register custom error handlers
    @app.errorhandler(404)
    def page_not_found(e: Exception) -> tuple[str, int]:
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def internal_server_error(e: Exception) -> tuple[str, int]:
        return render_template("errors/500.html"), 500

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
    except ImportError:
        # Routes not yet implemented - skip registration during setup phase
        pass

    # Register history blueprint
    try:
        from solar_challenge.web.history import bp as history_bp
        app.register_blueprint(history_bp, url_prefix="/history")
    except ImportError:
        # History blueprint not yet implemented
        pass

    # Register scenarios blueprint
    try:
        from solar_challenge.web.scenarios import bp as scenarios_bp
        app.register_blueprint(scenarios_bp, url_prefix="/scenarios")
    except ImportError:
        # Scenarios blueprint not yet implemented
        pass

    # Register API blueprint (background simulation endpoints)
    try:
        from solar_challenge.web.api import api_bp
        app.register_blueprint(api_bp)
    except ImportError:
        # API blueprint not yet implemented
        pass

    # Register assistant blueprint
    try:
        from solar_challenge.web.assistant import bp as assistant_bp
        app.register_blueprint(assistant_bp, url_prefix="/assistant")
    except ImportError:
        # Assistant blueprint not yet implemented
        pass


if __name__ == "__main__":
    application = create_app()
    application.run(debug=True)
