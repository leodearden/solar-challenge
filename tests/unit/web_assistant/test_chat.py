# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the AI assistant's chat routes, including the chat transcript they persist.

The routes are the /assistant page, GET /assistant/history and POST /assistant/chat.
"""

import os
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from tests._sse import SseFrame, parse_sse_events
from tests.unit.web_assistant._fakes import FakeAnthropic, install_fake_anthropic, seed_run


def reply_text(events: list[SseFrame]) -> str:
    """Return the reply the delta frames in *events* carry, in stream order."""
    return "".join(e.data["text"] for e in events if e.event == "delta")


@pytest.fixture
def anthropic_api(monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
    """Stand a FakeAnthropic in for the Anthropic API; each test sets its reply with set_chunks()."""
    return install_fake_anthropic(monkeypatch)


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


class TestChatEndpointHappyPath:
    """Tests for POST /assistant/chat with a mocked Anthropic client."""

    def test_chat_returns_sse_stream(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """POST /chat returns 200 text/event-stream with delta + done frames."""
        anthropic_api.set_chunks(["Hello", " world"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "hi"},
        )
        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type

        body = resp.get_data(as_text=True)
        event_types = [e.event for e in parse_sse_events(body)]
        assert "delta" in event_types, f"Expected delta frames; got: {event_types}"
        assert "done" in event_types, f"Expected done frame; got: {event_types}"

    def test_chat_delta_frames_reconstruct_reply(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """Concatenated delta frame texts equal the mocked reply."""
        anthropic_api.set_chunks(["Hello", " world"])

        resp = client.post("/assistant/chat", json={"message": "test"})
        body = resp.get_data(as_text=True)

        assert reply_text(parse_sse_events(body)) == "Hello world"

    def test_chat_uses_default_model(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """Without SOLAR_ASSISTANT_MODEL env var, model defaults to claude-opus-4-8."""
        anthropic_api.set_chunks(["ok"])

        client.post("/assistant/chat", json={"message": "ping"})

        kwargs = anthropic_api.last_kwargs
        assert kwargs.get("model") == "claude-opus-4-8"

    def test_chat_system_block_has_cache_control(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """system block list has cache_control == {'type': 'ephemeral'}."""
        anthropic_api.set_chunks(["ok"])

        client.post("/assistant/chat", json={"message": "ping"})

        kwargs = anthropic_api.last_kwargs
        system_list = kwargs.get("system", [])
        assert len(system_list) >= 1
        first_block = system_list[0]
        assert first_block.get("cache_control") == {"type": "ephemeral"}

    def test_chat_persists_user_and_assistant_turns(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
        app: Flask,
    ) -> None:
        """After POST /chat, user+assistant rows appear in GET /history on the SAME client."""
        anthropic_api.set_chunks(["mock reply"])

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


class TestChatDegradation:
    """Graceful degradation: a chat that cannot start returns an error SSE frame, never a 500."""

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
        events = parse_sse_events(body)
        assert [e.event for e in events] == ["error"], f"Expected a lone error frame; got: {events}"

    def test_missing_api_key_error_frame_has_message_field(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The error SSE frame carries a JSON data payload whose 'message' names ANTHROPIC_API_KEY."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        resp = client.post("/assistant/chat", json={"message": "hi"})
        body = resp.get_data(as_text=True)

        events = parse_sse_events(body)
        error_frames = [e for e in events if e.event == "error"]
        assert error_frames, f"Could not find error data payload; events: {events}"
        error_data = error_frames[0].data
        assert isinstance(error_data, dict) and "message" in error_data, (
            f"Error payload missing 'message': {error_data}"
        )
        assert "ANTHROPIC_API_KEY" in error_data["message"], (
            f"Expected the error message to name ANTHROPIC_API_KEY; got: {error_data['message']!r}"
        )

    def test_client_construction_failure_returns_error_frame_and_saves_no_turn(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A client the SDK cannot construct, as from a malformed ANTHROPIC_BASE_URL,
        yields an error frame naming that failure and saves no chat turn."""
        malformed_port = "notaport"
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy-test-key")
        monkeypatch.setenv("ANTHROPIC_BASE_URL", f"http://localhost:{malformed_port}")
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "construction-failure-sid"

        resp = client.post("/assistant/chat", json={"message": "hi"})

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        body = resp.get_data(as_text=True)
        events = parse_sse_events(body)
        assert [e.event for e in events] == ["error"], f"Expected a lone error frame; got: {events}"
        assert malformed_port in events[0].data["message"], (
            f"Expected the error message to name {malformed_port!r}; got: {events[0].data}"
        )
        assert client.get("/assistant/history").get_json() == {"messages": []}


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
            "The 'next release' placeholder must not appear on the chat page"
        )


