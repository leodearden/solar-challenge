# SPDX-License-Identifier: AGPL-3.0-or-later
"""Canned collaborators the web-assistant tests drive the assistant with.

``install_fake_anthropic`` stands a ``FakeAnthropic`` in for the Anthropic API;
the fake's ``set_streams`` and ``set_chunks`` script its replies with the
``make_*_stream`` builders. ``thinking_block``, ``redacted_thinking_block``,
``text_block`` and ``tool_use_block`` build the content blocks a
``make_tool_use_stream_from_blocks`` reply carries. ``seed_run`` inserts a row
into the runs table.

Usage::

    from tests.unit.web_assistant._fakes import (
        install_fake_anthropic,
        make_end_turn_stream,
        make_tool_use_stream,
        seed_run,
    )

    seed_run(db_path, run_id="run-1", name="my-run",
             created_at="2026-01-01T00:00:00+00:00", summary={})
    anthropic_api = install_fake_anthropic(monkeypatch)
    anthropic_api.set_streams([
        make_tool_use_stream("toolu_1", "get_run_results", {"run_id_or_name": "run-1"}),
        make_end_turn_stream(["Here is your run."]),
    ])
    resp = client.post("/assistant/chat", json={"message": "How did run-1 go?"})
    body = resp.get_data(as_text=True)
    messages_with_tool_result = anthropic_api.calls[1]["messages"]
"""

import json
from collections.abc import Iterator, Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from solar_challenge.web.database import get_db, init_db


class FakeAnthropic:
    """Plays the Anthropic API for the chat under test. It records each
    ``messages.stream()`` call's kwargs and answers with the next stream
    ``set_streams`` scripted or, once none remain, a stream of the ``set_chunks`` text.
    """

    def __init__(self) -> None:
        self._calls: list[dict[str, Any]] = []
        self._scripted_streams: Iterator[MagicMock] = iter(())
        self._reply_chunks: tuple[str, ...] = ("mock ", "reply")

    @property
    def calls(self) -> list[dict[str, Any]]:
        """Every ``messages.stream()`` call's kwargs since the fake was built, oldest first,
        as a fresh list. The setters never clear it: a test that chats twice sees both chats' calls.
        """
        return list(self._calls)

    @property
    def last_kwargs(self) -> dict[str, Any]:
        """The kwargs of the latest ``messages.stream()`` call."""
        if not self._calls:
            raise AssertionError("Expected a recorded messages.stream() call; the chat made none")
        return self._calls[-1]

    def set_chunks(self, chunks: list[str]) -> None:
        """Set the text of every reply after the scripted ones."""
        self._reply_chunks = tuple(chunks)

    def set_streams(self, streams: list[MagicMock]) -> None:
        """Script the next replies, one stream per ``messages.stream()`` call."""
        self._scripted_streams = iter(streams)

    def stream(self, **kwargs: Any) -> MagicMock:
        """Record this ``messages.stream()`` call and return its reply."""
        self._calls.append(dict(kwargs))
        scripted = next(self._scripted_streams, None)
        if scripted is not None:
            return scripted
        return make_fake_stream(list(self._reply_chunks))


def install_fake_anthropic(monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
    """Set a dummy ANTHROPIC_API_KEY and patch ``anthropic.Anthropic`` with a mock class.

    The client it constructs sends ``messages.stream()`` to a new FakeAnthropic,
    which is returned.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-test-key")

    fake = FakeAnthropic()
    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.messages.stream.side_effect = fake.stream
    mock_cls.return_value = mock_instance

    monkeypatch.setattr("anthropic.Anthropic", mock_cls, raising=False)
    return fake


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
    """Build a ``make_tool_use_stream_from_blocks`` stream whose final message's
    content is one tool_use block."""
    return make_tool_use_stream_from_blocks([tool_use_block(tool_id, tool_name, tool_input)])


def make_tool_use_stream_from_blocks(blocks: Sequence[SimpleNamespace]) -> MagicMock:
    """Build a context-manager mock for a stream that ends with stop_reason='tool_use'.

    Like the real ``text_stream``, the fake streams the text of *blocks*' text blocks
    and none of their thinking; get_final_message() returns a SimpleNamespace with
    stop_reason='tool_use' whose content lists *blocks* in order.
    """
    final_message = SimpleNamespace(
        stop_reason="tool_use",
        content=list(blocks),
        usage=SimpleNamespace(
            cache_creation_input_tokens=50,
            cache_read_input_tokens=0,
        ),
    )
    text_chunks = [block.text for block in blocks if block.type == "text"]
    return _stream_manager(text_chunks, final_message)


def make_end_turn_stream(
    text_chunks: list[str],
    *,
    cache_creation_input_tokens: int | None = 0,
    cache_read_input_tokens: int | None = 80,
) -> MagicMock:
    """Build a context-manager mock for a stream that ends with stop_reason='end_turn'.

    The usage counts default to ints; pass ``None`` to mirror the real SDK's
    ``Optional[int]`` cache-token fields when the API leaves them out.
    """
    final_message = SimpleNamespace(
        stop_reason="end_turn",
        content=[SimpleNamespace(type="text", text="".join(text_chunks))],
        usage=SimpleNamespace(
            cache_creation_input_tokens=cache_creation_input_tokens,
            cache_read_input_tokens=cache_read_input_tokens,
        ),
    )
    return _stream_manager(text_chunks, final_message)


def thinking_block(thinking: str, signature: str) -> SimpleNamespace:
    """A content block shaped like the SDK's ``ThinkingBlock``."""
    return SimpleNamespace(type="thinking", thinking=thinking, signature=signature)


def redacted_thinking_block(data: str) -> SimpleNamespace:
    """A content block shaped like the SDK's ``RedactedThinkingBlock``."""
    return SimpleNamespace(type="redacted_thinking", data=data)


def text_block(text: str) -> SimpleNamespace:
    """A content block shaped like the SDK's ``TextBlock``."""
    return SimpleNamespace(type="text", text=text)


def tool_use_block(tool_id: str, tool_name: str, tool_input: dict[str, Any]) -> SimpleNamespace:
    """A content block shaped like the SDK's ``ToolUseBlock``."""
    return SimpleNamespace(type="tool_use", id=tool_id, name=tool_name, input=tool_input)


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
