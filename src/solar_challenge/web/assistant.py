# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI assistant Blueprint for the Solar Challenge web interface.

Serves the chat page (GET /assistant), streams the model's replies as
Server-Sent Events (POST /assistant/chat) and returns the session's stored
conversation (GET /assistant/history).  User and assistant turns persist in
chat_messages through database.py.  While replying, the model can call tools
that explain metrics, suggest system sizes, look up past runs and submit
simulation jobs.

The design is specified in docs/prds/web-ai-assistant.md.

The Anthropic SDK is imported only inside _create_client(); its docstring
gives the reason.
"""

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from types import MappingProxyType
from typing import Any, Generator
from uuid import uuid4

from flask import Blueprint, Response, current_app, jsonify, render_template, session
from flask.helpers import stream_with_context
from flask.typing import ResponseReturnValue

from solar_challenge.web import database
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.shared import NotAJsonObject, get_job_manager, get_storage, request_json_object
from solar_challenge.web.simulation_params import parse_home_config, with_default_days
from solar_challenge.web.storage import RunStorage

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
MAX_HISTORY_TURNS = 20

# Maximum number of tool-use iterations per request; prevents a runaway model
# from looping and streaming forever (hanging the single worker / test suite).
MAX_TOOL_ITERATIONS = 10

# ---------------------------------------------------------------------------
# Grounded metric table — canonical UK benchmark bands
# Keyed by normalized metric id (lowercase, spaces/hyphens → underscores).
# explain_metric answers from this table so the model quotes these benchmark
# numbers instead of hallucinating them.
# ---------------------------------------------------------------------------
METRIC_TABLE: Mapping[str, Mapping[str, str]] = MappingProxyType({
    "self_consumption_ratio": MappingProxyType({
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
    }),
    "self_sufficiency": MappingProxyType({
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
    }),
    "solar_fraction": MappingProxyType({
        "definition": (
            "The proportion of annual energy demand covered by solar PV (generation "
            "used on-site + battery discharge).  Equivalent to self-sufficiency when "
            "battery losses are excluded."
        ),
        "uk_benchmark_band": (
            "20–60 % depending on system size and household demand profile; "
            "higher in summer-heavy usage patterns."
        ),
    }),
    "grid_import": MappingProxyType({
        "definition": (
            "Total electrical energy (kWh) drawn from the public grid over the "
            "simulation period, i.e. demand not met by on-site generation or battery."
        ),
        "uk_benchmark_band": (
            "Ofgem TDCV benchmarks: low 1,900 kWh/yr, medium 2,700 kWh/yr, "
            "high 4,100 kWh/yr (net of solar for a typical 3-4 kWp system)."
        ),
    }),
    "grid_export": MappingProxyType({
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
    }),
    "battery_cycles": MappingProxyType({
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
    }),
    "annual_consumption": MappingProxyType({
        "definition": (
            "Total household electricity consumption (kWh) over a full year, "
            "covering all appliances, heating, and lighting."
        ),
        "uk_benchmark_band": (
            "Ofgem Typical Domestic Consumption Values (TDCVs) 2023: "
            "low 1,900 kWh/yr, medium 2,900 kWh/yr, high 4,200 kWh/yr."
        ),
    }),
    "pv_generation": MappingProxyType({
        "definition": (
            "Total AC electrical energy (kWh) produced by the PV array over the "
            "simulation period, after inverter losses."
        ),
        "uk_benchmark_band": (
            "UK average yield: ~850–950 kWh/kWp/yr (south-facing, 35° tilt, no shading). "
            "Bristol latitude (~51.5°N) typically 900–970 kWh/kWp/yr. "
            "Source: PVGIS TMY data, EC JRC."
        ),
    }),
})


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
        ``METRIC_TABLE``, or a graceful unknown-metric dict if not found.
        Never raises.
    """
    key = _normalize_metric_key(metric)
    if key in METRIC_TABLE:
        return dict(METRIC_TABLE[key])
    return {
        "definition": f"Metric '{metric}' is not recognised in the benchmark table.",
        "uk_benchmark_band": (
            "Unknown metric — no UK benchmark band available. "
            "Please run a simulation to obtain site-specific values."
        ),
    }


