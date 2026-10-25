# SPDX-License-Identifier: AGPL-3.0-or-later
"""save_chat_message and get_chat_history: the chat history's store in solar_challenge.web.chat_messages.

save_chat_message stores one message under its browser session, with an optional metadata dict.
get_chat_history reads back that session's messages, and no other session's, in the order they
were saved, each with its role, content, created_at and metadata, None for a message saved
without one; a session with no messages reads back as an empty list.
"""

from pathlib import Path

from solar_challenge.web.chat_messages import get_chat_history, save_chat_message
from solar_challenge.web.schema import open_database


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
