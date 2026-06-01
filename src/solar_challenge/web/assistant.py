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


def _normalize_metric_key(metric: str) -> str:
    """Normalize a metric name to the canonical _METRIC_TABLE key form.

    Converts to lowercase and replaces spaces and hyphens with underscores.
    """
    return metric.lower().replace(" ", "_").replace("-", "_")


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
    - Battery kWh ≈ daily_shortfall × 1.2    (daily shortfall = daily demand × (1 − self-consumption))

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

    # Goal-aware nudging
    normalised_goal = goal.lower().strip().replace(" ", "_").replace("-", "_")
    if normalised_goal == "self_sufficiency":
        pv_kwp *= 1.10
        battery_kwh *= 1.15
    # "bill_savings" and unknown goals → standard sizing (no multiplier)

    return {
        "recommended_pv_kwp": round(pv_kwp, 2),
        "recommended_battery_kwh": round(battery_kwh, 2),
        "note": (
            "These figures are indicative estimates based on the PRD §11.4 rule-of-thumb "
            "(PV kWp ≈ annual_consumption / 950; battery ≈ daily shortfall × 1.2). "
            "Please run a simulation to confirm sizing for your specific site."
        ),
    }


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
    sid = _session_id()
    db_path = current_app.config["DATABASE"]

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
        }

        accumulated = ""
        usage_meta: dict[str, Any] = {}
        try:
            with client.messages.stream(**params) as stream:  # type: ignore[arg-type]
                for text in stream.text_stream:
                    accumulated += text
                    yield f"event: delta\ndata: {json.dumps({'text': text})}\n\n"
                final_msg = stream.get_final_message()
                usage = getattr(final_msg, "usage", None)
                if usage is not None:
                    usage_meta = {
                        "cache_creation_input_tokens": getattr(
                            usage, "cache_creation_input_tokens", 0
                        ),
                        "cache_read_input_tokens": getattr(
                            usage, "cache_read_input_tokens", 0
                        ),
                        "model": model,
                    }
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

        # Persist assistant turn on success
        database.save_chat_message(
            db_path, sid, "assistant", accumulated, metadata=usage_meta or None
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
