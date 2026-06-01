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

import os
from uuid import uuid4

from flask import Blueprint, current_app, jsonify, render_template, session
from flask.typing import ResponseReturnValue

from solar_challenge.web import database

bp = Blueprint("assistant", __name__)


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
