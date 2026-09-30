# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for scenario building and parameter sweep configuration.

Provides page routes for the scenario builder and sweep configuration UI,
as well as API endpoints for YAML preview, validation, saving, and loading
scenario presets.
"""

import logging
from typing import Any

from flask import Blueprint, redirect, render_template, url_for

logger = logging.getLogger(__name__)

bp = Blueprint("scenarios", __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@bp.route("/builder")
def builder() -> str:
    """Render the scenario builder page with dual-pane editor.

    Returns:
        Rendered builder.html template.
    """
    return str(render_template("scenarios/builder.html", page="scenarios-builder"))


@bp.route("/sweep")
def sweep() -> str:
    """Render the parameter sweep configuration page.

    Returns:
        Rendered sweep.html template.
    """
    return str(render_template("scenarios/sweep.html", page="scenarios-sweep"))


# ---------------------------------------------------------------------------
# API routes (legacy redirects to /api/scenarios/*)
# ---------------------------------------------------------------------------


@bp.route("/api/preview-yaml", methods=["POST"])
def preview_yaml() -> Any:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_preview_yaml"), code=307)

@bp.route("/api/validate", methods=["POST"])
def validate_scenario() -> Any:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_validate_scenario"), code=307)

@bp.route("/api/save", methods=["POST"])
def save_scenario() -> Any:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_save_scenario"), code=307)

@bp.route("/api/presets", methods=["GET"])
def list_presets() -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.scenarios_list_presets"), code=301)

@bp.route("/api/presets/<name>", methods=["GET"])
def get_preset(name: str) -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.scenarios_get_preset", name=name), code=301)