"""Flask Blueprint routes for the Solar Challenge web dashboard."""

import html
import io
import tempfile
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
from flask import (
    Blueprint,
    Response,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from solar_challenge.battery import BatteryConfig
from solar_challenge.home import HomeConfig, calculate_summary, simulate_home
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.output import aggregate_daily, export_to_csv, generate_summary_report
from solar_challenge.pv import PVConfig
from solar_challenge.web.storage import RunStorage

bp = Blueprint("main", __name__)


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


def _request_data() -> dict[str, str]:
    """Return a unified string dict from form data or JSON body.

    Supports both HTMX form submissions (application/x-www-form-urlencoded)
    and direct JSON API calls (application/json).
    """
    if request.is_json:
        raw = request.get_json(silent=True) or {}
        return {k: str(v) for k, v in raw.items()}
    # form is an ImmutableMultiDict — convert to a plain dict of first values
    return {k: v for k, v in request.form.items()}


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


def _build_energy_chart_json(daily: pd.DataFrame) -> str:
    """Build a Plotly grouped-bar chart JSON figure for daily energy flows."""
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    dates = [d.strftime("%Y-%m-%d") for d in daily.index]

    series: list[tuple[str, str, str]] = [
        ("generation_kwh", "Generation", "#f5a623"),
        ("demand_kwh", "Demand", "#d0021b"),
        ("self_consumption_kwh", "Self-Consumption", "#7ed321"),
        ("grid_import_kwh", "Grid Import", "#9b9b9b"),
        ("grid_export_kwh", "Grid Export", "#4a90e2"),
    ]

    traces: list[Any] = []
    for col, name, color in series:
        if col in daily.columns:
            traces.append(
                go.Bar(
                    name=name,
                    x=dates,
                    y=daily[col].round(3).tolist(),
                    marker_color=color,
                )
            )

    layout = go.Layout(
        barmode="group",
        xaxis={"title": "Date", "type": "category"},
        yaxis={"title": "Energy (kWh)"},
        legend={"orientation": "h", "y": -0.25},
        margin={"l": 50, "r": 20, "t": 20, "b": 100},
        height=420,
    )

    fig = go.Figure(data=traces, layout=layout)
    return fig.to_json()


def _build_battery_chart_json(results: Any) -> str:
    """Build a Plotly line chart JSON figure for battery state of charge."""
    try:
        import plotly.graph_objects as go  # noqa: PLC0415
    except ImportError:
        return "{}"

    # Hourly averages keep the chart readable without overwhelming the browser.
    soc_hourly = results.battery_soc.resample("h").mean()
    dates = [d.isoformat() for d in soc_hourly.index]
    values = soc_hourly.round(4).tolist()

    trace = go.Scatter(
        name="Battery SOC",
        x=dates,
        y=values,
        mode="lines",
        fill="tozeroy",
        line={"color": "#7ed321", "width": 1.5},
        fillcolor="rgba(126,211,33,0.15)",
    )

    layout = go.Layout(
        xaxis={"title": "Time"},
        yaxis={"title": "State of Charge (kWh)"},
        margin={"l": 50, "r": 20, "t": 20, "b": 60},
        height=350,
    )

    fig = go.Figure(data=[trace], layout=layout)
    return fig.to_json()


@bp.route("/", methods=["GET"])
def index() -> str:
    """Render the simulation configuration form."""
    return render_template("index.html")


@bp.route("/simulate", methods=["POST"])
def simulate() -> Any:
    """Run simulation and return the results HTML partial (for HTMX injection)."""
    try:
        data = _request_data()

        # --- Parse parameters ---
        pv_kw = float(data.get("pv_kw", 4.0))
        battery_kwh_val = float(data.get("battery_kwh", 0.0))
        consumption_kwh_raw = data.get("consumption_kwh", "").strip()
        occupants = int(data.get("occupants", 3))
        location_preset = data.get("location", "bristol")

        # Support 'days' shorthand (HTMX form & JSON API) or explicit start/end dates.
        days_raw = data.get("days", "").strip()
        start_raw = data.get("start", "").strip()
        end_raw = data.get("end", "").strip()

        if days_raw:
            days = int(days_raw)
            if days == 365:
                start = "2024-01-01"
                end = "2024-12-31"
            else:
                ref = pd.Timestamp("2024-06-01")
                start = ref.strftime("%Y-%m-%d")
                end = (ref + pd.Timedelta(days=days - 1)).strftime("%Y-%m-%d")
        else:
            start = start_raw or "2024-01-01"
            end = end_raw or "2024-12-31"

        # --- Validate inputs ---
        if not (0.5 <= pv_kw <= 20.0):
            raise ValueError(f"PV capacity must be 0.5–20 kW, got {pv_kw}")
        if battery_kwh_val < 0:
            raise ValueError(f"Battery capacity cannot be negative, got {battery_kwh_val}")

        # --- Resolve location ---
        loc = _resolve_location(location_preset)

        # --- Build component configs ---
        pv_config = PVConfig(capacity_kw=pv_kw)

        has_battery = battery_kwh_val > 0
        battery_config: BatteryConfig | None = None
        if has_battery:
            battery_config = BatteryConfig(capacity_kwh=battery_kwh_val)

        annual_consumption: float | None = None
        if consumption_kwh_raw:
            annual_consumption = float(consumption_kwh_raw)

        load_config = LoadConfig(
            annual_consumption_kwh=annual_consumption,
            household_occupants=occupants,
        )

        home_config = HomeConfig(
            pv_config=pv_config,
            load_config=load_config,
            battery_config=battery_config,
            location=loc,
            name="Web Simulation",
        )

        # --- Run simulation ---
        start_date = pd.Timestamp(start, tz=loc.timezone)
        end_date = pd.Timestamp(end, tz=loc.timezone)

        results = simulate_home(home_config, start_date, end_date)
        summary = calculate_summary(results)

        # --- Aggregate daily and build chart JSON ---
        daily = aggregate_daily(results)
        energy_chart_json = _build_energy_chart_json(daily)
        battery_chart_json = _build_battery_chart_json(results) if has_battery else None

        # --- Serialise summary for session / template ---
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

        # --- Persist results to storage ---
        run_id = str(uuid.uuid4())
        storage = get_storage()
        storage.save_home_run(
            run_id=run_id,
            config=home_config,
            results=results,
            summary=summary,
            name=home_config.name,
        )

        session["run_id"] = run_id
        session["summary"] = summary_dict
        session["has_battery"] = has_battery

        return render_template(
            "partials/results.html",
            summary=summary_dict,
            energy_chart_json=energy_chart_json,
            battery_chart_json=battery_chart_json,
            has_battery=has_battery,
        )

    except ValueError as exc:
        error_html = (
            '<div class="card" role="alert"'
            ' style="border-left:4px solid #d0021b;padding:1rem;">'
            f"<strong>Validation error:</strong> {exc}"
            "</div>"
        )
        return Response(error_html, status=400, mimetype="text/html")

    except Exception as exc:  # noqa: BLE001
        flash(f"Simulation failed: {exc}", "error")
        return redirect(url_for("main.index"))


@bp.route("/results", methods=["GET"])
def results() -> Any:
    """Display simulation results page (fallback for non-HTMX access)."""
    if "run_id" not in session:
        flash("No simulation results found. Please run a simulation first.", "info")
        return redirect(url_for("main.index"))

    summary = session.get("summary", {})
    return render_template("results.html", summary=summary)


@bp.route("/download/csv", methods=["GET"])
def download_csv() -> Response:
    """Stream simulation results as a CSV file download."""
    run_id = session.get("run_id")
    if not run_id:
        flash("No simulation results available. Please run a simulation first.", "error")
        return redirect(url_for("main.index"))  # type: ignore[return-value]

    try:
        storage = get_storage()
        config, sim_results, summary = storage.load_home_run(run_id)
    except FileNotFoundError:
        flash("Simulation results not found. Please run a new simulation.", "error")
        return redirect(url_for("main.index"))  # type: ignore[return-value]

    # Use export_to_csv() to write to a temp file, then load into BytesIO buffer.
    with tempfile.TemporaryDirectory() as tmpdir:
        csv_path = export_to_csv(sim_results, f"{tmpdir}/simulation_results.csv")
        buffer = io.BytesIO(csv_path.read_bytes())

    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=simulation_results.csv"},
    )


