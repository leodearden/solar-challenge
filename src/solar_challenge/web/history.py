"""Flask Blueprint for run history browsing and comparison.

Provides routes for listing, filtering, searching, and comparing
past simulation runs, plus API endpoints for CRUD operations and
data export.
"""

import json
from typing import Any

from flask import (
    Blueprint,
    Response,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
)

from solar_challenge.web.database import get_db
from solar_challenge.web.storage import RunStorage

bp = Blueprint("history", __name__)


def _get_storage() -> RunStorage:
    """Get RunStorage instance configured from Flask app config.

    Returns:
        RunStorage: Configured storage service instance.
    """
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]
    return RunStorage(db_path=db_path, data_dir=data_dir)


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@bp.route("/runs")
def runs_page() -> str:
    """Render the run history browser page.

    Returns:
        Rendered HTML for the runs list page.
    """
    return render_template("history/runs.html", page="history-runs")


@bp.route("/compare")
def compare_page() -> str | tuple[str, int]:
    """Render the run comparison page.

    Expects query parameter ``ids`` as comma-separated run IDs.
    Returns 400 if no IDs are provided or if fewer than 2 are given.

    Returns:
        Rendered HTML for the comparison page, or 400 error.
    """
    ids_param = request.args.get("ids", "")
    if not ids_param:
        abort(400, description="No run IDs provided. Select 2-4 runs to compare.")

    run_ids = [rid.strip() for rid in ids_param.split(",") if rid.strip()]
    if len(run_ids) < 2:
        abort(400, description="At least 2 runs are required for comparison.")
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
        abort(400, description="Could not find at least 2 valid runs to compare.")

    # Build comparison charts
    charts: dict[str, str] = {}
    try:
        from solar_challenge.web.charts import comparison_bar_chart, comparison_radar

        summaries = [r.get("summary", {}) for r in runs]
        labels = [r.get("name", f"Run {i+1}") for i, r in enumerate(runs)]
        charts["bar"] = comparison_bar_chart(summaries, labels)
        charts["radar"] = comparison_radar(summaries, labels)
    except Exception:
        pass

    return render_template(
        "history/compare.html",
        page="history-compare",
        runs=runs,
        charts=charts,
    )


# ---------------------------------------------------------------------------
# API routes (JSON)
# ---------------------------------------------------------------------------


@bp.route("/api/runs")
def api_list_runs() -> Response:
    """Paginated, filterable run list API.

    Query parameters:
        page: Page number (default 1)
        per_page: Items per page (default 20)
        sort: Sort column (default 'created_at')
        order: Sort order 'asc' or 'desc' (default 'desc')
        type: Filter by run type (home, fleet, sweep)
        q: Search query (searches name and notes)
        date_from: Filter runs created on or after this date
        date_to: Filter runs created on or before this date

    Returns:
        JSON response with ``runs`` list and ``pagination`` metadata.
    """
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 20, type=int)
    sort_col = request.args.get("sort", "created_at")
    order = request.args.get("order", "desc")
    run_type = request.args.get("type")
    search_q = request.args.get("q")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")

    # Clamp per_page
    per_page = max(1, min(per_page, 100))
    page = max(1, page)

    # Whitelist sort columns to prevent injection
    allowed_sorts = {"created_at", "name", "type", "status", "duration_seconds", "n_homes"}
    if sort_col not in allowed_sorts:
        sort_col = "created_at"

    order_dir = "ASC" if order.lower() == "asc" else "DESC"

    db_path = current_app.config["DATABASE"]

    with get_db(db_path) as conn:
        cursor = conn.cursor()

        # Build WHERE clause
        conditions: list[str] = []
        params: list[Any] = []

        if run_type:
            conditions.append("type = ?")
            params.append(run_type)

        if search_q:
            conditions.append("(name LIKE ? OR notes LIKE ?)")
            like_q = f"%{search_q}%"
            params.extend([like_q, like_q])

        if date_from:
            conditions.append("created_at >= ?")
            params.append(date_from)

        if date_to:
            conditions.append("created_at <= ?")
            params.append(date_to + "T23:59:59")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Count total matching rows
        count_query = f"SELECT COUNT(*) as cnt FROM runs WHERE {where_clause}"
        cursor.execute(count_query, params)
        total = cursor.fetchone()["cnt"]

        # Fetch paginated results
        offset = (page - 1) * per_page
        data_query = (
            f"SELECT id, name, type, status, created_at, completed_at, "
            f"duration_seconds, n_homes, notes, summary_json "
            f"FROM runs WHERE {where_clause} "
            f"ORDER BY {sort_col} {order_dir} "
            f"LIMIT ? OFFSET ?"
        )
        cursor.execute(data_query, params + [per_page, offset])
        rows = cursor.fetchall()

    # Build response
    runs_list: list[dict[str, Any]] = []
    for row in rows:
        run_dict = dict(row)
        # Parse summary_json to extract key metrics for the table
        summary = {}
        if run_dict.get("summary_json"):
            try:
                summary = json.loads(run_dict["summary_json"])
            except (json.JSONDecodeError, TypeError):
                pass
        run_dict["total_generation_kwh"] = summary.get("total_generation_kwh")
        run_dict["self_consumption_ratio"] = summary.get("self_consumption_ratio")
        # Remove the full JSON from the list response to save bandwidth
        run_dict.pop("summary_json", None)
        runs_list.append(run_dict)

    total_pages = max(1, (total + per_page - 1) // per_page)

    return jsonify({
        "runs": runs_list,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        },
    })


