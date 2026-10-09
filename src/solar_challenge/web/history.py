# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for run history browsing and comparison.

Provides routes for listing, filtering, searching, and comparing
past simulation runs, plus API endpoints for CRUD operations and
data export.
"""

import logging
from dataclasses import asdict
from typing import Any

logger = logging.getLogger(__name__)

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from solar_challenge.web.shared import get_storage

bp = Blueprint("history", __name__)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@bp.route("/")
def history_index() -> Response:
    """Redirect /history to /history/runs."""
    return redirect(url_for("history.runs_page"))  # type: ignore[return-value]


@bp.route("/runs")
def runs_page() -> str:
    """Render the run history browser page.

    Returns:
        Rendered HTML for the runs list page.
    """
    return str(render_template("history/runs.html", page="history-runs"))


@bp.route("/compare")
def compare_page() -> str | Response:
    """Render the run comparison page.

    Expects query parameter ``ids`` as comma-separated run IDs.
    Redirects to runs page with a flash message only if fewer than two IDs are
    given or fewer than two of them are found in the database; a missing or
    empty ``ids`` renders the no-runs-selected empty state instead.

    Returns:
        Rendered HTML for the comparison page, or redirect.
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        return str(render_template(
            "history/compare.html",
            page="history-compare",
            runs=[],
            charts={},
        ))

    run_ids = [rid.strip() for rid in ids_param.split(",") if rid.strip()]
    if len(run_ids) < 2:
        flash("At least 2 runs are required for comparison.", "error")
        return redirect(url_for("history.runs_page"))  # type: ignore[return-value]
    if len(run_ids) > 4:
        run_ids = run_ids[:4]

    storage = get_storage()
    runs: list[dict[str, Any]] = []
    for rid in run_ids:
        record = storage.run_record(rid)
        if record is not None:
            runs.append(
                {**asdict(record), "summary": record.decoded_summary(), "config": record.decoded_config()}
            )

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


@bp.route("/api/runs")
def api_list_runs() -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_list_runs", **request.args.to_dict()), code=301)  # type: ignore[arg-type]


@bp.route("/api/runs/<run_id>")
def api_get_run(run_id: str) -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_get_run", run_id=run_id), code=301)


@bp.route("/api/runs/<run_id>", methods=["DELETE"])
def api_delete_run(run_id: str) -> Any:
    """Redirect to consolidated API endpoint (preserves DELETE method)."""
    return redirect(url_for("api.history_delete_run", run_id=run_id), code=307)


@bp.route("/api/runs/<run_id>", methods=["PATCH"])
def api_patch_run(run_id: str) -> Any:
    """Redirect to consolidated API endpoint (preserves PATCH method)."""
    return redirect(url_for("api.history_patch_run", run_id=run_id), code=307)


@bp.route("/api/runs/<run_id>/export/csv")
def api_export_csv(run_id: str) -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_export_csv", run_id=run_id), code=301)


@bp.route("/api/runs/<run_id>/export/yaml")
def api_export_yaml(run_id: str) -> Any:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.history_export_yaml", run_id=run_id), code=301)
