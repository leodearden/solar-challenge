# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI assistant Blueprint for the Solar Challenge web interface.

Serves the chat page (GET /assistant), streams the model's replies as
Server-Sent Events (POST /assistant/chat) and returns the session's stored
conversation (GET /assistant/history).  User and assistant turns persist in
the chat_messages table through its store, chat_messages.py.  While replying,
the model can call tools that explain metrics, suggest system sizes, look up
past runs and submit simulation jobs.

The design is specified in docs/prds/web-ai-assistant.md.

The Anthropic SDK is imported only inside _create_client(); its docstring
gives the reason.
"""

import json
import os
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import closing
from dataclasses import asdict, dataclass, field, replace
from functools import partial
from types import MappingProxyType
from typing import Any, Generator, assert_never
from uuid import uuid4

from flask import Blueprint, Response, current_app, jsonify, render_template, request, session
from flask.typing import ResponseReturnValue

from solar_challenge.load import OFGEM_TDCV_BY_OCCUPANTS, LoadConfig
from solar_challenge.number_fields import Interval, as_finite_float, as_whole_number
from solar_challenge.validation import (
    BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP,
    UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT,
    UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT,
    UK_YIELD_BENCHMARK_KWH_PER_KWP,
)
from solar_challenge.web.chat_messages import get_chat_history, save_chat_message
from solar_challenge.web.database import Database
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.request_boundary import NotAJsonObject, request_json_object
from solar_challenge.web.shared import get_database, get_job_manager, get_storage
from solar_challenge.web.simulation_params import (
    DAYS_WINDOW_START,
    FULL_YEAR_DAYS_SENTINEL,
    FULL_YEAR_END,
    FULL_YEAR_START,
    MAX_DAYS,
    MAX_WINDOW_DAYS,
    parse_home_config,
    with_default_days,
)
from solar_challenge.web.sse import (
    CHAT_DELTA,
    CHAT_DONE,
    CHAT_FAILED,
    CHAT_TOOL,
    ChatDelta,
    ChatDone,
    ChatFailed,
    ChatToolCall,
    event_stream,
    sse_frame,
)
from solar_challenge.web.storage import RunQuery, RunRecord, RunStorage, headline_figures

bp = Blueprint("assistant", __name__)

# ---------------------------------------------------------------------------
# The engine's facts — formatted once, at import, from its constants, so the
# cached prompt prefix stays byte-stable between requests
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _Unit:
    """A unit the assistant states the engine's figures in: its *symbol*, and the format *spec* of its numbers."""

    symbol: str
    spec: str

    def value(self, number: float) -> str:
        """*number* in this unit, e.g. ``1,800 kWh``."""
        return f"{number:{self.spec}} {self.symbol}"

    def band(self, ends: tuple[float, float]) -> str:
        """The band from *ends*' low to its high in this unit, e.g. ``10–45 %``."""
        low, high = ends
        return f"{low:{self.spec}}–{high:{self.spec}} {self.symbol}"


_KWH = _Unit("kWh", ",g")
_PERCENT = _Unit("%", "g")
_KWH_PER_KWP = _Unit("kWh/kWp", "g")


def _occupants(count: int) -> str:
    """*count* occupants, e.g. ``1 occupant`` or ``3 occupants``."""
    return f"{count} occupant" if count == 1 else f"{count} occupants"


_DEFAULT_CONSUMPTION_BY_HOUSEHOLD_SIZE = (
    "The simulator's default annual consumption by household size, excluding electric heating: "
    + ", ".join(
        f"{_occupants(count)} {_KWH.value(kwh)}" for count, kwh in sorted(OFGEM_TDCV_BY_OCCUPANTS.items())
    )
)


_DEFAULT_HOUSEHOLD_CONSUMPTION = (
    f"{_KWH.value(LoadConfig().get_annual_consumption())}, which the simulator assumes "
    f"for its default household of {_occupants(LoadConfig().household_occupants)}"
)


# ---------------------------------------------------------------------------
# System prompt — cached at module level for prompt-cache efficiency
# ---------------------------------------------------------------------------
SIMULATOR_SYSTEM_PROMPT = f"""You are the AI assistant for the Solar Challenge web dashboard.
You help users understand and analyse their domestic solar PV and battery simulation results
for the Bristol community energy project.

You have expert knowledge of:
- Solar PV generation (pvlib/PVGIS TMY data, 1-minute resolution simulation)
- Battery storage systems (state of charge, charging/discharging power limits, round-trip efficiency)
- Household energy consumption profiles (UK CREST model)
- Energy flow dispatch: self-consumption priority → battery charge → grid export
- Grid import/export and time-of-use (TOU) tariffs
- Fleet-level aggregation across 100-home Bristol scenarios

When discussing simulation parameters use these reference figures:
- {_DEFAULT_CONSUMPTION_BY_HOUSEHOLD_SIZE}
- Small PV system: 2–3 kWp; medium: 3–5 kWp; large: 5–8 kWp
- Battery capacity: 5–15 kWh residential; discharge rate: 0.5–1C typical

Be concise and precise. If the user asks about specific simulation results, explain what
the numbers mean in practical terms (bill savings, self-sufficiency rates, etc.).
""".strip()

