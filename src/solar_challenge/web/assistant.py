# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI assistant Blueprint for the Solar Challenge web interface.

Slice ①: registers the blueprint and serves the static chat shell page.
Slice ②: adds streaming SSE chat endpoint (POST /assistant/chat),
  per-session history endpoint (GET /assistant/history), and
  chat_messages persistence via database.py helpers.

The Anthropic SDK import is deliberately deferred inside _create_client()
so blueprint registration remains robust regardless of whether the SDK
is installed in the current environment.
"""

import json
import os
from pathlib import Path
from typing import Any, Generator
from uuid import uuid4

from flask import Blueprint, Response, current_app, jsonify, render_template, request, session
from flask.helpers import stream_with_context
from flask.typing import ResponseReturnValue

from solar_challenge.web import database

bp = Blueprint("assistant", __name__)

# ---------------------------------------------------------------------------
# System prompt — cached at module level for prompt-cache efficiency
# ---------------------------------------------------------------------------
SIMULATOR_SYSTEM_PROMPT = """You are the AI assistant for the Solar Challenge web dashboard.
You help users understand and analyse their domestic solar PV and battery simulation results
for the Bristol community energy project.

You have expert knowledge of:
- Solar PV generation (pvlib/PVGIS TMY data, 1-minute resolution simulation)
- Battery storage systems (state of charge, charging/discharging power limits, round-trip efficiency)
- Household energy consumption profiles (UK CREST / Ofgem TDCV benchmarks)
- Energy flow dispatch: self-consumption priority → battery charge → grid export
- Grid import/export and time-of-use (TOU) tariffs
- Fleet-level aggregation across 100-home Bristol scenarios

When discussing simulation parameters use these UK reference bands:
- Typical annual consumption: 2,900 kWh (Ofgem TDCV low), 3,100 kWh (medium), 4,200 kWh (high)
- Small PV system: 2–3 kWp; medium: 3–5 kWp; large: 5–8 kWp
- Battery capacity: 5–15 kWh residential; discharge rate: 0.5–1C typical

