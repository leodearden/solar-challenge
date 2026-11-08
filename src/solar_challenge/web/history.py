# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint for the run history pages: the run browser and the run comparison page.

The JSON endpoints the run browser calls, and each run's CSV and YAML exports,
live under /api/history/, in api.py.
"""

from dataclasses import asdict
from typing import Any

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from werkzeug.wrappers import Response

from solar_challenge.web.charts import ComparedRun, comparison_tabs
from solar_challenge.web.shared import get_storage
from solar_challenge.web.stored_runs import StoredRunUnreadable

bp = Blueprint("history", __name__)


@bp.route("/")
def history_index() -> Response:
    """Redirect /history to /history/runs."""
    return redirect(url_for("history.runs_page"))


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

    Each run found is charted from its RunRecord.headline(), under its name. The page also
    gets each run's columns and, as ``summary``, its RunRecord.summary_tree(), for the Key
    Metrics table. A run that cannot be compared is not compared as a run of zeros: the page
    redirects to the runs page and flashes why. For a run whose summary cannot be read, or
    holds a figure its headline cannot show, the flash is its StoredRunUnreadable's message,
    which names the run, the document and the field. For a run with no summary yet, such as
    one still running or one that failed, the flash names the run.

    Returns:
        Rendered HTML for the comparison page, or redirect.
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        return str(render_template("history/compare.html", runs=[]))

    run_ids = [rid.strip() for rid in ids_param.split(",") if rid.strip()]
    if len(run_ids) < 2:
        return _back_to_runs("At least 2 runs are required for comparison.")
    if len(run_ids) > 4:
        run_ids = run_ids[:4]

    storage = get_storage()
    runs: list[dict[str, Any]] = []
    compared: list[ComparedRun] = []
    for rid in run_ids:
        record = storage.run_record(rid)
        if record is None:
            continue
        try:
            summary_tree = record.summary_tree()
            headline = record.headline()
        except StoredRunUnreadable as unreadable:
            return _back_to_runs(str(unreadable))
        if headline is None:
            return _back_to_runs(f"The run {record.name!r} ({record.id}) cannot be compared: it has no summary.")
        runs.append({**asdict(record), "summary": summary_tree})
        compared.append(ComparedRun(record.name, headline))

    if len(runs) < 2:
        return _back_to_runs("Could not find at least 2 valid runs to compare.")

    return str(render_template("history/compare.html", runs=runs, tabs=comparison_tabs(compared)))


def _back_to_runs(message: str) -> Response:
    """Redirect to the runs page, flashing *message* as an error."""
    flash(message, "error")
    return redirect(url_for("history.runs_page"))