@bp.route("/download/report", methods=["GET"])
def download_report() -> Response:
    """Return simulation report wrapped in a minimal HTML page for download."""
    run_id = session.get("run_id")
    if not run_id:
        flash("No simulation results available. Please run a simulation first.", "error")
        return redirect(url_for("main.index"))  # type: ignore[return-value]

    try:
        storage = get_storage()
        config, sim_results, summary = storage.load_home_run(run_id)
    except FileNotFoundError:
        flash("Simulation results not found. Please run a new simulation.", "error")
        return redirect(url_for("main.index"))  # type: ignore[return-value]

    home_name = config.name or "Home"
    report_markdown = generate_summary_report(sim_results, home_name)

    # Escape the markdown text and render inside a minimal HTML page so that
    # it is human-readable in a browser while still preserving all formatting.
    escaped = html.escape(report_markdown)
    page_title = html.escape(f"Simulation Report: {home_name}")
    html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{page_title}</title>
  <style>
    body {{ font-family: sans-serif; max-width: 860px; margin: 2rem auto; padding: 0 1rem; color: #333; }}
    pre {{ white-space: pre-wrap; word-wrap: break-word; background: #f8f8f8; padding: 1.5rem; border-radius: 4px; font-size: 0.9rem; line-height: 1.6; }}
  </style>
</head>
<body>
<pre>{escaped}</pre>
</body>
</html>"""

    return Response(
        html_content,
        mimetype="text/html",
        headers={"Content-Disposition": "attachment; filename=simulation_report.html"},
    )
