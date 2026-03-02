"""Flask Blueprint for scenario building and parameter sweep configuration.

Provides page routes for the scenario builder and sweep configuration UI,
as well as API endpoints for YAML preview, validation, saving, and loading
scenario presets.
"""

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, Response, current_app, jsonify, render_template, request

bp = Blueprint("scenarios", __name__)


# ---------------------------------------------------------------------------
# Helper utilities
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
        presets = {
            "bristol": {"latitude": 51.45, "longitude": -2.58, "altitude": 11.0, "name": "Bristol, UK"},
            "london": {"latitude": 51.51, "longitude": -0.13, "altitude": 11.0, "name": "London, UK"},
            "edinburgh": {"latitude": 55.95, "longitude": -3.19, "altitude": 47.0, "name": "Edinburgh, UK"},
            "manchester": {"latitude": 53.48, "longitude": -2.24, "altitude": 38.0, "name": "Manchester, UK"},
        }
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


# ---------------------------------------------------------------------------
# Page routes
# ---------------------------------------------------------------------------


@bp.route("/builder")  # type: ignore[untyped-decorator]
def builder() -> str:
    """Render the scenario builder page with dual-pane editor.

    Returns:
        Rendered builder.html template.
    """
    return str(render_template("scenarios/builder.html", page="scenarios-builder"))


@bp.route("/sweep")  # type: ignore[untyped-decorator]
def sweep() -> str:
    """Render the parameter sweep configuration page.

    Returns:
        Rendered sweep.html template.
    """
    return str(render_template("scenarios/sweep.html", page="scenarios-sweep"))


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------


@bp.route("/api/preview-yaml", methods=["POST"])  # type: ignore[untyped-decorator]
def preview_yaml() -> tuple[Response, int]:
    """Convert form data to a YAML string preview.

    Expects a JSON body with scenario builder form fields.

    Returns:
        JSON with ``yaml`` string, HTTP 200 on success.
    """
    data = request.get_json(silent=True) or {}
    scenario_dict = _form_to_yaml_dict(data)
    yaml_str = yaml.dump(scenario_dict, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return jsonify({"yaml": yaml_str}), 200

@bp.route("/api/validate", methods=["POST"])  # type: ignore[untyped-decorator]
def validate_scenario() -> tuple[Response, int]:
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

@bp.route("/api/save", methods=["POST"])  # type: ignore[untyped-decorator]
def save_scenario() -> tuple[Response, int]:
    """Save a scenario configuration to the config_presets table.

    Expects a JSON body with at least ``name`` and ``config`` fields.

    Returns:
        JSON confirmation with preset name and id, HTTP 201 on success.
    """
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
        from solar_challenge.web.database import get_db  # noqa: PLC0415

        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT OR REPLACE INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (preset_id, name, "fleet", json.dumps(config_payload), now),
            )
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": str(exc)}), 500
    return jsonify({"name": name, "id": preset_id}), 201

@bp.route("/api/presets", methods=["GET"])  # type: ignore[untyped-decorator]
def list_presets() -> tuple[Response, int]:
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
        from solar_challenge.web.database import get_db  # noqa: PLC0415

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
        pass

    return jsonify({"presets": presets}), 200

@bp.route("/api/presets/<name>", methods=["GET"])  # type: ignore[untyped-decorator]
def get_preset(name: str) -> tuple[Response, int]:
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
                content = yaml.safe_load(path.read_text())
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
            return jsonify({
                "name": row["name"],
                "source": "saved",
                "config": cfg,
                "created_at": row["created_at"],
            }), 200
    except Exception:  # noqa: BLE001
        pass

    return jsonify({"error": f"Preset '{name}' not found"}), 404