# Rule-of-thumb sizing behind suggest_config.  Its returned note quotes these
# figures, so the arithmetic and the note share one source.
_UK_YIELD_KWH_PER_KWP = 950.0
_BATTERY_DAILY_DEMAND_COVERAGE = 0.5
_BATTERY_USABLE_CAPACITY_HEADROOM = 1.2


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
    pv_kwp: float = annual_consumption_kwh / _UK_YIELD_KWH_PER_KWP

    # Battery: cover a share of daily demand (rule-of-thumb shortfall for a typical
    # house without PV self-consumption), with headroom for usable capacity
    daily_kwh = annual_consumption_kwh / 365.0
    battery_kwh: float = (
        daily_kwh * _BATTERY_DAILY_DEMAND_COVERAGE * _BATTERY_USABLE_CAPACITY_HEADROOM
    )

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
            "These figures are indicative estimates from a simple rule of thumb: "
            f"PV kWp ≈ annual consumption in kWh / {_UK_YIELD_KWH_PER_KWP:g}, and "
            f"battery kWh ≈ {_BATTERY_DAILY_DEMAND_COVERAGE * 100:g} % of daily demand "
            f"× {_BATTERY_USABLE_CAPACITY_HEADROOM:g}, "
            "both sized up slightly when the goal is self-sufficiency. "
            "Please run a simulation to confirm sizing for your specific site."
        ),
    }


# The days a trigger tool's simulation spans when the model sends no window.
_TRIGGER_TOOL_DEFAULT_DAYS = 7


# ---------------------------------------------------------------------------
# Tool definitions — fixed order for prompt-cache stability.  The tools render
# ahead of the cached system block, so they belong to the cached prompt prefix;
# any change in their order or content between requests misses the cache.
# TOOLS is a tuple so its order cannot change at runtime.  Its entries stay
# plain dicts: the SDK hands nested schema values to JSON encoding as they
# are, and JSON encoding rejects read-only mappings.
# ---------------------------------------------------------------------------
TOOLS: Sequence[Mapping[str, Any]] = (
    # --- Advisory tools: answered in-process, no database or job access ---
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
    # --- Read-only DB tools: look up past runs in the runs table ---
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
    # --- Trigger tools: submit home and fleet simulation jobs to the JobManager ---
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
                    "description": f"Simulation duration in days (default {_TRIGGER_TOOL_DEFAULT_DAYS}).",
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
                    "description": f"Simulation duration in days (default {_TRIGGER_TOOL_DEFAULT_DAYS}).",
                },
            },
            "required": ["n_homes"],
        },
    },
)


