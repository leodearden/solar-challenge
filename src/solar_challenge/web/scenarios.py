"""Flask Blueprint for scenario building and parameter sweep configuration.

Provides page routes for the scenario builder and sweep configuration UI,
as well as API endpoints for YAML preview, validation, saving, and loading
scenario presets.
"""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from flask import Blueprint, Response, current_app, jsonify, redirect, render_template, request, url_for

from solar_challenge.web.shared import location_presets_as_dicts

logger = logging.getLogger(__name__)

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
# API routes (legacy redirects to /api/scenarios/*)
# ---------------------------------------------------------------------------


@bp.route("/api/preview-yaml", methods=["POST"])  # type: ignore[untyped-decorator]
def preview_yaml() -> Response:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_preview_yaml"), code=307)

@bp.route("/api/validate", methods=["POST"])  # type: ignore[untyped-decorator]
def validate_scenario() -> Response:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_validate_scenario"), code=307)

@bp.route("/api/save", methods=["POST"])  # type: ignore[untyped-decorator]
def save_scenario() -> Response:
    """Redirect to consolidated API endpoint (preserves POST method)."""
    return redirect(url_for("api.scenarios_save_scenario"), code=307)

@bp.route("/api/presets", methods=["GET"])  # type: ignore[untyped-decorator]
def list_presets() -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.scenarios_list_presets"), code=301)

@bp.route("/api/presets/<name>", methods=["GET"])  # type: ignore[untyped-decorator]
def get_preset(name: str) -> Response:
    """Redirect to consolidated API endpoint."""
    return redirect(url_for("api.scenarios_get_preset", name=name), code=301)