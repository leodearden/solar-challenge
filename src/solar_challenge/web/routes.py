# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flask Blueprint routes for the Solar Challenge web dashboard."""

from typing import Any, assert_never

from flask import (
    Blueprint,
    flash,
    redirect,
    render_template,
    url_for,
)

from solar_challenge.seg import SEG_PRESETS
from solar_challenge.web.charts import (
    battery_soc_chart,
    daily_energy_balance,
    financial_breakdown,
    fleet_aggregate_timeline,
    fleet_box_plots,
    fleet_distribution_histograms,
    fleet_grid_impact,
    fleet_heatmap,
    heat_pump_analysis,
    monthly_summary,
    power_flow_timeline,
    sankey_diagram,
    seasonal_comparison,
)
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.fleet_presets import fleet_preset_names
from solar_challenge.web.shared import get_storage
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.stored_runs import StoredFleetRun, StoredHomeRun

bp = Blueprint("main", __name__)


def _get_aggregate_stats(storage: RunStorage) -> dict[str, Any]:
    """Compute aggregate statistics across all completed simulation runs.

    Uses SQL aggregate queries instead of loading all rows for O(1) performance.

    Args:
        storage: RunStorage instance to query.

    Returns:
        Dict with total_runs, total_homes, and total_energy_mwh.
    """
    with storage.database.transaction() as conn:
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
    ))


@bp.route("/simulate/home", methods=["GET"])
def simulate_home_page() -> str:
    """Render the enhanced home simulation configuration page."""
    return str(render_template(
        "simulate/home.html",
        fleet_components=FLEET_COMPONENTS,
        seg_presets=SEG_PRESETS,
    ))


@bp.route("/simulate/fleet", methods=["GET"])
def simulate_fleet_page() -> str:
    """Render the fleet simulation configuration page, its Load Preset menu offering the presets its form loads."""
    return str(render_template(
        "simulate/fleet.html",
        fleet_components=FLEET_COMPONENTS,
        presets=fleet_preset_names(),
        seg_presets=SEG_PRESETS,
    ))




@bp.route("/results/<run_id>", methods=["GET"])
def run_results(run_id: str) -> Any:
    """Display a run's results page: the template its record's kind names, with the values its stored run gives.

    A run with no record, or whose files load_run cannot find, redirects to the dashboard,
    which flashes "Run not found.".
    """
    storage = get_storage()
    record = storage.run_record(run_id)
    if record is None:
        return _run_not_found()
    try:
        stored = storage.load_run(run_id)
    except FileNotFoundError:
        return _run_not_found()

    match stored:
        case StoredHomeRun():
            unnamed_title = "Home Simulation"
            page_values = _home_results_values(stored)
        case StoredFleetRun():
            unnamed_title = "Fleet Simulation"
            page_values = _fleet_results_values(stored)
        case _:
            assert_never(stored)

    return render_template(
        record.kind.results_template,
        run_id=run_id,
        run_name=record.name or unnamed_title,
        **page_values,
    )


@bp.route("/results/home/<run_id>", methods=["GET"], endpoint="home_results")
@bp.route("/results/fleet/<run_id>", methods=["GET"], endpoint="fleet_results")
def results_page_moved(run_id: str) -> Any:
    """Answer 301 to the run's one results page, /results/<run_id>, whatever kind of run the old URL named."""
    return redirect(url_for("main.run_results", run_id=run_id), code=301)


def _run_not_found() -> Any:
    """Redirect to the dashboard, flashing that the run asked for was not found."""
    flash("Run not found.", "error")
    return redirect(url_for("main.index"))


def _home_results_values(run: StoredHomeRun) -> dict[str, Any]:
    """The values results/home.html shows a home run with, besides its id and name: its summary, whether it has a battery, and its charts."""
    results = run.results
    battery_config = run.config.battery_config
    charts: dict[str, Any] = {
        "sankey": sankey_diagram(run.summary),
        "daily_balance": daily_energy_balance(results),
        "power_flow": power_flow_timeline(results),
        "battery_soc": None if battery_config is None else battery_soc_chart(results, battery_config),
        "financial": financial_breakdown(results),
        "monthly": monthly_summary(results),
        "seasonal": seasonal_comparison(results),
        "heat_pump": heat_pump_analysis(results),
    }
    return {"summary": run.summary, "charts": charts, "has_battery": battery_config is not None}


def _fleet_results_values(run: StoredFleetRun) -> dict[str, Any]:
    """The values results/fleet.html shows a fleet run with, besides its id and name: its summary and its charts."""
    charts: dict[str, Any] = {
        "aggregate_timeline": fleet_aggregate_timeline(run.fleet_results),
        "grid_impact": fleet_grid_impact(run.fleet_results),
        "heatmap": fleet_heatmap(run.home_summaries),
        "box_plots": fleet_box_plots(run.home_summaries),
        "distribution_histograms": fleet_distribution_histograms(run.home_summaries),
    }
    return {"summary": run.summary, "charts": charts}