def get_run_results(run_id_or_name: str, storage: RunStorage) -> dict[str, Any]:
    """Return a simulation run's fields and parsed summary, or a graceful error dict.

    Tries to resolve *run_id_or_name* first as an ``id`` (exact match), then as a
    ``name`` (most-recent row by ``created_at``).  READ-ONLY — no writes to the DB.

    Args:
        run_id_or_name: A run ``id`` or ``name`` string to look up.
        storage:        The RunStorage whose runs are looked up.

    Returns:
        Dict with keys ``run_id``, ``name``, ``type``, ``status``,
        ``created_at``, ``n_homes``, and ``summary`` (parsed dict).
        Returns ``{"error": "<reason>"}`` when not found or on any DB error.
        Never raises.
    """
    try:
        run = storage.run_record(run_id_or_name) or storage.latest_run_named(run_id_or_name)
        if run is None:
            return {"error": f"Run not found: {run_id_or_name!r}"}

        summary: dict[str, Any] = json.loads(run.summary_json) if run.summary_json else {}

        return {
            "run_id": run.id,
            "name": run.name,
            "type": run.type,
            "status": run.status,
            "created_at": run.created_at,
            "n_homes": run.n_homes,
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
    # Clamp limit to a sane range; treat <= 0 as "use default 10"
    _DEFAULT_LIMIT = 10
    _MAX_LIMIT = 50
    effective_limit = max(1, min(limit if limit > 0 else _DEFAULT_LIMIT, _MAX_LIMIT))

    try:
        with database.get_db(db_path) as conn:
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
    job_manager: JobManager,
    db_path: "str | Path",
    data_dir: "str | Path",
) -> dict[str, Any]:
    """Submit a home simulation job via the JobManager and return {run_id, results_url}.

    Parses *params* with ``parse_home_config`` from
    ``solar_challenge.web.simulation_params``.
    Returns a graceful ``{"error": ...}`` dict when the params fail validation
    or the job submission fails.  Never raises.

    Args:
        params:      Flat parameter dict (pv_kw, battery_kwh, occupants,
                     location, days, name, …) — same shape as the JSON body
                     accepted by POST /api/simulate/home.  Params that send no
                     window run _TRIGGER_TOOL_DEFAULT_DAYS days; an off-schema
                     start/end is read as that endpoint reads it.
        job_manager: The app's JobManager.
        db_path:     Path to the SQLite database.
        data_dir:    Root directory for storing run artefacts.

    Returns:
        ``{"run_id": str, "results_url": str}`` on success, or
        ``{"error": str}`` on failure.  Never raises.
    """
    try:
        home_config, start_date, end_date, name = parse_home_config(
            with_default_days(params, _TRIGGER_TOOL_DEFAULT_DAYS)
        )
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
    job_manager: JobManager,
    db_path: "str | Path",
    data_dir: "str | Path",
) -> dict[str, Any]:
    """Submit a fleet simulation job via the JobManager and return {run_id, results_url}.

    Builds a homogeneous N-home fleet by parsing the per-home param dict
    (minus ``n_homes``) once with ``parse_home_config`` and repeating the
    resulting frozen ``HomeConfig`` ``n_homes`` times.  ``n_homes``
    is clamped to [1, 100] to protect the single-worker JobManager.

    Args:
        params:      Flat parameter dict including ``n_homes`` plus the per-home
                     fields accepted by ``parse_home_config``
                     (pv_kw, battery_kwh, location, days, …).
        job_manager: The app's JobManager.
        db_path:     Path to the SQLite database.
        data_dir:    Root directory for storing run artefacts.

    Returns:
        ``{"run_id": str, "results_url": str}`` on success, or
        ``{"error": str}`` on failure.  Never raises.
    """
    # Clamp n_homes to [1, 100]
    try:
        n_homes: int = max(1, min(int(params.get("n_homes", 1)), 100))
    except (ValueError, TypeError):
        n_homes = 1

    # Build per-home dict by excluding the fleet-level n_homes key
    per_home: dict[str, Any] = {k: v for k, v in params.items() if k != "n_homes"}

    # Validate once; if it fails, return early without submitting
    try:
        home_config_0, start_date, end_date, name = parse_home_config(
            with_default_days(per_home, _TRIGGER_TOOL_DEFAULT_DAYS)
        )
    except (ValueError, TypeError) as exc:
        return {"error": f"Invalid simulation parameters: {exc}"}

    # The fleet is homogeneous by design (PRD §4, "Fleet trigger scope"): every
    # home gets the same parameters; fleets that vary per home come from
    # distribution configs, which this tool does not take.  HomeConfig is a frozen
    # dataclass, so all N entries can share one immutable object — re-parsing N
    # times would add no diversity and only waste CPU.
    configs: list[Any] = [home_config_0] * n_homes

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


