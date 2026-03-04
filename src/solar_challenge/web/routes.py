"""Flask Blueprint routes for the Solar Challenge web dashboard."""

import json
from pathlib import Path
from typing import Any

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    url_for,
)

from solar_challenge.location import Location
from solar_challenge.web.storage import RunStorage

bp = Blueprint("main", __name__)

# Built-in configuration presets for home simulations.
BUILTIN_PRESETS: list[dict[str, Any]] = [
    {"name": "Small Urban", "pv_kw": 3.0, "battery_kwh": 0, "consumption_kwh": 2900},
    {"name": "Medium Suburban", "pv_kw": 4.0, "battery_kwh": 5.0, "consumption_kwh": 3500},
    {"name": "Large with Battery", "pv_kw": 6.0, "battery_kwh": 10.0, "consumption_kwh": 4500},
]


def get_storage() -> RunStorage:
    """Get RunStorage instance configured from Flask app config.

    Returns:
        RunStorage: Configured storage service instance.
    """
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]
    return RunStorage(db_path=db_path, data_dir=data_dir)


# UK location presets available from the web form.
_LOCATION_PRESETS: dict[str, Location] = {
    "bristol": Location(
        latitude=51.45, longitude=-2.58,
        timezone="Europe/London", altitude=11.0, name="Bristol, UK",
    ),
    "london": Location(
        latitude=51.51, longitude=-0.13,
        timezone="Europe/London", altitude=11.0, name="London, UK",
    ),
    "edinburgh": Location(
        latitude=55.95, longitude=-3.19,
        timezone="Europe/London", altitude=47.0, name="Edinburgh, UK",
    ),
    "manchester": Location(
        latitude=53.48, longitude=-2.24,
        timezone="Europe/London", altitude=38.0, name="Manchester, UK",
    ),
}


def _resolve_location(preset_str: str) -> Location:
    """Map a location string to a Location instance.

    Accepts preset names (bristol, london, edinburgh, manchester) or
    a 'lat,lon' string.  Falls back to Bristol on parse errors.
    """
    key = preset_str.strip().lower()
    if key in _LOCATION_PRESETS:
        return _LOCATION_PRESETS[key]
    try:
        lat, lon = map(float, key.split(","))
        return Location(latitude=lat, longitude=lon)
    except ValueError:
        return Location.bristol()


def _get_aggregate_stats(storage: RunStorage) -> dict[str, Any]:
    """Compute aggregate statistics across all simulation runs.

    Args:
        storage: RunStorage instance to query.

    Returns:
        Dict with total_runs, total_homes, and total_energy_mwh.
    """
    all_runs = storage.list_runs()
    total_runs = len(all_runs)
    total_homes = 0
    total_energy_kwh = 0.0

    for run in all_runs:
        total_homes += run.get("n_homes", 1) or 1
        summary_json = run.get("summary_json")
        if summary_json:
            try:
                summary = json.loads(summary_json) if isinstance(summary_json, str) else summary_json
                # Home runs have total_generation_kwh at top level
                gen = summary.get("total_generation_kwh", 0) or 0
                total_energy_kwh += float(gen)
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

    return {
        "total_runs": total_runs,
        "total_homes": total_homes,
        "total_energy_mwh": round(total_energy_kwh / 1000.0, 2),
    }


@bp.route("/", methods=["GET"])  # type: ignore[untyped-decorator]
def index() -> str:
    """Render the dashboard page with recent runs and aggregate stats."""
    storage = get_storage()
    runs_raw = storage.list_runs(limit=10)
    stats = _get_aggregate_stats(storage)

    # Format runs for the template table
    runs = []
    for run in runs_raw:
        runs.append({
            "name": run.get("name", "Unnamed"),
            "type": run.get("type", "home"),
            "date": (run.get("created_at", "")[:10] if run.get("created_at") else ""),
            "status": run.get("status", "unknown"),
            "_row": [
                run.get("name", "Unnamed"),
                run.get("type", "home"),
                (run.get("created_at", "")[:10] if run.get("created_at") else ""),
                run.get("status", "unknown"),
            ],
        })

    return str(render_template(
        "dashboard.html",
        runs=runs,
        stats=stats,
        page="dashboard",
    ))


@bp.route("/simulate/home", methods=["GET"])  # type: ignore[untyped-decorator]
def simulate_home_page() -> str:
    """Render the enhanced home simulation configuration page."""
    return str(render_template(
        "simulate/home.html",
        page="simulate-home",
    ))