# Maximum number of prior turns to replay to the model on each request;
# prevents unbounded context growth and eventual context-window exhaustion.
MAX_HISTORY_TURNS = 20

# The most rounds of tool calls one reply runs. The model's next call is sent
# each round's results, so a reply calls the model at most MAX_TOOL_ITERATIONS + 1
# times. The bound prevents a runaway model from looping and streaming forever
# (hanging the single worker / test suite).
MAX_TOOL_ITERATIONS = 10

# The text that ends a reply whose model still calls tools after MAX_TOOL_ITERATIONS
# rounds; those calls do not run.
TOOL_CALL_LIMIT_NOTICE = "\n[Tool-call limit reached. Please rephrase or simplify your request.]"

# ---------------------------------------------------------------------------
# Grounded metric table — the benchmark bands explain_metric quotes
# Keyed by normalized metric id (lowercase, spaces/hyphens → underscores).
# explain_metric answers from this table so the model quotes these benchmark
# numbers instead of hallucinating them.  The self_consumption_ratio,
# grid_import, annual_consumption and pv_generation bands are formatted at
# import from load's and validation's constants, which name their sources;
# the other bands carry their external citation.
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
            "The UK benchmark the simulator's validation applies: "
            f"{_PERCENT.band(UK_PV_ONLY_SELF_CONSUMPTION_BENCHMARK_PERCENT)} without storage, "
            f"{_PERCENT.band(UK_BATTERY_SELF_CONSUMPTION_BENCHMARK_PERCENT)} with a battery."
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
            "No fixed benchmark: grid import is the demand that PV and battery do not cover, "
            "so unless the battery charges from the grid it is at most the home's annual demand. "
            f"{_DEFAULT_CONSUMPTION_BY_HOUSEHOLD_SIZE}."
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
        "uk_benchmark_band": f"{_DEFAULT_CONSUMPTION_BY_HOUSEHOLD_SIZE}.",
    }),
    "pv_generation": MappingProxyType({
        "definition": (
            "Total AC electrical energy (kWh) produced by the PV array over the "
            "simulation period, after inverter losses."
        ),
        "uk_benchmark_band": (
            f"The simulator accepts {_KWH_PER_KWP.band(UK_YIELD_BENCHMARK_KWH_PER_KWP)} a year "
            "as plausible for an unshaded UK array. Its default PV system yields "
            f"{_KWH_PER_KWP.value(BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP)} a year in Bristol."
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


# The battery half of the rule of thumb behind suggest_config.  Its returned
# note quotes these figures, so the arithmetic and the note share one source.
_BATTERY_DAILY_DEMAND_COVERAGE = 0.5
_BATTERY_USABLE_CAPACITY_HEADROOM = 1.2

# suggest_config's note, formatted once, at import, from the figures it sizes with.
_SIZING_NOTE = (
    "These figures are indicative estimates from a simple rule of thumb: "
    f"PV kWp ≈ annual consumption in kWh / {_KWH_PER_KWP.value(BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP)}, "
    "the yearly yield of the simulator's default PV system in Bristol, and "
    f"battery kWh ≈ {_PERCENT.value(_BATTERY_DAILY_DEMAND_COVERAGE * 100)} of daily demand "
    f"× {_BATTERY_USABLE_CAPACITY_HEADROOM:g}, "
    "both sized up slightly when the goal is self-sufficiency. "
    "Please run a simulation to confirm sizing for your specific site."
)


def suggest_config(
    annual_consumption_kwh: float,
    goal: str,
) -> dict[str, Any]:
    """Return rule-of-thumb PV and battery sizing for a household.

    Uses the heuristics of docs/prds/web-ai-assistant.md §11, open question 4:
    - PV kWp ≈ annual_consumption_kwh / BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP  (the yearly yield of the simulator's default PV system in Bristol)
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
    # Base heuristics
    pv_kwp: float = annual_consumption_kwh / BRISTOL_DEFAULT_SYSTEM_YIELD_KWH_PER_KWP

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
        "note": _SIZING_NOTE,
    }


# The days a trigger tool's simulation spans when the model sends no window.
_TRIGGER_TOOL_DEFAULT_DAYS = 7

# The most homes run_fleet_simulation submits: a larger n_homes is clamped to it, to protect the single-worker JobManager.
_FLEET_TOOL_MAX_HOMES = 100

# The runs list_recent_runs returns when the model sends no positive limit, and the most it returns for any limit.
_LIST_RUNS_DEFAULT_LIMIT = 10
_LIST_RUNS_MAX_LIMIT = 50

# The window both trigger tools take, days or a start and end, as parse_date_range reads it.
_TRIGGER_TOOL_WINDOW_PROPERTIES: Mapping[str, Mapping[str, str]] = {
    "days": {
        "type": "integer",
        "description": (
            f"Simulation duration in days (1–{MAX_DAYS}), counted from {DAYS_WINDOW_START} "
            f"and running on past {FULL_YEAR_END} when longer than the rest of that year, "
            f"except that {FULL_YEAR_DAYS_SENTINEL} runs the whole year {FULL_YEAR_START} to "
            f"{FULL_YEAR_END}. Must not be sent with start or end; with none of the three "
            f"sent, the run spans {_TRIGGER_TOOL_DEFAULT_DAYS} days."
        ),
    },
    "start": {
        "type": "string",
        "format": "date",
        "description": (
            f"First simulated day, an ISO 8601 date (YYYY-MM-DD); {FULL_YEAR_START} when only "
            "end is sent. Must not be sent with days."
        ),
    },
    "end": {
        "type": "string",
        "format": "date",
        "description": (
            f"Last simulated day, inclusive, an ISO 8601 date (YYYY-MM-DD); {FULL_YEAR_END} "
            "when only start is sent. Must not be sent with days. The window from start to "
            f"end spans at most {MAX_WINDOW_DAYS} days."
        ),
    },
}


def get_run_results(run_id_or_name: str, storage: RunStorage) -> dict[str, Any]:
    """Return a simulation run's fields and parsed summary, or a graceful error dict.

    Tries to resolve *run_id_or_name* first as an ``id`` (exact match), then as a
    ``name`` (most-recent row by ``created_at``).  READ-ONLY — no writes to the DB.

    Args:
        run_id_or_name: A run ``id`` or ``name`` string to look up.
        storage:        The RunStorage whose runs are looked up.

    Returns:
        Dict with keys ``run_id``, ``name``, ``type``, ``status``,
        ``created_at``, ``n_homes``, and ``summary``, the field tree of the
        run's summary, {} while it has none. Returns ``{"error": "<reason>"}``
        when not found, on any DB error, or when the run's summary does not
        decode, the reason then RunRecord.summary's refusal naming the run and
        runs.summary_json. Never raises.
    """
    try:
        run = storage.run_record(run_id_or_name) or storage.latest_run_named(run_id_or_name)
    except Exception as exc:
        return {"error": f"Database error fetching run {run_id_or_name!r}: {exc}"}
    if run is None:
        return {"error": f"Run not found: {run_id_or_name!r}"}
    try:
        summary = run.summary()
    except ValueError as unreadable:
        return {"error": str(unreadable)}
    return {
        "run_id": run.id,
        "name": run.name,
        "type": run.type,
        "status": run.status,
        "created_at": run.created_at,
        "n_homes": run.n_homes,
        "summary": {} if summary is None else asdict(summary),
    }


def list_recent_runs(limit: int, storage: RunStorage) -> dict[str, Any]:
    """Return a list of recent simulation runs, newest first.

    Reads the first page of *storage*'s run list; a limit above _LIST_RUNS_MAX_LIMIT
    is clamped to it, so callers cannot request an unbounded result set.  Returns
    identifying fields plus each run's headline figures.

    Args:
        limit:   Maximum number of runs to return (at most
                 _LIST_RUNS_MAX_LIMIT; _LIST_RUNS_DEFAULT_LIMIT when <= 0).
        storage: The RunStorage whose runs are listed.

    Returns:
        ``{"runs": [...]}``, _recent_run_entry's entry for each run.  Returns
        ``{"runs": []}`` when there are no runs.  On any DB error returns
        ``{"runs": [], "error": "<reason>"}``.  Never raises.
    """
    effective_limit = min(limit if limit > 0 else _LIST_RUNS_DEFAULT_LIMIT, _LIST_RUNS_MAX_LIMIT)

    try:
        records = storage.page_runs(RunQuery(per_page=effective_limit)).records
    except Exception as exc:
        return {"runs": [], "error": f"Database error listing recent runs: {exc}"}
    return {"runs": [_recent_run_entry(record) for record in records]}


def _recent_run_entry(record: RunRecord) -> dict[str, Any]:
    """list_recent_runs' entry for *record*'s run: its identifying fields and its headline_figures."""
    return {
        "run_id": record.id,
        "name": record.name,
        "type": record.type,
        "status": record.status,
        "created_at": record.created_at,
        "n_homes": record.n_homes,
        **headline_figures(record),
    }


def run_home_simulation(
    params: Mapping[str, Any], job_manager: JobManager, results_url: Callable[[str], str]
) -> dict[str, Any]:
    """Submit a home simulation job via the JobManager and return {run_id, results_url}.

    Parses *params* with ``parse_home_config`` from
    ``solar_challenge.web.simulation_params``.
    Returns a graceful ``{"error": ...}`` dict when the params fail validation
    or the job submission fails.  Never raises.

    Args:
        params:      Flat parameters (pv_kw, battery_kwh, occupants,
                     location, days or start/end, name, …) — same shape as
                     the JSON body accepted by POST /api/simulate/home, and
                     its window is read as that endpoint reads it.  Params
                     that send no window run _TRIGGER_TOOL_DEFAULT_DAYS days.
        job_manager: The app's JobManager, which records the job's run in
                     the app's RunStorage.
        results_url: Builds the path of a run's results page from its run id.

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
            name=name,
        )
    except Exception as exc:
        return {"error": f"Failed to submit home simulation job: {exc}"}

    return {"run_id": run_id, "results_url": results_url(run_id)}


def run_fleet_simulation(
    n_homes: int, params: Mapping[str, Any], job_manager: JobManager, results_url: Callable[[str], str]
) -> dict[str, Any]:
    """Submit a fleet simulation job via the JobManager and return {run_id, results_url}.

    Builds a homogeneous fleet by parsing the per-home *params* once with
    ``parse_home_config`` and repeating the resulting frozen ``HomeConfig``
    for each home.  *n_homes* is clamped to [1, _FLEET_TOOL_MAX_HOMES] to
    protect the single-worker JobManager.

    Args:
        n_homes:     The number of homes in the fleet, before the clamp.
        params:      The per-home fields accepted by ``parse_home_config``
                     (pv_kw, battery_kwh, location, days or start/end, …),
                     without ``n_homes``.  Params that send no window run
                     _TRIGGER_TOOL_DEFAULT_DAYS days.
        job_manager: The app's JobManager, which records the job's run in
                     the app's RunStorage.
        results_url: Builds the path of a run's results page from its run id.

    Returns:
        ``{"run_id": str, "results_url": str}`` on success, or
        ``{"error": str}`` on failure.  Never raises.
    """
    fleet_size = max(1, min(n_homes, _FLEET_TOOL_MAX_HOMES))

    # Validate once; if it fails, return early without submitting
    try:
        home_config_0, start_date, end_date, name = parse_home_config(
            with_default_days(params, _TRIGGER_TOOL_DEFAULT_DAYS)
        )
    except (ValueError, TypeError) as exc:
        return {"error": f"Invalid simulation parameters: {exc}"}

    # The fleet is homogeneous by design (docs/prds/web-ai-assistant.md §4,
    # "Fleet trigger scope"): every home gets the same parameters; fleets that
    # vary per home come from distribution configs, which this tool does not
    # take.  HomeConfig is a frozen dataclass, so all N entries can share one
    # immutable object — re-parsing N times would add no diversity and only
    # waste CPU.
    configs: list[Any] = [home_config_0] * fleet_size

    try:
        _job_id, run_id = job_manager.submit_fleet_job(
            configs=configs,
            start_date=start_date,
            end_date=end_date,
            name=name,
        )
    except Exception as exc:
        return {"error": f"Failed to submit fleet simulation job: {exc}"}

    return {"run_id": run_id, "results_url": results_url(run_id)}


@dataclass(frozen=True)
class ToolContext:
    """The collaborators a tool call runs with.

    *storage* is the app's RunStorage, whose runs the lookup tools read.
    *job_manager* is the app's JobManager, which the trigger tools submit jobs
    to and which records their runs in the app's RunStorage.
    *results_url* builds the path of a run's results page from its run id,
    the link the trigger tools return for the run they start.
    """

    storage: RunStorage
    job_manager: JobManager
    results_url: Callable[[str], str]


def _as_text(value: Any, field: str) -> str:
    """Return *value*, a text field as the model sent it, refusing one that is not a string.

    Raises:
        ValueError: If *value* is not a str; the error names *field* and the value sent.
    """
    if not isinstance(value, str):
        raise ValueError(f"{field} must be a string, got {value!r}")
    return value


@dataclass(frozen=True)
class _Tool:
    """A tool the model can call: the *schema* the model reads, and the *run* that answers a call."""

    schema: Mapping[str, Any]
    run: Callable[[Mapping[str, Any], ToolContext], dict[str, Any]]

    @property
    def name(self) -> str:
        """The name the model calls this tool by."""
        return str(self.schema["name"])

    def answer(self, tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
        """Return the result of the call that sent *tool_input*, run in *context*.

        Raises:
            ValueError: When *tool_input* does not send a field the schema requires,
                naming each one it does not send, or when the run refuses a value
                *tool_input* sends.
        """
        required = self.schema["input_schema"].get("required", ())
        unsent = [field_name for field_name in required if field_name not in tool_input]
        if unsent:
            raise ValueError("; ".join(f"{field_name} is required" for field_name in unsent))
        return self.run(tool_input, context)


def _call_explain_metric(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer an explain_metric call: explain the metric *tool_input* names."""
    return explain_metric(_as_text(tool_input["metric"], "metric"))


def _call_suggest_config(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer a suggest_config call: size a system for the consumption and goal *tool_input* sends."""
    annual_kwh = as_finite_float(
        tool_input["annual_consumption_kwh"],
        "annual_consumption_kwh",
        within=Interval(*FLEET_COMPONENTS["load"].fixed_range),
    )
    return suggest_config(annual_kwh, _as_text(tool_input["goal"], "goal"))


def _call_get_run_results(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer a get_run_results call: look up the run *tool_input* names among *context*'s runs."""
    return get_run_results(
        _as_text(tool_input["run_id_or_name"], "run_id_or_name"),
        context.storage,
    )


def _call_list_recent_runs(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer a list_recent_runs call: list *context*'s latest runs, up to the limit *tool_input* sends."""
    return list_recent_runs(as_whole_number(tool_input["limit"], "limit"), context.storage)


def _call_run_home_simulation(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer a run_home_simulation call: submit the home *tool_input* describes to *context*'s JobManager."""
    return run_home_simulation(tool_input, context.job_manager, context.results_url)


def _call_run_fleet_simulation(tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer a run_fleet_simulation call: submit the fleet *tool_input* describes to *context*'s JobManager."""
    per_home = {key: value for key, value in tool_input.items() if key != "n_homes"}
    return run_fleet_simulation(
        as_whole_number(tool_input["n_homes"], "n_homes"),
        per_home,
        context.job_manager,
        context.results_url,
    )


# ---------------------------------------------------------------------------
# Tool table — one record per tool, in a fixed order for prompt-cache
# stability.  The tools render ahead of the cached system block, so they
# belong to the cached prompt prefix; any change in their order or content
# between requests misses the cache.
# ---------------------------------------------------------------------------
_TOOL_TABLE: tuple[_Tool, ...] = (
    # --- Advisory tools: answered in-process, no database or job access ---
    _Tool(
        schema={
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
        run=_call_explain_metric,
    ),
    _Tool(
        schema={
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
                            "({:g}–{:g}; ".format(*FLEET_COMPONENTS["load"].fixed_range)
                            + f"e.g. {_DEFAULT_HOUSEHOLD_CONSUMPTION})."
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
        run=_call_suggest_config,
    ),
    # --- Read-only DB tools: look up past runs in the runs table ---
    _Tool(
        schema={
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
        run=_call_get_run_results,
    ),
    _Tool(
        schema={
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
                            f"Maximum number of runs to return (1–{_LIST_RUNS_MAX_LIMIT}, "
                            f"default {_LIST_RUNS_DEFAULT_LIMIT}). "
                            "Values <= 0 are treated as the default "
                            f"({_LIST_RUNS_DEFAULT_LIMIT})."
                        ),
                    },
                },
                "required": ["limit"],
            },
        },
        run=_call_list_recent_runs,
    ),
    # --- Trigger tools: submit home and fleet simulation jobs to the JobManager ---
    _Tool(
        schema={
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
                        "description": "Annual household electricity consumption in kWh ({:g}–{:g}).".format(
                            *FLEET_COMPONENTS["load"].fixed_range
                        ),
                    },
                    "occupants": {
                        "type": "integer",
                        "description": "Number of household occupants (default 3).",
                    },
                    "location": {
                        "type": "string",
                        "description": "Location preset, e.g. 'bristol' (default) or 'london'.",
                    },
                    **_TRIGGER_TOOL_WINDOW_PROPERTIES,
                },
                "required": ["pv_kw"],
            },
        },
        run=_call_run_home_simulation,
    ),
    _Tool(
        schema={
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
                        "description": f"Number of homes in the fleet (1–{_FLEET_TOOL_MAX_HOMES}).",
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
                    **_TRIGGER_TOOL_WINDOW_PROPERTIES,
                },
                "required": ["n_homes"],
            },
        },
        run=_call_run_fleet_simulation,
    ),
)

# The tools' schemas, as every chat request offers them.  TOOLS is a tuple so
# its order cannot change at runtime.  Its entries stay plain dicts: the SDK
# hands nested schema values to JSON encoding as they are, and JSON encoding
# rejects read-only mappings.
TOOLS: Sequence[Mapping[str, Any]] = tuple(tool.schema for tool in _TOOL_TABLE)


def _tools_by_name(tools: Sequence[_Tool]) -> Mapping[str, _Tool]:
    """Return *tools* keyed by name, in their order.

    Raises:
        ValueError: When more than one of *tools* has the same name, naming each such name.
    """
    repeated = [name for name, uses in Counter(tool.name for tool in tools).items() if uses > 1]
    if repeated:
        raise ValueError(
            f"Tool names must be unique, but these name more than one tool: {', '.join(repeated)}"
        )
    return MappingProxyType({tool.name: tool for tool in tools})


_TOOL_BY_NAME = _tools_by_name(_TOOL_TABLE)


def dispatch_tool(name: str, tool_input: Mapping[str, Any], context: ToolContext) -> dict[str, Any]:
    """Answer the model's call of the tool *name* with *tool_input*, running the tool in *context*.

    Returns the tool's result, its handler's own error dict included.  An
    unknown *name*, and an input the tool refuses (a required field it does
    not send, or a value a field's reader refuses), come back as
    ``{"error": ...}`` naming the problem, so the model can correct its call.
    Never raises.
    """
    tool = _TOOL_BY_NAME.get(name)
    if tool is None:
        return {"error": f"Unknown tool '{name}'. Available tools: {', '.join(_TOOL_BY_NAME)}."}
    try:
        return tool.answer(tool_input, context)
    except ValueError as refusal:
        return {"error": str(refusal)}


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
    return str(render_template("assistant/chat.html", api_key_configured=api_key_configured))


@bp.route("/history", methods=["GET"])
def chat_history() -> ResponseReturnValue:
    """Return the chat history for the current session as JSON.

    Returns:
        JSON ``{"messages": [...]}`` where each message has
        ``role``, ``content``, ``created_at``, and ``metadata`` keys.
    """
    sid = _session_id()
    messages = get_chat_history(get_database(), sid)
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
        key: totals.get(key, 0) + (getattr(usage, key, None) or 0)
        for key in ("cache_creation_input_tokens", "cache_read_input_tokens")
    }


def _has_text(content: str) -> bool:
    """Whether *content* holds text a Messages API message may carry: something besides whitespace."""
    return bool(content.strip())


def _replay_window(turns: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the messages that replay the stored *turns* to the model.

    A turn without text is left out, because the API refuses an empty message
    anywhere but last. At most MAX_HISTORY_TURNS turns are kept, and the window
    starts on a user turn, because the API needs one first; the API combines the
    consecutive user turns a left-out reply leaves behind.
    """
    window = [
        {"role": turn["role"], "content": turn["content"]}
        for turn in turns
        if _has_text(turn["content"])
    ][-MAX_HISTORY_TURNS:]
    first_user = next((i for i, m in enumerate(window) if m["role"] == "user"), len(window))
    return window[first_user:]


def request_messages(
    history: Sequence[Mapping[str, Any]], user_message: str, run_context: str = ""
) -> list[dict[str, Any]]:
    """Return the messages a chat turn sends the model.

    They are the stored *history*, replayed, then *user_message* with
    *run_context* in front.
    """
    return _replay_window([*history, {"role": "user", "content": run_context + user_message}])


def _run_context(run_id: str, storage: RunStorage) -> str:
    """Return the preamble that tells the model the name and summary of the run *run_id* names.

    Empty when *run_id* is empty or names no run in *storage*.
    """
    if not run_id:
        return ""
    run = get_run_results(run_id, storage)
    if "error" in run:
        return ""
    return (
        f"[Run context for run_id={run_id!r}, name={run['name']!r}: "
        f"{json.dumps(run['summary'], ensure_ascii=False)}]\n\n"
    )


def _model_request(model: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
    """Return the Messages API request asking *model* to answer *messages*.

    It offers TOOLS and sends SIMULATOR_SYSTEM_PROMPT as the cached system block.
    """
    return {
        "model": model,
        "thinking": {"type": "adaptive"},
        "output_config": {"effort": "low"},
        "max_tokens": 4096,
        "system": [
            {"type": "text", "text": SIMULATOR_SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        ],
        "messages": messages,
        "tools": TOOLS,
    }


@dataclass(frozen=True)
class _ReplyText:
    """A piece of the reply's text, as the user sees it."""

    text: str


@dataclass(frozen=True)
class _ToolCalled:
    """The model called the tool *name*, which runs next."""

    name: str


@dataclass(frozen=True)
class _ToolRan:
    """The tool *name* ran."""

    name: str


@dataclass(frozen=True)
class _ModelCallEnded:
    """One call to the model ended; *usage* is the token usage the SDK reported for it."""

    usage: Any


_ReplyEvent = _ReplyText | _ToolCalled | _ToolRan | _ModelCallEnded
_ToolRunner = Callable[[str, dict[str, Any]], dict[str, Any]]


def _reply_events(
    client: Any, request: Mapping[str, Any], run_tool: _ToolRunner
) -> Generator[_ReplyEvent, None, None]:
    """Yield the events of the model's reply to *request*, running each tool it calls with *run_tool*.

    The tool calls run in at most MAX_TOOL_ITERATIONS rounds, and the model is
    called again after each round, so every tool call that runs has its result
    sent to the model:
    tests/unit/web_assistant/test_tool_use.py::TestToolUseLoop::test_every_tool_call_a_capped_turn_runs_has_its_result_sent_to_the_model
    A reply that still calls tools after the last round has its calls left
    unrun, and ends with TOOL_CALL_LIMIT_NOTICE as its text. The text of
    every call, those after a tool call included, is yielded as it streams:
    tests/unit/web_assistant/test_tool_use.py::TestToolUseLoop::test_a_reply_after_a_tool_call_streams_one_delta_frame_per_chunk
    """
    messages = list(request["messages"])
    for tool_rounds_run in range(MAX_TOOL_ITERATIONS + 1):
        message = yield from _model_call(client, {**request, "messages": messages})
        if not _calls_tools(message):
            return
        if tool_rounds_run == MAX_TOOL_ITERATIONS:
            yield _ReplyText(TOOL_CALL_LIMIT_NOTICE)
            return
        results = yield from _tool_results(message.content, run_tool)
        messages = [
            *messages,
            {"role": "assistant", "content": list(message.content)},
            {"role": "user", "content": results},
        ]


def _model_call(client: Any, request: Mapping[str, Any]) -> Generator[_ReplyEvent, None, Any]:
    """Yield the text of one call to the model as it streams, then the call's end; return the message the model sent."""
    with client.messages.stream(**request) as stream:
        for text in stream.text_stream:
            yield _ReplyText(text)
        message = stream.get_final_message()
    yield _ModelCallEnded(message.usage)
    return message


def _calls_tools(message: Any) -> bool:
    """Whether the model stopped *message* to call tools."""
    stop_reason: object = getattr(message, "stop_reason", None)
    return stop_reason == "tool_use"


def _tool_results(
    content: Sequence[Any], run_tool: _ToolRunner
) -> Generator[_ReplyEvent, None, list[dict[str, Any]]]:
    """Run the tool calls among *content*'s blocks with *run_tool*, in order, each announced before it runs.

    Returns the tool_result blocks that answer the calls.
    """
    results: list[dict[str, Any]] = []
    for call in [block for block in content if block.type == "tool_use"]:
        yield _ToolCalled(call.name)
        result = run_tool(call.name, dict(call.input))
        yield _ToolRan(call.name)
        results.append({
            "type": "tool_result",
            "tool_use_id": call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })
    return results


@dataclass(frozen=True)
class _ReplyRecord:
    """What a reply's events put on record: its text, the tools that ran and the cache tokens its model calls used."""

    reply: str = ""
    tools_run: tuple[str, ...] = ()
    cache_usage: Mapping[str, int] = field(default_factory=lambda: MappingProxyType({}))

    def after(self, event: _ReplyEvent) -> "_ReplyRecord":
        """Return this record with *event* added."""
        if isinstance(event, _ReplyText):
            return replace(self, reply=self.reply + event.text)
        if isinstance(event, _ToolCalled):
            return self
        if isinstance(event, _ToolRan):
            return replace(self, tools_run=(*self.tools_run, event.name))
        if isinstance(event, _ModelCallEnded):
            return replace(
                self, cache_usage=MappingProxyType(_add_cache_usage(self.cache_usage, event.usage))
            )
        assert_never(event)


_NO_REPLY_TEXT = "[No reply text was received.]"


@dataclass(frozen=True)
class _TurnEnding:
    """How an assistant turn ended.

    *final_frame* ends the client's stream, and is empty once the client has
    left; *stand_in* is stored as the reply when no text streamed; *metadata*
    joins the stored reply's metadata.
    """

    final_frame: str
    stand_in: str
    metadata: Mapping[str, Any]


_FINISHED = _TurnEnding(sse_frame(CHAT_DONE, ChatDone()), _NO_REPLY_TEXT, MappingProxyType({}))
_CUT_SHORT = _TurnEnding("", _NO_REPLY_TEXT, MappingProxyType({"truncated": True}))


def _failed(error: Exception) -> _TurnEnding:
    """The ending of a turn that *error* stopped.

    The notice it shows the user stands in for the reply when no text streamed.
    """
    notice = f"Streaming error: {error}"
    return _TurnEnding(
        sse_frame(CHAT_FAILED, ChatFailed(notice)),
        notice,
        MappingProxyType({"error": str(error), "truncated": True}),
    )


@dataclass(frozen=True)
class _TurnRecorder:
    """Stores one chat turn in the session's chat_messages rows: the user's message, then the reply."""

    database: Database
    session_id: str
    model: str

    def store_user_message(self, text: str) -> None:
        """Store *text* as the turn's user row."""
        save_chat_message(self.database, self.session_id, "user", text)

    def store_reply(self, record: _ReplyRecord, ending: _TurnEnding) -> None:
        """Store the turn's one reply row: *record*'s text, or *ending*'s stand-in when it has none.

        Its metadata holds the cache tokens the turn used and the model, the
        tools that ran, then *ending*'s marks; it is None when that is empty.
        """
        metadata: dict[str, Any] = {**record.cache_usage, "model": self.model} if record.cache_usage else {}
        if record.tools_run:
            metadata["invoked_tools"] = list(record.tools_run)
        save_chat_message(
            self.database,
            self.session_id,
            "assistant",
            record.reply if _has_text(record.reply) else ending.stand_in,
            metadata={**metadata, **ending.metadata} or None,
        )


def _sse_frames(event: _ReplyEvent) -> tuple[str, ...]:
    """Return the SSE frames that show *event* to the client: ``delta`` for reply text, ``tool`` for a tool call, none for the rest."""
    if isinstance(event, _ReplyText):
        return (sse_frame(CHAT_DELTA, ChatDelta(event.text)),)
    if isinstance(event, _ToolCalled):
        return (sse_frame(CHAT_TOOL, ChatToolCall(event.name)),)
    if isinstance(event, (_ToolRan, _ModelCallEnded)):
        return ()
    assert_never(event)


def _turn_frames(
    user_message: str, events: Generator[_ReplyEvent, None, None], recorder: _TurnRecorder
) -> Generator[str, None, None]:
    """Yield the SSE frames of the turn that answers *user_message* with the reply *events*.

    *recorder* stores the user row as the turn starts, and the reply once,
    however the turn ends, before the frame that ends the stream:
    tests/unit/web_assistant/test_chat.py::TestEveryTurnStoresAReplyWithText
    """
    recorder.store_user_message(user_message)
    record, ending = _ReplyRecord(), _CUT_SHORT
    try:
        with closing(events):
            for event in events:
                record = record.after(event)
                yield from _sse_frames(event)
        ending = _FINISHED
    except Exception as error:
        ending = _failed(error)
    finally:
        recorder.store_reply(record, ending)
    yield ending.final_frame


def _refusal(user_message: str) -> str | None:
    """Return why a turn with *user_message* cannot reach the model, or None when it can."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return "AI assistant is not configured: set ANTHROPIC_API_KEY."
    if not user_message:
        return "Message cannot be empty."
    return None


def _refused_turn(reason: str) -> Response:
    """The response that refuses a chat turn: one ``failed`` frame carrying *reason*."""
    return event_stream([sse_frame(CHAT_FAILED, ChatFailed(reason))])


def _run_results_url_builder() -> Callable[[str], str]:
    """Return a builder of the path of a run's results page, made in the request and callable after it ends.

    It builds the URL ``url_for("main.run_results", run_id=...)`` builds in the
    request, through the request's URL adapter, which the builder keeps.

    Raises:
        RuntimeError: If the app gives the request no URL adapter to build it with.
    """
    adapter = current_app.create_url_adapter(request)
    if adapter is None:
        raise RuntimeError("The app gave the request no URL adapter, so a run's results page URL cannot be built")
    return lambda run_id: adapter.build("main.run_results", {"run_id": run_id})


def _answer_frames(client: Any, user_message: str, run_id: str) -> Generator[str, None, None]:
    """Return the SSE frames of the session's turn in which the model, through *client*, answers *user_message*.

    The run *run_id* names, if any, is the turn's context. This reads the
    session, the app's extensions and the request's URL adapter, in the
    request; the frames it returns read no request state, so the stream needs
    no request context.
    """
    database = get_database()
    storage = get_storage()
    session_id = _session_id()
    model = os.environ.get("SOLAR_ASSISTANT_MODEL") or "claude-opus-4-8"
    messages = request_messages(
        get_chat_history(database, session_id), user_message, _run_context(run_id, storage)
    )
    context = ToolContext(
        storage=storage, job_manager=get_job_manager(), results_url=_run_results_url_builder()
    )
    run_tool = partial(dispatch_tool, context=context)
    return _turn_frames(
        user_message,
        _reply_events(client, _model_request(model, messages), run_tool),
        _TurnRecorder(database, session_id, model),
    )


@bp.route("/chat", methods=["POST"])
def chat() -> Response:
    """Stream an AI assistant reply as Server-Sent Events.

    Request JSON body: ``{"message": "<user text>", "run_id": "<optional>"}``.
    A ``run_id`` puts that run's summary in front of the message as context.
    A body that is not a JSON object, an unset ANTHROPIC_API_KEY, a message
    without text and a client that cannot be built are each answered with a
    lone ``failed`` frame, and no turn is stored.

    The frames are web/sse.py's chat catalogue: ``delta`` and ``tool`` while the
    reply streams, then ``done``, or ``failed`` carrying the notice to show.

    Returns:
        ``text/event-stream`` 200 response, even when the turn fails.
    """
    try:
        data = request_json_object()
    except NotAJsonObject as refusal:
        return _refused_turn(str(refusal))
    user_message: str = str(data.get("message", "")).strip()
    refusal_reason = _refusal(user_message)
    if refusal_reason is not None:
        return _refused_turn(refusal_reason)
    try:
        client = _create_client()
    except Exception as exc:
        return _refused_turn(f"Could not initialise Anthropic client: {exc}")
    run_id: str = str(data.get("run_id", "")).strip()
    return event_stream(_answer_frames(client, user_message, run_id))