@bp.route("/api/runs/<run_id>")
def api_get_run(run_id: str) -> Response | tuple[Response, int]:
    """Get full run detail including summary and config.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with full run detail, or 404 if not found.
    """
    db_path = current_app.config["DATABASE"]

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

    if row is None:
        return jsonify({"error": "Run not found"}), 404

    run_dict = dict(row)

    # Parse JSON fields
    for field in ("config_json", "summary_json"):
        raw = run_dict.get(field)
        if raw:
            try:
                run_dict[field.replace("_json", "")] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                run_dict[field.replace("_json", "")] = {}

    return jsonify(run_dict)


@bp.route("/api/runs/<run_id>", methods=["DELETE"])
def api_delete_run(run_id: str) -> Response | tuple[Response, int]:
    """Delete a run and its associated files.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON success response, or 404 if not found.
    """
    db_path = current_app.config["DATABASE"]

    # Check if run exists first
    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

    if row is None:
        return jsonify({"error": "Run not found"}), 404

    storage = _get_storage()
    storage.delete_run(run_id)
    return jsonify({"success": True, "message": f"Run {run_id} deleted"})


@bp.route("/api/runs/<run_id>", methods=["PATCH"])
def api_patch_run(run_id: str) -> Response | tuple[Response, int]:
    """Update a run's name and/or notes.

    Expects a JSON body with optional ``name`` and ``notes`` fields.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with updated run data, or 404 if not found.
    """
    db_path = current_app.config["DATABASE"]
    data = request.get_json(silent=True) or {}

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

        if row is None:
            return jsonify({"error": "Run not found"}), 404

        updates: list[str] = []
        params: list[Any] = []

        if "name" in data:
            updates.append("name = ?")
            params.append(data["name"])

        if "notes" in data:
            updates.append("notes = ?")
            params.append(data["notes"])

        if not updates:
            return jsonify({"error": "No fields to update"}), 400

        params.append(run_id)
        set_clause = ", ".join(updates)
        cursor.execute(f"UPDATE runs SET {set_clause} WHERE id = ?", params)

        # Return updated row
        cursor.execute("SELECT * FROM runs WHERE id = ?", (run_id,))
        updated_row = cursor.fetchone()

    return jsonify(dict(updated_row))


@bp.route("/api/runs/<run_id>/export/csv")
def api_export_csv(run_id: str) -> Response | tuple[Response, int]:
    """Export run results as CSV download.

    Args:
        run_id: Unique run identifier.

    Returns:
        CSV file response, or 404 if not found.
    """
    db_path = current_app.config["DATABASE"]

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, type FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

    if row is None:
        return jsonify({"error": "Run not found"}), 404

    storage = _get_storage()
    run_type = row["type"]
    run_name = row["name"] or "run"

    try:
        if run_type == "home":
            _config, results, _summary = storage.load_home_run(run_id)
            df = results.to_dataframe()
        else:
            # For fleet runs, export the aggregate
            fleet_results, _fleet_summary, _per_home = storage.load_fleet_run(run_id)
            # Export first home as representative; full fleet export would need
            # more complex handling
            if fleet_results.per_home_results:
                df = fleet_results.per_home_results[0].to_dataframe()
            else:
                return jsonify({"error": "No data to export"}), 404
    except FileNotFoundError:
        return jsonify({"error": "Run data files not found"}), 404

    csv_data = df.to_csv()
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@bp.route("/api/runs/<run_id>/export/yaml")
def api_export_yaml(run_id: str) -> Response | tuple[Response, int]:
    """Export run config as YAML download.

    Args:
        run_id: Unique run identifier.

    Returns:
        YAML file response, or 404 if not found.
    """
    db_path = current_app.config["DATABASE"]

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, config_json FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

    if row is None:
        return jsonify({"error": "Run not found"}), 404

    config_json = row["config_json"]
    if not config_json:
        return jsonify({"error": "No config data available"}), 404

    try:
        config_dict = json.loads(config_json)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Invalid config data"}), 500

    # Convert to YAML format
    try:
        import yaml
        yaml_data = yaml.dump(config_dict, default_flow_style=False, sort_keys=False)
    except ImportError:
        # Fallback: export as formatted JSON if yaml is not available
        yaml_data = json.dumps(config_dict, indent=2)

    run_name = row["name"] or "run"
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.yaml"

    return Response(
        yaml_data,
        mimetype="text/yaml",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
