"""Flask Blueprint providing JSON API endpoints for background simulations.

Provides REST endpoints for submitting simulation jobs, polling status,
streaming progress via SSE, and retrieving results.
"""

import json
import logging
import time
from typing import Any, Generator

logger = logging.getLogger(__name__)

import pandas as pd
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.shared import resolve_location

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_job_manager() -> Any:
    """Get the JobManager instance from the Flask app extensions.

    Returns:
        JobManager instance.

    Raises:
        RuntimeError: If JobManager is not initialized.
    """
    jm = current_app.extensions.get("job_manager")
    if jm is None:
        raise RuntimeError("JobManager not initialized")
    return jm


def _parse_home_config(data: dict[str, Any]) -> tuple[HomeConfig, pd.Timestamp, pd.Timestamp, str | None]:
    """Parse JSON request body into HomeConfig and date range.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of (HomeConfig, start_date, end_date, name).

    Raises:
        ValueError: If required fields are missing or invalid.
    """
    pv_kw = float(data.get("pv_kw", 4.0))
    azimuth = float(data.get("azimuth", 180))
    tilt = float(data.get("tilt", 35))
    battery_kwh_val = float(data.get("battery_kwh", 0.0))
    max_charge_kw_raw = data.get("max_charge_kw")
    max_discharge_kw_raw = data.get("max_discharge_kw")
    efficiency_pct_raw = data.get("efficiency_pct")
    consumption_kwh_raw = data.get("consumption_kwh")
    occupants = int(data.get("occupants", 3))
    stochastic = bool(data.get("stochastic", False))
    location_preset = str(data.get("location", "bristol"))
    name = data.get("name")

    # Parse date range
    days_raw = data.get("days")
    start_raw = data.get("start", "")
    end_raw = data.get("end", "")

    if days_raw is not None:
        days = int(days_raw)
        if days == 365:
            start = "2024-01-01"
            end = "2024-12-31"
        else:
            ref = pd.Timestamp("2024-06-01")
            start = ref.strftime("%Y-%m-%d")
            end = (ref + pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")
    else:
        start = str(start_raw) if start_raw else "2024-01-01"
        end = str(end_raw) if end_raw else "2024-12-31"

    # Validate inputs
    if not (0.5 <= pv_kw <= 20.0):
        raise ValueError(f"PV capacity must be 0.5-20 kW, got {pv_kw}")
    if battery_kwh_val < 0:
        raise ValueError(f"Battery capacity cannot be negative, got {battery_kwh_val}")

    # Resolve location
    loc = resolve_location(location_preset)

    # Build component configs
    pv_config = PVConfig(capacity_kw=pv_kw, azimuth=azimuth, tilt=tilt)

    battery_config: BatteryConfig | None = None
    if battery_kwh_val > 0:
        battery_kwargs: dict[str, Any] = {"capacity_kwh": battery_kwh_val}
        if max_charge_kw_raw is not None:
            battery_kwargs["max_charge_kw"] = float(max_charge_kw_raw)
        if max_discharge_kw_raw is not None:
            battery_kwargs["max_discharge_kw"] = float(max_discharge_kw_raw)
        if efficiency_pct_raw is not None:
            eff = float(efficiency_pct_raw)
            if not (0 < eff <= 100):
                raise ValueError(f"Efficiency must be between 0 and 100, got {eff}")
            battery_kwargs["efficiency_pct"] = eff
        battery_config = BatteryConfig(**battery_kwargs)

    annual_consumption: float | None = None
    if consumption_kwh_raw is not None:
        annual_consumption = float(consumption_kwh_raw)

    load_config = LoadConfig(
        annual_consumption_kwh=annual_consumption,
        household_occupants=occupants,
        use_stochastic=stochastic,
    )

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        location=loc,
        name=name or "Web Simulation",
    )

    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    return home_config, start_date, end_date, name


