# SPDX-License-Identifier: AGPL-3.0-or-later
"""AI assistant Blueprint for the Solar Challenge web interface.

Slice ①: registers the blueprint and serves the static chat shell page.
The Anthropic SDK import is deliberately deferred to slice ② (chat core)
so blueprint registration remains robust regardless of whether the SDK
is installed in the current environment.
"""

from flask import Blueprint, render_template

bp = Blueprint("assistant", __name__)


@bp.route("/", methods=["GET"], strict_slashes=False)
def chat_page() -> str:
    """Render the AI assistant chat shell page."""
    return str(render_template("assistant/chat.html", page="assistant"))
