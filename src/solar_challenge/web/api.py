# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint providing JSON API endpoints for background simulations.

Provides REST endpoints for submitting simulation jobs, polling status,
streaming progress via SSE, retrieving results, and consolidated history
and scenarios API endpoints under the /api/ prefix.
"""

import json
import logging
import time
from collections.abc import Mapping
from dataclasses import asdict
from pathlib import Path
from typing import Any, Generator

import yaml as _yaml
import pandas as pd
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from solar_challenge.config import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.scenario_writer import fleet_scenario, home_scenario, scenario_yaml
from solar_challenge.web.builder_form import builder_form_errors, scenario_from_builder_form
from solar_challenge.web.database import get_db
from solar_challenge.web.fleet_scenario import (
    fleet_form_from_scenario,
    parse_fleet_form,
    scenario_from_fleet_form,
)
from solar_challenge.web.presets import (
    PresetNameTaken,
    PresetType,
    home_preset_named,
    home_presets,
    save_config_preset,
)
from solar_challenge.web.shared import (
    NotAJsonObject,
    get_job_manager,
    get_storage,
    request_json_object,
    require_json_object,
)
from solar_challenge.web.simulation_params import parse_home_config, with_default_days
from solar_challenge.web.storage import RUN_LABELS, stored_fleet_home_configs, stored_home_config

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.errorhandler(NotAJsonObject)
def _refuse_a_value_that_is_not_a_json_object(refusal: NotAJsonObject) -> tuple[Response, int]:
    """Answer HTTP 400 with the refusal of a request value that must be a JSON object and is not one.

    Any endpoint of this blueprint that reads such a value is answered this way.
    """
    return jsonify({"error": str(refusal)}), 400


@api_bp.route("/simulate/home", methods=["POST"])
def simulate_home_api() -> tuple[Response, int]:
    """Submit a home simulation job for background execution.

    Expects a JSON body with simulation parameters.

    Returns:
        JSON with job_id and run_id, HTTP 201 on success.
    """
    data = request_json_object()
    try:
        home_config, start_date, end_date, name = parse_home_config(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    job_manager = get_job_manager()
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]

    job_id, run_id = job_manager.submit_home_job(
        config=home_config,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
        data_dir=data_dir,
        name=name,
    )

    return jsonify({"job_id": job_id, "run_id": run_id}), 201

@api_bp.route("/simulate/fleet", methods=["POST"])
def simulate_fleet_api() -> tuple[Response, int]:
    """Submit a fleet simulation job for background execution.

    Expects a JSON body with a non-empty array of home configs under the 'homes' key.

    Returns:
        JSON with job_id and run_id, HTTP 201 on success.
    """
    data = request_json_object()
    homes_data = data.get("homes", [])
    if not isinstance(homes_data, list):
        return jsonify({"error": f"homes must be a JSON array, got {type(homes_data).__name__}"}), 400
    if not homes_data:
        return jsonify({"error": "Fleet requires at least one home config in 'homes' array"}), 400
    try:
        configs = []
        # Use first home's date config for the fleet
        first_config, start_date, end_date, _ = parse_home_config(homes_data[0])
        configs.append(first_config)

        for home_data in homes_data[1:]:
            config, _, _, _ = parse_home_config(home_data)
            configs.append(config)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    fleet_name = data.get("name", "Fleet Simulation")

    job_manager = get_job_manager()
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]

    job_id, run_id = job_manager.submit_fleet_job(
        configs=configs,
        start_date=start_date,
        end_date=end_date,
        db_path=db_path,
        data_dir=data_dir,
        name=fleet_name,
    )

    return jsonify({"job_id": job_id, "run_id": run_id}), 201

@api_bp.route("/jobs/<job_id>", methods=["GET"])
def get_job_status(job_id: str) -> tuple[Response, int]:
    """Return current job status as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with job status fields, or 404 if not found.
    """
    job_manager = get_job_manager()
    status = job_manager.get_job_status(job_id)

    if status is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status), 200

@api_bp.route("/jobs/<job_id>/progress", methods=["GET"])
def get_job_progress(job_id: str) -> Response:
    """SSE endpoint for streaming job progress events.

    Sends heartbeat every 2 seconds and streams progress/completion events.

    Args:
        job_id: Unique job identifier.

    Returns:
        text/event-stream response.
    """
    job_manager = get_job_manager()

    def generate_events() -> Generator[str, None, None]:
        """Generate SSE events for the job."""
        start_time = time.time()
        max_duration = 600  # 10 minutes
        while True:
            if time.time() - start_time > max_duration:
                yield "event: error\ndata: {\"error\": \"SSE stream timed out after 10 minutes\"}\n\n"
                return
            # Check if job exists
            status = job_manager.get_job_status(job_id)
            if status is None:
                yield "event: error\ndata: {\"error\": \"Job not found\"}\n\n"
                return

            # Drain event queue
            for event in job_manager.get_events(job_id):
                event_type = event.get("event", "message")
                event_data = json.dumps(event.get("data", {}))
                yield f"event: {event_type}\ndata: {event_data}\n\n"

                # If this is a completion or error event, stop streaming
                if event_type in ("complete", "error"):
                    return

            # Check if job is in a terminal state (might have finished
            # before we started listening)
            if status.get("status") in ("completed", "failed"):
                if status["status"] == "completed":
                    yield (
                        f"event: complete\n"
                        f"data: {json.dumps({'status': 'completed', 'run_id': status.get('run_id', '')})}\n\n"
                    )
                else:
                    yield (
                        f"event: error\n"
                        f"data: {json.dumps({'status': 'failed', 'message': status.get('message', 'Unknown error')})}\n\n"
                    )
                return

            # Send heartbeat
            yield ":heartbeat\n\n"
            time.sleep(2)

    return Response(
        stream_with_context(generate_events()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@api_bp.route("/jobs/<job_id>/results", methods=["GET"])
def get_job_results(job_id: str) -> tuple[Response, int]:
    """Return completed job results as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with summary data, or 404/409 on error.
    """
    job_manager = get_job_manager()
    status = job_manager.get_job_status(job_id)

    if status is None:
        return jsonify({"error": "Job not found"}), 404
    if status.get("status") != "completed":
        return jsonify({
            "error": "Job not yet completed",
            "status": status.get("status"),
            "progress_pct": status.get("progress_pct", 0),
        }), 409
    # Load run summary from database
    run_id = status.get("run_id", "")
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404
    summary = json.loads(run.summary_json) if run.summary_json else {}

    return jsonify({
        "run_id": run_id,
        "name": run.name,
        "type": run.type,
        "created_at": run.created_at,
        "summary": summary,
    }), 200

# ---------------------------------------------------------------------------
# Config preset endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/presets", methods=["GET"])
def list_presets() -> tuple[Response, int]:
    """List the home presets: the built-in presets, then the saved home presets by name, each name once.

    Returns:
        JSON array of preset objects, HTTP 200.
    """
    return jsonify(home_presets(current_app.config["DATABASE"])), 200

def _answer_preset_save(name: str, preset_type: PresetType, config: Mapping[str, Any]) -> tuple[Response, int]:
    """Save *config* as the *preset_type* preset *name*, answering as both preset save endpoints do.

    Returns:
        JSON with the preset name and id, HTTP 201; or the ``error``: HTTP 409 for a
        name another preset holds, HTTP 500 for a database fault.
    """
    try:
        preset_id = save_config_preset(current_app.config["DATABASE"], name, preset_type, config)
    except PresetNameTaken as taken:
        return jsonify({"error": str(taken)}), 409
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201

@api_bp.route("/presets", methods=["POST"])
def save_preset() -> tuple[Response, int]:
    """Save a home preset to the database.

    Expects a JSON body with at least ``name`` and configuration fields. A ``type``, when sent,
    must be 'home': fleet presets are saved through POST /api/scenarios/save.

    Returns:
        JSON confirmation with the preset name and id, HTTP 201 on success; or the ``error``:
        HTTP 400 for an empty name or a type other than 'home', HTTP 409 for a name a built-in
        home preset or a saved fleet preset holds.
    """
    data = request_json_object()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Preset name is required"}), 400
    preset_type = data.get("type", "home")
    if preset_type != "home":
        return jsonify(
            {"error": f"type must be 'home', got {preset_type!r}; POST /api/scenarios/save saves fleet presets"}
        ), 400
    config_payload = {
        k: v for k, v in data.items() if k not in ("name", "type")
    }
    return _answer_preset_save(name, "home", config_payload)

@api_bp.route("/presets/<name>", methods=["GET"])
def get_preset(name: str) -> tuple[Response, int]:
    """Get the home preset GET /api/presets lists under *name*.

    A built-in preset's name therefore answers the built-in preset, and a name only a
    saved fleet preset holds is not found.

    Args:
        name: The preset name to look up.

    Returns:
        JSON preset object, HTTP 200; or the ``error``, HTTP 404, when no home preset has the name.
    """
    preset = home_preset_named(current_app.config["DATABASE"], name)
    if preset is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return jsonify(preset), 200

# ---------------------------------------------------------------------------
# Fleet distribution endpoints
# ---------------------------------------------------------------------------


@api_bp.route("/fleet/preview-distribution", methods=["POST"])
def preview_distribution() -> tuple[Response, int]:
    """Generate sample data for distribution histogram preview.

    Expects a JSON body with ``type``, ``params``, and an optional ``n_samples``
    from 1 to MAX_FLEET_HOMES (default 100).

    Returns:
        JSON with ``samples`` array, HTTP 200 on success; or the ``error``,
        HTTP 400, when sample_distribution refuses the type, params or n_samples.
    """
    data = request_json_object()
    dist_type = data.get("type", "normal")
    params = data.get("params", {})
    n_samples = data.get("n_samples", 100)

    from solar_challenge.web.fleet_config import sample_distribution  # noqa: PLC0415

    try:
        samples = sample_distribution(dist_type, params, n_samples)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"samples": samples}), 200

@api_bp.route("/simulate/fleet-from-distribution", methods=["POST"])
def simulate_fleet_from_distribution() -> tuple[Response, int]:
    """Submit a fleet simulation using distribution configuration.

    Expects the JSON body the fleet page posts, a fleet form, read by
    :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`.

    Returns:
        JSON with ``job_id`` and ``run_id``, HTTP 201 on success; or the ``error``,
        HTTP 400, for a form parse_fleet_form refuses.
    """
    data = request_json_object()

    job_manager = get_job_manager()

    try:
        fleet = parse_fleet_form(data)
    except (ValueError, TypeError, ConfigurationError) as exc:
        return jsonify({"error": str(exc)}), 400

    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]

    job_id, run_id = job_manager.submit_fleet_job(
        configs=list(fleet.homes),
        start_date=fleet.start_date,
        end_date=fleet.end_date,
        db_path=db_path,
        data_dir=data_dir,
        name=fleet.name,
    )

    return jsonify({"job_id": job_id, "run_id": run_id}), 201

@api_bp.route("/fleet/export-yaml", methods=["POST"])
def export_fleet_yaml() -> Response | tuple[Response, int]:
    """Export the fleet page's form as the fleet scenario load_fleet_config reads back.

    Expects the JSON body the fleet page posts to /api/simulate/fleet-from-distribution.

    Returns:
        The scenario's YAML file as a download, HTTP 200; or the ``error``, HTTP 400, for a
        form the simulate endpoint refuses, with its message: both read the form with
        :func:`~solar_challenge.web.fleet_scenario.parse_fleet_form`.
    """
    data = request_json_object()
    try:
        document = scenario_from_fleet_form(data)
    except (ValueError, TypeError, ConfigurationError) as exc:
        return jsonify({"error": str(exc)}), 400
    return Response(
        scenario_yaml(document),
        mimetype="text/yaml",
        headers={"Content-Disposition": "attachment; filename=fleet-config.yaml"},
    )


@api_bp.route("/fleet/import-yaml", methods=["POST"])
def import_fleet_yaml() -> tuple[Response, int]:
    """Import a fleet scenario's YAML as the fleet page's form.

    Accepts the raw YAML text as the request body (Content-Type: text/yaml).

    Returns:
        The answer of :func:`_imported_fleet_form_answer`; or the ``error``, HTTP 400,
        for an empty body.
    """
    yaml_text = request.get_data(as_text=True)
    if not yaml_text:
        return jsonify({"error": "Empty request body"}), 400
    return _imported_fleet_form_answer(yaml_text)


@api_bp.route("/fleet/presets/<name>", methods=["GET"])
def fleet_preset(name: str) -> tuple[Response, int]:
    """Load the built-in scenario file *name* as the fleet page's form.

    Returns:
        The answer of :func:`_imported_fleet_form_answer` for the file's YAML; or the
        ``error``, HTTP 404, when no built-in scenario file is named *name*.
    """
    path = _builtin_scenario_path(name)
    if path is None:
        return jsonify({"error": f"Preset '{name}' not found"}), 404
    return _imported_fleet_form_answer(path.read_text(encoding="utf-8"))


def _imported_fleet_form_answer(yaml_text: str) -> tuple[Response, int]:
    """The fleet page's answer for the fleet scenario *yaml_text* holds.

    Returns:
        JSON ``{"form", "not_loaded"}``, HTTP 200: the form is the body the fleet page
        posts, and not_loaded the paths of the scenario's settings it has no control for
        (see :func:`~solar_challenge.web.fleet_scenario.fleet_form_from_scenario`).  Or the
        ``error``, HTTP 400, for YAML that does not parse, or a scenario the fleet page
        cannot load.
    """
    try:
        document = _yaml.safe_load(yaml_text)
    except _yaml.YAMLError as exc:
        return jsonify({"error": f"Invalid YAML: {exc}"}), 400
    try:
        imported = fleet_form_from_scenario(document)
    except (ValueError, TypeError, ConfigurationError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"form": dict(imported.form), "not_loaded": list(imported.not_loaded)}), 200

# ---------------------------------------------------------------------------
# Parameter sweep endpoint
# ---------------------------------------------------------------------------


_SWEEP_PARAMETER_HOME_KEYS: Mapping[str, str] = {
    "pv_capacity_kw": "pv_kw",
    "battery_capacity_kwh": "battery_kwh",
    "annual_consumption_kwh": "consumption_kwh",
}

#: The days each point of a sweep runs when its base_config sends no window of its own.
_SWEEP_DEFAULT_DAYS = 7


@api_bp.route("/simulate/sweep", methods=["POST"])
def simulate_sweep() -> tuple[Response, int]:
    """Submit a parameter sweep for background execution.

    Generates a set of sweep points (linear or geometric) and submits one
    background home-simulation job per point.  Returns the sweep id, the
    rounded sweep values and the ids of the submitted jobs.

    Expects a JSON object whose fields are all optional, so ``{}`` runs the default sweep:
      - parameter: str, a key of _SWEEP_PARAMETER_HOME_KEYS (default "pv_capacity_kw")
      - min: float
      - max: float
      - steps: int (>= 2)
      - mode: "linear" | "geometric"
      - base_config: JSON object (optional, default {}), the home config
        every sweep point starts from.  A window it sends is read as
        parse_home_config reads a home's; one that sends none, as
        with_default_days reads a body, runs _SWEEP_DEFAULT_DAYS days.

    Returns:
        JSON with sweep_id, parameter, values and job_ids, HTTP 201.
        HTTP 400 for an unsupported parameter (the error lists the supported
        ones), an invalid range, a base_config that is not a JSON object (the
        error names the type sent), or a point whose home config is invalid,
        a window parse_home_config refuses included.
        Every 400 comes before any job is submitted.
    """
    import uuid as _uuid  # noqa: PLC0415

    data = request_json_object()
    parameter = str(data.get("parameter", "pv_capacity_kw"))
    home_config_key = _SWEEP_PARAMETER_HOME_KEYS.get(parameter)
    if home_config_key is None:
        supported = ", ".join(_SWEEP_PARAMETER_HOME_KEYS)
        return jsonify({
            "error": f"Unsupported sweep parameter {parameter!r}; supported parameters: {supported}",
        }), 400
    try:
        min_val = float(data.get("min", 1.0))
        max_val = float(data.get("max", 10.0))
        steps = int(data.get("steps", 5))
    except (ValueError, TypeError) as exc:
        return jsonify({"error": f"Invalid numeric parameter: {exc}"}), 400
    if steps < 2:
        return jsonify({"error": "Steps must be at least 2"}), 400
    if min_val >= max_val:
        return jsonify({"error": "Min must be less than max"}), 400
    mode = str(data.get("mode", "linear"))
    base_config = require_json_object(data.get("base_config", {}), "base_config")

    # Generate sweep points
    if mode == "geometric":
        import math  # noqa: PLC0415

        if min_val <= 0:
            return jsonify({"error": "Min must be positive for geometric sweep"}), 400
        log_min = math.log(min_val)
        log_max = math.log(max_val)
        values = [math.exp(log_min + (log_max - log_min) * i / (steps - 1)) for i in range(steps)]
    else:
        values = [min_val + (max_val - min_val) * i / (steps - 1) for i in range(steps)]

    rounded_values = [round(v, 3) for v in values]

    # Build every point's home before any job is submitted
    point_base_config = with_default_days(base_config, _SWEEP_DEFAULT_DAYS)
    point_homes: list[tuple[float, HomeConfig, pd.Timestamp, pd.Timestamp]] = []
    for val in rounded_values:
        point_config = {**point_base_config, home_config_key: val}
        try:
            home_config, start_date, end_date, _ = parse_home_config(point_config)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": f"Invalid config for {parameter}={val}: {exc}"}), 400
        point_homes.append((val, home_config, start_date, end_date))

    # Submit one home job per sweep point
    sweep_id = str(_uuid.uuid4())
    job_manager = get_job_manager()
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]

    job_ids: list[str] = []
    for val, home_config, start_date, end_date in point_homes:
        job_id, _ = job_manager.submit_home_job(
            config=home_config,
            start_date=start_date,
            end_date=end_date,
            db_path=db_path,
            data_dir=data_dir,
            name=f"Sweep {parameter}={val}",
        )
        job_ids.append(job_id)

    return jsonify({
        "sweep_id": sweep_id,
        "parameter": parameter,
        "values": rounded_values,
        "job_ids": job_ids,
    }), 201


# ---------------------------------------------------------------------------
# History API endpoints (consolidated from history.py)
# ---------------------------------------------------------------------------


@api_bp.route("/history/runs")
def history_list_runs() -> Response:
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


@api_bp.route("/history/runs/<run_id>")
def history_get_run(run_id: str) -> Response | tuple[Response, int]:
    """Get full run detail including summary and config.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with full run detail, or 404 if not found.
    """
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    run_dict = asdict(run)
    if run.config_json:
        run_dict["config"] = run.decoded_config()
    if run.summary_json:
        run_dict["summary"] = run.decoded_summary()

    return jsonify(run_dict)


@api_bp.route("/history/runs/<run_id>", methods=["DELETE"])
def history_delete_run(run_id: str) -> Response | tuple[Response, int]:
    """Delete a run and its associated files.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON success response, or 404 if not found.
    """
    storage = get_storage()
    if storage.run_record(run_id) is None:
        return jsonify({"error": "Run not found"}), 404

    storage.delete_run(run_id)
    return jsonify({"success": True, "message": f"Run {run_id} deleted"})


@api_bp.route("/history/runs/<run_id>", methods=["PATCH"])
def history_patch_run(run_id: str) -> Response | tuple[Response, int]:
    """Update a run's name and/or notes.

    Expects a JSON body with optional ``name`` and ``notes`` fields.

    Args:
        run_id: Unique run identifier.

    Returns:
        JSON response with updated run data, or 404 if not found.
    """
    data = request_json_object()
    storage = get_storage()

    if storage.run_record(run_id) is None:
        return jsonify({"error": "Run not found"}), 404

    labels = {label: data[label] for label in RUN_LABELS if label in data}
    if not labels:
        return jsonify({"error": "No fields to update"}), 400

    updated = storage.update_run_labels(run_id, labels)
    if updated is None:
        return jsonify({"error": "Run not found"}), 404

    return jsonify(asdict(updated))


@api_bp.route("/history/runs/<run_id>/export/csv")
def history_export_csv(run_id: str) -> Response | tuple[Response, int]:
    """Export run results as CSV download.

    Args:
        run_id: Unique run identifier.

    Returns:
        CSV file response, or 404 if not found.
    """
    storage = get_storage()
    run = storage.run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    run_name = run.name or "run"

    try:
        if run.type == "home":
            _config, results, _summary = storage.load_home_run(run_id)
            df = results.to_dataframe()
        else:
            # For fleet runs, export the aggregate (sum across all homes)
            fleet_results, _fleet_summary, _per_home = storage.load_fleet_run(run_id)
            df = fleet_results.to_aggregate_dataframe()
    except FileNotFoundError:
        return jsonify({"error": "Run data files not found"}), 404

    csv_data = df.to_csv()
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.csv"

    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.route("/history/runs/<run_id>/export/yaml")
def history_export_yaml(run_id: str) -> Response | tuple[Response, int]:
    """Export a run's config as the scenario YAML that `home run` or load_fleet_config reads back.

    Args:
        run_id: Unique run identifier.

    Returns:
        YAML file response; 404 if the run or its config is missing, 500 if the
        stored config does not decode, 422 if the scenario grammar cannot express it.
    """
    run = get_storage().run_record(run_id)

    if run is None:
        return jsonify({"error": "Run not found"}), 404

    if not run.config_json:
        return jsonify({"error": "No config data available"}), 404

    try:
        config = json.loads(run.config_json)
    except (json.JSONDecodeError, TypeError):
        return jsonify({"error": "Invalid config data"}), 500

    is_fleet = run.type == "fleet"
    try:
        homes = stored_fleet_home_configs(config) if is_fleet else [stored_home_config(config)]
    except (TypeError, ValueError, KeyError, AttributeError, ConfigurationError) as exc:
        return jsonify({"error": f"Invalid config data: {exc}"}), 500

    run_name = run.name or "run"
    try:
        document = (
            fleet_scenario(homes, name=run_name)
            if is_fleet
            else home_scenario(homes[0], name=run_name)
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 422

    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.yaml"

    return Response(
        scenario_yaml(document),
        mimetype="text/yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Scenarios API endpoints (consolidated from scenarios.py)
# ---------------------------------------------------------------------------


def _scenarios_dir() -> Path:
    """Return the path to the project-level scenarios/ directory.

    Returns:
        Path to the scenarios directory (may not exist).
    """
    return Path(__file__).resolve().parents[3] / "scenarios"


def _builtin_scenario_path(name: str) -> Path | None:
    """The built-in scenario file *name*, its .yaml file before its .yml one; None when there is neither."""
    for suffix in (".yaml", ".yml"):
        path = _scenarios_dir() / f"{name}{suffix}"
        if path.is_file():
            return path
    return None


@api_bp.route("/scenarios/preview-yaml", methods=["POST"])
def scenarios_preview_yaml() -> tuple[Response, int]:
    """The YAML text of the fleet scenario a builder form describes.

    Expects a JSON body with the scenario builder's form fields.

    Returns:
        JSON with the ``yaml`` text, HTTP 200; or the ``error``, HTTP 400, for a
        form the builder does not send.
    """
    data = request_json_object()
    try:
        document = scenario_from_builder_form(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"yaml": scenario_yaml(document)}), 200


@api_bp.route("/scenarios/validate", methods=["POST"])
def scenarios_validate_scenario() -> tuple[Response, int]:
    """Validate a builder form against the dashboard's limits and the scenario readers.

    Expects a JSON body with the scenario builder's form fields.

    Returns:
        JSON with ``valid`` and the ``errors`` list, empty for a valid form, HTTP 200.
    """
    data = request_json_object()
    errors = builder_form_errors(data)
    return jsonify({"valid": not errors, "errors": errors}), 200


@api_bp.route("/scenarios/save", methods=["POST"])
def scenarios_save_scenario() -> tuple[Response, int]:
    """Save a scenario configuration as a fleet preset.

    Expects a JSON body with at least ``name`` and ``config`` fields.

    Returns:
        JSON confirmation with preset name and id, HTTP 201 on success; or the ``error``:
        HTTP 400 for an empty name, HTTP 409 for a name a saved home preset holds.
    """
    data = request_json_object()
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Scenario name is required"}), 400
    config_payload = data.get("config", {})
    if not config_payload:
        # Accept flat form data as config
        config_payload = {k: v for k, v in data.items() if k not in ("name", "type")}
    return _answer_preset_save(name, "fleet", config_payload)


@api_bp.route("/scenarios/presets", methods=["GET"])
def scenarios_list_presets() -> tuple[Response, int]:
    """List built-in (from scenarios/ dir) and saved scenario presets.

    Returns:
        JSON with ``presets`` array containing built-in and saved items.
    """
    presets: list[dict[str, Any]] = []

    # Built-in presets from scenarios/ directory
    scenarios_dir = _scenarios_dir()
    if scenarios_dir.is_dir():
        for path in sorted(scenarios_dir.iterdir()):
            if path.suffix in (".yaml", ".yml") and path.is_file():
                presets.append({
                    "name": path.stem,
                    "source": "builtin",
                    "filename": path.name,
                })

    # Saved presets from database
    db_path = current_app.config["DATABASE"]
    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE type = 'fleet' ORDER BY name"
            )
            for row in cursor.fetchall():
                presets.append({
                    "name": row["name"],
                    "source": "saved",
                    "created_at": row["created_at"],
                })
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load saved scenario presets", exc_info=True)

    return jsonify({"presets": presets}), 200


@api_bp.route("/scenarios/presets/<name>", methods=["GET"])
def scenarios_get_preset(name: str) -> tuple[Response, int]:
    """Load a specific preset by name (from file or DB).

    Checks the scenarios/ directory first for built-in YAML files,
    then falls back to saved presets in the database.

    Args:
        name: The preset name to look up.

    Returns:
        JSON preset object, or 404 if not found.
    """
    # Try built-in scenarios directory
    path = _builtin_scenario_path(name)
    if path is not None:
        try:
            content = _yaml.safe_load(path.read_text())
            return jsonify({
                "name": name,
                "source": "builtin",
                "config": content,
            }), 200
        except Exception as exc:  # noqa: BLE001
            return jsonify({"error": f"Failed to parse {path.name}: {exc}"}), 500
    # Try database
    db_path = current_app.config["DATABASE"]
    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()

        if row:
            cfg = json.loads(row["config_json"]) if row["config_json"] else {}
            return jsonify({
                "name": row["name"],
                "source": "saved",
                "config": cfg,
                "created_at": row["created_at"],
            }), 200
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load preset '%s' from database", name, exc_info=True)

    return jsonify({"error": f"Preset '{name}' not found"}), 404