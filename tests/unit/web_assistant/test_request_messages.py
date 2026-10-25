# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for request_messages, which builds the messages a chat turn sends the model.

request_messages reads no Flask state, so these tests call it with plain values
and no app, request or database.
"""

from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.web.assistant import MAX_HISTORY_TURNS, request_messages


def stored_turn(role: str, content: str) -> dict[str, Any]:
    """A chat turn shaped as chat_messages.get_chat_history returns one."""
    return {"role": role, "content": content, "created_at": "2026-10-14T12:00:00+00:00", "metadata": None}


def test_the_stored_turns_are_replayed_by_role_and_content_before_the_users_message() -> None:
    """Each stored turn is replayed as its role and content alone, and the user's message follows them."""
    history = [stored_turn("user", "What is SOC?"), stored_turn("assistant", "State of charge.")]

    assert request_messages(history, "And DoD?") == [
        {"role": "user", "content": "What is SOC?"},
        {"role": "assistant", "content": "State of charge."},
        {"role": "user", "content": "And DoD?"},
    ]


def test_run_context_goes_in_front_of_the_users_message_and_nowhere_else() -> None:
    """The run context starts the user's message; the stored turns are replayed without it."""
    history = [stored_turn("user", "What is SOC?"), stored_turn("assistant", "State of charge.")]

    assert request_messages(history, "summarise", run_context="[Run context: r1]\n\n") == [
        {"role": "user", "content": "What is SOC?"},
        {"role": "assistant", "content": "State of charge."},
        {"role": "user", "content": "[Run context: r1]\n\nsummarise"},
    ]


class TestHistoryWindowAlternation:
    """The replayed messages window always starts with a user turn.

    After 11 complete exchanges (22 stored turns) request_messages adds the new
    user turn as a 23rd, then keeps the last MAX_HISTORY_TURNS. With
    MAX_HISTORY_TURNS=20 that tail starts at stored-turn index 3, an assistant
    turn, while the Anthropic Messages API needs a user turn first.
    """

    def test_window_starts_with_user_turn_after_many_exchanges(self) -> None:
        """The first replayed message is a user turn even when the tail starts on an assistant turn."""
        history = [
            turn
            for i in range(11)
            for turn in (stored_turn("user", f"user-{i}"), stored_turn("assistant", f"assistant-{i}"))
        ]

        msgs = request_messages(history, "latest")

        assert msgs[0]["role"] == "user", (
            f"Expected first replayed message to be 'user', got {msgs[0]['role']!r}"
        )
        assert len(msgs) <= MAX_HISTORY_TURNS, (
            f"Expected <= {MAX_HISTORY_TURNS} messages, got {len(msgs)}"
        )
        for earlier, later in zip(msgs, msgs[1:]):
            assert earlier["role"] != later["role"], (
                f"Non-alternating roles: {earlier!r} then {later!r}"
            )
        assert msgs[-1] == {"role": "user", "content": "latest"}, (
            f"Expected the user's message last, got {msgs[-1]!r}"
        )
