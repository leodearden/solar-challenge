# SPDX-License-Identifier: AGPL-3.0-or-later
"""save_chat_message and get_chat_history: the chat history's store in solar_challenge.web.chat_messages.

save_chat_message stores one message under its browser session, with an optional metadata dict.
get_chat_history reads back that session's messages, and no other session's, in the order they
were saved, each with its role, content, created_at and metadata, None for a message saved
without one; a session with no messages reads back as an empty list. A message whose stored
metadata cannot be read as a JSON object reads back with metadata None, and a warning names the
message and the fault.
"""

import logging
from pathlib import Path

import pytest

from solar_challenge.web.chat_messages import get_chat_history, save_chat_message
from solar_challenge.web.schema import open_database
from tests._chat_message_rows import insert_chat_message
from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE


class TestChatMessagePersistence:
    """Tests for save_chat_message and get_chat_history helpers."""

    def test_write_and_read_two_turns(self, tmp_path: Path) -> None:
        """Writing user+assistant rows for one session_id returns both in order."""
        database = open_database(tmp_path / "chat_test.db")

        save_chat_message(database, "session-1", "user", "Hello")
        save_chat_message(database, "session-1", "assistant", "Hi there!")

        history = get_chat_history(database, "session-1")
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"
        assert history[1]["content"] == "Hi there!"
        # created_at must be populated
        assert history[0]["created_at"] is not None
        assert history[1]["created_at"] is not None

    def test_session_scoping(self, tmp_path: Path) -> None:
        """Rows for a different session_id are NOT returned."""
        database = open_database(tmp_path / "scope_test.db")

        save_chat_message(database, "session-A", "user", "For A")
        save_chat_message(database, "session-B", "user", "For B")

        history_a = get_chat_history(database, "session-A")
        history_b = get_chat_history(database, "session-B")

        assert len(history_a) == 1
        assert history_a[0]["content"] == "For A"
        assert len(history_b) == 1
        assert history_b[0]["content"] == "For B"

    def test_metadata_roundtrip(self, tmp_path: Path) -> None:
        """A metadata dict round-trips through metadata_json (dict in → dict out)."""
        database = open_database(tmp_path / "meta_test.db")

        meta = {"cache_read_input_tokens": 42, "model": "claude-opus-4-8"}
        save_chat_message(database, "session-meta", "assistant", "reply", metadata=meta)

        history = get_chat_history(database, "session-meta")
        assert len(history) == 1
        assert history[0]["metadata"] == meta

    def test_no_metadata_returns_none(self, tmp_path: Path) -> None:
        """A row written without metadata returns metadata=None."""
        database = open_database(tmp_path / "nometa_test.db")

        save_chat_message(database, "session-nm", "user", "no meta")

        history = get_chat_history(database, "session-nm")
        assert history[0]["metadata"] is None

    @pytest.mark.parametrize(
        ("metadata_json", "fault"),
        [
            ("{not json", "is not JSON"),
            (JSON_NESTED_TOO_DEEPLY_TO_DECODE, "is nested too deeply to decode as JSON"),
            ("[1]", "is not a JSON object"),
        ],
        ids=["not-json", "nested-too-deeply", "not-an-object"],
    )
    def test_a_message_whose_metadata_cannot_be_read_as_a_json_object_is_read_without_it_and_a_warning_names_it_and_the_fault(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture, metadata_json: str, fault: str
    ) -> None:
        """A message whose stored metadata cannot be read as a JSON object reads back, between its session's other messages, with metadata None, and one warning names its id and the fault."""
        database = open_database(tmp_path / "damaged_meta_test.db")
        save_chat_message(database, "session-dm", "user", "Hello")
        damaged = insert_chat_message(database, "session-dm", "assistant", "Hi there!", metadata_json)
        save_chat_message(database, "session-dm", "assistant", "Anything else?", metadata={"input_tokens": 1})

        with caplog.at_level(logging.WARNING):
            history = get_chat_history(database, "session-dm")

        assert [(m["role"], m["content"], m["metadata"]) for m in history] == [
            ("user", "Hello", None),
            ("assistant", "Hi there!", None),
            ("assistant", "Anything else?", {"input_tokens": 1}),
        ]
        records = [r for r in caplog.records if r.name == "solar_challenge.web.chat_messages"]
        assert [(r.levelno, r.getMessage()) for r in records] == [
            (logging.WARNING, f"Chat message {damaged}'s metadata {fault}, so the message is read without it")
        ]

    def test_empty_session_returns_empty_list(self, tmp_path: Path) -> None:
        """get_chat_history returns [] for a session with no messages."""
        database = open_database(tmp_path / "empty_test.db")

        history = get_chat_history(database, "nonexistent-session")
        assert history == []

    def test_insertion_order_preserved(self, tmp_path: Path) -> None:
        """Multiple messages are returned in insertion order (ORDER BY id ASC)."""
        database = open_database(tmp_path / "order_test.db")

        for i in range(5):
            save_chat_message(database, "session-ord", "user", f"msg-{i}")

        history = get_chat_history(database, "session-ord")
        contents = [h["content"] for h in history]
        assert contents == [f"msg-{i}" for i in range(5)]
