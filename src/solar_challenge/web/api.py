# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint providing JSON API endpoints for background simulations.

Provides REST endpoints for submitting simulation jobs, polling status,
streaming progress via SSE, retrieving results, and consolidated history
and scenarios API endpoints under the /api/ prefix.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any, Generator

import yaml as _yaml
import pandas as pd
from flask import Blueprint, Response, current_app, jsonify, request, stream_with_context

from solar_challenge.battery import BatteryConfig
from solar_challenge.config import (
    ConfigurationError,
    _parse_dispatch_strategy_config,
    _parse_tariff_config,
)
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.database import get_db
from solar_challenge.web.shared import get_storage, resolve_location

logger = logging.getLogger(__name__)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def _get_job_manager() -> Any:
    """Get the JobManager instance from the Flask app extensions.

    Returns:
        JobManager instance.

    Aborts:
        503: If JobManager is not initialized.
    """
    from flask import abort  # noqa: PLC0415

    jm = current_app.extensions.get("job_manager")
    if jm is None:
        abort(503, description="Simulation service is not available")
    return jm


def _parse_date_range(data: dict[str, Any]) -> tuple[str, str]:
    """Extract a (start, end) date-string pair from a JSON request body.

    Three resolution modes (checked in order):

    1. ``days == 365``  → **sentinel for a full calendar year**: returns the
       complete 2024 calendar year ``("2024-01-01", "2024-12-31")``.  Because
       2024 is a leap year this window spans 366 days; ``365`` is intentionally
       a *named sentinel* (not a literal day count) so callers can request a
       full-year run without specifying explicit dates.
    2. ``days`` key present (any *positive* integer ≠ 365) → *days*-day window
       anchored at 2024-06-01.  ``days <= 0`` raises ``ValueError``.
    3. Otherwise → use ``start`` / ``end`` keys with defaults
       ``"2024-01-01"`` / ``"2024-12-31"``.

    Args:
        data: Parsed JSON body from the request.

    Returns:
        Tuple of ``(start, end)`` as ``"YYYY-MM-DD"`` strings.

    Raises:
        ValueError: If ``days`` is present but not a positive integer.
    """
    days_raw = data.get("days")
    start_raw = data.get("start", "")
    end_raw = data.get("end", "")

    if days_raw is not None:
        days = int(days_raw)
        if days <= 0:
            raise ValueError(f"days must be a positive integer, got {days}")
        if days == 365:
            return "2024-01-01", "2024-12-31"
        ref = pd.Timestamp("2024-06-01")
        start = ref.strftime("%Y-%m-%d")
        end = (ref + pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")
        return start, end

    start = str(start_raw) if start_raw else "2024-01-01"
    end = str(end_raw) if end_raw else "2024-12-31"
    return start, end


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
    system_age_years = float(data.get("system_age_years", 0.0))
    degradation_rate_per_year = float(data.get("degradation_rate_per_year", 0.005))
    battery_kwh_val = float(data.get("battery_kwh", 0.0))
    max_charge_kw_raw = data.get("max_charge_kw")
    max_discharge_kw_raw = data.get("max_discharge_kw")
    efficiency_pct_raw = data.get("efficiency_pct")
    consumption_kwh_raw = data.get("consumption_kwh")
    occupants = int(data.get("occupants", 3))
    stochastic = bool(data.get("stochastic", False))
    location_preset = str(data.get("location", "bristol"))
    name = data.get("name")

    # Parse date range using shared helper
    start, end = _parse_date_range(data)

    # Validate inputs
    if not (0.5 <= pv_kw <= 20.0):
        raise ValueError(f"PV capacity must be 0.5-20 kW, got {pv_kw}")
    if battery_kwh_val < 0:
        raise ValueError(f"Battery capacity cannot be negative, got {battery_kwh_val}")

    # Resolve location
    loc = resolve_location(location_preset)

    # Build component configs
    pv_config = PVConfig(
        capacity_kw=pv_kw,
        azimuth=azimuth,
        tilt=tilt,
        system_age_years=system_age_years,
        degradation_rate_per_year=degradation_rate_per_year,
    )

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
        try:
            dispatch_data = data.get("dispatch_strategy")
            if dispatch_data:
                battery_kwargs["dispatch_strategy"] = _parse_dispatch_strategy_config(dispatch_data)
        except ConfigurationError as exc:
            raise ValueError(str(exc)) from exc
        battery_config = BatteryConfig(**battery_kwargs)

    annual_consumption: float | None = None
    if consumption_kwh_raw is not None:
        annual_consumption = float(consumption_kwh_raw)

    load_config = LoadConfig(
        annual_consumption_kwh=annual_consumption,
        household_occupants=occupants,
        use_stochastic=stochastic,
    )

    # Build optional heat pump config.
    #
    # Note on key naming: the web JSON contract uses "type" (a shorter, idiomatic
    # form-field name) whereas the YAML/config.py contract uses "heat_pump_type".
    # The mapping is intentional and happens here on the single `hp_data.get("type")`
    # call.  This is the only place that translation is needed.
    #
    # Note on implementation pattern: tariff and dispatch configs are built via
    # shared config._parse_tariff_config / _parse_dispatch_strategy_config helpers
    # because those helpers exist in config.py.  No equivalent
    # config._parse_heat_pump_config helper exists, and config.py is outside this
    # task's scope (consume-only).  HeatPumpConfig.__post_init__ already raises
    # ValueError on invalid inputs, which the endpoint's (ValueError, TypeError)
    # handler converts to HTTP 400 — no extra wrapping is needed here.
    heat_pump_config: HeatPumpConfig | None = None
    hp_data = data.get("heat_pump")
    if hp_data:
        heat_pump_config = HeatPumpConfig(
            heat_pump_type=hp_data.get("type", "ASHP"),
            thermal_capacity_kw=float(hp_data.get("thermal_capacity_kw", 8.0)),
            annual_heat_demand_kwh=float(hp_data.get("annual_heat_demand_kwh", 8000.0)),
        )

    # Build optional tariff config
    try:
        tariff_config = _parse_tariff_config(data.get("tariff"))
    except ConfigurationError as exc:
        raise ValueError(str(exc)) from exc

    home_config = HomeConfig(
        pv_config=pv_config,
        load_config=load_config,
        battery_config=battery_config,
        heat_pump_config=heat_pump_config,
        tariff_config=tariff_config,
        location=loc,
        name=name or "Web Simulation",
    )

    start_date = pd.Timestamp(start, tz=loc.timezone)
    end_date = pd.Timestamp(end, tz=loc.timezone)

    return home_config, start_date, end_date, name


@api_bp.route("/simulate/home", methods=["POST"])
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

@api_bp.route("/simulate/fleet", methods=["POST"])
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

@api_bp.route("/jobs/<job_id>", methods=["GET"])
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

@api_bp.route("/jobs/<job_id>/progress", methods=["GET"])
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


@api_bp.route("/jobs/<job_id>/results", methods=["GET"])
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

@api_bp.route("/presets", methods=["GET"])
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

@api_bp.route("/presets", methods=["POST"])
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
                "SELECT id FROM config_presets WHERE name = ? AND type = ?",
                (name, preset_type),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE config_presets SET config_json = ?, created_at = ? WHERE id = ?",
                    (json.dumps(config_payload), now, existing["id"]),
                )
                preset_id = existing["id"]
            else:
                cursor.execute(
                    "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (preset_id, name, preset_type, json.dumps(config_payload), now),
                )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201

