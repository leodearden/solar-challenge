# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for the run history pages: the run browser and the run comparison page.

The JSON endpoints the run browser calls, and each run's CSV and YAML exports,
live under /api/history/, in api.py.
"""

from dataclasses import asdict
from typing import Any

from flask import (
    Blueprint,
    Response,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)

from solar_challenge.web.charts import comparison_tabs
from solar_challenge.web.shared import get_storage
from solar_challenge.web.stored_runs import StoredRunUnreadable

bp = Blueprint("history", __name__)


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
    return str(render_template("history/runs.html"))


@bp.route("/compare")
def compare_page() -> str | Response:
    """Render the run comparison page.

    Expects query parameter ``ids`` as comma-separated run IDs.
    Redirects to runs page with a flash message only if fewer than two IDs are
    given or fewer than two of them are found in the database; a missing or
    empty ``ids`` renders the no-runs-selected empty state instead.

    Each run found is compared by its columns and, as ``summary``, its summary's field
    tree, {} while it has none. A run whose summary cannot be read is not compared as a run
    of zeros: the page redirects to the runs page, flashing its StoredRunUnreadable's message,
    which names the run, the document and the field.

    Returns:
        Rendered HTML for the comparison page, or redirect.
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        return str(render_template("history/compare.html", runs=[]))

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
            try:
                summary = record.summary()
            except StoredRunUnreadable as unreadable:
                flash(str(unreadable), "error")
                return redirect(url_for("history.runs_page"))  # type: ignore[return-value]
            runs.append({**asdict(record), "summary": {} if summary is None else asdict(summary)})

    if len(runs) < 2:
        flash("Could not find at least 2 valid runs to compare.", "error")
        return redirect(url_for("history.runs_page"))  # type: ignore[return-value]

    summaries = [r.get("summary", {}) for r in runs]
    labels = [r.get("name", f"Run {i+1}") for i, r in enumerate(runs)]
    return str(render_template(
        "history/compare.html",
        runs=runs,
        tabs=comparison_tabs(summaries, labels),
    ))
