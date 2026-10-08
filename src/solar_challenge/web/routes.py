# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint routes for the Solar Challenge web dashboard."""

from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    url_for,
)

from solar_challenge.seg import SEG_PRESETS
from solar_challenge.web.shared import get_storage
from solar_challenge.web.storage import RunStorage

bp = Blueprint("main", __name__)


def _get_aggregate_stats(storage: RunStorage) -> dict[str, Any]:
    """Compute aggregate statistics across all completed simulation runs.

    Uses SQL aggregate queries instead of loading all rows for O(1) performance.

    Args:
        storage: RunStorage instance to query.

    Returns:
        Dict with total_runs, total_homes, and total_energy_mwh.
    """
    from solar_challenge.web.database import get_db  # noqa: PLC0415

    with get_db(storage.db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT
                COUNT(*) as total_runs,
                COALESCE(SUM(CASE WHEN n_homes IS NOT NULL AND n_homes > 0 THEN n_homes ELSE 1 END), 0) as total_homes
            FROM runs
            WHERE status = 'completed'
        """)
        row = cursor.fetchone()
        total_runs = row["total_runs"]
        total_homes = row["total_homes"]

        # Get total energy from summary_json using json_extract
        cursor.execute("""
            SELECT COALESCE(SUM(
                CAST(json_extract(summary_json, '$.total_generation_kwh') AS REAL)
            ), 0.0) as total_energy_kwh
            FROM runs
            WHERE status = 'completed' AND summary_json IS NOT NULL
        """)
        energy_row = cursor.fetchone()
        total_energy_kwh = energy_row["total_energy_kwh"]

    return {
        "total_runs": total_runs,
        "total_homes": total_homes,
        "total_energy_mwh": round(total_energy_kwh / 1000.0, 2),
    }


@bp.route("/", methods=["GET"])
def index() -> str:
    """Render the dashboard page with recent runs and aggregate stats."""
    storage = get_storage()
    runs_raw = storage.list_runs(limit=10)
    stats = _get_aggregate_stats(storage)

    # Format runs for the template table
    runs = []
    for run in runs_raw:
        runs.append({
            "id": run.get("id", ""),
            "name": run.get("name", "Unnamed"),
            "type": run.get("type", "home"),
            "date": (run.get("created_at", "")[:10] if run.get("created_at") else ""),
            "status": run.get("status", "unknown"),
        })

    return str(render_template(
        "dashboard.html",
        runs=runs,
        stats=stats,
        page="dashboard",
    ))


@bp.route("/simulate/home", methods=["GET"])
def simulate_home_page() -> str:
    """Render the enhanced home simulation configuration page."""
    return str(render_template(
        "simulate/home.html",
        page="simulate-home",
        seg_presets=SEG_PRESETS,
    ))


@bp.route("/results/home/<run_id>", methods=["GET"])
def home_results(run_id: str) -> Any:
    """Display results for a completed home simulation.

    Loads persisted results from storage, builds chart JSON using the
    centralized charts module, and renders the full results page.

    Args:
        run_id: Unique identifier for the simulation run.

    Returns:
        Rendered results/home.html template.
    """
    storage = get_storage()
    try:
        config, sim_results, summary = storage.load_home_run(run_id)
    except FileNotFoundError:
        flash("Run not found.", "error")
        return redirect(url_for("main.index"))

    from solar_challenge.web.charts import (  # noqa: PLC0415
        battery_soc_chart,
        daily_energy_balance,
        financial_breakdown,
        heat_pump_analysis,
        monthly_summary,
        power_flow_timeline,
        sankey_diagram,
        seasonal_comparison,
    )

    has_battery = config.battery_config is not None

    charts: dict[str, Any] = {
        "sankey": sankey_diagram(summary),
        "daily_balance": daily_energy_balance(sim_results),
        "power_flow": power_flow_timeline(sim_results),
        "battery_soc": (
            battery_soc_chart(sim_results, config.battery_config.capacity_kwh)
            if has_battery and config.battery_config is not None
            else None
        ),
        "financial": financial_breakdown(sim_results),
        "monthly": monthly_summary(sim_results),
        "seasonal": seasonal_comparison(sim_results),
        "heat_pump": heat_pump_analysis(sim_results),
    }

    return render_template(
        "results/home.html",
        summary=summary,
        charts=charts,
        has_battery=has_battery,
        run_id=run_id,
        run_name=storage.run_name(run_id) or "Home Simulation",
        page="results",
    )


def _load_scenario_presets() -> list[str]:
    """Scan the scenarios/ directory for YAML files and return preset names.

    Searches in the project root ``scenarios/`` directory for files
    ending in ``.yaml`` or ``.yml``.

    Returns:
        Sorted list of scenario file names (without extension).
    """

    presets: list[str] = []

    # Try the project-level scenarios/ directory
    project_root = Path(__file__).resolve().parents[3]
    scenarios_dir = project_root / "scenarios"
    if scenarios_dir.is_dir():
        for path in sorted(scenarios_dir.iterdir()):
            if path.suffix in (".yaml", ".yml") and path.is_file():
                presets.append(path.stem)

    return presets


@bp.route("/simulate/fleet", methods=["GET"])
def simulate_fleet_page() -> str:
    """Render the fleet simulation configuration page."""
    presets = _load_scenario_presets()
    return str(render_template(
        "simulate/fleet.html",
        presets=presets,
        page="simulate-fleet",
        seg_presets=SEG_PRESETS,
    ))


@bp.route("/results/fleet/<run_id>", methods=["GET"])
def fleet_results(run_id: str) -> Any:
    """Display results for a completed fleet simulation.

    Loads persisted fleet results from storage, builds chart JSON
    using the centralized charts module, and renders the fleet
    results page with aggregate and per-home visualizations.

    Args:
        run_id: Unique identifier for the fleet simulation run.

    Returns:
        Rendered results/fleet.html template.
    """
    storage = get_storage()
    try:
        fleet_results_data, fleet_summary, per_home_summaries = storage.load_fleet_run(run_id)
    except FileNotFoundError:
        flash("Fleet run not found.", "error")
        return redirect(url_for("main.index"))

    from solar_challenge.web.charts import (  # noqa: PLC0415
        fleet_aggregate_timeline,
        fleet_box_plots,
        fleet_distribution_histograms,
        fleet_grid_impact,
        fleet_heatmap,
    )

    charts: dict[str, Any] = {
        "aggregate_timeline": fleet_aggregate_timeline(fleet_results_data),
        "grid_impact": fleet_grid_impact(fleet_results_data),
        "heatmap": fleet_heatmap(per_home_summaries),
        "box_plots": fleet_box_plots(per_home_summaries),
        "distribution_histograms": fleet_distribution_histograms(per_home_summaries),
    }

    return render_template(
        "results/fleet.html",
        summary=fleet_summary,
        charts=charts,
        run_id=run_id,
        run_name=storage.run_name(run_id) or "Fleet Simulation",
        page="results",
    )