@bp.route("/results/home/<run_id>", methods=["GET"])  # type: ignore[untyped-decorator]
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

    summary_dict: dict[str, Any] = {
        "total_generation_kwh": round(summary.total_generation_kwh, 2),
        "total_demand_kwh": round(summary.total_demand_kwh, 2),
        "total_self_consumption_kwh": round(summary.total_self_consumption_kwh, 2),
        "total_grid_import_kwh": round(summary.total_grid_import_kwh, 2),
        "total_grid_export_kwh": round(summary.total_grid_export_kwh, 2),
        "total_battery_charge_kwh": round(summary.total_battery_charge_kwh, 2),
        "total_battery_discharge_kwh": round(summary.total_battery_discharge_kwh, 2),
        "peak_generation_kw": round(summary.peak_generation_kw, 2),
        "peak_demand_kw": round(summary.peak_demand_kw, 2),
        "self_consumption_ratio": round(summary.self_consumption_ratio, 4),
        "grid_dependency_ratio": round(summary.grid_dependency_ratio, 4),
        "export_ratio": round(summary.export_ratio, 4),
        "simulation_days": summary.simulation_days,
    }

    has_battery = config.battery_config is not None

    charts: dict[str, Any] = {
        "sankey": sankey_diagram(summary_dict),
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
        summary=summary_dict,
        charts=charts,
        has_battery=has_battery,
        run_id=run_id,
        run_name=config.name or "Home Simulation",
        page="results",
    )


def _load_scenario_presets() -> list[str]:
    """Scan the scenarios/ directory for YAML files and return preset names.

    Searches in the project root ``scenarios/`` directory for files
    ending in ``.yaml`` or ``.yml``.

    Returns:
        Sorted list of scenario file names (without extension).
    """
    import importlib.resources  # noqa: PLC0415

    presets: list[str] = []

    # Try the project-level scenarios/ directory
    project_root = Path(__file__).resolve().parents[3]
    scenarios_dir = project_root / "scenarios"
    if scenarios_dir.is_dir():
        for path in sorted(scenarios_dir.iterdir()):
            if path.suffix in (".yaml", ".yml") and path.is_file():
                presets.append(path.stem)

    return presets


@bp.route("/simulate/fleet", methods=["GET"])  # type: ignore[untyped-decorator]
def simulate_fleet_page() -> str:
    """Render the fleet simulation configuration page."""
    presets = _load_scenario_presets()
    return str(render_template(
        "simulate/fleet.html",
        presets=presets,
        page="simulate-fleet",
    ))


@bp.route("/results/fleet/<run_id>", methods=["GET"])  # type: ignore[untyped-decorator]
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

    summary_dict: dict[str, Any] = {
        "n_homes": fleet_summary.n_homes,
        "total_generation_kwh": round(fleet_summary.total_generation_kwh, 2),
        "total_demand_kwh": round(fleet_summary.total_demand_kwh, 2),
        "total_self_consumption_kwh": round(fleet_summary.total_self_consumption_kwh, 2),
        "total_grid_import_kwh": round(fleet_summary.total_grid_import_kwh, 2),
        "total_grid_export_kwh": round(fleet_summary.total_grid_export_kwh, 2),
        "fleet_self_consumption_ratio": round(fleet_summary.fleet_self_consumption_ratio, 4),
        "fleet_grid_dependency_ratio": round(fleet_summary.fleet_grid_dependency_ratio, 4),
        "simulation_days": fleet_summary.simulation_days,
    }

    home_summaries = [
        {
            "total_generation_kwh": s.total_generation_kwh,
            "total_demand_kwh": s.total_demand_kwh,
            "total_self_consumption_kwh": s.total_self_consumption_kwh,
            "total_grid_import_kwh": s.total_grid_import_kwh,
            "total_grid_export_kwh": s.total_grid_export_kwh,
            "self_consumption_ratio": s.self_consumption_ratio,
            "grid_dependency_ratio": s.grid_dependency_ratio,
            "export_ratio": s.export_ratio,
        }
        for s in per_home_summaries
    ]

    # Build aggregate SimulationResults for timeline/grid charts
    # by summing per-home time series
    aggregate = fleet_results_data.per_home_results[0]
    if len(fleet_results_data.per_home_results) > 1:
        from solar_challenge.home import SimulationResults as SR  # noqa: PLC0415

        aggregate = SR(
            generation=fleet_results_data.total_generation,
            demand=fleet_results_data.total_demand,
            self_consumption=fleet_results_data.total_self_consumption,
            battery_charge=fleet_results_data.get_aggregate_series("battery_charge"),
            battery_discharge=fleet_results_data.get_aggregate_series("battery_discharge"),
            battery_soc=fleet_results_data.get_aggregate_series("battery_soc"),
            grid_import=fleet_results_data.total_grid_import,
            grid_export=fleet_results_data.total_grid_export,
            import_cost=fleet_results_data.get_aggregate_series("import_cost"),
            export_revenue=fleet_results_data.get_aggregate_series("export_revenue"),
            tariff_rate=fleet_results_data.per_home_results[0].tariff_rate,
            strategy_name="fleet_aggregate",
        )

    charts: dict[str, Any] = {
        "aggregate_timeline": fleet_aggregate_timeline(aggregate),
        "grid_impact": fleet_grid_impact(aggregate),
        "heatmap": fleet_heatmap(home_summaries),
        "box_plots": fleet_box_plots(home_summaries),
        "distribution_histograms": fleet_distribution_histograms(home_summaries),
    }

    return render_template(
        "results/fleet.html",
        summary=summary_dict,
        charts=charts,
        n_homes=fleet_summary.n_homes,
        run_id=run_id,
        run_name="Fleet Simulation",
        page="results",
    )