@api_bp.route("/simulate/home", methods=["POST"])  # type: ignore[untyped-decorator]
def simulate_home_api() -> tuple[Response, int]:
    """Submit a home simulation job for background execution.

    Expects a JSON body with simulation parameters.

    Returns:
        JSON with job_id and run_id, HTTP 201 on success.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    try:
        home_config, start_date, end_date, name = _parse_home_config(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    job_manager = _get_job_manager()
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

@api_bp.route("/simulate/fleet", methods=["POST"])  # type: ignore[untyped-decorator]
def simulate_fleet_api() -> tuple[Response, int]:
    """Submit a fleet simulation job for background execution.

    Expects a JSON body with a list of home configs under 'homes' key.

    Returns:
        JSON with job_id and run_id, HTTP 201 on success.
    """
    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    homes_data = data.get("homes", [])
    if not homes_data:
        return jsonify({"error": "Fleet requires at least one home config in 'homes' array"}), 400
    try:
        configs = []
        # Use first home's date config for the fleet
        first_config, start_date, end_date, _ = _parse_home_config(homes_data[0])
        configs.append(first_config)

        for home_data in homes_data[1:]:
            config, _, _, _ = _parse_home_config(home_data)
            configs.append(config)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    fleet_name = data.get("name", "Fleet Simulation")

    job_manager = _get_job_manager()
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

@api_bp.route("/jobs/<job_id>", methods=["GET"])  # type: ignore[untyped-decorator]
def get_job_status(job_id: str) -> tuple[Response, int]:
    """Return current job status as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with job status fields, or 404 if not found.
    """
    job_manager = _get_job_manager()
    status = job_manager.get_job_status(job_id)

    if status is None:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(status), 200

@api_bp.route("/jobs/<job_id>/progress", methods=["GET"])  # type: ignore[untyped-decorator]
def get_job_progress(job_id: str) -> Response:
    """SSE endpoint for streaming job progress events.

    Sends heartbeat every 2 seconds and streams progress/completion events.

    Args:
        job_id: Unique job identifier.

    Returns:
        text/event-stream response.
    """
    job_manager = _get_job_manager()

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


@api_bp.route("/jobs/<job_id>/results", methods=["GET"])  # type: ignore[untyped-decorator]
def get_job_results(job_id: str) -> tuple[Response, int]:
    """Return completed job results as JSON.

    Args:
        job_id: Unique job identifier.

    Returns:
        JSON with summary data, or 404/409 on error.
    """
    job_manager = _get_job_manager()
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
    db_path = current_app.config["DATABASE"]

    from solar_challenge.web.database import get_db

    with get_db(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT summary_json, name, type, created_at FROM runs WHERE id = ?", (run_id,))
        row = cursor.fetchone()

    if row is None:
        return jsonify({"error": "Run not found"}), 404
    summary_json = row["summary_json"]
    summary = json.loads(summary_json) if summary_json else {}

    return jsonify({
        "run_id": run_id,
        "name": row["name"],
        "type": row["type"],
        "created_at": row["created_at"],
        "summary": summary,
    }), 200

# ---------------------------------------------------------------------------
# Config preset endpoints
# ---------------------------------------------------------------------------

@api_bp.route("/presets", methods=["GET"])  # type: ignore[untyped-decorator]
def list_presets() -> tuple[Response, int]:
    """List all configuration presets (built-in + saved).

    Returns:
        JSON array of preset objects, HTTP 200.
    """
    from solar_challenge.web.shared import BUILTIN_PRESETS  # noqa: PLC0415

    db_path = current_app.config["DATABASE"]
    saved: list[dict[str, Any]] = []

    try:
        from solar_challenge.web.database import get_db  # noqa: PLC0415

        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE type = 'home' ORDER BY name"
            )
            for row in cursor.fetchall():
                cfg = json.loads(row["config_json"]) if row["config_json"] else {}
                cfg["name"] = row["name"]
                cfg["created_at"] = row["created_at"]
                cfg["source"] = "saved"
                saved.append(cfg)
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load saved presets", exc_info=True)

    # Tag built-in presets
    builtin = [{**p, "source": "builtin"} for p in BUILTIN_PRESETS]

    return jsonify(builtin + saved), 200

@api_bp.route("/presets", methods=["POST"])  # type: ignore[untyped-decorator]
def save_preset() -> tuple[Response, int]:
    """Save a configuration preset to the database.

    Expects a JSON body with at least ``name`` and configuration fields.

    Returns:
        JSON confirmation with the preset name, HTTP 201 on success.
    """
    import uuid as _uuid  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    data = request.get_json(silent=True)
    if data is None:
        return jsonify({"error": "Request body must be JSON"}), 400
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Preset name is required"}), 400
    preset_type = data.get("type", "home")
    config_payload = {
        k: v for k, v in data.items() if k not in ("name", "type")
    }

    db_path = current_app.config["DATABASE"]

    from solar_challenge.web.database import get_db  # noqa: PLC0415

    preset_id = str(_uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (preset_id, name, preset_type, json.dumps(config_payload), now),
            )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201

@api_bp.route("/presets/<name>", methods=["GET"])  # type: ignore[untyped-decorator]
def get_preset(name: str) -> tuple[Response, int]:
    """Get a specific configuration preset by name.

    Checks saved presets first, then falls back to built-in presets.

    Args:
        name: The preset name to look up.

    Returns:
        JSON preset object, or 404 if not found.
    """
    from solar_challenge.web.shared import BUILTIN_PRESETS  # noqa: PLC0415

    db_path = current_app.config["DATABASE"]

    # Try database first
    try:
        from solar_challenge.web.database import get_db  # noqa: PLC0415

        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT name, config_json, created_at FROM config_presets WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()

        if row:
            cfg = json.loads(row["config_json"]) if row["config_json"] else {}
            cfg["name"] = row["name"]
            cfg["created_at"] = row["created_at"]
            cfg["source"] = "saved"
            return jsonify(cfg), 200
    except Exception:  # noqa: BLE001
        logger.warning("Failed to load preset '%s' from database", name, exc_info=True)

    # Fall back to built-in presets
    for preset in BUILTIN_PRESETS:
        if preset["name"] == name:
            result = {**preset, "source": "builtin"}
            return jsonify(result), 200
    return jsonify({"error": f"Preset '{name}' not found"}), 404

# ---------------------------------------------------------------------------
# Fleet distribution endpoints
# ---------------------------------------------------------------------------


@api_bp.route("/fleet/preview-distribution", methods=["POST"])  # type: ignore[untyped-decorator]
def preview_distribution() -> tuple[Response, int]:
    """Generate sample data for distribution histogram preview.

    Expects a JSON body with ``type``, ``params``, and optional ``n_samples``.

    Returns:
        JSON with ``samples`` array, HTTP 200 on success.
    """
    data = request.get_json(silent=True) or {}
    dist_type = data.get("type", "normal")
    params = data.get("params", {})
    n_samples = int(data.get("n_samples", 100))

    from solar_challenge.web.fleet_config import sample_distribution  # noqa: PLC0415

    try:
        samples = sample_distribution(dist_type, params, n_samples)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"samples": samples}), 200

@api_bp.route("/simulate/fleet-from-distribution", methods=["POST"])  # type: ignore[untyped-decorator]
def simulate_fleet_from_distribution() -> tuple[Response, int]:
    """Submit a fleet simulation using distribution configuration.

    Expects a JSON body describing distribution parameters for PV, battery,
    and load components.

    Returns:
        JSON with ``job_id`` and ``run_id``, HTTP 201 on success.
    """
    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    from solar_challenge.web.fleet_config import form_to_fleet_distribution_config  # noqa: PLC0415

    try:
        config = form_to_fleet_distribution_config(data)
    except (ValueError, TypeError) as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({
        "error": "Fleet distribution simulation not yet implemented",
        "n_homes": config.get("n_homes", 0),
    }), 501

@api_bp.route("/fleet/export-yaml", methods=["POST"])  # type: ignore[untyped-decorator]
def export_fleet_yaml() -> Response:
    """Export fleet configuration as YAML.

    Expects a JSON body with fleet distribution parameters.

    Returns:
        YAML file download response.
    """
    data = request.get_json(silent=True) or {}

    from solar_challenge.web.fleet_config import fleet_distribution_to_yaml  # noqa: PLC0415

    yaml_str = fleet_distribution_to_yaml(data)
    return Response(
        yaml_str,
        mimetype="text/yaml",
        headers={"Content-Disposition": "attachment; filename=fleet-config.yaml"},
    )


@api_bp.route("/fleet/import-yaml", methods=["POST"])  # type: ignore[untyped-decorator]
def import_fleet_yaml() -> tuple[Response, int]:
    """Import fleet configuration from YAML.

    Accepts raw YAML text in the request body (Content-Type: text/yaml)
    or a JSON-encoded YAML string.

    Returns:
        JSON with parsed fleet distribution config, HTTP 200 on success.
    """
    from solar_challenge.web.fleet_config import yaml_to_fleet_distribution  # noqa: PLC0415

    # Try to get raw body text
    yaml_str = request.get_data(as_text=True)
    if not yaml_str:
        return jsonify({"error": "Empty request body"}), 400
    try:
        config = yaml_to_fleet_distribution(yaml_str)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(config), 200

# ---------------------------------------------------------------------------
# Parameter sweep endpoint
# ---------------------------------------------------------------------------


@api_bp.route("/simulate/sweep", methods=["POST"])  # type: ignore[untyped-decorator]
def simulate_sweep() -> tuple[Response, int]:
    """Submit a parameter sweep for background execution.

    Generates a set of sweep points (linear or geometric) and returns
    them for tracking.  Full job submission is deferred until the
    JobManager integration is complete.

    Expects a JSON body with:
      - parameter: str (e.g. "pv_capacity_kw")
      - min: float
      - max: float
      - steps: int (>= 2)
      - mode: "linear" | "geometric"
      - base_config: dict (optional base simulation configuration)

    Returns:
        JSON with sweep_id, parameter, values and job_ids, HTTP 201.
    """
    import uuid as _uuid  # noqa: PLC0415

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    parameter = str(data.get("parameter", "pv_capacity_kw"))
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
    base_config = data.get("base_config", {})

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

    # Submit individual home jobs for each sweep point
    sweep_id = str(_uuid.uuid4())
    job_manager = _get_job_manager()
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]

    # Map parameter names to config keys
    param_map = {
        "pv_capacity_kw": "pv_kw",
        "battery_capacity_kwh": "battery_kwh",
        "annual_consumption_kwh": "consumption_kwh",
    }
    config_key = param_map.get(parameter, parameter)

    job_ids: list[str] = []
    rounded_values = [round(v, 3) for v in values]

    for val in rounded_values:
        point_config = dict(base_config)
        point_config[config_key] = val
        # Ensure defaults for required fields
        point_config.setdefault("pv_kw", 4.0)
        point_config.setdefault("battery_kwh", 0)
        point_config.setdefault("occupants", 3)
        point_config.setdefault("location", "bristol")
        point_config.setdefault("days", 7)

        try:
            home_config, start_date, end_date, name = _parse_home_config(point_config)
        except (ValueError, TypeError) as exc:
            return jsonify({"error": f"Invalid config for {parameter}={val}: {exc}"}), 400

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