def dispatch_tool(
    name: str,
    tool_input: dict[str, Any],
    *,
    db_path: "str | Path",
    job_manager: JobManager,
    data_dir: "str | Path",
) -> dict[str, Any]:
    """Route a tool call to its handler and return the result dict.

    Args:
        name:        The tool name as sent by the model.
        tool_input:  The validated input dict from the model's tool_use block.
        db_path:     The SQLite database that the DB-backed tools read and that
                     submitted jobs record their runs in.
        job_manager: The app's JobManager, which the trigger tools submit jobs to.
        data_dir:    The root directory for submitted runs' artefacts.

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
        run_id_or_name: str = str(tool_input.get("run_id_or_name", ""))
        return get_run_results(run_id_or_name, RunStorage(db_path=db_path, data_dir=data_dir))
    if name == "list_recent_runs":
        try:
            limit: int = int(tool_input.get("limit", 10))
        except (ValueError, TypeError):
            limit = 10
        return list_recent_runs(limit, db_path)
    if name == "run_home_simulation":
        return run_home_simulation(dict(tool_input), job_manager, db_path, data_dir)
    if name == "run_fleet_simulation":
        return run_fleet_simulation(dict(tool_input), job_manager, db_path, data_dir)
    all_names = ", ".join(t["name"] for t in TOOLS)
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
    """Create and return an Anthropic client.

    Imports the SDK here rather than at module top level because it is slow to
    import and only answering a chat needs it: building the app and serving the
    chat page never import it, as
    tests/unit/test_web_app.py::test_building_the_app_does_not_import_the_anthropic_sdk
    pins.

    Returns:
        An ``anthropic.Anthropic`` instance.
    """
    import anthropic  # deferred — do not move to module top level

    return anthropic.Anthropic()


def _add_cache_usage(totals: Mapping[str, int], usage: Any) -> dict[str, int]:
    """Return the running cache-token sums *totals* with one API call's *usage* added.

    The SDK types both counts ``Optional[int]``; a count it reports as None adds 0.
    """
    return {
        field: totals.get(field, 0) + (getattr(usage, field, None) or 0)
        for field in ("cache_creation_input_tokens", "cache_read_input_tokens")
    }


def _error_frame(message: str) -> str:
    """Return the SSE ``error`` frame carrying *message*."""
    return f"event: error\ndata: {json.dumps({'message': message})}\n\n"


def _event_stream(frames: Iterable[str]) -> Response:
    """Return the 200 ``text/event-stream`` response sending *frames*, uncached and unbuffered by proxies."""
    return Response(
        frames,
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@bp.route("/chat", methods=["POST"])
def chat() -> Response:
    """Stream an AI assistant reply as Server-Sent Events.

    Request JSON body: ``{"message": "<user text>", "run_id": "<optional>"}``.
    A body that is not a JSON object is answered with a lone ``error`` frame.
    A ``run_id`` puts that run's summary in front of the message as context.

    SSE frame contract:
    - ``event: delta`` / ``data: {"text": "<token>"}``  — streamed token
    - ``event: tool``  / ``data: {"name": "<tool>"}``   — the model called a tool
    - ``event: done``  / ``data: {}``                   — stream complete
    - ``event: error`` / ``data: {"message": "<msg>"}`` — error (no 500)

    Returns:
        ``text/event-stream`` 200 response (even on error).
    """
    try:
        data = request_json_object()
    except NotAJsonObject as refusal:
        return _event_stream([_error_frame(str(refusal))])
    user_message: str = str(data.get("message", "")).strip()
    run_id: str = str(data.get("run_id", "")).strip()
    sid = _session_id()
    db_path = current_app.config["DATABASE"]
    data_dir = current_app.config["DATA_DIR"]
    job_manager = get_job_manager()
    storage = get_storage()

    def generate() -> Generator[str, None, None]:
        # Pre-check: API key must be set
        if not os.environ.get("ANTHROPIC_API_KEY"):
            yield _error_frame("AI assistant is not configured: set ANTHROPIC_API_KEY.")
            return

        # Pre-check: reject empty/whitespace messages before hitting the API
        # or writing a dangling user row (JS guards are insufficient).
        if not user_message:
            yield _error_frame("Message cannot be empty.")
            return

        # Constructing a client fails on a misconfigured environment, such as a
        # malformed ANTHROPIC_BASE_URL.
        try:
            client = _create_client()
        except Exception as exc:
            yield _error_frame(f"Could not initialise Anthropic client: {exc}")
            return

        # Persist the user turn
        database.save_chat_message(db_path, sid, "user", user_message)

        # Build conversation history for the API.  The just-saved user turn is
        # intentionally included as the final message in the request.
        # Cap to MAX_HISTORY_TURNS to prevent unbounded context growth.
        all_turns = database.get_chat_history(db_path, sid)
        messages: list[dict[str, Any]] = [
            {"role": row["role"], "content": row["content"]}
            for row in all_turns[-MAX_HISTORY_TURNS:]
        ]
        # API invariant: the first message must be role=user and roles must
        # strictly alternate.  After the even-width tail-slice, the window can
        # start on an assistant row once the history exceeds MAX_HISTORY_TURNS.
        # Drop any leading non-user turns to restore the invariant.
        while messages and messages[0]["role"] != "user":
            messages.pop(0)

        # Run-context injection: when the request carries a run_id,
        # prepend a compact preamble to the final (user) message in-memory ONLY.
        # - NOT written to chat_messages (keeps stored history clean).
        # - NOT placed in the cached system block (preserves prompt-cache stability).
        # - Graceful no-op when run_id is absent/empty or the run is not found.
        if run_id and messages and messages[-1]["role"] == "user":
            run_data = get_run_results(run_id, storage)
            if "error" not in run_data:
                preamble = (
                    f"[Run context for run_id={run_id!r}, name={run_data.get('name')!r}: "
                    f"{json.dumps(run_data.get('summary', {}), ensure_ascii=False)}]\n\n"
                )
                original_content: str = str(messages[-1]["content"])
                messages[-1] = dict(messages[-1])
                messages[-1]["content"] = preamble + original_content

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
            "tools": TOOLS,
        }

        accumulated = ""
        cache_usage: dict[str, int] = {}
        invoked_tools: list[str] = []

        try:
            # Manual agentic loop — bounded by MAX_TOOL_ITERATIONS so a
            # runaway model cannot hang the single Flask worker or the test suite.
            # The manual loop is REQUIRED for per-token SSE streaming WITH tools:
            # the SDK tool_runner returns complete messages, not deltas.
            for _iteration in range(MAX_TOOL_ITERATIONS):
                with client.messages.stream(**params) as stream:
                    for text in stream.text_stream:
                        accumulated += text
                        yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"
                    final_msg = stream.get_final_message()
                    usage = getattr(final_msg, "usage", None)
                    if usage is not None:
                        # Accumulate across all loop iterations so the persisted
                        # metadata reflects the full turn's token cost, not just
                        # the final API call.
                        cache_usage = _add_cache_usage(cache_usage, usage)

                # Only "tool_use" means the model is waiting for tool results.
                # Any other stop_reason ends the loop — including None, which
                # getattr returns when the final message has no stop_reason.
                stop_reason: Any = getattr(final_msg, "stop_reason", None)
                if stop_reason != "tool_use":
                    break

                # Process each tool_use block emitted by the model.
                content_blocks: Any = getattr(final_msg, "content", [])
                tool_calls = [
                    block for block in content_blocks
                    if getattr(block, "type", None) == "tool_use"
                ]
                tool_result_content: list[dict[str, Any]] = []

                for block in tool_calls:
                    block_id: str = str(getattr(block, "id", ""))
                    block_name: str = str(getattr(block, "name", ""))
                    raw_input: Any = getattr(block, "input", {})
                    block_input: dict[str, Any] = dict(raw_input) if raw_input else {}

                    # Emit the `tool` SSE frame (§8 contract).
                    yield (
                        f"event: tool\n"
                        f"data: {json.dumps({'name': block_name})}\n\n"
                    )

                    # Dispatch to the handler and collect the result.
                    tool_result = dispatch_tool(
                        block_name,
                        block_input,
                        db_path=db_path,
                        job_manager=job_manager,
                        data_dir=data_dir,
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

                # Replay the turn exactly as the model sent it: with thinking on,
                # the API needs its thinking blocks back unchanged.
                cur_messages: list[dict[str, Any]] = list(params["messages"])
                cur_messages.append({"role": "assistant", "content": list(content_blocks)})
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
            yield _error_frame(f"Streaming error: {exc}")
            return

        # Persist assistant turn on success; record any invoked tool names.
        final_meta: dict[str, Any] = {**cache_usage, "model": model} if cache_usage else {}
        if invoked_tools:
            final_meta["invoked_tools"] = invoked_tools
        database.save_chat_message(
            db_path, sid, "assistant", accumulated, metadata=final_meta or None
        )

        yield "event: done\ndata: {}\n\n"

    return _event_stream(stream_with_context(generate()))