@api_bp.route("/presets/<name>", methods=["GET"])
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


@api_bp.route("/fleet/preview-distribution", methods=["POST"])
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

@api_bp.route("/simulate/fleet-from-distribution", methods=["POST"])
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

    # Validate service availability first — avoids wasted sampling on 503 path.
    job_manager = _get_job_manager()

    from solar_challenge.web.fleet_config import form_to_fleet_distribution_config  # noqa: PLC0415
    from solar_challenge.config import (  # noqa: PLC0415
        _parse_fleet_distribution_config,
        generate_homes_from_distribution,
    )

    try:
        cfg_dict = form_to_fleet_distribution_config(data)
        fleet_cfg = _parse_fleet_distribution_config(cfg_dict)
        loc = resolve_location(data.get("location", "bristol"))
        configs = generate_homes_from_distribution(fleet_cfg, loc)
        start_s, end_s = _parse_date_range(data)
        start_date = pd.Timestamp(start_s, tz=loc.timezone)
        end_date = pd.Timestamp(end_s, tz=loc.timezone)
    except (ValueError, TypeError, ConfigurationError) as exc:
        return jsonify({"error": str(exc)}), 400

    fleet_name = data.get("name", "Fleet Distribution Simulation")
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

@api_bp.route("/fleet/export-yaml", methods=["POST"])
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


