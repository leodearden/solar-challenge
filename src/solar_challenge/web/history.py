"""Flask Blueprint for run history browsing and comparison.

Provides routes for listing, filtering, searching, and comparing
past simulation runs, plus API endpoints for CRUD operations and
data export.
"""

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from solar_challenge.web.database import get_db
from solar_challenge.web.shared import get_storage

bp = Blueprint("history", __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@bp.route("/")
def history_index() -> Response:
    """Redirect /history to /history/runs."""
    return redirect(url_for("history.runs_page"))  # type: ignore[return-value]


@bp.route("/runs")  # type: ignore[untyped-decorator]
def runs_page() -> str:
    """Render the run history browser page.

    Returns:
        Rendered HTML for the runs list page.
    """
    return str(render_template("history/runs.html", page="history-runs"))


@bp.route("/compare")  # type: ignore[untyped-decorator]
def compare_page() -> str | Response:
    """Render the run comparison page.

    Expects query parameter ``ids`` as comma-separated run IDs.
    Redirects to runs page with a flash message if IDs are missing or insufficient.

    Returns:
        Rendered HTML for the comparison page, or redirect.
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        flash("No run IDs provided. Select 2-4 runs to compare.", "error")
        return redirect(url_for("history.runs_page"))  # type: ignore[return-value]

    run_ids = [rid.strip() for rid in ids_param.split(",") if rid.strip()]
    if len(run_ids) < 2:
        flash("At least 2 runs are required for comparison.", "error")
        return redirect(url_for("history.runs_page"))  # type: ignore[return-value]
    if len(run_ids) > 4:
        run_ids = run_ids[:4]

    db_path = current_app.config["DATABASE"]
    runs: list[dict[str, Any]] = []
    for rid in run_ids:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM runs WHERE id = ?", (rid,))
            row = cursor.fetchone()
            if row is not None:
                run_dict = dict(row)
                # Parse summary JSON for display
                if run_dict.get("summary_json"):
                    try:
                        run_dict["summary"] = json.loads(run_dict["summary_json"])
                    except (json.JSONDecodeError, TypeError):
                        run_dict["summary"] = {}
                else:
                    run_dict["summary"] = {}
                # Parse config JSON for display
                if run_dict.get("config_json"):
                    try:
                        run_dict["config"] = json.loads(run_dict["config_json"])
                    except (json.JSONDecodeError, TypeError):
                        run_dict["config"] = {}
                else:
                    run_dict["config"] = {}
                runs.append(run_dict)

    if len(runs) < 2:
        flash("Could not find at least 2 valid runs to compare.", "error")
        return redirect(url_for("history.runs_page"))  # type: ignore[return-value]

    # Build comparison charts
    charts: dict[str, str] = {}
    try:
        from solar_challenge.web.charts import comparison_bar_chart, comparison_radar

        summaries = [r.get("summary", {}) for r in runs]
        labels = [r.get("name", f"Run {i+1}") for i, r in enumerate(runs)]
        charts["bar"] = comparison_bar_chart(summaries, labels)
        charts["radar"] = comparison_radar(summaries, labels)
    except Exception:
        logger.warning("Failed to generate comparison charts", exc_info=True)

    return str(render_template(
        "history/compare.html",
        page="history-compare",
        runs=runs,
        charts=charts,
    ))


# ---------------------------------------------------------------------------
# API routes (legacy redirects to /api/history/*)
# ---------------------------------------------------------------------------


@bp.route("/api/runs")  # type: ignore[untyped-decorator]
def api_list_runs() -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_list_runs", **request.args), code=301)  # type: ignore[return-value]


@bp.route("/api/runs/<run_id>")  # type: ignore[untyped-decorator]
def api_get_run(run_id: str) -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_get_run", run_id=run_id), code=301)  # type: ignore[return-value]


@bp.route("/api/runs/<run_id>", methods=["DELETE"])  # type: ignore[untyped-decorator]
def api_delete_run(run_id: str) -> Response:
    """Redirect to consolidated API endpoint (preserves DELETE method)."""
    return redirect(url_for("api.history_delete_run", run_id=run_id), code=307)  # type: ignore[return-value]


@bp.route("/api/runs/<run_id>", methods=["PATCH"])  # type: ignore[untyped-decorator]
def api_patch_run(run_id: str) -> Response:
    """Redirect to consolidated API endpoint (preserves PATCH method)."""
    return redirect(url_for("api.history_patch_run", run_id=run_id), code=307)  # type: ignore[return-value]


@bp.route("/api/runs/<run_id>/export/csv")  # type: ignore[untyped-decorator]
def api_export_csv(run_id: str) -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_export_csv", run_id=run_id), code=301)  # type: ignore[return-value]


@bp.route("/api/runs/<run_id>/export/yaml")  # type: ignore[untyped-decorator]
def api_export_yaml(run_id: str) -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_export_yaml", run_id=run_id), code=301)  # type: ignore[return-value]