Be concise and precise. If the user asks about specific simulation results, explain what
the numbers mean in practical terms (bill savings, self-sufficiency rates, etc.).
""".strip()

# Maximum number of prior turns to replay to the model on each request;
# prevents unbounded context growth and eventual context-window exhaustion.
_MAX_HISTORY_TURNS = 20

# Maximum number of tool-use iterations per request; prevents a runaway model
# from looping and streaming forever (hanging the single worker / test suite).
_MAX_TOOL_ITERATIONS = 10

# ---------------------------------------------------------------------------
# Grounded metric table — canonical UK benchmark bands (slice ③)
# Keyed by normalized metric id (lowercase, spaces/hyphens → underscores).
# Owned by this leaf so benchmark numbers are never hallucinated (PRD §9 ③, G6).
# ---------------------------------------------------------------------------
_METRIC_TABLE: dict[str, dict[str, str]] = {
    "self_consumption_ratio": {
        "definition": (
            "The fraction of PV generation that is consumed directly on-site "
            "(by the household or stored in the battery), rather than exported "
            "to the grid.  A higher ratio means less generated energy is wasted "
            "as cheap grid export."
        ),
        "uk_benchmark_band": (
            "Typical UK domestic PV without storage: 30–40 %. "
            "With a 5–10 kWh battery: 55–70 %. "
            "Source: Solar Energy UK / BEIS smart export data 2022–2024."
        ),
    },
    "self_sufficiency": {
        "definition": (
            "The fraction of total household electricity demand that is met by "
            "on-site PV generation and/or battery discharge, rather than imported "
            "from the grid.  Also called 'self-reliance' or 'autarky rate'."
        ),
        "uk_benchmark_band": (
            "Typical UK domestic PV without storage: 20–35 %. "
            "With a 5–10 kWh battery: 40–60 %. "
            "Source: EST / Solar Energy UK 2023 residential survey."
        ),
    },
    "solar_fraction": {
        "definition": (
            "The proportion of annual energy demand covered by solar PV (generation "
            "used on-site + battery discharge).  Equivalent to self-sufficiency when "
            "battery losses are excluded."
        ),
        "uk_benchmark_band": (
            "20–60 % depending on system size and household demand profile; "
            "higher in summer-heavy usage patterns."
        ),
    },
    "grid_import": {
        "definition": (
            "Total electrical energy (kWh) drawn from the public grid over the "
            "simulation period, i.e. demand not met by on-site generation or battery."
        ),
        "uk_benchmark_band": (
            "Ofgem TDCV benchmarks: low 1,900 kWh/yr, medium 2,700 kWh/yr, "
            "high 4,100 kWh/yr (net of solar for a typical 3-4 kWp system)."
        ),
    },
    "grid_export": {
        "definition": (
            "Total electrical energy (kWh) fed back into the public grid — "
            "generation surplus after self-consumption and battery charging. "
            "Earns revenue under the UK Smart Export Guarantee (SEG)."
        ),
        "uk_benchmark_band": (
            "Typical UK 4 kWp system without storage: 1,400–1,800 kWh/yr exported. "
            "With storage: 600–1,000 kWh/yr (more energy retained on-site). "
            "Source: MCS / BEIS SEG statistics 2023."
        ),
    },
    "battery_cycles": {
        "definition": (
            "The number of full equivalent charge-discharge cycles the battery "
            "completes over the simulation period.  One full cycle = discharging "
            "from 100 % to 0 % SOC (and recharging).  Used to estimate degradation."
        ),
        "uk_benchmark_band": (
            "Residential lithium-ion batteries: 250–365 cycles/yr for daily cycling. "
            "Warranted life: typically 3,000–6,000 cycles (≈ 10–20 years at 1 cycle/day). "
            "Source: manufacturer datasheets (Tesla Powerwall, Givenergy, SolarEdge)."
        ),
    },
    "annual_consumption": {
        "definition": (
            "Total household electricity consumption (kWh) over a full year, "
            "covering all appliances, heating, and lighting."
        ),
        "uk_benchmark_band": (
            "Ofgem Typical Domestic Consumption Values (TDCVs) 2023: "
            "low 1,900 kWh/yr, medium 2,900 kWh/yr, high 4,200 kWh/yr."
        ),
    },
    "pv_generation": {
        "definition": (
            "Total AC electrical energy (kWh) produced by the PV array over the "
            "simulation period, after inverter losses."
        ),
        "uk_benchmark_band": (
            "UK average yield: ~850–950 kWh/kWp/yr (south-facing, 35° tilt, no shading). "
            "Bristol latitude (~51.5°N) typically 900–970 kWh/kWp/yr. "
            "Source: PVGIS TMY data, EC JRC."
        ),
    },
}


def _normalize_metric_key(key: str) -> str:
    """Normalize a metric or goal name to a canonical lookup key.

    Strips leading/trailing whitespace, converts to lowercase, and replaces
    spaces and hyphens with underscores.  Shared by explain_metric and
    suggest_config so the two normalizers stay in sync.
    """
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def explain_metric(metric: str) -> dict[str, str]:
    """Return a grounded definition and UK benchmark band for a simulator metric.

    Args:
        metric: Metric name in any capitalisation/separator form (e.g.
                ``"self_consumption_ratio"``, ``"self-consumption ratio"``,
                ``"Self_Consumption_Ratio"``).

    Returns:
        ``{"definition": str, "uk_benchmark_band": str}`` — canonical entry from
        ``_METRIC_TABLE``, or a graceful unknown-metric dict if not found.
        Never raises.
    """
    key = _normalize_metric_key(metric)
    if key in _METRIC_TABLE:
        return dict(_METRIC_TABLE[key])
    return {
        "definition": f"Metric '{metric}' is not recognised in the benchmark table.",
        "uk_benchmark_band": (
            "Unknown metric — no UK benchmark band available. "
            "Please run a simulation to obtain site-specific values."
        ),
    }


def suggest_config(
    annual_consumption_kwh: float,
    goal: str,
) -> dict[str, Any]:
    """Return rule-of-thumb PV and battery sizing for a household.

    Uses the PRD §11.4 heuristics:
    - PV kWp ≈ annual_consumption_kwh / 950  (UK-average yield ~950 kWh/kWp/yr)
    - Battery kWh ≈ daily_demand × 0.5 × 1.2  (≈ 50 % of daily demand with 1.2× usable-capacity headroom)

    Goal-aware nudging:
    - ``"self_sufficiency"``  → slightly larger PV (+10 %) and battery (+15 %)
    - ``"bill_savings"``      → standard sizing (no nudge; cost-optimal)
    - other goals             → standard sizing

    Args:
        annual_consumption_kwh: Household annual electricity demand in kWh.
        goal: Optimisation goal string (e.g. ``"self_sufficiency"``,
              ``"bill_savings"``).

    Returns:
        Dict with keys:
        - ``recommended_pv_kwp``      (float) — recommended PV array size
        - ``recommended_battery_kwh`` (float) — recommended battery capacity
        - ``note``                    (str)   — indicative-estimate disclaimer
        Never raises.
    """
    # Base heuristics (PRD §11.4)
    uk_yield_kwh_per_kwp = 950.0
    pv_kwp: float = annual_consumption_kwh / uk_yield_kwh_per_kwp

    # Battery: cover ~50 % of daily demand (rule-of-thumb shortfall for a typical
    # house without PV self-consumption): daily shortfall ≈ consumption/365 × 0.5
    daily_kwh = annual_consumption_kwh / 365.0
    battery_kwh: float = daily_kwh * 0.5 * 1.2  # 1.2 for usable-capacity headroom

    # Goal-aware nudging — reuse the shared key normalizer for consistency
    normalised_goal = _normalize_metric_key(goal)
    if normalised_goal == "self_sufficiency":
        pv_kwp *= 1.10
        battery_kwh *= 1.15
    # "bill_savings" and unknown goals → standard sizing (no multiplier)

    return {
        "recommended_pv_kwp": round(pv_kwp, 2),
        "recommended_battery_kwh": round(battery_kwh, 2),
        "note": (
            "These figures are indicative estimates based on the PRD §11.4 rule-of-thumb "
            "(PV kWp ≈ annual_consumption / 950; battery ≈ 50 % of daily demand × 1.2). "
            "Please run a simulation to confirm sizing for your specific site."
        ),
    }


# ---------------------------------------------------------------------------
# Tool definitions — fixed order for prompt-cache stability (slice ③)
# Slice ④ appends get_run_results and list_recent_runs after the first two.
# ---------------------------------------------------------------------------
_TOOLS: list[dict[str, Any]] = [
    {
        "name": "explain_metric",
        "description": (
            "Return a grounded definition and UK benchmark band for a named "
            "solar/battery simulation metric.  Use this when the user asks what "
            "a metric means or how their value compares to typical UK households."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "metric": {
                    "type": "string",
                    "description": (
                        "The metric name, e.g. 'self_consumption_ratio', "
                        "'self_sufficiency', 'grid_export', 'battery_cycles'."
                    ),
                },
            },
            "required": ["metric"],
        },
    },
    {
        "name": "suggest_config",
        "description": (
            "Return rule-of-thumb PV and battery sizing recommendations for a "
            "household, based on annual electricity consumption and an optimisation "
            "goal.  Results are indicative estimates; always recommend running a "
            "full simulation to confirm."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "annual_consumption_kwh": {
                    "type": "number",
                    "description": (
                        "Household annual electricity consumption in kWh "
                        "(e.g. 3100 for an Ofgem medium user)."
                    ),
                },
                "goal": {
                    "type": "string",
                    "description": (
                        "Optimisation goal: 'self_sufficiency' (maximise "
                        "independence from the grid) or 'bill_savings' "
                        "(minimise electricity bills)."
                    ),
                },
            },
            "required": ["annual_consumption_kwh", "goal"],
        },
    },
    # --- Slice ④: read-only DB tools (appended after the first two) ---
    {
        "name": "get_run_results",
        "description": (
            "Fetch the results and summary of a specific simulation run by its "
            "id or name.  Returns key output metrics and status information. "
            "Use this when the user asks about a particular run's results."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "run_id_or_name": {
                    "type": "string",
                    "description": (
                        "The run id (UUID) or run name to look up.  "
                        "Resolves by exact id first, then most-recent name match."
                    ),
                },
            },
            "required": ["run_id_or_name"],
        },
    },
    {
        "name": "list_recent_runs",
        "description": (
            "List recent simulation runs in reverse chronological order.  "
            "Returns identifying fields and key summary metrics for each run. "
            "Use this when the user asks what simulations have been run recently."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": (
                        "Maximum number of runs to return (1–50, default 10). "
                        "Values <= 0 are treated as the default (10)."
                    ),
                },
            },
            "required": ["limit"],
        },
    },
    # --- Slice ⑤: trigger tools (appended after slice ④ read-only tools) ---
    {
        "name": "run_home_simulation",
        "description": (
            "Submit a single-home simulation job and return the run id and a "
            "URL to the results page.  Use this when the user asks to run or "
            "start a home simulation with specific PV/battery parameters."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pv_kw": {
                    "type": "number",
                    "description": "PV array capacity in kW (0.5–20).",
                },
                "battery_kwh": {
                    "type": "number",
                    "description": "Battery capacity in kWh (0 = no battery).",
                },
                "consumption_kwh": {
                    "type": "number",
                    "description": "Annual household electricity consumption in kWh.",
                },
                "occupants": {
                    "type": "integer",
                    "description": "Number of household occupants (default 3).",
                },
                "location": {
                    "type": "string",
                    "description": "Location preset, e.g. 'bristol' (default) or 'london'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Simulation duration in days (default 7).",
                },
            },
            "required": ["pv_kw"],
        },
    },
    {
        "name": "run_fleet_simulation",
        "description": (
            "Submit a homogeneous N-home fleet simulation job and return the "
            "run id and a URL to the fleet results page.  Use this when the "
            "user asks to run a fleet or multi-home simulation."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n_homes": {
                    "type": "integer",
                    "description": "Number of homes in the fleet (1–100).",
                },
                "pv_kw": {
                    "type": "number",
                    "description": "PV capacity per home in kW (0.5–20).",
                },
                "battery_kwh": {
                    "type": "number",
                    "description": "Battery capacity per home in kWh (0 = no battery).",
                },
                "location": {
                    "type": "string",
                    "description": "Location preset, e.g. 'bristol' (default) or 'london'.",
                },
                "days": {
                    "type": "integer",
                    "description": "Simulation duration in days (default 7).",
                },
            },
            "required": ["n_homes"],
        },
    },
]


def get_run_results(run_id_or_name: str, db_path: "str | Path") -> dict[str, Any]:
    """Return a simulation run's fields and parsed summary, or a graceful error dict.

    Tries to resolve *run_id_or_name* first as an ``id`` (exact match), then as a
    ``name`` (most-recent row by ``created_at``).  READ-ONLY — no writes to the DB.

    Args:
        run_id_or_name: A run ``id`` or ``name`` string to look up.
        db_path:        Path to the SQLite database file.

    Returns:
        Dict with keys ``run_id``, ``name``, ``type``, ``status``,
        ``created_at``, ``n_homes``, and ``summary`` (parsed dict).
        Returns ``{"error": "<reason>"}`` when not found or on any DB error.
        Never raises.
    """
    from solar_challenge.web.database import get_db

    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            # First attempt: exact id match
            cursor.execute(
                "SELECT id, name, type, status, created_at, n_homes, summary_json "
                "FROM runs WHERE id = ?",
                (run_id_or_name,),
            )
            row = cursor.fetchone()

            # Fallback: most-recent row with matching name
            if row is None:
                cursor.execute(
                    "SELECT id, name, type, status, created_at, n_homes, summary_json "
                    "FROM runs WHERE name = ? ORDER BY created_at DESC LIMIT 1",
                    (run_id_or_name,),
                )
                row = cursor.fetchone()

        if row is None:
            return {"error": f"Run not found: {run_id_or_name!r}"}

        summary_raw: Any = row["summary_json"]
        summary: dict[str, Any] = json.loads(summary_raw) if summary_raw else {}

        return {
            "run_id": row["id"],
            "name": row["name"],
            "type": row["type"],
            "status": row["status"],
            "created_at": row["created_at"],
            "n_homes": row["n_homes"],
            "summary": summary,
        }
    except Exception as exc:
        return {"error": f"Database error fetching run {run_id_or_name!r}: {exc}"}


def list_recent_runs(limit: int, db_path: "str | Path") -> dict[str, Any]:
    """Return a list of recent simulation runs, newest first.

    Read-only SELECT on the runs table; limit is clamped to [1, 50] so callers
    cannot request an unbounded result set.  Returns identifying fields plus key
    summary metrics for each run.

    Args:
        limit:   Maximum number of runs to return (clamped to 1–50; defaults to
                 10 when <= 0).
        db_path: Path to the SQLite database file.

    Returns:
        ``{"runs": [...]}`` where each entry has ``run_id``, ``name``, ``type``,
        ``status``, ``created_at``, ``n_homes``, ``total_generation_kwh``, and
        ``self_consumption_ratio``.  Returns ``{"runs": []}`` on an empty table.
        On any DB error returns ``{"runs": [], "error": "<reason>"}``.
        Never raises.
    """
    from solar_challenge.web.database import get_db

    # Clamp limit to a sane range; treat <= 0 as "use default 10"
    _DEFAULT_LIMIT = 10
    _MAX_LIMIT = 50
    effective_limit = max(1, min(limit if limit > 0 else _DEFAULT_LIMIT, _MAX_LIMIT))

    try:
        with get_db(db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, name, type, status, created_at, n_homes, summary_json "
                "FROM runs ORDER BY created_at DESC LIMIT ?",
                (effective_limit,),
            )
            rows = cursor.fetchall()

        runs: list[dict[str, Any]] = []
        for row in rows:
            summary_raw: Any = row["summary_json"]
            summary: dict[str, Any] = json.loads(summary_raw) if summary_raw else {}

            entry: dict[str, Any] = {
                "run_id": row["id"],
                "name": row["name"],
                "type": row["type"],
                "status": row["status"],
                "created_at": row["created_at"],
                "n_homes": row["n_homes"],
                # Key summary metrics (omit raw summary_json blob)
                "total_generation_kwh": summary.get("total_generation_kwh"),
                "self_consumption_ratio": summary.get("self_consumption_ratio"),
            }
            runs.append(entry)

        return {"runs": runs}

    except Exception as exc:
        return {"runs": [], "error": f"Database error listing recent runs: {exc}"}


def run_home_simulation(
    params: dict[str, Any],
    job_manager: Any,
    db_path: "str | Path",
    data_dir: "str | Path",
) -> dict[str, Any]:
    """Submit a home simulation job via the JobManager and return {run_id, results_url}.

    Parses *params* using the shared ``_parse_home_config`` helper from
    ``solar_challenge.web.api`` (deferred import to avoid circular imports).
    Returns a graceful ``{"error": ...}`` dict when *job_manager* is None or
    when the params fail validation.  Never raises.

    Args:
        params:      Flat parameter dict (pv_kw, battery_kwh, occupants,
                     location, days, name, …) — same shape as the JSON body
                     accepted by POST /api/simulate/home.
        job_manager: A ``JobManager`` instance (or ``None``).
        db_path:     Path to the SQLite database.
        data_dir:    Root directory for storing run artefacts.

    Returns:
        ``{"run_id": str, "results_url": str}`` on success, or
        ``{"error": str}`` on failure.  Never raises.
    """
    if job_manager is None:
        return {"error": "run_home_simulation requires a running JobManager (job_manager is None)"}

    from solar_challenge.web.api import _parse_home_config  # deferred to avoid circularity

    try:
        home_config, start_date, end_date, name = _parse_home_config(params)
    except (ValueError, TypeError) as exc:
        return {"error": f"Invalid simulation parameters: {exc}"}

    try:
        _job_id, run_id = job_manager.submit_home_job(
            config=home_config,
            start_date=start_date,
            end_date=end_date,
            db_path=str(db_path),
            data_dir=str(data_dir),
            name=name,
        )
    except Exception as exc:
        return {"error": f"Failed to submit home simulation job: {exc}"}

    return {"run_id": run_id, "results_url": f"/results/home/{run_id}"}


def run_fleet_simulation(
    params: dict[str, Any],
    job_manager: Any,
    db_path: "str | Path",
    data_dir: "str | Path",
) -> dict[str, Any]:
    """Submit a fleet simulation job via the JobManager and return {run_id, results_url}.

    Builds a homogeneous N-home fleet by parsing the per-home param dict
    (minus ``n_homes``) N times using ``_parse_home_config``.  ``n_homes``
    is clamped to [1, 100] to protect the single-worker JobManager.

    Args:
        params:      Flat parameter dict including ``n_homes`` plus the per-home
                     fields accepted by ``_parse_home_config``
                     (pv_kw, battery_kwh, location, days, …).
        job_manager: A ``JobManager`` instance (or ``None``).
        db_path:     Path to the SQLite database.
        data_dir:    Root directory for storing run artefacts.

    Returns:
        ``{"run_id": str, "results_url": str}`` on success, or
        ``{"error": str}`` on failure.  Never raises.
    """
    if job_manager is None:
        return {"error": "run_fleet_simulation requires a running JobManager (job_manager is None)"}

    from solar_challenge.web.api import _parse_home_config  # deferred

    # Clamp n_homes to [1, 100]
    try:
        n_homes: int = max(1, min(int(params.get("n_homes", 1)), 100))
    except (ValueError, TypeError):
        n_homes = 1

    # Build per-home dict by excluding the fleet-level n_homes key
    per_home: dict[str, Any] = {k: v for k, v in params.items() if k != "n_homes"}

    # Validate once; if it fails, return early without submitting
    try:
        home_config_0, start_date, end_date, name = _parse_home_config(per_home)
    except (ValueError, TypeError) as exc:
        return {"error": f"Invalid simulation parameters: {exc}"}

    # Build the homogeneous configs list (parse N times for correctness/independence)
    configs = [home_config_0]
    for _ in range(n_homes - 1):
        try:
            home_config_i, _, _, _ = _parse_home_config(per_home)
            configs.append(home_config_i)
        except (ValueError, TypeError) as exc:
            return {"error": f"Invalid simulation parameters: {exc}"}

    try:
        _job_id, run_id = job_manager.submit_fleet_job(
            configs=configs,
            start_date=start_date,
            end_date=end_date,
            db_path=str(db_path),
            data_dir=str(data_dir),
            name=name or "Fleet Simulation",
        )
    except Exception as exc:
        return {"error": f"Failed to submit fleet simulation job: {exc}"}

    return {"run_id": run_id, "results_url": f"/results/fleet/{run_id}"}


def _dispatch_tool(
    name: str,
    tool_input: dict[str, Any],
    db_path: "str | Path | None" = None,
    job_manager: Any = None,
    data_dir: "str | Path | None" = None,
) -> dict[str, Any]:
    """Route a tool call to its handler and return the result dict.

    Args:
        name:        The tool name as sent by the model.
        tool_input:  The validated input dict from the model's tool_use block.
        db_path:     Optional path to the SQLite database file.  Required for
                     DB-backed tools (``get_run_results``, ``list_recent_runs``);
                     those tools return a graceful ``{"error": ...}`` when None.
        job_manager: Optional JobManager instance.  Required for trigger tools
                     (``run_home_simulation``, ``run_fleet_simulation``); those
                     tools return a graceful ``{"error": ...}`` when None.
        data_dir:    Optional path to the run data directory.  Required for
                     trigger tools alongside *job_manager*.

    Returns:
        The handler's result dict, or ``{"error": "..."}`` for unknown names.
        Never raises.
    """
    if name == "explain_metric":
        metric: str = str(tool_input.get("metric", ""))
        return explain_metric(metric)
    if name == "suggest_config":
        try:
            annual_kwh: float = float(tool_input.get("annual_consumption_kwh", 0.0))
        except (ValueError, TypeError):
            return {"error": "annual_consumption_kwh must be numeric"}
        goal: str = str(tool_input.get("goal", ""))
        return suggest_config(annual_kwh, goal)
    if name == "get_run_results":
        if db_path is None:
            return {"error": "get_run_results requires a database path (db_path is None)"}
        run_id_or_name: str = str(tool_input.get("run_id_or_name", ""))
        return get_run_results(run_id_or_name, db_path)
    if name == "list_recent_runs":
        if db_path is None:
            return {"error": "list_recent_runs requires a database path (db_path is None)"}
        try:
            limit: int = int(tool_input.get("limit", 10))
        except (ValueError, TypeError):
            limit = 10
        return list_recent_runs(limit, db_path)
    if name == "run_home_simulation":
        _db = str(db_path) if db_path is not None else ""
        _dir = str(data_dir) if data_dir is not None else ""
        return run_home_simulation(dict(tool_input), job_manager, _db, _dir)
    if name == "run_fleet_simulation":
        _db = str(db_path) if db_path is not None else ""
        _dir = str(data_dir) if data_dir is not None else ""
        return run_fleet_simulation(dict(tool_input), job_manager, _db, _dir)
    all_names = ", ".join(t["name"] for t in _TOOLS)
    return {"error": f"Unknown tool '{name}'. Available tools: {all_names}."}


def _session_id() -> str:
    """Return the assistant session id from the Flask session cookie.

    Creates a new uuid4 hex when the key is absent (lazy creation).
    """
    key = "assistant_session_id"
    if key not in session:
        session[key] = uuid4().hex
    return str(session[key])


@bp.route("/", methods=["GET"], strict_slashes=False)
def chat_page() -> str:
    """Render the AI assistant chat shell page."""
    api_key_configured = bool(os.environ.get("ANTHROPIC_API_KEY"))
    return str(render_template("assistant/chat.html", page="assistant",
                               api_key_configured=api_key_configured))


@bp.route("/history", methods=["GET"])
def chat_history() -> ResponseReturnValue:
    """Return the chat history for the current session as JSON.

    Returns:
        JSON ``{"messages": [...]}`` where each message has
        ``role``, ``content``, ``created_at``, and ``metadata`` keys.
    """
    sid = _session_id()
    db_path = current_app.config["DATABASE"]
    messages = database.get_chat_history(db_path, sid)
    return jsonify({"messages": messages})


def _create_client() -> Any:
    """Create and return an Anthropic client (deferred import seam).

    Defers ``import anthropic`` so blueprint registration works even when the
    SDK is not installed.  Callers should wrap this in try/except ImportError
    to handle the absent-SDK case gracefully.

    Returns:
        An ``anthropic.Anthropic`` instance.
    """
    import anthropic  # deferred — do not move to module top level

    return anthropic.Anthropic()


@bp.route("/chat", methods=["POST"])
def chat() -> Response:
    """Stream an AI assistant reply as Server-Sent Events.

    Request JSON body: ``{"message": "<user text>"}``

    SSE frame contract (slice ②):
    - ``event: delta`` / ``data: {"text": "<token>"}`` — streamed token
    - ``event: done``  / ``data: {}``                  — stream complete
    - ``event: error`` / ``data: {"message": "<msg>"}`` — error (no 500)

    Returns:
        ``text/event-stream`` 200 response (even on error).
    """
    data = request.get_json(silent=True) or {}
    user_message: str = str(data.get("message", "")).strip()
    run_id: str = str(data.get("run_id", "")).strip()
    sid = _session_id()
    db_path = current_app.config["DATABASE"]
    data_dir: str = str(current_app.config.get("DATA_DIR", ""))
    job_manager: Any = current_app.extensions.get("job_manager")

    def generate() -> Generator[str, None, None]:
        # Pre-check: API key must be set
        if not os.environ.get("ANTHROPIC_API_KEY"):
            yield (
                "event: error\n"
                'data: {"message": "AI assistant is not configured: set ANTHROPIC_API_KEY."}\n\n'
            )
            return

        # Pre-check: reject empty/whitespace messages before hitting the API
        # or writing a dangling user row (JS guards are insufficient).
        if not user_message:
            yield (
                "event: error\n"
                'data: {"message": "Message cannot be empty."}\n\n'
            )
            return

        # Deferred client construction — catches ImportError / SDK construction errors
        try:
            client = _create_client()
        except Exception as exc:
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': f'Could not initialise Anthropic client: {exc}'})}\n\n"
            )
            return

        # Persist the user turn
        database.save_chat_message(db_path, sid, "user", user_message)

        # Build conversation history for the API.  The just-saved user turn is
        # intentionally included as the final message in the request.
        # Cap to _MAX_HISTORY_TURNS to prevent unbounded context growth.
        all_turns = database.get_chat_history(db_path, sid)
        messages: list[dict[str, Any]] = [
            {"role": row["role"], "content": row["content"]}
            for row in all_turns[-_MAX_HISTORY_TURNS:]
        ]
        # API invariant: the first message must be role=user and roles must
        # strictly alternate.  After the even-width tail-slice, the window can
        # start on an assistant row once the history exceeds _MAX_HISTORY_TURNS.
        # Drop any leading non-user turns to restore the invariant.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

        # Run-context injection (slice ④): when the request carries a run_id,
        # prepend a compact preamble to the final (user) message in-memory ONLY.
        # - NOT written to chat_messages (keeps stored history clean).
        # - NOT placed in the cached system block (preserves prompt-cache stability).
        # - Graceful no-op when run_id is absent/empty or the run is not found.
        if run_id and messages and messages[-1]["role"] == "user":
            run_data = get_run_results(run_id, db_path)
            if "error" not in run_data:
                preamble = (
                    f"[Run context for run_id={run_id!r}, name={run_data.get('name')!r}: "
                    f"{json.dumps(run_data.get('summary', {}), ensure_ascii=False)}]\n\n"
                )
                original_content: str = str(messages[-1]["content"])
                messages[-1] = dict(messages[-1])
                messages[-1]["content"] = preamble + original_content

        # Request params (dict[str, Any] splat to stay mypy --strict compatible
        # with the installed anthropic 0.97.0 stubs that predate output_config /
        # adaptive thinking / claude-opus-4-8)
        model = os.environ.get("SOLAR_ASSISTANT_MODEL") or "claude-opus-4-8"
        system_block: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": SIMULATOR_SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ]
        params: dict[str, Any] = {
            "model": model,
            "thinking": {"type": "adaptive"},
            "output_config": {"effort": "low"},
            "max_tokens": 4096,
            "system": system_block,
            "messages": messages,
            "tools": _TOOLS,
        }

        accumulated = ""
        usage_meta: dict[str, Any] = {}
        invoked_tools: list[str] = []

        try:
            # Manual agentic loop — bounded by _MAX_TOOL_ITERATIONS so a
            # runaway model cannot hang the single Flask worker or the test suite.
            # The manual loop is REQUIRED for per-token SSE streaming WITH tools:
            # the SDK tool_runner returns complete messages, not deltas.
            for _iteration in range(_MAX_TOOL_ITERATIONS):
                with client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                    for text in stream.text_stream:
                        accumulated += text
                        yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"
                    final_msg = stream.get_final_message()
                    usage = getattr(final_msg, "usage", None)
                    if usage is not None:
                        # Accumulate across all loop iterations so the persisted
                        # metadata reflects the full turn's token cost, not just
                        # the final API call.
                        usage_meta["cache_creation_input_tokens"] = (
                            usage_meta.get("cache_creation_input_tokens", 0)
                            + getattr(usage, "cache_creation_input_tokens", 0)
                        )
                        usage_meta["cache_read_input_tokens"] = (
                            usage_meta.get("cache_read_input_tokens", 0)
                            + getattr(usage, "cache_read_input_tokens", 0)
                        )
                        usage_meta["model"] = model

                # Anything other than "tool_use" (incl. None — preserves slice-②
                # behaviour where get_final_message() has no stop_reason attr)
                # terminates the loop.
                stop_reason: Any = getattr(final_msg, "stop_reason", None)
                if stop_reason != "tool_use":
                    break

                # Process each tool_use block emitted by the model.
                content_blocks: Any = getattr(final_msg, "content", [])
                assistant_content: list[dict[str, Any]] = []
                tool_result_content: list[dict[str, Any]] = []

                for block in content_blocks:
                    block_type: Any = getattr(block, "type", None)
                    if block_type == "tool_use":
                        block_id: str = str(getattr(block, "id", ""))
                        block_name: str = str(getattr(block, "name", ""))
                        raw_input: Any = getattr(block, "input", {})
                        block_input: dict[str, Any] = dict(raw_input) if raw_input else {}

                        # Serialize to plain dict — keeps messages list mypy --strict clean.
                        assistant_content.append({
                            "type": "tool_use",
                            "id": block_id,
                            "name": block_name,
                            "input": block_input,
                        })

                        # Emit the `tool` SSE frame (§8 contract).
                        yield (
                            f"event: tool\n"
                            f"data: {json.dumps({'name': block_name})}\n\n"
                        )

                        # Dispatch to the handler and collect the result.
                        tool_result = _dispatch_tool(
                            block_name, block_input, db_path, job_manager, data_dir
                        )
                        invoked_tools.append(block_name)

                        tool_result_content.append({
                            "type": "tool_result",
                            "tool_use_id": block_id,
                            # tool_result content must be a text string.
                            # ensure_ascii=False preserves Unicode characters
                            # (e.g. em-dashes in benchmark band strings).
                            "content": json.dumps(tool_result, ensure_ascii=False),
                        })

                    elif block_type == "text":
                        assistant_content.append({
                            "type": "text",
                            "text": str(getattr(block, "text", "")),
                        })

                # Append the assistant tool_use turn and the user tool_result
                # turn to the in-memory messages for the next iteration.
                cur_messages: list[dict[str, Any]] = list(params["messages"])
                cur_messages.append({"role": "assistant", "content": assistant_content})
                cur_messages.append({"role": "user", "content": tool_result_content})
                params["messages"] = cur_messages
            else:
                # for/else: loop completed without a break, meaning stop_reason was
                # "tool_use" on every iteration — the cap was reached.  Emit a brief
                # notice so the user isn't left with an empty or unexplained response.
                _cap_notice = (
                    "\n[Tool-call limit reached. Please rephrase or simplify your request.]"
                )
                accumulated += _cap_notice
                yield (
                    f"event: delta\n"
                    f"data: {json.dumps({'text': _cap_notice})}\n\n"
                )

        except Exception as exc:
            # Persist whatever was accumulated so history stays consistent with
            # what the user already saw, and role alternation is preserved for
            # future turns (a dangling user-only row causes consecutive
            # user-role messages which the Anthropic API rejects with a 400).
            database.save_chat_message(
                db_path, sid, "assistant", accumulated,
                metadata={"error": str(exc), "truncated": True},
            )
            yield (
                "event: error\n"
                f"data: {json.dumps({'message': f'Streaming error: {exc}'})}\n\n"
            )
            return

        # Persist assistant turn on success; record any invoked tool names.
        final_meta: dict[str, Any] = dict(usage_meta) if usage_meta else {}
        if invoked_tools:
            final_meta["invoked_tools"] = invoked_tools
        database.save_chat_message(
            db_path, sid, "assistant", accumulated, metadata=final_meta or None
        )

        yield "event: done\ndata: {}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
