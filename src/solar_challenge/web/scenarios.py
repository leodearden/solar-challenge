# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for the scenario builder and parameter sweep pages.

The JSON endpoints these pages call live under /api/scenarios/, in api.py.
"""

from typing import Any

from flask import Blueprint, render_template

from solar_challenge.web.api import SWEEP_MAX_STEPS
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.simulation_params import MAX_DAYS

bp = Blueprint("scenarios", __name__)


@bp.route("/builder")
def builder() -> str:
    """Render the scenario builder page with dual-pane editor: a card per fleet component, and its script's part of each.

    Returns:
        Rendered builder.html template.
    """
    return str(render_template(
        "scenarios/builder.html",
        fleet_components=FLEET_COMPONENTS,
        script_components=_script_components(),
    ))


def _script_components() -> list[dict[str, Any]]:
    """What static/js/scenario-builder.js reads of each fleet component, in FLEET_COMPONENTS order."""
    return [
        {
            "key": component.key,
            "fixed_field": component.fixed_field,
            "grammar_key": component.grammar_key,
            "dist": component.builder_default.editor_state(),
        }
        for component in FLEET_COMPONENTS.values()
    ]


@bp.route("/sweep")
def sweep() -> str:
    """Render the parameter sweep configuration page.

    Returns:
        Rendered sweep.html template.
    """
    return str(render_template(
        "scenarios/sweep.html",
        max_days=MAX_DAYS,
        sweep_max_steps=SWEEP_MAX_STEPS,
    ))
