# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for the scenario builder and parameter sweep pages.

The JSON endpoints these pages call live under /api/scenarios/, in api.py.
"""

from flask import Blueprint, render_template

from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS

bp = Blueprint("scenarios", __name__)


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
    return str(render_template(
        "scenarios/sweep.html",
        page="scenarios-sweep",
        max_window_days=MAX_WINDOW_DAYS,
    ))
