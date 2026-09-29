# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canned collaborators the web-assistant tests drive the assistant with.

The ``make_*_stream`` builders script the context managers that
``anthropic.Anthropic().messages.stream()`` returns; ``seed_run`` inserts a row
into the runs table.

Usage::

    from tests.unit.web_assistant._fakes import make_end_turn_stream, make_tool_use_stream, seed_run

    seed_run(db_path, run_id="run-1", name="my-run",
             created_at="2026-01-01T00:00:00+00:00", summary={})
    anthropic_client.messages.stream.side_effect = [
        make_tool_use_stream("toolu_1", "get_run_results", {"run_id_or_name": "run-1"}),
        make_end_turn_stream(["Here is your run."]),
    ]
"""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from solar_challenge.web.database import get_db, init_db


def make_fake_stream(text_chunks: list[str]) -> MagicMock:
    """Build a context-manager mock for anthropic.Anthropic().messages.stream().

    Returns a context-manager mock whose ``__enter__`` yields a fake stream
    object with:
      - ``stream.text_stream``        — an iterable over *text_chunks*
      - ``stream.get_final_message()`` — a SimpleNamespace with ``.content``
        and ``.usage`` (cache_creation_input_tokens, cache_read_input_tokens)
    """
    def _make_fake_usage() -> SimpleNamespace:
        return SimpleNamespace(
            cache_creation_input_tokens=100,
            cache_read_input_tokens=0,
        )

    def _make_final_message() -> SimpleNamespace:
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text="".join(text_chunks))],
            usage=_make_fake_usage(),
        )

    fake_stream = MagicMock()
    fake_stream.text_stream = iter(text_chunks)
    fake_stream.get_final_message.return_value = _make_final_message()

    cm = MagicMock()
    cm.__enter__.return_value = fake_stream
    cm.__exit__.return_value = False

    return cm


def make_tool_use_stream(
    tool_id: str,
    tool_name: str,
    tool_input: dict[str, Any],
) -> MagicMock:
    """Build a context-manager mock for a stream that ends with stop_reason='tool_use'.

    The fake stream yields no text chunks; get_final_message() returns a
    SimpleNamespace with stop_reason='tool_use' and a content list containing
    one tool_use block.
    """
    def _make_final_message() -> SimpleNamespace:
        return SimpleNamespace(
            stop_reason="tool_use",
            content=[
                SimpleNamespace(
                    type="tool_use",
                    id=tool_id,
                    name=tool_name,
                    input=tool_input,
                ),
            ],
            usage=SimpleNamespace(
                cache_creation_input_tokens=50,
                cache_read_input_tokens=0,
            ),
        )

    fake_stream = MagicMock()
    fake_stream.text_stream = iter([])  # no text in tool-use turn
    fake_stream.get_final_message.return_value = _make_final_message()

    cm = MagicMock()
    cm.__enter__.return_value = fake_stream
    cm.__exit__.return_value = False
    return cm


def make_end_turn_stream(text_chunks: list[str]) -> MagicMock:
    """Build a context-manager mock for a stream that ends with stop_reason='end_turn'."""
    def _make_final_message() -> SimpleNamespace:
        return SimpleNamespace(
            stop_reason="end_turn",
            content=[SimpleNamespace(type="text", text="".join(text_chunks))],
            usage=SimpleNamespace(
                cache_creation_input_tokens=0,
                cache_read_input_tokens=80,
            ),
        )

    fake_stream = MagicMock()
    fake_stream.text_stream = iter(text_chunks)
    fake_stream.get_final_message.return_value = _make_final_message()

    cm = MagicMock()
    cm.__enter__.return_value = fake_stream
    cm.__exit__.return_value = False
    return cm


def seed_run(
    db_path: "str | Path",
    *,
    run_id: str,
    name: str,
    type: str = "home",
    status: str = "completed",
    created_at: str,
    summary: dict[str, Any],
) -> None:
    """Insert a row into the runs table for testing read-only handlers.

    Calls init_db (idempotent) to ensure the schema exists, then inserts
    a minimal runs row with summary_json=json.dumps(summary).
    """
    init_db(db_path)
    with get_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO runs (id, name, type, status, created_at, summary_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, name, type, status, created_at, json.dumps(summary)),
        )
