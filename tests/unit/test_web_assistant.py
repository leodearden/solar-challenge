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


@pytest.fixture
def mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Set a dummy ANTHROPIC_API_KEY and patch anthropic.Anthropic.

    Returns a dict with keys:
      - 'client_cls' : the patched MagicMock class
      - 'set_chunks' : callable(chunks) — replace what text_stream yields next call
      - 'state'      : internal state dict; access kwargs from the last stream()
                       call via ``state["last_kwargs"]``

    Usage in tests:
        info = mock_anthropic
        info['set_chunks'](["Hello", " world"])
        resp = client.post('/assistant/chat', json={'message': 'hi'})
        kwargs = info['state']['last_kwargs']
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-test-key")

    state: dict[str, Any] = {"chunks": ["mock ", "reply"], "last_kwargs": {}}

    def _stream_factory(**kwargs: Any) -> Any:
        # Mutate in-place so all references to state["last_kwargs"] stay current.
        state["last_kwargs"].clear()
        state["last_kwargs"].update(kwargs)
        return make_fake_stream(list(state["chunks"]))

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


# ---------------------------------------------------------------------------
# Slice ② — GET /assistant/history tests (step-3)
# ---------------------------------------------------------------------------

class TestAssistantHistory:
    """Tests for GET /assistant/history endpoint."""

    def test_history_returns_seeded_messages(self, client: FlaskClient, app: Flask) -> None:
        """Seeding rows under a pinned session_id → GET /history returns them in order."""
        from solar_challenge.web.database import save_chat_message

        db_path = app.config["DATABASE"]

        # Pin a session_id in the signed cookie
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "test-history-sid"

        save_chat_message(db_path, "test-history-sid", "user", "What is SOC?")
        save_chat_message(db_path, "test-history-sid", "assistant", "SOC is state of charge.")

        resp = client.get("/assistant/history")
        assert resp.status_code == 200
        assert "application/json" in resp.content_type
        data = resp.get_json()
        assert "messages" in data
        msgs = data["messages"]
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"
        assert msgs[0]["content"] == "What is SOC?"
        assert msgs[1]["role"] == "assistant"
        assert msgs[1]["content"] == "SOC is state of charge."

    def test_history_empty_for_new_session(self, app: Flask) -> None:
        """A fresh client (no session cookie) returns {messages: []}."""
        fresh_client = app.test_client()
        resp = fresh_client.get("/assistant/history")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data == {"messages": []}

    def test_history_session_isolation(self, app: Flask) -> None:
        """Two clients with different session_ids see only their own messages."""
        from solar_challenge.web.database import save_chat_message

        db_path = app.config["DATABASE"]

        client_a = app.test_client()
        client_b = app.test_client()

        with client_a.session_transaction() as sess:
            sess["assistant_session_id"] = "sid-a"
        with client_b.session_transaction() as sess:
            sess["assistant_session_id"] = "sid-b"

        save_chat_message(db_path, "sid-a", "user", "message A")
        save_chat_message(db_path, "sid-b", "user", "message B")

        resp_a = client_a.get("/assistant/history")
        resp_b = client_b.get("/assistant/history")

        msgs_a = resp_a.get_json()["messages"]
        msgs_b = resp_b.get_json()["messages"]

        assert len(msgs_a) == 1
        assert msgs_a[0]["content"] == "message A"
        assert len(msgs_b) == 1
        assert msgs_b[0]["content"] == "message B"


# ---------------------------------------------------------------------------
# Slice ② — POST /assistant/chat happy-path tests (step-5)
# ---------------------------------------------------------------------------

