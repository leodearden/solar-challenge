# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the AI assistant web blueprint (slice ①: foundation wiring + slice ②: chat core)."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


# ---------------------------------------------------------------------------
# Slice ② helpers & fixtures
# ---------------------------------------------------------------------------

def make_fake_stream(text_chunks: list[str]) -> tuple[MagicMock, dict[str, Any]]:
    """Build a context-manager mock for anthropic.Anthropic().messages.stream().

    Returns (context_manager_mock, captured_kwargs_container) where
    captured_kwargs_container['kwargs'] is populated when __enter__ is called.

    The fake stream exposes:
      - stream.text_stream   — an iterable over *text_chunks*
      - stream.get_final_message() — returns a SimpleNamespace with .content (list)
        and .usage (cache_creation_input_tokens, cache_read_input_tokens attrs)
    """
    captured: dict[str, Any] = {}

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

    return cm, captured


@pytest.fixture
def mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Set a dummy ANTHROPIC_API_KEY and patch anthropic.Anthropic.

    Returns a dict with keys:
      - 'client_cls'  : the patched MagicMock class
      - 'set_chunks'  : callable(chunks) — replace what text_stream yields next call
      - 'last_kwargs' : dict populated with the kwargs from the last stream() call

    Usage in tests:
        info = mock_anthropic
        info['set_chunks'](["Hello", " world"])
        resp = client.post('/assistant/chat', json={'message': 'hi'})
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-test-key")

    state: dict[str, Any] = {"chunks": ["mock ", "reply"], "last_kwargs": {}}

    def _stream_factory(**kwargs: Any) -> Any:
        state["last_kwargs"] = kwargs
        cm, _ = make_fake_stream(list(state["chunks"]))
        return cm

    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_instance.messages.stream.side_effect = _stream_factory
    mock_cls.return_value = mock_instance

    monkeypatch.setattr("anthropic.Anthropic", mock_cls, raising=False)

    def _set_chunks(chunks: list[str]) -> None:
        state["chunks"] = chunks

    return {
        "client_cls": mock_cls,
        "set_chunks": _set_chunks,
        "last_kwargs": state["last_kwargs"],
        "state": state,
    }


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


# ---------------------------------------------------------------------------
# Slice ② — database helper tests (step-1)
# ---------------------------------------------------------------------------

class TestChatMessagePersistence:
    """Tests for save_chat_message and get_chat_history helpers."""

    def test_write_and_read_two_turns(self, tmp_path: Path) -> None:
        """Writing user+assistant rows for one session_id returns both in order."""
        from solar_challenge.web.database import get_chat_history, init_db, save_chat_message

        db_path = tmp_path / "chat_test.db"
        init_db(db_path)

        save_chat_message(db_path, "session-1", "user", "Hello")
        save_chat_message(db_path, "session-1", "assistant", "Hi there!")

        history = get_chat_history(db_path, "session-1")
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
        from solar_challenge.web.database import get_chat_history, init_db, save_chat_message

        db_path = tmp_path / "scope_test.db"
        init_db(db_path)

        save_chat_message(db_path, "session-A", "user", "For A")
        save_chat_message(db_path, "session-B", "user", "For B")

        history_a = get_chat_history(db_path, "session-A")
        history_b = get_chat_history(db_path, "session-B")

        assert len(history_a) == 1
        assert history_a[0]["content"] == "For A"
        assert len(history_b) == 1
        assert history_b[0]["content"] == "For B"

    def test_metadata_roundtrip(self, tmp_path: Path) -> None:
        """A metadata dict round-trips through metadata_json (dict in → dict out)."""
        from solar_challenge.web.database import get_chat_history, init_db, save_chat_message

        db_path = tmp_path / "meta_test.db"
        init_db(db_path)

        meta = {"cache_read_input_tokens": 42, "model": "claude-opus-4-8"}
        save_chat_message(db_path, "session-meta", "assistant", "reply", metadata=meta)

        history = get_chat_history(db_path, "session-meta")
        assert len(history) == 1
        assert history[0]["metadata"] == meta

    def test_no_metadata_returns_none(self, tmp_path: Path) -> None:
        """A row written without metadata returns metadata=None."""
        from solar_challenge.web.database import get_chat_history, init_db, save_chat_message

        db_path = tmp_path / "nometa_test.db"
        init_db(db_path)

        save_chat_message(db_path, "session-nm", "user", "no meta")

        history = get_chat_history(db_path, "session-nm")
        assert history[0]["metadata"] is None

    def test_empty_session_returns_empty_list(self, tmp_path: Path) -> None:
        """get_chat_history returns [] for a session with no messages."""
        from solar_challenge.web.database import get_chat_history, init_db

        db_path = tmp_path / "empty_test.db"
        init_db(db_path)

        history = get_chat_history(db_path, "nonexistent-session")
        assert history == []

    def test_insertion_order_preserved(self, tmp_path: Path) -> None:
        """Multiple messages are returned in insertion order (ORDER BY id ASC)."""
        from solar_challenge.web.database import get_chat_history, init_db, save_chat_message

        db_path = tmp_path / "order_test.db"
        init_db(db_path)

        for i in range(5):
            save_chat_message(db_path, "session-ord", "user", f"msg-{i}")

        history = get_chat_history(db_path, "session-ord")
        contents = [h["content"] for h in history]
        assert contents == [f"msg-{i}" for i in range(5)]


def test_assistant_blueprint_registers_without_warning(app: Flask) -> None:
    """Blueprint imports and registers cleanly — blueprint presence proves no ImportError was swallowed.

    The app.py try/except either registers the blueprint (success) or logs a warning and skips
    registration (ImportError). Checking 'assistant' in app.blueprints is therefore sufficient;
    the warning-free path is the only way the blueprint ends up registered.

    TODO (slice ②): when the chat handler gains a deferred ``import anthropic``, add a test that
    patches ``sys.modules['anthropic']`` to ``None`` at the point of blueprint registration and
    verifies the blueprint still registers — covering the robustness claim in assistant.py's
    docstring.
    """
    assert "assistant" in app.blueprints, (
        f"Expected 'assistant' blueprint to be registered; got: {list(app.blueprints.keys())}"
    )


def test_assistant_page_renders_chat_shell(client: FlaskClient) -> None:
    """GET /assistant → 200 with chat shell markers (chat-messages + chat-input containers)."""
    resp = client.get("/assistant")
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
    assert "text/html" in resp.content_type, (
        f"Expected text/html content type, got {resp.content_type!r}"
    )
    html = resp.data.decode()
    assert "AI Assistant" in html, "Expected 'AI Assistant' heading in page"
    assert 'id="chat-messages"' in html, (
        "Expected scrollable message container id='chat-messages' in page"
    )
    assert 'id="chat-input"' in html, (
        "Expected message input id='chat-input' in page"
    )


def test_sidebar_shows_assistant_link(client: FlaskClient) -> None:
    """Every page's nav sidebar includes an 'AI Assistant' link to /assistant."""
    resp = client.get("/")
    assert resp.status_code == 200, f"Expected 200 from dashboard, got {resp.status_code}"
    html = resp.data.decode()
    assert "AI Assistant" in html, "Expected 'AI Assistant' nav label in sidebar"
    # url_for('assistant.chat_page') generates /assistant/ (canonical Flask URL with trailing slash);
    # strict_slashes=False on the route makes both /assistant and /assistant/ return 200.
    assert 'href="/assistant/"' in html, (
        "Expected href='/assistant/' link in sidebar (url_for('assistant.chat_page'))"
    )
