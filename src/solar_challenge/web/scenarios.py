# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for the scenario builder and parameter sweep pages, and the sweep page's chart endpoint.

The chart endpoint, POST /scenarios/sweep/chart, answers HTML: the sweep's chart panels, drawn
from its finished points' stored runs. It refuses a request in JSON, and a stored run it cannot
read with the 409 of every JSON answer (D-S19-9), which the blueprint registers. The JSON
endpoints these pages call live under /api/, in api.py.
"""

from typing import Any, assert_never

from flask import Blueprint, Response, jsonify, render_template

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet import FleetSummary
from solar_challenge.fleet_distribution import SweepMode, SweepSpec
from solar_challenge.home import SummaryStatistics
from solar_challenge.location import LOCATION_PRESETS
from solar_challenge.number_fields import as_finite_float
from solar_challenge.web.charts import SweepPoint, sweep_panels
from solar_challenge.web.dashboard import get_storage
from solar_challenge.web.request_boundary import (
    refusal_text,
    refuse_unrecognised_keys,
    request_json_object,
    require_encodable_text,
    require_json_object,
)
from solar_challenge.web.stored_runs import StoredRunUnreadable
from solar_challenge.web.sweep_request import SWEEP_MAX_STEPS, SWEEP_PARAMETERS
from solar_challenge.web.unreadable_run_answer import answer_stored_run_unreadable

bp = Blueprint("scenarios", __name__)
bp.register_error_handler(StoredRunUnreadable, answer_stored_run_unreadable)


@bp.route("/builder")
def builder() -> str:
    """Render the scenario builder page with dual-pane editor: a card per fleet component, each starting at its start in #page-limits.

    Returns:
        Rendered builder.html template.
    """
    return str(render_template("scenarios/builder.html", location_presets=LOCATION_PRESETS))


@bp.route("/sweep")
def sweep() -> str:
    """Render the parameter sweep configuration page: an option per SWEEP_PARAMETERS row, carrying the range the page starts at when it is chosen, and a radio per SweepMode, SweepSpec's default checked.

    Returns:
        Rendered sweep.html template.
    """
    return str(render_template(
        "scenarios/sweep.html",
        sweep_parameters=SWEEP_PARAMETERS,
        sweep_modes=tuple(SweepMode),
        default_sweep_mode=SweepSpec.mode,
        sweep_max_steps=SWEEP_MAX_STEPS,
        location_presets=LOCATION_PRESETS,
    ))


@bp.route("/sweep/chart", methods=["POST"])
def sweep_chart() -> str | tuple[Response, int]:
    """Answer the HTML of the sweep page's chart panels, drawn from the stored runs of the sweep's finished points.

    The body is {"parameter_label": str, "points": [{"value": number, "run_id": str}, ...]},
    the points those whose jobs completed, in sweep order. The whole body is read before any run.

    Returns:
        The panels sweep_panels draws, one per SweepMetric. HTTP 400 with the error naming the
        field or the run refused; HTTP 409, as the blueprint answers a StoredRunUnreadable, for a
        run whose summary cannot be read.
    """
    try:
        parameter_label, requested = _sweep_chart_request(request_json_object())
    except ValueError as refusal:
        return jsonify({"error": refusal_text(refusal)}), 400
    try:
        points = [_finished_point(value, run_id) for value, run_id in requested]
    except _NotAFinishedHomeRun as refusal:
        return jsonify({"error": str(refusal)}), 400
    return str(render_template(
        "scenarios/partials/sweep-panels.html",
        panels=sweep_panels(parameter_label, points),
    ))


def _sweep_chart_request(body: dict[str, Any]) -> tuple[str, list[tuple[float, str]]]:
    """The parameter label of the sweep chart request *body*, and each of its points' value and run id, in order.

    Raises:
        ConfigurationError: Naming the field of *body* the sweep chart cannot read.
    """
    refuse_unrecognised_keys(body, {"parameter_label", "points"}, "Request body")
    parameter_label = body.get("parameter_label")
    if not isinstance(parameter_label, str) or not parameter_label.strip():
        raise ConfigurationError(f"parameter_label must be the swept parameter's label, not blank; got {parameter_label!r}")
    points = body.get("points")
    if not isinstance(points, list):
        raise ConfigurationError(f"points must be a list of the sweep's finished points, got {type(points).__name__}")
    if len(points) > SWEEP_MAX_STEPS:
        raise ConfigurationError(
            f"points must hold at most {SWEEP_MAX_STEPS} points, the most steps a sweep has; got {len(points)}"
        )
    return parameter_label, [_requested_point(point, f"points[{index}]") for index, point in enumerate(points)]


def _requested_point(point: object, what: str) -> tuple[float, str]:
    """The value and run id of *point*, the request's *what*.

    Raises:
        ConfigurationError: Naming *what*, or its field, when *point* is not a {"value", "run_id"}
            object of a finite number and a string that encodes as UTF-8.
    """
    fields = require_json_object(point, what)
    refuse_unrecognised_keys(fields, {"value", "run_id"}, what)
    value = as_finite_float(fields.get("value"), f"{what}.value")
    run_id = fields.get("run_id")
    if not isinstance(run_id, str):
        raise ConfigurationError(f"{what}.run_id must be the id of the point's run, a string; got {run_id!r}")
    return value, require_encodable_text(run_id, f"{what}.run_id")


class _NotAFinishedHomeRun(ConfigurationError):
    """The request's refusal of a sweep point whose run is not a finished home run: no run has its id, or it is a fleet run or has no summary yet; the message names the run id."""


def _finished_point(value: float, run_id: str) -> SweepPoint:
    """The sweep point that swept to *value*, its summary that of home run *run_id*.

    Raises:
        _NotAFinishedHomeRun: If no run has *run_id*, or that run is a fleet run or has no
            summary yet.
        StoredRunUnreadable: From RunRecord.summary(), for a summary that cannot be read.
    """
    record = get_storage().run_record(run_id)
    if record is None:
        raise _NotAFinishedHomeRun(f"Run {run_id!r} is unknown: no run has that id")
    match record.summary():
        case SummaryStatistics() as summary:
            return SweepPoint(value, summary)
        case FleetSummary():
            raise _NotAFinishedHomeRun(f"Run {run_id!r} is a fleet run, not a home run: each sweep point runs one home")
        case None:
            raise _NotAFinishedHomeRun(f"Run {run_id!r} has no summary yet: its job has not saved its results")
        case unexpected:
            assert_never(unexpected)
