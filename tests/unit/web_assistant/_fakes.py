# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canned collaborators the web-assistant tests drive the assistant with.

``install_fake_anthropic`` patches ``anthropic.Anthropic`` with a mock whose
``messages.stream()`` returns what the ``make_*_stream`` builders script;
``seed_run`` inserts a row into the runs table.

Usage::

    from tests.unit.web_assistant._fakes import (
        install_fake_anthropic,
        make_end_turn_stream,
        make_tool_use_stream,
        seed_run,
    )

    seed_run(db_path, run_id="run-1", name="my-run",
             created_at="2026-01-01T00:00:00+00:00", summary={})
    streams = iter([
        make_tool_use_stream("toolu_1", "get_run_results", {"run_id_or_name": "run-1"}),
        make_end_turn_stream(["Here is your run."]),
    ])
    install_fake_anthropic(monkeypatch, lambda **kwargs: next(streams))
"""

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from solar_challenge.web.database import get_db, init_db


def install_fake_anthropic(
    monkeypatch: pytest.MonkeyPatch,
    stream_factory: Callable[..., MagicMock],
) -> MagicMock:
    """Set a dummy ANTHROPIC_API_KEY and patch ``anthropic.Anthropic`` with a mock class.

    The client it constructs answers ``messages.stream(**kwargs)`` with
    ``stream_factory(**kwargs)``. Returns the mock class.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-test-key")

    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.messages.stream.side_effect = stream_factory
    mock_cls.return_value = mock_instance

    monkeypatch.setattr("anthropic.Anthropic", mock_cls, raising=False)
    return mock_cls


def make_fake_stream(text_chunks: list[str]) -> MagicMock:
    """Build a context-manager mock for anthropic.Anthropic().messages.stream().

    It streams *text_chunks*; its final message has ``.content`` and ``.usage``
    but no ``stop_reason``.
    """
    final_message = SimpleNamespace(
        content=[SimpleNamespace(type="text", text="".join(text_chunks))],
        usage=SimpleNamespace(
            cache_creation_input_tokens=100,
            cache_read_input_tokens=0,
        ),
    )
    return _stream_manager(text_chunks, final_message)


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
    final_message = SimpleNamespace(
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
    return _stream_manager([], final_message)


def make_end_turn_stream(text_chunks: list[str]) -> MagicMock:
    """Build a context-manager mock for a stream that ends with stop_reason='end_turn'."""
    final_message = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="".join(text_chunks))],
        usage=SimpleNamespace(
            cache_creation_input_tokens=0,
            cache_read_input_tokens=80,
        ),
    )
    return _stream_manager(text_chunks, final_message)


def _stream_manager(text_chunks: list[str], final_message: SimpleNamespace) -> MagicMock:
    """Fake the MessageStreamManager that ``messages.stream()`` returns.

    Entering it gives a stream whose ``text_stream`` yields *text_chunks* and whose
    ``get_final_message()`` returns *final_message*.
    """
    stream = MagicMock()
    stream.text_stream = iter(text_chunks)
    stream.get_final_message.return_value = final_message

    manager = MagicMock()
    manager.__enter__.return_value = stream
    manager.__exit__.return_value = False
    return manager


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