@api_bp.route("/fleet/import-yaml", methods=["POST"])
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


@api_bp.route("/simulate/sweep", methods=["POST"])
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


@api_bp.route("/history/runs/<run_id>", methods=["DELETE"])
def history_delete_run(run_id: str) -> Response | tuple[Response, int]:
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

    storage = get_storage()
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


@api_bp.route("/history/runs/<run_id>/export/csv")
def history_export_csv(run_id: str) -> Response | tuple[Response, int]:
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

    storage = get_storage()
    run_type = row["type"]
    run_name = row["name"] or "run"

    try:
        if run_type == "home":
            _config, results, _summary = storage.load_home_run(run_id)
            df = results.to_dataframe()
        else:
            # For fleet runs, export the aggregate (sum across all homes)
            fleet_results, _fleet_summary, _per_home = storage.load_fleet_run(run_id)
            if fleet_results.per_home_results:
                df = fleet_results.to_aggregate_dataframe()
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api_bp.route("/history/runs/<run_id>/export/yaml")
def history_export_yaml(run_id: str) -> Response | tuple[Response, int]:
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
    yaml_data = _yaml.dump(config_dict, default_flow_style=False, sort_keys=False)

    run_name = row["name"] or "run"
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in run_name)
    filename = f"{safe_name}_{run_id[:8]}.yaml"

    return Response(
        yaml_data,
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


def _form_to_yaml_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Convert form/JSON data into a scenario YAML-compatible dict.

    Args:
        data: Parsed request data from the builder form.

    Returns:
        Dictionary suitable for YAML serialisation.
    """
    from solar_challenge.web.shared import location_presets_as_dicts  # noqa: PLC0415

    result: dict[str, Any] = {}

    # General section
    if data.get("name"):
        result["name"] = str(data["name"])
    if data.get("description"):
        result["description"] = str(data["description"])

    # Location section
    location: dict[str, Any] = {}
    loc_preset = data.get("location_preset", "")
    if loc_preset == "custom":
        location["latitude"] = float(data.get("latitude", 51.45))
        location["longitude"] = float(data.get("longitude", -2.58))
        if data.get("altitude"):
            location["altitude"] = float(data["altitude"])
    elif loc_preset:
        presets = location_presets_as_dicts()
        location = dict(presets.get(loc_preset, presets["bristol"]))
    location["timezone"] = "Europe/London"
    if location:
        result["location"] = location

    # Period section
    if data.get("start_date"):
        result["start_date"] = str(data["start_date"])
    if data.get("end_date"):
        result["end_date"] = str(data["end_date"])

    # Fleet distribution section
    fleet: dict[str, Any] = {}
    if data.get("n_homes"):
        fleet["n_homes"] = int(data["n_homes"])

    # PV distribution
    pv: dict[str, Any] = {}
    if data.get("pv_capacity_kw"):
        pv["capacity_kw"] = float(data["pv_capacity_kw"])
    elif data.get("pv_distribution_type"):
        pv["capacity_kw"] = {
            "type": data["pv_distribution_type"],
        }
        if data.get("pv_mean"):
            pv["capacity_kw"]["mean"] = float(data["pv_mean"])
        if data.get("pv_std"):
            pv["capacity_kw"]["std"] = float(data["pv_std"])
        if data.get("pv_min"):
            pv["capacity_kw"]["min"] = float(data["pv_min"])
        if data.get("pv_max"):
            pv["capacity_kw"]["max"] = float(data["pv_max"])
    if pv:
        fleet["pv"] = pv

    # Battery distribution
    battery: dict[str, Any] = {}
    if data.get("battery_capacity_kwh"):
        battery["capacity_kwh"] = float(data["battery_capacity_kwh"])
    elif data.get("battery_distribution_type"):
        battery["capacity_kwh"] = {
            "type": data["battery_distribution_type"],
        }
        if data.get("battery_mean"):
            battery["capacity_kwh"]["mean"] = float(data["battery_mean"])
        if data.get("battery_std"):
            battery["capacity_kwh"]["std"] = float(data["battery_std"])
        if data.get("battery_min"):
            battery["capacity_kwh"]["min"] = float(data["battery_min"])
        if data.get("battery_max"):
            battery["capacity_kwh"]["max"] = float(data["battery_max"])
    if battery:
        fleet["battery"] = battery

    # Load distribution
    load: dict[str, Any] = {}
    if data.get("annual_consumption_kwh"):
        load["annual_consumption_kwh"] = float(data["annual_consumption_kwh"])
    elif data.get("load_distribution_type"):
        load["annual_consumption_kwh"] = {
            "type": data["load_distribution_type"],
        }
        if data.get("load_mean"):
            load["annual_consumption_kwh"]["mean"] = float(data["load_mean"])
        if data.get("load_std"):
            load["annual_consumption_kwh"]["std"] = float(data["load_std"])
        if data.get("load_min"):
            load["annual_consumption_kwh"]["min"] = float(data["load_min"])
        if data.get("load_max"):
            load["annual_consumption_kwh"]["max"] = float(data["load_max"])
    if load:
        fleet["load"] = load

    if fleet:
        result["fleet_distribution"] = fleet

    # Tariff section
    tariff: dict[str, Any] = {}
    if data.get("import_rate"):
        tariff["import_rate"] = float(data["import_rate"])
    if data.get("export_rate"):
        tariff["export_rate"] = float(data["export_rate"])
    if tariff:
        result["tariff"] = tariff

    return result


@api_bp.route("/scenarios/preview-yaml", methods=["POST"])
def scenarios_preview_yaml() -> tuple[Response, int]:
    """Convert form data to a YAML string preview.

    Expects a JSON body with scenario builder form fields.

    Returns:
        JSON with ``yaml`` string, HTTP 200 on success.
    """
    data = request.get_json(silent=True) or {}
    scenario_dict = _form_to_yaml_dict(data)
    yaml_str = _yaml.dump(scenario_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return jsonify({"yaml": yaml_str}), 200


@api_bp.route("/scenarios/validate", methods=["POST"])
def scenarios_validate_scenario() -> tuple[Response, int]:
    """Validate scenario data against basic rules.

    Expects a JSON body with scenario fields. Performs lightweight
    validation (not a full ScenarioConfig parse since the form data
    may be incomplete).

    Returns:
        JSON with ``valid`` boolean and optional ``errors`` list, HTTP 200.
    """
    data = request.get_json(silent=True) or {}
    errors: list[str] = []

    if not data.get("name"):
        errors.append("Scenario name is required.")

    n_homes = data.get("n_homes")
    if n_homes is not None:
        try:
            n = int(n_homes)
            if n < 1 or n > 10000:
                errors.append("Number of homes must be between 1 and 10,000.")
        except (ValueError, TypeError):
            errors.append("Number of homes must be an integer.")

    pv_kw = data.get("pv_capacity_kw")
    if pv_kw is not None:
        try:
            kw = float(pv_kw)
            if kw < 0.5 or kw > 20.0:
                errors.append("PV capacity must be between 0.5 and 20 kW.")
        except (ValueError, TypeError):
            errors.append("PV capacity must be a number.")

    if errors:
        return jsonify({"valid": False, "errors": errors}), 200
    return jsonify({"valid": True, "errors": []}), 200


@api_bp.route("/scenarios/save", methods=["POST"])
def scenarios_save_scenario() -> tuple[Response, int]:
    """Save a scenario configuration to the config_presets table.

    Expects a JSON body with at least ``name`` and ``config`` fields.

    Returns:
        JSON confirmation with preset name and id, HTTP 201 on success.
    """
    import uuid  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "Request body must be JSON"}), 400
    name = str(data.get("name", "")).strip()
    if not name:
        return jsonify({"error": "Scenario name is required"}), 400
    config_payload = data.get("config", {})
    if not config_payload:
        # Accept flat form data as config
        config_payload = {k: v for k, v in data.items() if k not in ("name", "type")}

    db_path = current_app.config["DATABASE"]
    preset_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id FROM config_presets WHERE name = ? AND type = ?",
                (name, "fleet"),
            )
            existing = cursor.fetchone()
            if existing:
                cursor.execute(
                    "UPDATE config_presets SET config_json = ?, created_at = ? WHERE id = ?",
                    (json.dumps(config_payload), now, existing["id"]),
                )
                preset_id = existing["id"]
            else:
                cursor.execute(
                    "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
                    (preset_id, name, "fleet", json.dumps(config_payload), now),
                )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201


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
    scenarios_dir = _scenarios_dir()
    for suffix in (".yaml", ".yml"):
        path = scenarios_dir / f"{name}{suffix}"
        if path.is_file():
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