class TestChatEndpointHappyPath:
    """Tests for POST /assistant/chat with a mocked Anthropic client."""

    def test_chat_returns_sse_stream(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
    ) -> None:
        """POST /chat returns 200 text/event-stream with delta + done frames."""
        mock_anthropic["set_chunks"](["Hello", " world"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "hi"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

        body = resp.get_data(as_text=True)
        assert "event: delta" in body
        assert "event: done" in body

    def test_chat_delta_frames_reconstruct_reply(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
    ) -> None:
        """Concatenated delta frame texts equal the mocked reply."""
        import json as _json

        mock_anthropic["set_chunks"](["Hello", " world"])

        resp = client.post("/assistant/chat", json={"message": "test"})
        body = resp.get_data(as_text=True)

        # Parse SSE frames: collect event types and data
        reconstructed = ""
        for line in body.splitlines():
            if line.startswith("data: ") and "text" in line:
                try:
                    payload = _json.loads(line[6:])
                    if "text" in payload:
                        reconstructed += payload["text"]
                except _json.JSONDecodeError:
                    pass

        assert reconstructed == "Hello world"

    def test_chat_uses_default_model(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
    ) -> None:
        """Without SOLAR_ASSISTANT_MODEL env var, model defaults to claude-opus-4-8."""
        mock_anthropic["set_chunks"](["ok"])

        client.post("/assistant/chat", json={"message": "ping"})

        kwargs = mock_anthropic["state"]["last_kwargs"]
        assert kwargs.get("model") == "claude-opus-4-8"

    def test_chat_system_block_has_cache_control(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
    ) -> None:
        """system block list has cache_control == {'type': 'ephemeral'}."""
        mock_anthropic["set_chunks"](["ok"])

        client.post("/assistant/chat", json={"message": "ping"})

        kwargs = mock_anthropic["state"]["last_kwargs"]
        system_list = kwargs.get("system", [])
        assert len(system_list) >= 1
        first_block = system_list[0]
        assert first_block.get("cache_control") == {"type": "ephemeral"}

    def test_chat_persists_user_and_assistant_turns(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
        app: Flask,
    ) -> None:
        """After POST /chat, user+assistant rows appear in GET /history on the SAME client."""
        mock_anthropic["set_chunks"](["mock reply"])

        # Pin the session_id so we can be sure we're checking the right one
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "persist-test-sid"

        resp = client.post("/assistant/chat", json={"message": "hi there"})
        assert resp.status_code == 200
        # consume the stream
        resp.get_data(as_text=True)

        # Now check history on the SAME client (cookie persists)
        hist_resp = client.get("/assistant/history")
        assert hist_resp.status_code == 200
        messages = hist_resp.get_json()["messages"]

        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[0]["content"] == "hi there"
        assert messages[1]["role"] == "assistant"
        assert "mock reply" in messages[1]["content"]


# ---------------------------------------------------------------------------
# Slice ② — graceful degradation tests (step-7)
# ---------------------------------------------------------------------------

class TestChatDegradation:
    """Graceful-degradation tests: no key → error SSE frame (never 500)."""

    def test_missing_api_key_returns_error_frame(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /chat without ANTHROPIC_API_KEY returns 200 with an error SSE frame."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        resp = client.post("/assistant/chat", json={"message": "hi"})
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}"
        assert "text/event-stream" in resp.content_type

        body = resp.get_data(as_text=True)
        assert "event: error" in body
        assert "event: delta" not in body
        assert "event: done" not in body

    def test_missing_api_key_error_frame_has_message_field(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The error SSE frame carries a JSON data payload with a 'message' field."""
        import json as _json

        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        resp = client.post("/assistant/chat", json={"message": "hi"})
        body = resp.get_data(as_text=True)

        # Find the data line after the error event
        error_data = None
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if line.strip() == "event: error" and i + 1 < len(lines):
                data_line = lines[i + 1]
                if data_line.startswith("data: "):
                    try:
                        error_data = _json.loads(data_line[6:])
                    except _json.JSONDecodeError:
                        pass
                break

        assert error_data is not None, "Could not find error data payload"
        assert "message" in error_data, f"Error payload missing 'message': {error_data}"

    def test_blueprint_registers_when_sdk_absent(self) -> None:
        """Blueprint registers even if 'anthropic' is absent from sys.modules.

        Fulfils the slice-② TODO from the slice-① foundation test:
        deferred import keeps blueprint registration robust.
        """
        import sys

        # Patch sys.modules so `import anthropic` would fail
        original = sys.modules.get("anthropic", None)
        sys.modules["anthropic"] = None  # type: ignore[assignment]
        try:
            # Build a fresh app — should NOT raise during blueprint registration
            from solar_challenge.web.app import create_app as _create_app
            import tempfile, os

            with tempfile.TemporaryDirectory() as tmp:
                db_path = os.path.join(tmp, "test.db")
                fresh_app = _create_app(
                    test_config={
                        "TESTING": True,
                        "SECRET_KEY": "deferred-test",
                        "WTF_CSRF_ENABLED": False,
                        "DATABASE": db_path,
                        "DATA_DIR": tmp,
                    }
                )
            assert "assistant" in fresh_app.blueprints, (
                "Expected 'assistant' blueprint registered even when anthropic SDK absent"
            )
            # GET /assistant should still return 200 (page renders without the SDK)
            with fresh_app.test_client() as fc:
                resp = fc.get("/assistant")
                assert resp.status_code == 200
        finally:
            # Restore sys.modules to original state
            if original is None:
                sys.modules.pop("anthropic", None)
            else:
                sys.modules["anthropic"] = original


# ---------------------------------------------------------------------------
# Slice ② — chat page wiring + configure-notice tests (step-9)
# ---------------------------------------------------------------------------

class TestChatPageWiring:
    """Tests for chat.html JS include, data-* attributes, and configure-notice."""

    def test_page_includes_assistant_js_when_key_set(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ANTHROPIC_API_KEY set, GET /assistant HTML includes assistant.js."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "assistant.js" in html, (
            "Expected assistant.js script include when ANTHROPIC_API_KEY is set"
        )

    def test_page_exposes_chat_url_data_attribute(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chat.html exposes the chat endpoint URL via a data-* attribute."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "data-chat-url" in html, (
            "Expected data-chat-url attribute for JS to POST to"
        )

    def test_page_exposes_history_url_data_attribute(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """chat.html exposes the history endpoint URL via a data-* attribute."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "data-history-url" in html, (
            "Expected data-history-url attribute for JS to load history from"
        )

    def test_no_configure_notice_when_key_set(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ANTHROPIC_API_KEY set, page does NOT show the configure-notice."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "ANTHROPIC_API_KEY" not in html, (
            "Configure-notice should NOT appear when ANTHROPIC_API_KEY is set"
        )

    def test_configure_notice_when_key_absent(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ANTHROPIC_API_KEY, page shows configure-notice mentioning the var name."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "ANTHROPIC_API_KEY" in html, (
            "Configure-notice MUST appear when ANTHROPIC_API_KEY is unset"
        )

    def test_foundation_markers_present_key_set(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Foundation markers (#chat-messages, #chat-input, 'AI Assistant') still present with key."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert 'id="chat-messages"' in html
        assert 'id="chat-input"' in html
        assert "AI Assistant" in html

    def test_foundation_markers_present_key_absent(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Foundation markers still present even when the key is absent."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert 'id="chat-messages"' in html
        assert 'id="chat-input"' in html
        assert "AI Assistant" in html

    def test_next_release_placeholder_removed(
        self, client: FlaskClient
    ) -> None:
        """The 'Streaming chat will be available in the next release' placeholder is gone."""
        resp = client.get("/assistant")
        html = resp.data.decode()
        assert "next release" not in html, (
            "The 'next release' placeholder should be removed in slice ②"
        )


# ---------------------------------------------------------------------------
# Slice ② — optional real-Anthropic smoke test (step-11)
# Excluded from the standard verify loop by: -m 'not slow and not e2e'
# Skipped automatically when ANTHROPIC_API_KEY is absent.
# ---------------------------------------------------------------------------

@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live Anthropic smoke test",
)
class TestChatLiveSmoke:
    """Real Anthropic API smoke tests — excluded from CI verify loop."""

    def test_single_turn_returns_nonempty_reply(self, client: FlaskClient) -> None:
        """A real POST /chat returns delta frames that reconstruct a non-empty reply."""
        import json as _json

        resp = client.post("/assistant/chat", json={"message": "Reply with exactly one word: hello"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        assert "event: delta" in body, "Expected at least one delta frame"
        assert "event: done" in body, "Expected done frame"
        assert "event: error" not in body, f"Unexpected error frame: {body[:500]}"

        reconstructed = ""
        for line in body.splitlines():
            if line.startswith("data: "):
                try:
                    payload = _json.loads(line[6:])
                    reconstructed += payload.get("text", "")
                except _json.JSONDecodeError:
                    pass
        assert len(reconstructed) > 0, "Expected non-empty reconstructed reply"

    def test_second_turn_shows_cache_hit(self, client: FlaskClient) -> None:
        """A second turn in the same session shows cache_read_input_tokens > 0."""
        # First turn
        client.post("/assistant/chat", json={"message": "Say: first"})

        # Second turn — system prompt cached from first turn
        resp2 = client.post("/assistant/chat", json={"message": "Say: second"})
        assert resp2.status_code == 200
        resp2.get_data(as_text=True)

        # Check history for cache metadata on the assistant's second turn
        hist_resp = client.get("/assistant/history")
        messages = hist_resp.get_json()["messages"]
        # Find assistant messages and check for cache_read_input_tokens
        assistant_msgs = [m for m in messages if m["role"] == "assistant"]
        assert len(assistant_msgs) >= 2, "Expected at least two assistant turns"
        last_meta = assistant_msgs[-1].get("metadata") or {}
        cache_reads = last_meta.get("cache_read_input_tokens", 0)
        assert cache_reads > 0, (
            f"Expected cache_read_input_tokens > 0 on second turn (prompt-cache hit); "
            f"got metadata: {last_meta}"
        )


# ---------------------------------------------------------------------------
# Slice ② — history window alternation invariant tests (step-12)
# ---------------------------------------------------------------------------

class TestHistoryWindowAlternation:
    """The replayed messages window must always start with a user turn.

    After 11 complete exchanges (22 DB rows) the handler adds a 23rd user
    row, then slices all_turns[-_MAX_HISTORY_TURNS:].  With _MAX_HISTORY_TURNS=20
    the tail starts at DB-row index 3 which is an assistant row — violating the
    Anthropic Messages API's "first message must be role=user" invariant.
    """

    def test_window_starts_with_user_turn_after_many_exchanges(
        self,
        client: FlaskClient,
        mock_anthropic: dict,
        app: Flask,
    ) -> None:
        """msgs[0]["role"] must be 'user' even when the tail starts on an assistant row."""
        from solar_challenge.web.assistant import _MAX_HISTORY_TURNS
        from solar_challenge.web.database import save_chat_message

        db_path = app.config["DATABASE"]

        # Pin a session_id
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "window-sid"

        # Seed 11 complete turns = 22 rows strictly alternating user/assistant
        for i in range(11):
            save_chat_message(db_path, "window-sid", "user", f"user-{i}")
            save_chat_message(db_path, "window-sid", "assistant", f"assistant-{i}")

        mock_anthropic["set_chunks"](["window reply"])

        # Handler saves user row → 23 total; slices last 20 → starts on assistant row
        resp = client.post("/assistant/chat", json={"message": "latest"})
        assert resp.status_code == 200
        resp.get_data(as_text=True)  # consume the stream

        msgs = mock_anthropic["state"]["last_kwargs"]["messages"]
        assert msgs, "Expected non-empty messages list in captured kwargs"

        # API invariant: window must start with a user turn
        assert msgs[0]["role"] == "user", (
            f"Expected first replayed message to be 'user', got {msgs[0]['role']!r}"
        )

        # Window must not exceed the cap
        assert len(msgs) <= _MAX_HISTORY_TURNS, (
            f"Expected <= {_MAX_HISTORY_TURNS} messages, got {len(msgs)}"
        )

        # Roles must strictly alternate throughout the window
        for i in range(len(msgs) - 1):
            assert msgs[i]["role"] != msgs[i + 1]["role"], (
                f"Non-alternating roles at positions {i}/{i+1}: "
                f"{msgs[i]['role']!r} then {msgs[i + 1]['role']!r}"
            )

        # The final replayed message must be the just-sent user turn
        assert msgs[-1]["role"] == "user", (
            f"Expected last replayed message to be 'user', got {msgs[-1]['role']!r}"
        )
        assert msgs[-1]["content"] == "latest", (
            f"Expected last message content 'latest', got {msgs[-1]['content']!r}"
        )


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


# ---------------------------------------------------------------------------
# Slice ③ — explain_metric tests (step-1)
# ---------------------------------------------------------------------------

class TestExplainMetric:
    """Tests for the explain_metric(metric) -> dict[str, str] handler."""

    def test_known_metric_self_consumption_ratio(self) -> None:
        """explain_metric('self_consumption_ratio') returns dict with non-empty definition and band."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("self_consumption_ratio")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "definition" in result, f"Missing 'definition' key: {result}"
        assert "uk_benchmark_band" in result, f"Missing 'uk_benchmark_band' key: {result}"
        assert isinstance(result["definition"], str) and result["definition"], (
            "definition must be a non-empty string"
        )
        assert isinstance(result["uk_benchmark_band"], str) and result["uk_benchmark_band"], (
            "uk_benchmark_band must be a non-empty string"
        )

    def test_known_metric_self_sufficiency(self) -> None:
        """explain_metric('self_sufficiency') returns dict with non-empty definition and band."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("self_sufficiency")
        assert "definition" in result
        assert "uk_benchmark_band" in result
        assert result["definition"]
        assert result["uk_benchmark_band"]

    def test_key_normalization_hyphen(self) -> None:
        """'self-consumption ratio' normalizes to same canonical entry as 'self_consumption_ratio'."""
        from solar_challenge.web.assistant import explain_metric

        r1 = explain_metric("self_consumption_ratio")
        r2 = explain_metric("self-consumption ratio")
        assert r1 == r2, (
            f"Expected same result for canonical and hyphenated form; "
            f"got {r1!r} vs {r2!r}"
        )

    def test_key_normalization_case(self) -> None:
        """'Self_Consumption_Ratio' normalizes to same canonical entry."""
        from solar_challenge.web.assistant import explain_metric

        r1 = explain_metric("self_consumption_ratio")
        r2 = explain_metric("Self_Consumption_Ratio")
        assert r1 == r2, (
            f"Expected case-insensitive lookup; got {r1!r} vs {r2!r}"
        )

    def test_unknown_metric_returns_graceful_dict(self) -> None:
        """An unrecognized metric returns a dict with both keys present mentioning 'unknown'."""
        from solar_challenge.web.assistant import explain_metric

        result = explain_metric("nonexistent_metric_xyz")
        assert isinstance(result, dict), "Must return a dict, not raise"
        assert "definition" in result, f"Missing 'definition' in graceful response: {result}"
        assert "uk_benchmark_band" in result, (
            f"Missing 'uk_benchmark_band' in graceful response: {result}"
        )
        # Must mention the metric is unknown
        combined = (result["definition"] + " " + result["uk_benchmark_band"]).lower()
        assert "unknown" in combined or "not found" in combined or "not recognised" in combined, (
            f"Graceful response should mention metric is unknown/not found: {result}"
        )

    def test_unknown_metric_does_not_raise(self) -> None:
        """explain_metric with an unknown name must NOT raise any exception."""
        from solar_challenge.web.assistant import explain_metric

        try:
            explain_metric("totally_made_up_metric_12345")
        except Exception as exc:
            raise AssertionError(
                f"explain_metric should not raise for unknown metric, got: {exc!r}"
            ) from exc

    def test_all_known_metrics_have_both_keys(self) -> None:
        """Every entry in _METRIC_TABLE has non-empty definition and uk_benchmark_band."""
        from solar_challenge.web.assistant import _METRIC_TABLE

        assert _METRIC_TABLE, "Expected _METRIC_TABLE to be non-empty"
        for name, entry in _METRIC_TABLE.items():
            assert "definition" in entry, f"Entry {name!r} missing 'definition'"
            assert "uk_benchmark_band" in entry, f"Entry {name!r} missing 'uk_benchmark_band'"
            assert entry["definition"], f"Entry {name!r} has empty definition"
            assert entry["uk_benchmark_band"], f"Entry {name!r} has empty uk_benchmark_band"


# ---------------------------------------------------------------------------
# Slice ③ — suggest_config tests (step-3)
# ---------------------------------------------------------------------------

class TestSuggestConfig:
    """Tests for suggest_config(annual_consumption_kwh, goal) -> dict[str, Any]."""

    def test_returns_dict_with_sizing_keys(self) -> None:
        """suggest_config returns a dict with recommended_pv_kwp and recommended_battery_kwh."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "recommended_pv_kwp" in result, f"Missing 'recommended_pv_kwp': {result}"
        assert "recommended_battery_kwh" in result, f"Missing 'recommended_battery_kwh': {result}"

    def test_numeric_outputs_are_positive_floats(self) -> None:
        """recommended_pv_kwp and recommended_battery_kwh must be positive floats."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        pv = result["recommended_pv_kwp"]
        batt = result["recommended_battery_kwh"]
        assert isinstance(pv, (int, float)) and pv > 0, (
            f"recommended_pv_kwp must be positive float, got {pv!r}"
        )
        assert isinstance(batt, (int, float)) and batt > 0, (
            f"recommended_battery_kwh must be positive float, got {batt!r}"
        )

    def test_higher_consumption_gives_larger_pv(self) -> None:
        """Higher annual consumption → larger recommended PV (scaling check)."""
        from solar_challenge.web.assistant import suggest_config

        low_result = suggest_config(1900.0, "self_sufficiency")
        high_result = suggest_config(4200.0, "self_sufficiency")
        assert high_result["recommended_pv_kwp"] > low_result["recommended_pv_kwp"], (
            f"Expected larger PV for higher consumption: "
            f"got {high_result['recommended_pv_kwp']} vs {low_result['recommended_pv_kwp']}"
        )

    def test_caveat_contains_run_a_simulation(self) -> None:
        """Result dict must include a caveat/note string containing 'run a simulation'."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "bill_savings")
        # Look for a string value that mentions "run a simulation"
        found = any(
            isinstance(v, str) and "run a simulation" in v.lower()
            for v in result.values()
        )
        assert found, (
            f"Expected at least one string value containing 'run a simulation': {result}"
        )

    def test_accepts_self_sufficiency_goal(self) -> None:
        """suggest_config with goal='self_sufficiency' must not raise."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "self_sufficiency")
        assert isinstance(result, dict)

    def test_accepts_bill_savings_goal(self) -> None:
        """suggest_config with goal='bill_savings' must not raise."""
        from solar_challenge.web.assistant import suggest_config

        result = suggest_config(3100.0, "bill_savings")
        assert isinstance(result, dict)

    def test_accepts_unknown_goal_without_raising(self) -> None:
        """suggest_config with an unrecognised goal must not raise."""
        from solar_challenge.web.assistant import suggest_config

        try:
            result = suggest_config(3100.0, "mystery_goal")
            assert isinstance(result, dict)
        except Exception as exc:
            raise AssertionError(
                f"suggest_config should not raise for unknown goal; got: {exc!r}"
            ) from exc

    def test_battery_scales_with_consumption(self) -> None:
        """Higher annual consumption → larger recommended battery."""
        from solar_challenge.web.assistant import suggest_config

        low = suggest_config(1900.0, "self_sufficiency")
        high = suggest_config(4200.0, "self_sufficiency")
        assert high["recommended_battery_kwh"] > low["recommended_battery_kwh"], (
            f"Expected larger battery for higher consumption: "
            f"{high['recommended_battery_kwh']} vs {low['recommended_battery_kwh']}"
        )


# ---------------------------------------------------------------------------
# Slice ③ — tool surface tests (step-5)
# ---------------------------------------------------------------------------

class TestToolSurface:
    """Tests for _TOOLS list and _dispatch_tool router."""

    def test_tools_order_is_explain_metric_then_suggest_config(self) -> None:
        """[t['name'] for t in _TOOLS] == ['explain_metric', 'suggest_config'] (fixed order)."""
        from solar_challenge.web.assistant import _TOOLS

        names = [t["name"] for t in _TOOLS]
        assert names == ["explain_metric", "suggest_config"], (
            f"Expected fixed order ['explain_metric', 'suggest_config'], got {names}"
        )

    def test_every_tool_entry_has_required_keys(self) -> None:
        """Every entry in _TOOLS has 'name', 'description', and 'input_schema'."""
        from solar_challenge.web.assistant import _TOOLS

        for tool in _TOOLS:
            assert "name" in tool, f"Missing 'name' in tool: {tool}"
            assert "description" in tool, f"Missing 'description' in tool: {tool}"
            assert "input_schema" in tool, f"Missing 'input_schema' in tool: {tool}"

    def test_every_tool_input_schema_is_object_with_required(self) -> None:
        """Every input_schema has type=='object' and a non-empty 'required' list."""
        from solar_challenge.web.assistant import _TOOLS

        for tool in _TOOLS:
            schema = tool["input_schema"]
            assert isinstance(schema, dict), f"input_schema must be dict for {tool['name']!r}"
            assert schema.get("type") == "object", (
                f"input_schema.type must be 'object' for {tool['name']!r}; got {schema.get('type')!r}"
            )
            assert "required" in schema, f"input_schema missing 'required' for {tool['name']!r}"
            assert isinstance(schema["required"], list) and schema["required"], (
                f"input_schema.required must be non-empty list for {tool['name']!r}"
            )

    def test_dispatch_explain_metric(self) -> None:
        """_dispatch_tool('explain_metric', {...}) returns the same dict as explain_metric()."""
        from solar_challenge.web.assistant import _dispatch_tool, explain_metric

        result = _dispatch_tool("explain_metric", {"metric": "self_consumption_ratio"})
        expected = explain_metric("self_consumption_ratio")
        assert result == expected, (
            f"_dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_dispatch_suggest_config(self) -> None:
        """_dispatch_tool('suggest_config', {...}) returns the same dict as suggest_config()."""
        from solar_challenge.web.assistant import _dispatch_tool, suggest_config

        result = _dispatch_tool(
            "suggest_config",
            {"annual_consumption_kwh": 3100, "goal": "self_sufficiency"},
        )
        expected = suggest_config(3100, "self_sufficiency")
        assert result == expected, (
            f"_dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_dispatch_unknown_returns_error_dict(self) -> None:
        """_dispatch_tool with unknown name returns a dict with 'error' key, does NOT raise."""
        from solar_challenge.web.assistant import _dispatch_tool

        try:
            result = _dispatch_tool("nonexistent_tool", {})
        except Exception as exc:
            raise AssertionError(
                f"_dispatch_tool should not raise for unknown tool; got: {exc!r}"
            ) from exc
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, f"Expected 'error' key in result: {result}"
