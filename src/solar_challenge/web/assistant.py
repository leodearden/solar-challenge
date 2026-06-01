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
