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

from solar_challenge.web.chat_messages import get_chat_history, save_chat_message
from tests._chat_message_rows import insert_chat_message
from tests._css_classes import names_palette
from tests._html_page import element_attributes
from tests._run_summaries import home_summary
from tests._sse import SseFrame, parse_sse_events
from tests._web_app import database_of, point_store_config_at_a_missing_directory
from tests.unit.web_assistant._fakes import (
    FakeAnthropic,
    install_fake_anthropic,
    make_end_turn_stream,
    make_failing_stream,
    make_failing_stream_after,
    make_tool_use_stream,
    make_tool_use_stream_from_blocks,
    seed_run,
    tool_use_block,
)


def reply_text(events: list[SseFrame]) -> str:
    """Return the reply the delta frames in *events* carry, in stream order."""
    return "".join(e.data["text"] for e in events if e.event == "delta")


@pytest.fixture
def anthropic_api(monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
    """Stand a FakeAnthropic in for the Anthropic API; each test sets its reply with set_chunks()."""
    return install_fake_anthropic(monkeypatch)


class TestAssistantHistory:
    """Tests for GET /assistant/history endpoint."""

    def test_history_returns_seeded_messages(self, client: FlaskClient, app: Flask) -> None:
        """Seeding rows under a pinned session_id → GET /history returns them in order."""
        database = database_of(app)

        # Pin a session_id in the signed cookie
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "test-history-sid"

        save_chat_message(database, "test-history-sid", "user", "What is SOC?")
        save_chat_message(database, "test-history-sid", "assistant", "SOC is state of charge.")

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
        database = database_of(app)

        client_a = app.test_client()
        client_b = app.test_client()

        with client_a.session_transaction() as sess:
            sess["assistant_session_id"] = "sid-a"
        with client_b.session_transaction() as sess:
            sess["assistant_session_id"] = "sid-b"

        save_chat_message(database, "sid-a", "user", "message A")
        save_chat_message(database, "sid-b", "user", "message B")

        resp_a = client_a.get("/assistant/history")
        resp_b = client_b.get("/assistant/history")

        msgs_a = resp_a.get_json()["messages"]
        msgs_b = resp_b.get_json()["messages"]

        assert len(msgs_a) == 1
        assert msgs_a[0]["content"] == "message A"
        assert len(msgs_b) == 1
        assert msgs_b[0]["content"] == "message B"

    def test_history_answers_from_the_apps_database_after_its_store_config_names_a_missing_directory(
        self, client: FlaskClient, app: Flask, tmp_path: Path
    ) -> None:
        """GET /history reads the Database create_app built, whatever the app's store config names afterwards."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "moved-store-config-sid"
        save_chat_message(database_of(app), "moved-store-config-sid", "user", "What is SOC?")
        point_store_config_at_a_missing_directory(app, tmp_path / "missing")

        resp = client.get("/assistant/history")

        assert resp.status_code == 200
        assert [(m["role"], m["content"]) for m in resp.get_json()["messages"]] == [("user", "What is SOC?")]

    def test_history_lists_a_message_whose_stored_metadata_is_not_json_with_metadata_null(
        self, client: FlaskClient, app: Flask
    ) -> None:
        """A stored message whose metadata is not JSON leaves GET /history answering, with that message listed and its metadata null."""
        database = database_of(app)
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "damaged-metadata-history-sid"
        save_chat_message(database, "damaged-metadata-history-sid", "user", "What is SOC?")
        insert_chat_message(
            database, "damaged-metadata-history-sid", "assistant", "SOC is state of charge.", "{not json"
        )

        resp = client.get("/assistant/history")

        assert resp.status_code == 200
        assert [(m["role"], m["content"], m["metadata"]) for m in resp.get_json()["messages"]] == [
            ("user", "What is SOC?", None),
            ("assistant", "SOC is state of charge.", None),
        ]


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

    def test_a_chat_turn_is_stored_in_the_apps_database_after_its_store_config_names_a_missing_directory(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
        tmp_path: Path,
    ) -> None:
        """POST /chat stores its turn in the Database create_app built, whatever the app's store config names afterwards."""
        database = database_of(app)
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "moved-store-config-chat-sid"
        anthropic_api.set_chunks(["Hi", " there"])
        point_store_config_at_a_missing_directory(app, tmp_path / "missing")

        body = client.post("/assistant/chat", json={"message": "Hello"}).get_data(as_text=True)

        assert reply_text(parse_sse_events(body)) == "Hi there"
        stored = get_chat_history(database, "moved-store-config-chat-sid")
        assert [(m["role"], m["content"]) for m in stored] == [("user", "Hello"), ("assistant", "Hi there")]

    def test_chat_completes_when_sdk_reports_cache_tokens_as_none(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """The SDK types both cache-token usage fields Optional[int]; None counts as 0."""
        anthropic_api.set_streams(
            [
                make_end_turn_stream(
                    ["mock reply"],
                    cache_creation_input_tokens=None,
                    cache_read_input_tokens=None,
                )
            ]
        )
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "none-usage-sid"

        resp = client.post("/assistant/chat", json={"message": "hi there"})
        events = parse_sse_events(resp.get_data(as_text=True))

        event_types = [e.event for e in events]
        assert "failed" not in event_types, f"Unexpected failed frame: {events}"
        assert event_types[-1] == "done"
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        assert messages[1]["content"] == "mock reply"
        assert messages[1]["metadata"]["cache_creation_input_tokens"] == 0
        assert messages[1]["metadata"]["cache_read_input_tokens"] == 0

    def test_tool_use_turn_sums_cache_tokens_over_its_calls_counting_none_as_0(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A tool-use turn's metadata sums each cache-token count over the turn's API
        calls, a call that reports None adding 0, and records the model it called."""
        explain = {"metric": "self_sufficiency"}
        anthropic_api.set_streams(
            [
                make_tool_use_stream_from_blocks(
                    [tool_use_block("toolu_usage_1", "explain_metric", explain)],
                    cache_creation_input_tokens=40,
                    cache_read_input_tokens=3,
                ),
                make_tool_use_stream_from_blocks(
                    [tool_use_block("toolu_usage_2", "explain_metric", explain)],
                    cache_creation_input_tokens=None,
                    cache_read_input_tokens=None,
                ),
                make_end_turn_stream(
                    ["mock reply"],
                    cache_creation_input_tokens=2,
                    cache_read_input_tokens=50,
                ),
            ]
        )
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "none-usage-tool-use-sid"

        resp = client.post("/assistant/chat", json={"message": "explain self-sufficiency"})
        events = parse_sse_events(resp.get_data(as_text=True))

        event_types = [e.event for e in events]
        assert "failed" not in event_types, f"Unexpected failed frame: {events}"
        assert event_types[-1] == "done"
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [m["role"] for m in messages] == ["user", "assistant"]
        metadata = messages[1]["metadata"]
        assert metadata["cache_creation_input_tokens"] == 40 + 2
        assert metadata["cache_read_input_tokens"] == 3 + 50
        assert metadata["model"] == anthropic_api.last_kwargs["model"]

    def test_a_turn_replays_a_stored_reply_whose_metadata_is_not_json_and_streams_its_answer(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A session holding a reply whose stored metadata is not JSON still takes its next turn, which replays that reply and streams its answer."""
        database = database_of(app)
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "damaged-metadata-chat-sid"
        save_chat_message(database, "damaged-metadata-chat-sid", "user", "hello")
        insert_chat_message(database, "damaged-metadata-chat-sid", "assistant", "Hi there!", "{not json")
        anthropic_api.set_chunks(["Hello again."])

        body = client.post("/assistant/chat", json={"message": "again"}).get_data(as_text=True)

        assert reply_text(parse_sse_events(body)) == "Hello again."
        assert anthropic_api.last_kwargs["messages"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "Hi there!"},
            {"role": "user", "content": "again"},
        ]


class TestChatDegradation:
    """Graceful degradation: a chat that cannot start is answered with a lone ``failed`` SSE frame, never a 500."""

    def test_missing_api_key_answers_one_failed_frame_naming_the_key(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without ANTHROPIC_API_KEY, POST /chat answers 200 with exactly one ``failed`` frame: its
        data is just the message naming the key, and it carries no id or retry."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

        resp = client.post("/assistant/chat", json={"message": "hi"})

        assert resp.status_code == 200
        assert parse_sse_events(resp.get_data(as_text=True)) == [
            SseFrame("failed", {"message": "AI assistant is not configured: set ANTHROPIC_API_KEY."})
        ]

    @pytest.mark.parametrize(
        "body",
        [{"message": ""}, {"message": " \n"}, {}],
        ids=["empty", "whitespace", "absent"],
    )
    def test_a_message_without_text_returns_failed_frame_and_saves_no_turn(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
        body: dict[str, str],
    ) -> None:
        """A message without text gets a lone failed frame saying so; the model is not called and no chat turn is saved."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "empty-message-sid"

        resp = client.post("/assistant/chat", json=body)

        assert resp.status_code == 200
        assert parse_sse_events(resp.get_data(as_text=True)) == [
            SseFrame(event="failed", data={"message": "Message cannot be empty."})
        ]
        assert anthropic_api.calls == []
        assert client.get("/assistant/history").get_json() == {"messages": []}

    def test_client_construction_failure_returns_failed_frame_and_saves_no_turn(
        self,
        client: FlaskClient,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A client the SDK cannot construct, as from a malformed ANTHROPIC_BASE_URL,
        yields a failed frame naming that failure and saves no chat turn."""
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
        assert [e.event for e in events] == ["failed"], f"Expected a lone failed frame; got: {events}"
        assert malformed_port in events[0].data["message"], (
            f"Expected the error message to name {malformed_port!r}; got: {events[0].data}"
        )
        assert client.get("/assistant/history").get_json() == {"messages": []}

    def test_body_that_is_not_a_json_object_returns_failed_frame_naming_its_type_and_saves_no_turn(
        self, client: FlaskClient, anthropic_api: FakeAnthropic
    ) -> None:
        """A body that is not a JSON object gets a lone failed frame naming its type, and no chat turn is saved."""
        resp = client.post("/assistant/chat", json=[1])

        assert resp.status_code == 200
        assert "text/event-stream" in resp.content_type
        events = parse_sse_events(resp.get_data(as_text=True))
        assert [e.event for e in events] == ["failed"]
        assert events[0].data == {"message": "Request body must be a JSON object, got list"}
        assert anthropic_api.calls == []  # the model is never called
        assert client.get("/assistant/history").get_json() == {"messages": []}


class TestChatResponsePolicy:
    """POST /assistant/chat answers a chat it streams and one it refuses as the same uncached, unbuffered event stream."""

    @pytest.mark.parametrize(
        ("body", "model_called"),
        [({"message": "hi"}, True), ([1], False)],
        ids=["answered", "refused"],
    )
    def test_a_chat_is_served_with_the_event_stream_response_policy(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
        body: object,
        model_called: bool,
    ) -> None:
        anthropic_api.set_chunks(["ok"])

        resp = client.post("/assistant/chat", json=body)
        resp.get_data()

        assert bool(anthropic_api.calls) is model_called
        assert resp.status_code == 200
        assert resp.mimetype == "text/event-stream"
        assert resp.headers["Cache-Control"] == "no-cache"
        assert resp.headers["X-Accel-Buffering"] == "no"


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

    def test_the_one_assistant_chat_div_carries_the_chat_and_history_urls_assistant_js_reads(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """static/js/assistant.js finds the chat by its id, assistant-chat, and reads two URLs from
        it: data-chat-url, where it posts each message, and data-history-url, where it loads the
        chat history."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-dummy")
        page = client.get("/assistant").get_data(as_text=True)

        chat_roots = [div for div in element_attributes(page, "div") if div.get("id") == "assistant-chat"]

        assert [(root.get("data-chat-url"), root.get("data-history-url")) for root in chat_roots] == [
            ("/assistant/chat", "/assistant/history")
        ]

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

    def test_configure_notice_is_drawn_in_the_warning_palette(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without ANTHROPIC_API_KEY, the configure-notice is drawn in the token file's
        tailwind.warning role, and no other div of the page is."""
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        resp = client.get("/assistant")

        warning_classes = {
            css_class
            for div in element_attributes(resp.get_data(as_text=True), "div")
            for css_class in (div.get("class") or "").split()
            if names_palette(css_class, "warning")
        }

        assert warning_classes == {
            "border-warning-300",
            "bg-warning-50",
            "text-warning-800",
            "dark:border-warning-700",
            "dark:bg-warning-900/20",
            "dark:text-warning-300",
        }

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
        assert "failed" not in event_types, f"Unexpected failed frame: {body[:500]}"

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


class TestEveryTurnStoresAReplyWithText:
    """Every turn that reaches the model stores one reply with text, and the replay skips a reply without text.

    The Messages API refuses a message with empty content anywhere but last,
    while it combines consecutive user turns into one. So one stored empty reply
    makes every later request of the session fail, and a user turn left
    unanswered does not.

    Every turn that reaches the model therefore stores one reply with text,
    however it ends: finished; failed, i.e. an API error before or during the
    reply (overload, rate limit after retries, bad key or model, network); or cut
    short, i.e. a client disconnect closes the response and raises GeneratorExit
    at a yield, which ``except Exception`` does not catch.

    The replay leaves out a stored reply without text, which earlier releases
    stored for a failed turn.
    """

    @pytest.mark.parametrize("stored_reply", ["", " \n"], ids=["empty", "whitespace"])
    def test_a_stored_reply_without_text_is_left_out_of_the_replay(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
        stored_reply: str,
    ) -> None:
        """A reply stored without text, as the old error path stored one, is not replayed."""
        database = database_of(app)
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "replay-skip-sid"
        save_chat_message(database, "replay-skip-sid", "user", "hello")
        save_chat_message(
            database,
            "replay-skip-sid",
            "assistant",
            stored_reply,
            metadata={"error": "overloaded_error: Overloaded", "truncated": True},
        )

        client.post("/assistant/chat", json={"message": "again"}).get_data(as_text=True)

        assert anthropic_api.last_kwargs["messages"] == [
            {"role": "user", "content": "hello"},
            {"role": "user", "content": "again"},
        ]

    def test_an_api_error_before_the_first_token_is_stored_as_the_notice_the_user_was_shown(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A turn whose request fails stores the error notice it sent as its reply, which the next turn replays."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "api-error-sid"
        anthropic_api.set_streams(
            [
                make_failing_stream(RuntimeError("overloaded_error: Overloaded")),
                make_end_turn_stream(["Hello again."]),
            ]
        )

        failed = parse_sse_events(
            client.post("/assistant/chat", json={"message": "hello"}).get_data(as_text=True)
        )
        client.post("/assistant/chat", json={"message": "again"}).get_data(as_text=True)

        assert [f.event for f in failed] == ["failed"]
        notice = failed[0].data["message"]
        assert anthropic_api.calls[1]["messages"] == [
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": notice},
            {"role": "user", "content": "again"},
        ]
        stored_reply = client.get("/assistant/history").get_json()["messages"][1]
        assert stored_reply["metadata"] == {"error": "overloaded_error: Overloaded", "truncated": True}

    def test_an_api_error_after_the_first_token_stores_the_text_streamed_before_it(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A turn that fails mid-reply stores the text it streamed, not the notice, and marks the error."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "mid-reply-error-sid"
        anthropic_api.set_streams(
            [make_failing_stream_after(["Hello"], RuntimeError("overloaded_error: Overloaded"))]
        )

        frames = parse_sse_events(
            client.post("/assistant/chat", json={"message": "hi"}).get_data(as_text=True)
        )

        assert [f.event for f in frames] == ["delta", "failed"]
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [(m["role"], m["content"]) for m in messages] == [("user", "hi"), ("assistant", "Hello")]
        assert messages[1]["metadata"] == {"error": "overloaded_error: Overloaded", "truncated": True}

    def test_a_reply_the_model_ends_without_text_is_stored_with_text(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A reply the model ends without any text is stored with text, so the next turn replays it."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "no-text-sid"
        anthropic_api.set_streams([make_end_turn_stream([]), make_end_turn_stream(["ok"])])

        client.post("/assistant/chat", json={"message": "hello"}).get_data(as_text=True)
        client.post("/assistant/chat", json={"message": "again"}).get_data(as_text=True)

        replayed = anthropic_api.calls[1]["messages"]
        assert [m["role"] for m in replayed] == ["user", "assistant", "user"]
        assert all(m["content"].strip() for m in replayed), replayed

    def test_a_disconnect_after_the_first_frame_stores_the_text_streamed_so_far(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A client that leaves after the first delta frame leaves that text stored as a truncated reply.

        The disconnect also closes the model's stream, which was still open when
        that frame was sent, so no connection to the model outlives the turn.
        """
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "disconnect-sid"
        model_stream = make_end_turn_stream(["Hello", " world"])
        anthropic_api.set_streams([model_stream])

        response = client.post("/assistant/chat", json={"message": "hi"}, buffered=False)
        first = next(iter(response.response))
        model_stream.__exit__.assert_not_called()
        response.close()

        model_stream.__exit__.assert_called_once()
        assert parse_sse_events(first.decode()) == [SseFrame(event="delta", data={"text": "Hello"})]
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [(m["role"], m["content"]) for m in messages] == [("user", "hi"), ("assistant", "Hello")]
        assert messages[1]["metadata"] == {"truncated": True}

    def test_a_disconnect_after_a_tool_call_keeps_the_tools_the_turn_ran(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A client that leaves after a tool call leaves a truncated reply that names the tools the turn ran."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "disconnect-tool-sid"
        anthropic_api.set_streams(
            [
                make_tool_use_stream("toolu_cut_1", "explain_metric", {"metric": "self_sufficiency"}),
                make_end_turn_stream(["Self-sufficiency is", " the share of demand met on site."]),
            ]
        )

        response = client.post(
            "/assistant/chat", json={"message": "what is self-sufficiency?"}, buffered=False
        )
        frames = iter(response.response)
        read = [next(frames), next(frames)]
        response.close()

        assert [f.event for f in parse_sse_events(b"".join(read).decode())] == ["tool", "delta"]
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "what is self-sufficiency?"),
            ("assistant", "Self-sufficiency is"),
        ]
        assert messages[1]["metadata"]["invoked_tools"] == ["explain_metric"]
        assert messages[1]["metadata"]["truncated"] is True


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
        summary_marker = 987.65
        seed_run(
            database_of(app),
            run_id="ctx-run-001",
            name="ctx-signal-run",
            status="completed",
            created_at="2026-06-01T09:00:00+00:00",
            summary=home_summary(total_generation_kwh=summary_marker),
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
        seed_run(
            database_of(app),
            run_id="ctx-run-002",
            name="ctx-persist-run",
            status="completed",
            created_at="2026-06-01T10:00:00+00:00",
            summary=home_summary(total_generation_kwh=123.0),
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

    def test_run_context_leaves_the_cached_system_block_unchanged(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A turn with run context sends the system block a turn without it sends, so the cached prompt prefix still matches."""
        seed_run(
            database_of(app),
            run_id="ctx-run-003",
            name="ctx-cache-run",
            status="completed",
            created_at="2026-06-01T11:00:00+00:00",
            summary=home_summary(total_generation_kwh=456.0),
        )
        anthropic_api.set_chunks(["ok"])

        client.post("/assistant/chat", json={"message": "summarise", "run_id": "ctx-run-003"}).get_data()
        client.post("/assistant/chat", json={"message": "summarise"}).get_data()

        with_context, without_context = anthropic_api.calls
        assert "ctx-run-003" in with_context["messages"][-1]["content"], (
            f"Expected the run context in the user's message; got: {with_context['messages'][-1]!r}"
        )
        assert with_context["system"] == without_context["system"]

    def test_unknown_run_id_streams_normally(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """POST with an unknown run_id streams normally (delta+done, no failed frame, no 500)."""
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
        assert "failed" not in event_types, f"Unexpected failed frame for unknown run_id: {body[:300]}"

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