@pytest.mark.slow
@pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set — skipping live Anthropic smoke test",
)
class TestChatLiveSmoke:
    """Real Anthropic API smoke tests — excluded from CI verify loop."""

    def test_single_turn_returns_nonempty_reply(self, client: FlaskClient) -> None:
        """A real POST /chat returns delta frames that reconstruct a non-empty reply."""
        resp = client.post("/assistant/chat", json={"message": "Reply with exactly one word: hello"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)
        events = parse_sse_events(body)
        event_types = [e.event for e in events]
        assert "delta" in event_types, "Expected at least one delta frame"
        assert "done" in event_types, "Expected done frame"
        assert "error" not in event_types, f"Unexpected error frame: {body[:500]}"

        reconstructed = reply_text(events)
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
        anthropic_api: FakeAnthropic,
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

        anthropic_api.set_chunks(["window reply"])

        # Handler saves user row → 23 total; slices last 20 → starts on assistant row
        resp = client.post("/assistant/chat", json={"message": "latest"})
        assert resp.status_code == 200
        resp.get_data(as_text=True)  # consume the stream

        msgs = anthropic_api.last_kwargs["messages"]
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


class TestRunContextInjection:
    """Tests for run_id injection into the user turn on POST /assistant/chat."""

    def test_run_id_injects_summary_into_api_messages(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """POST with run_id injects summary into messages[-1]['content'] before API call."""
        db_path = app.config["DATABASE"]
        summary_marker = 987.65
        seed_run(
            db_path,
            run_id="ctx-run-001",
            name="ctx-signal-run",
            status="completed",
            created_at="2026-06-01T09:00:00+00:00",
            summary={"total_generation_kwh": summary_marker},
        )

        anthropic_api.set_chunks(["ok"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "summarise", "run_id": "ctx-run-001"},
        )
        assert resp.status_code == 200
        resp.get_data(as_text=True)

        msgs = anthropic_api.last_kwargs["messages"]
        last_msg = msgs[-1]
        assert last_msg["role"] == "user", f"Expected last msg role=user; got {last_msg['role']!r}"
        content = last_msg["content"]
        assert str(summary_marker) in content, (
            f"Expected seeded summary value {summary_marker!r} injected into last user message;\n"
            f"content: {content!r}"
        )
        assert "ctx-run-001" in content, (
            f"Expected run_id 'ctx-run-001' in injected content; got: {content!r}"
        )

    def test_injection_is_not_persisted_in_history(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """The persisted user row contains only the original user message, not injected context."""
        db_path = app.config["DATABASE"]
        seed_run(
            db_path,
            run_id="ctx-run-002",
            name="ctx-persist-run",
            status="completed",
            created_at="2026-06-01T10:00:00+00:00",
            summary={"total_generation_kwh": 123.0},
        )

        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "ctx-persist-sid"

        anthropic_api.set_chunks(["ok"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "summarise run", "run_id": "ctx-run-002"},
        )
        assert resp.status_code == 200
        resp.get_data(as_text=True)

        # The persisted user row must be the ORIGINAL message only
        hist_resp = client.get("/assistant/history")
        messages = hist_resp.get_json()["messages"]
        user_msgs = [m for m in messages if m["role"] == "user"]
        assert user_msgs, "Expected at least one user message in history"
        stored_content = user_msgs[0]["content"]
        assert stored_content == "summarise run", (
            f"Persisted user message should be original text 'summarise run'; "
            f"got: {stored_content!r}"
        )
        # The injected run context must NOT appear in stored history
        assert "123.0" not in stored_content, (
            f"Injected summary value should NOT be persisted; stored: {stored_content!r}"
        )

    def test_unknown_run_id_streams_normally(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """POST with an unknown run_id streams normally (delta+done, no error/500)."""
        anthropic_api.set_chunks(["normal reply"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "what happened?", "run_id": "totally-unknown-run-xyz"},
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        event_types = [e.event for e in parse_sse_events(body)]
        assert "delta" in event_types, "Expected delta frames for unknown run_id"
        assert "done" in event_types, "Expected done frame for unknown run_id"
        assert "error" not in event_types, f"Unexpected error frame for unknown run_id: {body[:300]}"

        # Messages sent to API must NOT contain injected run context for unknown id
        msgs = anthropic_api.last_kwargs["messages"]
        last_content = msgs[-1]["content"]
        assert "totally-unknown-run-xyz" not in last_content, (
            f"Unknown run_id should not appear in injected content; got: {last_content!r}"
        )

    def test_no_run_id_leaves_user_message_unchanged(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """POST without run_id: messages[-1]['content'] equals exactly the user message."""
        anthropic_api.set_chunks(["plain reply"])

        resp = client.post(
            "/assistant/chat",
            json={"message": "plain message no run"},
        )
        assert resp.status_code == 200
        resp.get_data(as_text=True)

        msgs = anthropic_api.last_kwargs["messages"]
        last_msg = msgs[-1]
        assert last_msg["role"] == "user"
        assert last_msg["content"] == "plain message no run", (
            f"Without run_id, last message content should be the raw user text; "
            f"got: {last_msg['content']!r}"
        )
