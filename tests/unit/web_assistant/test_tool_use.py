# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the tool-use path of the AI assistant's chat.

That is the TOOLS surface the chat offers the model, dispatch_tool's routing to
the handlers and its refusal of a malformed input, and the tool-use loop in
POST /assistant/chat that runs the model's tool calls.
"""

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import replace
from functools import partial
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.assistant import (
    MAX_TOOL_ITERATIONS,
    METRIC_TABLE,
    TOOL_CALL_LIMIT_NOTICE,
    TOOLS,
    ToolContext,
    dispatch_tool,
    explain_metric,
    get_run_results,
    list_recent_runs,
    run_fleet_simulation,
    run_home_simulation,
    suggest_config,
)
from solar_challenge.web.fleet_components import FLEET_COMPONENTS
from solar_challenge.web.number_fields import as_finite_float_within, as_whole_number
from solar_challenge.web.storage import RunStorage

from tests._job_manager_double import autospecced_job_manager
from tests._sse import SseFrame, parse_sse_events
from tests.unit.web_assistant._fakes import (
    FakeAnthropic,
    install_fake_anthropic,
    make_end_turn_stream,
    make_fake_stream,
    make_stopped_stream,
    make_tool_use_stream,
    make_tool_use_stream_from_blocks,
    redacted_thinking_block,
    seed_run,
    text_block,
    thinking_block,
    tool_use_block,
)


def tool_context(tmp_path: Path, **overrides: Any) -> ToolContext:
    """The ToolContext ``dispatch_tool`` runs a tool in, rooted in *tmp_path*.

    For tests that do not care which collaborators the tool gets; keyword
    *overrides* replace individual fields for those that do.
    """
    defaults = ToolContext(
        db_path=tmp_path / "assistant.db",
        data_dir=tmp_path,
        job_manager=autospecced_job_manager(),
    )
    return replace(defaults, **overrides)


@pytest.fixture
def anthropic_api(monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
    """Stand a FakeAnthropic in for the Anthropic API; each test scripts its replies with set_streams()."""
    return install_fake_anthropic(monkeypatch)


class TestToolSurface:
    """Tests for the TOOLS surface and the dispatch_tool router."""

    def test_tools_is_a_tuple_of_plain_dicts_the_sdk_can_json_encode(self) -> None:
        """TOOLS is a tuple, so the order of the tools in the cached prompt prefix cannot change
        at runtime, and its schemas come back from a JSON round trip unchanged, so none holds a
        read-only mapping, which the SDK's JSON encoding rejects."""
        assert isinstance(TOOLS, tuple), f"Expected TOOLS to be a tuple; got {type(TOOLS).__name__}"
        assert json.loads(json.dumps(TOOLS)) == list(TOOLS)

    def test_every_tool_entry_has_required_keys(self) -> None:
        """Every entry in TOOLS has 'name', 'description', and 'input_schema'."""
        for tool in TOOLS:
            assert "name" in tool, f"Missing 'name' in tool: {tool}"
            assert "description" in tool, f"Missing 'description' in tool: {tool}"
            assert "input_schema" in tool, f"Missing 'input_schema' in tool: {tool}"

    def test_every_tool_input_schema_is_object_with_required(self) -> None:
        """Every input_schema has type=='object' and a non-empty 'required' list."""
        for tool in TOOLS:
            schema = tool["input_schema"]
            assert isinstance(schema, dict), f"input_schema must be dict for {tool['name']!r}"
            assert schema.get("type") == "object", (
                f"input_schema.type must be 'object' for {tool['name']!r}; got {schema.get('type')!r}"
            )
            assert "required" in schema, f"input_schema missing 'required' for {tool['name']!r}"
            assert isinstance(schema["required"], list) and schema["required"], (
                f"input_schema.required must be non-empty list for {tool['name']!r}"
            )

    @pytest.mark.parametrize("schema", TOOLS, ids=lambda schema: schema["name"])
    def test_each_offered_tool_refuses_a_call_without_its_required_fields_naming_them(
        self, tmp_path: Path, schema: Mapping[str, Any]
    ) -> None:
        """A call to a tool TOOLS offers that sends none of its fields is answered with an error
        naming every field its schema requires, and nothing else: the name reaches the tool that
        holds this schema, and that tool applies the schema's required list."""
        result = dispatch_tool(schema["name"], {}, tool_context(tmp_path))

        assert list(result) == ["error"], f"Expected an error and nothing else; got {result!r}"
        assert "Unknown tool" not in result["error"], f"Expected the tool to be found; got {result!r}"
        unnamed = [field for field in schema["input_schema"]["required"] if field not in result["error"]]
        assert not unnamed, f"Expected the error to name {unnamed}; got {result['error']!r}"

    def test_dispatch_explain_metric(self, tmp_path: Path) -> None:
        """dispatch_tool('explain_metric', {...}) returns the same dict as explain_metric()."""
        result = dispatch_tool(
            "explain_metric",
            {"metric": "self_consumption_ratio"},
            tool_context(tmp_path),
        )
        expected = explain_metric("self_consumption_ratio")
        assert result == expected, (
            f"dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_dispatch_suggest_config(self, tmp_path: Path) -> None:
        """dispatch_tool('suggest_config', {...}) returns the same dict as suggest_config()."""
        result = dispatch_tool(
            "suggest_config",
            {"annual_consumption_kwh": 3100, "goal": "self_sufficiency"},
            tool_context(tmp_path),
        )
        expected = suggest_config(3100, "self_sufficiency")
        assert result == expected, (
            f"dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_an_unknown_tool_name_is_answered_with_the_available_tools_in_order(
        self, tmp_path: Path
    ) -> None:
        """A call naming no tool is answered, not raised, with an error that lists the tools
        TOOLS offers, in TOOLS' order, so the model can call one it was offered instead."""
        result = dispatch_tool("nonexistent_tool", {}, tool_context(tmp_path))

        available = ", ".join(tool["name"] for tool in TOOLS)
        assert result == {"error": f"Unknown tool 'nonexistent_tool'. Available tools: {available}."}


class TestToolUseLoop:
    """Boundary and termination tests for the manual agentic tool-use loop."""

    def test_tool_sse_frame_emitted(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A tool_use response causes a 'tool' SSE frame with the tool name."""
        TOOL_ID = "toolu_explain_001"

        anthropic_api.set_streams([
            make_tool_use_stream(TOOL_ID, "explain_metric", {"metric": "self_consumption_ratio"}),
            make_end_turn_stream(["The self-consumption ratio means X."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "explain my self-consumption ratio"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        events = parse_sse_events(body)
        tool_events = [e for e in events if e.event == "tool"]
        assert tool_events, f"Expected at least one 'tool' SSE frame; events: {events}"
        assert tool_events[0].data["name"] == "explain_metric", (
            f"Expected tool frame with name='explain_metric', got: {tool_events[0].data}"
        )

    def test_a_reply_after_a_tool_call_streams_one_delta_frame_per_chunk(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """The reply the model streams after a tool call reaches the client as it streams, one
        delta frame per chunk, as a reply without a tool call does. A loop that only sees each
        model call's whole message would send it as one frame."""
        anthropic_api.set_streams([
            make_tool_use_stream("toolu_stream_001", "explain_metric", {"metric": "self_sufficiency"}),
            make_end_turn_stream(["Self-sufficiency is", " the share of demand", " met on site."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "what is self-sufficiency?"})

        assert parse_sse_events(resp.get_data(as_text=True)) == [
            SseFrame(event="tool", data={"name": "explain_metric"}),
            SseFrame(event="delta", data={"text": "Self-sufficiency is"}),
            SseFrame(event="delta", data={"text": " the share of demand"}),
            SseFrame(event="delta", data={"text": " met on site."}),
            SseFrame(event="done", data={}),
        ]

    def test_stream_called_twice_and_tool_result_has_canonical_band(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """stream() called twice; 2nd call's messages[-1] contains the canonical band string."""
        TOOL_ID = "toolu_explain_002"
        CANONICAL_BAND = METRIC_TABLE["self_consumption_ratio"]["uk_benchmark_band"]

        anthropic_api.set_streams([
            make_tool_use_stream(TOOL_ID, "explain_metric", {"metric": "self_consumption_ratio"}),
            make_end_turn_stream(["Result follows."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "what is self-consumption ratio?"})
        assert resp.status_code == 200
        resp.get_data(as_text=True)

        call_kwargs_list = anthropic_api.calls
        assert len(call_kwargs_list) == 2, (
            f"Expected stream() to be called exactly 2 times, got {len(call_kwargs_list)}"
        )

        # The second call's messages must end with a user turn containing the tool_result
        second_messages = call_kwargs_list[1]["messages"]
        last_msg = second_messages[-1]
        assert last_msg["role"] == "user", (
            f"Expected last message in 2nd call to be role='user', got {last_msg['role']!r}"
        )

        # The tool_result content must carry the canonical band (data-seam cross)
        content = last_msg["content"]
        assert isinstance(content, list), f"Expected content list in tool_result turn: {content}"
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block in last user message; content: {content}"
        )
        assert tool_result_block.get("tool_use_id") == TOOL_ID, (
            f"tool_use_id mismatch: expected {TOOL_ID!r}, got {tool_result_block.get('tool_use_id')!r}"
        )
        result_content = tool_result_block.get("content", "")
        assert CANONICAL_BAND in result_content, (
            f"Expected canonical band string in tool_result content.\n"
            f"Band: {CANONICAL_BAND!r}\n"
            f"Content: {result_content!r}"
        )

    def test_tools_param_equals_TOOLS(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """stream() receives TOOLS, in TOOLS' order, as its 'tools' kwarg."""
        anthropic_api.set_streams([
            make_end_turn_stream(["reply"]),
        ])

        client.post("/assistant/chat", json={"message": "ping"})

        call_kwargs_list = anthropic_api.calls
        assert call_kwargs_list, "Expected at least one stream() call"
        first_kwargs = call_kwargs_list[0]
        assert "tools" in first_kwargs, f"Expected 'tools' in stream() kwargs: {first_kwargs.keys()}"
        assert first_kwargs["tools"] == TOOLS, (
            f"Expected stream()'s 'tools' kwarg to equal TOOLS; got tools {[t['name'] for t in first_kwargs['tools']]}"
        )

    def test_done_frame_terminates_stream(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """After a tool_use + end_turn, the SSE stream ends with a 'done' frame."""
        TOOL_ID = "toolu_explain_003"

        anthropic_api.set_streams([
            make_tool_use_stream(TOOL_ID, "explain_metric", {"metric": "self_consumption_ratio"}),
            make_end_turn_stream(["done"]),
        ])

        resp = client.post("/assistant/chat", json={"message": "explain"})
        body = resp.get_data(as_text=True)
        events = parse_sse_events(body)
        event_types = [e.event for e in events]
        assert "done" in event_types, (
            f"Expected 'done' frame in event types; got: {event_types}"
        )

    def test_termination_bounded_by_max_tool_iterations(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A model that calls a tool on every reply is called MAX_TOOL_ITERATIONS times.
        The turn then streams TOOL_CALL_LIMIT_NOTICE as its whole reply, stores it as
        the reply and ends with a done frame."""
        with client.session_transaction() as sess:
            sess["assistant_session_id"] = "tool-cap-sid"
        TOOL_ID_PREFIX = "toolu_inf_"
        infinite_streams = [
            make_tool_use_stream(
                f"{TOOL_ID_PREFIX}{i}",
                "explain_metric",
                {"metric": "self_consumption_ratio"},
            )
            for i in range(MAX_TOOL_ITERATIONS + 10)  # more than the cap
        ]
        anthropic_api.set_streams(infinite_streams)

        resp = client.post("/assistant/chat", json={"message": "explain forever"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        call_count = len(anthropic_api.calls)
        assert call_count == MAX_TOOL_ITERATIONS, (
            f"Expected exactly {MAX_TOOL_ITERATIONS} stream() calls (loop cap), "
            f"got {call_count}"
        )

        events = parse_sse_events(body)
        assert [e.data["text"] for e in events if e.event == "delta"] == [TOOL_CALL_LIMIT_NOTICE], (
            f"Expected the notice to be the reply's only text; events: {events}"
        )
        assert events[-1].event == "done", f"Expected the stream to end with 'done'; events: {events}"
        messages = client.get("/assistant/history").get_json()["messages"]
        assert [(m["role"], m["content"]) for m in messages] == [
            ("user", "explain forever"),
            ("assistant", TOOL_CALL_LIMIT_NOTICE),
        ]

    @pytest.mark.parametrize("stop_reason", ["end_turn", "max_tokens", "stop_sequence", "refusal", None])
    def test_a_reply_that_stops_for_any_reason_but_tool_use_ends_the_turn(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
        stop_reason: str | None,
    ) -> None:
        """A reply that stops for any reason but tool_use is the turn's last model call, and
        the turn ends with done. pause_turn is left out: only server tools, which TOOLS does
        not offer, pause a turn."""
        anthropic_api.set_streams([
            make_stopped_stream(stop_reason, ["Partial", " answer"]),
            make_end_turn_stream(["A call the turn must not make."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "hi"})
        events = parse_sse_events(resp.get_data(as_text=True))

        assert len(anthropic_api.calls) == 1, (
            f"Expected one model call; got {len(anthropic_api.calls)}"
        )
        assert "".join(e.data["text"] for e in events if e.event == "delta") == "Partial answer"
        assert events[-1].event == "done", f"Expected the stream to end with 'done'; events: {events}"

    def test_final_message_without_stop_reason_streams_reply(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """A final message with no stop_reason, as make_fake_stream builds it,
        still yields delta frames and a done frame."""
        anthropic_api.set_streams([
            make_fake_stream(["Hello", " world"]),
        ])

        resp = client.post("/assistant/chat", json={"message": "hi"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        events = parse_sse_events(body)
        event_types = [e.event for e in events]
        assert "delta" in event_types, f"Expected delta frames; got: {event_types}"
        assert "done" in event_types, f"Expected done frame; got: {event_types}"
        assert "failed" not in event_types, f"Unexpected failed frame; got: {event_types}"

    def test_thinking_before_a_tool_call_is_replayed_unchanged(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """When the model thinks before it calls a tool, the next request replays that
        turn exactly as the model returned it: its thinking blocks, signature included,
        ahead of the tool_use block."""
        TOOL_ID = "toolu_think_001"
        thinking = thinking_block(
            "They want self-sufficiency explained; explain_metric has its UK band.",
            signature="sig",
        )
        redacted = redacted_thinking_block("EmwKAhgBEgy3va3pzix/LafPsn4a")
        tool_call = tool_use_block(TOOL_ID, "explain_metric", {"metric": "self_sufficiency"})

        anthropic_api.set_streams([
            make_tool_use_stream_from_blocks([thinking, redacted, tool_call]),
            make_end_turn_stream(["Self-sufficiency is the share of demand met on site."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "what is self-sufficiency?"})
        assert resp.status_code == 200
        event_types = [e.event for e in parse_sse_events(resp.get_data(as_text=True))]
        assert "done" in event_types, f"Expected done frame; got: {event_types}"
        assert "failed" not in event_types, f"Unexpected failed frame; got: {event_types}"

        calls = anthropic_api.calls
        assert len(calls) == 2, f"Expected stream() called exactly 2 times; got {len(calls)}"
        assistant_turn, tool_result_turn = calls[1]["messages"][-2:]
        assert assistant_turn["role"] == "assistant", (
            f"Expected the assistant turn second to last in the 2nd call; got {assistant_turn!r}"
        )
        assert list(assistant_turn["content"]) == [thinking, redacted, tool_call], (
            "Expected the assistant turn to replay the model's blocks unchanged and in order.\n"
            f"Returned: {[thinking, redacted, tool_call]!r}\n"
            f"Replayed: {assistant_turn['content']!r}"
        )
        assert tool_result_turn["role"] == "user", (
            f"Expected the tool_result turn last in the 2nd call; got {tool_result_turn!r}"
        )
        assert [b["tool_use_id"] for b in tool_result_turn["content"]] == [TOOL_ID], (
            f"Expected one tool_result, answering {TOOL_ID!r}; got {tool_result_turn['content']!r}"
        )

    def test_a_turn_with_text_and_two_tool_calls_is_replayed_whole_and_answered_in_order(
        self,
        client: FlaskClient,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """When the model thinks, says something, then calls two tools in one turn, the
        next request replays that turn whole, its text block included, and the
        tool_result turn answers both calls in the order the model made them."""
        FIRST_TOOL_ID = "toolu_mixed_001"
        SECOND_TOOL_ID = "toolu_mixed_002"
        blocks = [
            thinking_block("Explain the metric, then size a system that raises it.", signature="sig"),
            text_block("I'll explain self-sufficiency, then suggest a setup."),
            tool_use_block(FIRST_TOOL_ID, "explain_metric", {"metric": "self_sufficiency"}),
            tool_use_block(
                SECOND_TOOL_ID,
                "suggest_config",
                {"annual_consumption_kwh": 3100, "goal": "self_sufficiency"},
            ),
        ]

        anthropic_api.set_streams([
            make_tool_use_stream_from_blocks(blocks),
            make_end_turn_stream(["Here is the metric, and a setup that raises it."]),
        ])

        resp = client.post(
            "/assistant/chat",
            json={"message": "explain self-sufficiency and suggest a setup for 3100 kWh a year"},
        )
        assert resp.status_code == 200
        event_types = [e.event for e in parse_sse_events(resp.get_data(as_text=True))]
        assert "done" in event_types, f"Expected done frame; got: {event_types}"
        assert "failed" not in event_types, f"Unexpected failed frame; got: {event_types}"

        calls = anthropic_api.calls
        assert len(calls) == 2, f"Expected stream() called exactly 2 times; got {len(calls)}"
        assistant_turn, tool_result_turn = calls[1]["messages"][-2:]
        assert assistant_turn["role"] == "assistant", (
            f"Expected the assistant turn second to last in the 2nd call; got {assistant_turn!r}"
        )
        assert list(assistant_turn["content"]) == blocks, (
            "Expected the assistant turn to replay the model's blocks unchanged and in order.\n"
            f"Returned: {blocks!r}\n"
            f"Replayed: {assistant_turn['content']!r}"
        )
        assert tool_result_turn["role"] == "user", (
            f"Expected the tool_result turn last in the 2nd call; got {tool_result_turn!r}"
        )
        answered_ids = [b["tool_use_id"] for b in tool_result_turn["content"]]
        assert answered_ids == [FIRST_TOOL_ID, SECOND_TOOL_ID], (
            "Expected one tool_result per tool call, in the order the model made them; "
            f"got {tool_result_turn['content']!r}"
        )


class TestRunLookupToolSurface:
    """get_run_results and list_recent_runs as the chat registers, dispatches and calls them."""

    def test_run_lookup_tools_required_fields(self) -> None:
        """get_run_results requires 'run_id_or_name' and list_recent_runs requires 'limit'."""
        run_lookup_tools = {t["name"]: t for t in TOOLS if t["name"] in ("get_run_results", "list_recent_runs")}
        assert "get_run_results" in run_lookup_tools, "get_run_results missing from TOOLS"
        assert "list_recent_runs" in run_lookup_tools, "list_recent_runs missing from TOOLS"

        grr_required = run_lookup_tools["get_run_results"]["input_schema"]["required"]
        assert "run_id_or_name" in grr_required, (
            f"get_run_results must require 'run_id_or_name'; got {grr_required}"
        )
        lrr_required = run_lookup_tools["list_recent_runs"]["input_schema"]["required"]
        assert "limit" in lrr_required, (
            f"list_recent_runs must require 'limit'; got {lrr_required}"
        )

    def test_dispatch_get_run_results_with_db_path(self, tmp_path: Path) -> None:
        """dispatch_tool('get_run_results', {...}) with the seeded db_path in its context returns same dict as handler."""
        db_path = tmp_path / "disp_grr_test.db"
        seed_run(
            db_path,
            run_id="disp-run-001",
            name="dispatch-run",
            status="completed",
            created_at="2026-04-01T10:00:00+00:00",
            summary={"total_generation_kwh": 500.0},
        )

        result = dispatch_tool(
            "get_run_results",
            {"run_id_or_name": "disp-run-001"},
            tool_context(tmp_path, db_path=str(db_path)),
        )
        expected = get_run_results("disp-run-001", RunStorage(db_path=db_path, data_dir=tmp_path))

        assert result == expected, f"dispatch result mismatch: {result!r} vs {expected!r}"

    def test_dispatch_list_recent_runs_with_db_path(self, tmp_path: Path) -> None:
        """dispatch_tool('list_recent_runs', {'limit': 5}) with the seeded db_path in its context returns same dict as handler."""
        db_path = tmp_path / "disp_lrr_test.db"
        seed_run(
            db_path,
            run_id="disp-lrr-001",
            name="lrr-dispatch-run",
            status="completed",
            created_at="2026-04-01T11:00:00+00:00",
            summary={"self_consumption_ratio": 0.55},
        )

        result = dispatch_tool(
            "list_recent_runs",
            {"limit": 5},
            tool_context(tmp_path, db_path=str(db_path)),
        )
        expected = list_recent_runs(5, db_path)

        assert result == expected, f"dispatch result mismatch: {result!r} vs {expected!r}"

    def test_dispatch_list_recent_runs_with_a_limit_of_zero_lists_runs_as_the_handler_does(
        self, tmp_path: Path
    ) -> None:
        """A limit of 0 is a whole number, so it is not refused: list_recent_runs' own rule for a
        limit <= 0 decides how many runs it lists."""
        db_path = tmp_path / "disp_lrr_zero.db"
        seed_run(
            db_path,
            run_id="disp-lrr-zero",
            name="lrr-zero-run",
            status="completed",
            created_at="2026-04-01T12:00:00+00:00",
            summary={"self_consumption_ratio": 0.5},
        )

        result = dispatch_tool("list_recent_runs", {"limit": 0}, tool_context(tmp_path, db_path=db_path))

        assert "error" not in result, f"Expected runs, not an error; got {result!r}"
        assert result == list_recent_runs(0, db_path)

    def test_end_to_end_get_run_results_tool_use_signal(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
        tmp_path: Path,
    ) -> None:
        """SSE 'tool' frame emitted for get_run_results; 2nd stream contains seeded summary value."""
        db_path = app.config["DATABASE"]
        summary_val = 999.75
        seed_run(
            db_path,
            run_id="e2e-run-001",
            name="e2e-signal-run",
            status="completed",
            created_at="2026-05-01T08:00:00+00:00",
            summary={"total_generation_kwh": summary_val},
        )

        TOOL_ID = "toolu_grr_e2e_001"
        anthropic_api.set_streams([
            make_tool_use_stream(
                TOOL_ID, "get_run_results", {"run_id_or_name": "e2e-run-001"}
            ),
            make_end_turn_stream(["The run generated lots of power."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "summarise my last run"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        # 1. A 'tool' SSE frame named 'get_run_results' must be emitted
        events = parse_sse_events(body)
        tool_events = [e for e in events if e.event == "tool"]
        assert tool_events, f"Expected at least one 'tool' SSE frame; events: {events}"
        assert tool_events[0].data["name"] == "get_run_results", (
            f"Expected tool frame 'get_run_results'; got: {tool_events[0].data}"
        )

        # 2. The 2nd stream() call's messages[-1] tool_result content must contain the summary value
        call_kwargs_list = anthropic_api.calls
        assert len(call_kwargs_list) == 2, (
            f"Expected stream() called exactly 2 times; got {len(call_kwargs_list)}"
        )
        second_messages = call_kwargs_list[1]["messages"]
        last_msg = second_messages[-1]
        assert last_msg["role"] == "user"
        content = last_msg["content"]
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block in last user message; content: {content}"
        )
        result_content = tool_result_block.get("content", "")
        # The seeded summary value must appear in the serialised tool_result
        assert str(summary_val) in result_content, (
            f"Expected summary value {summary_val!r} in tool_result content.\n"
            f"Content: {result_content!r}"
        )


class TestSimulationToolSurface:
    """run_home_simulation and run_fleet_simulation as the chat registers and dispatches them."""

    def test_run_home_simulation_requires_pv_kw(self) -> None:
        """run_home_simulation's input_schema requires 'pv_kw'."""
        tool = next((t for t in TOOLS if t["name"] == "run_home_simulation"), None)
        assert tool is not None, "run_home_simulation missing from TOOLS"
        schema = tool["input_schema"]
        required = schema.get("required", [])
        assert "pv_kw" in required, (
            f"run_home_simulation must require 'pv_kw'; got {required}"
        )

    def test_run_fleet_simulation_requires_n_homes(self) -> None:
        """run_fleet_simulation's input_schema requires 'n_homes'."""
        tool = next((t for t in TOOLS if t["name"] == "run_fleet_simulation"), None)
        assert tool is not None, "run_fleet_simulation missing from TOOLS"
        schema = tool["input_schema"]
        required = schema.get("required", [])
        assert "n_homes" in required, (
            f"run_fleet_simulation must require 'n_homes'; got {required}"
        )

    @pytest.mark.parametrize("tool_name", ["run_home_simulation", "run_fleet_simulation"])
    def test_trigger_tool_offers_start_and_end_as_optional_iso_dates(self, tool_name: str) -> None:
        """A trigger tool lists start and end as ISO 8601 date strings and requires no window field, so a call that sends none keeps the default window."""
        tool = next((t for t in TOOLS if t["name"] == tool_name), None)
        assert tool is not None, f"{tool_name} missing from TOOLS"
        schema = tool["input_schema"]
        properties = schema["properties"]
        for field in ("start", "end"):
            assert field in properties, (
                f"{tool_name} must list {field!r}; got {sorted(properties)}"
            )
            assert (properties[field]["type"], properties[field].get("format")) == (
                "string",
                "date",
            )
        assert not ({"days", "start", "end"} & set(schema["required"])), (
            f"{tool_name} must require no window field; got {schema['required']}"
        )

    def test_trigger_tools_list_their_window_identically(self) -> None:
        """Both trigger tools read their window with the same parse_date_range, so the model must be told one window grammar."""
        props = {t["name"]: t["input_schema"]["properties"] for t in TOOLS}
        window_fields = ("days", "start", "end")
        assert [props["run_home_simulation"][f] for f in window_fields] == [
            props["run_fleet_simulation"][f] for f in window_fields
        ]

    def test_dispatch_run_home_simulation(self, tmp_path: Path) -> None:
        """dispatch_tool('run_home_simulation', {...}) with a mock job_manager in its context returns handler result."""
        jm = autospecced_job_manager()
        jm.submit_home_job.return_value = ("job-h", "run-h")

        params = {"pv_kw": 4, "battery_kwh": 5, "days": 7, "location": "bristol"}
        direct = run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm2 = autospecced_job_manager()
        jm2.submit_home_job.return_value = ("job-h", "run-h")
        via_dispatch = dispatch_tool(
            "run_home_simulation",
            params,
            tool_context(tmp_path, job_manager=jm2),
        )

        assert direct == via_dispatch, (
            f"Expected dispatch result to match handler result; got {via_dispatch!r} vs {direct!r}"
        )

    def test_dispatch_run_fleet_simulation(self, tmp_path: Path) -> None:
        """dispatch_tool('run_fleet_simulation', {...}) with a mock job_manager in its context returns handler result."""
        params = {"n_homes": 2, "pv_kw": 4, "location": "bristol", "days": 7}

        jm = autospecced_job_manager()
        jm.submit_fleet_job.return_value = ("job-f", "run-f")
        direct = run_fleet_simulation(
            2, {"pv_kw": 4, "location": "bristol", "days": 7}, jm, str(tmp_path / "t.db"), str(tmp_path)
        )

        jm2 = autospecced_job_manager()
        jm2.submit_fleet_job.return_value = ("job-f", "run-f")
        via_dispatch = dispatch_tool(
            "run_fleet_simulation",
            params,
            tool_context(tmp_path, job_manager=jm2),
        )

        assert direct == via_dispatch, (
            f"Expected dispatch result to match handler result; got {via_dispatch!r} vs {direct!r}"
        )

    @pytest.mark.parametrize(("n_homes", "fleet_size"), [(0, 1), (10**6, 100)])
    def test_dispatch_run_fleet_simulation_clamps_n_homes_as_the_handler_does(
        self, tmp_path: Path, n_homes: int, fleet_size: int
    ) -> None:
        """An n_homes outside 1–100 is a whole number, so it is not refused: run_fleet_simulation
        clamps it, and submits a fleet of the nearest size it allows."""
        jm = autospecced_job_manager()
        jm.submit_fleet_job.return_value = ("job-f", "run-f")

        result = dispatch_tool(
            "run_fleet_simulation",
            {"n_homes": n_homes, "pv_kw": 4, "days": 7},
            tool_context(tmp_path, job_manager=jm),
        )

        assert result == {"run_id": "run-f", "results_url": "/results/fleet/run-f"}
        assert len(jm.submit_fleet_job.call_args.kwargs["configs"]) == fleet_size


class TestSimulationToolUseSignal:
    """E2E boundary tests: mock Anthropic + mock JobManager across the tool_result seam."""

    def test_run_home_simulation_tool_use_signal(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """run_home_simulation: tool SSE frame emitted; submit_home_job called with correct config
        against the app's DATABASE and DATA_DIR; tool_result contains /results/home/<run_id>."""
        RUN_ID = "run-home-001"
        JOB_ID = "job-home-001"
        TOOL_ID = "toolu_rhs_e2e_001"

        # Install mock JobManager with submit_home_job return value
        jm = autospecced_job_manager()
        jm.submit_home_job.return_value = (JOB_ID, RUN_ID)
        app.extensions["job_manager"] = jm

        anthropic_api.set_streams([
            make_tool_use_stream(
                TOOL_ID,
                "run_home_simulation",
                {"pv_kw": 4, "battery_kwh": 5, "days": 7},
            ),
            make_end_turn_stream(["Started your run."]),
        ])

        resp = client.post(
            "/assistant/chat",
            json={"message": "run a 4 kW home with a 5 kWh battery for 7 days"},
        )
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        # 1. 'tool' SSE frame named 'run_home_simulation' must be emitted
        events = parse_sse_events(body)
        tool_events = [e for e in events if e.event == "tool"]
        assert tool_events, f"Expected at least one 'tool' SSE frame; events: {events}"
        assert tool_events[0].data["name"] == "run_home_simulation", (
            f"Expected tool frame 'run_home_simulation'; got: {tool_events[0].data}"
        )

        # 2. submit_home_job called once with correct HomeConfig
        jm.submit_home_job.assert_called_once()
        call_kwargs = jm.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs.args[0]
        assert config.pv_config.capacity_kw == 4.0, (
            f"Expected pv capacity_kw=4.0; got {config.pv_config.capacity_kw}"
        )
        assert config.battery_config is not None, "Expected battery_config set"
        assert config.battery_config.capacity_kwh == 5.0, (
            f"Expected battery capacity_kwh=5.0; got {config.battery_config.capacity_kwh}"
        )
        assert call_kwargs.kwargs["db_path"] == app.config["DATABASE"]
        assert call_kwargs.kwargs["data_dir"] == app.config["DATA_DIR"]

        # 3. 2nd stream() call's messages[-1] tool_result content must contain results_url
        call_kwargs_list = anthropic_api.calls
        assert len(call_kwargs_list) == 2, (
            f"Expected stream() called exactly 2 times; got {len(call_kwargs_list)}"
        )
        second_messages = call_kwargs_list[1]["messages"]
        last_msg = second_messages[-1]
        assert last_msg["role"] == "user"
        content = last_msg["content"]
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block in last user message; content: {content}"
        )
        result_content = tool_result_block.get("content", "")
        expected_url = f"/results/home/{RUN_ID}"
        assert expected_url in result_content, (
            f"Expected '{expected_url}' in tool_result content.\n"
            f"Content: {result_content!r}"
        )

    def test_run_fleet_simulation_tool_use_signal(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
    ) -> None:
        """run_fleet_simulation: submit_fleet_job receives 3-home configs list against the app's
        DATABASE and DATA_DIR; tool_result contains /results/fleet/<run_id>."""
        RUN_ID = "run-fleet-001"
        JOB_ID = "job-fleet-001"
        TOOL_ID = "toolu_rfs_e2e_001"

        jm = autospecced_job_manager()
        jm.submit_fleet_job.return_value = (JOB_ID, RUN_ID)
        app.extensions["job_manager"] = jm

        anthropic_api.set_streams([
            make_tool_use_stream(
                TOOL_ID,
                "run_fleet_simulation",
                {"n_homes": 3, "pv_kw": 4, "days": 7},
            ),
            make_end_turn_stream(["Fleet run started."]),
        ])

        resp = client.post(
            "/assistant/chat",
            json={"message": "run a 3-home fleet"},
        )
        assert resp.status_code == 200
        # Consume the response body to force the SSE generator to run to completion
        resp.get_data(as_text=True)

        # submit_fleet_job called once with a 3-home configs list
        jm.submit_fleet_job.assert_called_once()
        call_kwargs = jm.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) == 3, (
            f"Expected submit_fleet_job configs list of length 3; got {len(configs)}"
        )
        assert call_kwargs.kwargs["db_path"] == app.config["DATABASE"]
        assert call_kwargs.kwargs["data_dir"] == app.config["DATA_DIR"]

        # 2nd stream's tool_result content must contain the fleet results_url
        call_kwargs_list = anthropic_api.calls
        assert len(call_kwargs_list) == 2, (
            f"Expected stream() called exactly 2 times; got {len(call_kwargs_list)}"
        )
        second_messages = call_kwargs_list[1]["messages"]
        last_msg = second_messages[-1]
        content = last_msg["content"]
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block; content: {content}"
        )
        result_content = tool_result_block.get("content", "")
        expected_url = f"/results/fleet/{RUN_ID}"
        assert expected_url in result_content, (
            f"Expected '{expected_url}' in tool_result content.\n"
            f"Content: {result_content!r}"
        )

    @pytest.mark.parametrize(
        ("tool_name", "tool_input"),
        [
            pytest.param(
                "run_home_simulation", {"pv_kw": 4, "heat_pump": "ASHP"}, id="home"
            ),
            pytest.param(
                "run_fleet_simulation",
                {"n_homes": 2, "pv_kw": 4, "heat_pump": "ASHP"},
                id="fleet",
            ),
        ],
    )
    def test_non_mapping_heat_pump_comes_back_as_a_tool_result_error(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
        tool_name: str,
        tool_input: dict[str, Any],
    ) -> None:
        """A heat_pump the model sends as a non-object reaches it as a tool_result error naming
        the block, and the turn goes on to its reply; nothing is submitted."""
        jm = autospecced_job_manager()
        app.extensions["job_manager"] = jm

        anthropic_api.set_streams([
            make_tool_use_stream("toolu_hp_not_mapping", tool_name, tool_input),
            make_end_turn_stream(["Let me fix that."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "run it with a heat pump"})
        events = parse_sse_events(resp.get_data(as_text=True))

        failed_events = [e for e in events if e.event == "failed"]
        assert not failed_events, f"Expected no 'failed' SSE frame; events: {events}"
        assert events[-1].event == "done", f"Expected the stream to end with 'done'; events: {events}"
        assert len(anthropic_api.calls) == 2, (
            f"Expected stream() called exactly 2 times; got {len(anthropic_api.calls)}"
        )
        content = anthropic_api.calls[1]["messages"][-1]["content"]
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block in last user message; content: {content}"
        )
        error = json.loads(tool_result_block["content"])["error"]
        assert "heat_pump must be a mapping, got str" in error, (
            f"Expected the tool_result error to name heat_pump; got: {error!r}"
        )
        jm.submit_home_job.assert_not_called()
        jm.submit_fleet_job.assert_not_called()


class TestMalformedToolInput:
    """A tool input the model leaves a field out of, or sends a value its field's reader refuses, comes back to it as an error naming the field."""

    @pytest.mark.parametrize(
        ("tool_name", "tool_input", "field"),
        [
            pytest.param(
                "run_fleet_simulation", {"n_homes": math.inf, "pv_kw": 4}, "n_homes", id="n_homes-infinite"
            ),
            pytest.param(
                "suggest_config", {"goal": "bill_savings"}, "annual_consumption_kwh", id="consumption-absent"
            ),
            pytest.param(
                "suggest_config",
                {"annual_consumption_kwh": -5, "goal": "bill_savings"},
                "annual_consumption_kwh",
                id="consumption-negative",
            ),
            pytest.param(
                "suggest_config",
                {"annual_consumption_kwh": True, "goal": "bill_savings"},
                "annual_consumption_kwh",
                id="consumption-boolean",
            ),
            pytest.param(
                "suggest_config",
                {"annual_consumption_kwh": 10**400, "goal": "bill_savings"},
                "annual_consumption_kwh",
                id="consumption-too-large-for-a-float",
            ),
            pytest.param("list_recent_runs", {"limit": math.inf}, "limit", id="limit-infinite"),
        ],
    )
    def test_a_malformed_tool_input_comes_back_to_the_model_as_an_error_naming_the_field(
        self,
        client: FlaskClient,
        app: Flask,
        anthropic_api: FakeAnthropic,
        tool_name: str,
        tool_input: dict[str, Any],
        field: str,
    ) -> None:
        """The model's next call receives a tool_result whose only key is an error naming the
        field, and the value it sent if it sent one; the turn goes on to its reply, and nothing
        is submitted."""
        jm = autospecced_job_manager()
        app.extensions["job_manager"] = jm

        anthropic_api.set_streams([
            make_tool_use_stream("toolu_malformed_input", tool_name, tool_input),
            make_end_turn_stream(["Let me fix that."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "go ahead"})
        events = parse_sse_events(resp.get_data(as_text=True))

        failed_events = [e for e in events if e.event == "failed"]
        assert not failed_events, f"Expected no 'failed' SSE frame; events: {events}"
        assert events[-1].event == "done", f"Expected the stream to end with 'done'; events: {events}"
        assert len(anthropic_api.calls) == 2, (
            f"Expected stream() called exactly 2 times; got {len(anthropic_api.calls)}"
        )
        content = anthropic_api.calls[1]["messages"][-1]["content"]
        tool_result_block = next(
            (b for b in content if isinstance(b, dict) and b.get("type") == "tool_result"),
            None,
        )
        assert tool_result_block is not None, (
            f"Expected tool_result block in last user message; content: {content}"
        )
        result = json.loads(tool_result_block["content"])
        assert list(result) == ["error"], f"Expected an error and nothing else; got {result!r}"
        assert field in result["error"], f"Expected the error to name {field}; got {result['error']!r}"
        if field in tool_input:
            assert repr(tool_input[field]) in result["error"], (
                f"Expected the error to show the value sent, {tool_input[field]!r}; got {result['error']!r}"
            )
        jm.submit_home_job.assert_not_called()
        jm.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("tool_name", "tool_input", "field"),
        [
            pytest.param("explain_metric", {"metric": 5}, "metric", id="explain_metric"),
            pytest.param(
                "suggest_config", {"annual_consumption_kwh": 3100, "goal": None}, "goal", id="suggest_config"
            ),
            pytest.param("get_run_results", {"run_id_or_name": 7}, "run_id_or_name", id="get_run_results"),
        ],
    )
    def test_a_text_field_that_is_not_a_string_is_refused_naming_the_field_and_the_value(
        self, tmp_path: Path, tool_name: str, tool_input: dict[str, Any], field: str
    ) -> None:
        """A text field sent as anything but a string is refused, not read as that value's str()."""
        result = dispatch_tool(tool_name, tool_input, tool_context(tmp_path))

        assert result == {"error": f"{field} must be a string, got {tool_input[field]!r}"}

    @pytest.mark.parametrize(
        ("tool_name", "tool_input", "read_field"),
        [
            pytest.param(
                "list_recent_runs",
                {"limit": 2.5},
                partial(as_whole_number, 2.5, "limit"),
                id="limit-fraction",
            ),
            pytest.param(
                "run_fleet_simulation",
                {"n_homes": True, "pv_kw": 4},
                partial(as_whole_number, True, "n_homes"),
                id="n_homes-boolean",
            ),
            pytest.param(
                "suggest_config",
                {"annual_consumption_kwh": 0, "goal": "bill_savings"},
                partial(
                    as_finite_float_within, 0, "annual_consumption_kwh", *FLEET_COMPONENTS["load"].fixed_range
                ),
                id="consumption-zero",
            ),
        ],
    )
    def test_a_number_field_is_refused_as_the_shared_number_reader_refuses_it(
        self,
        tmp_path: Path,
        tool_name: str,
        tool_input: dict[str, Any],
        read_field: Callable[[], object],
    ) -> None:
        """A number field reads through web/number_fields.py's reader for its kind, so a value that
        reader refuses comes back with that reader's own error. The sizing tool reads consumption
        over the range the trigger tools take, so it refuses zero."""
        with pytest.raises(ValueError) as refusal:
            read_field()

        assert dispatch_tool(tool_name, tool_input, tool_context(tmp_path)) == {"error": str(refusal.value)}
