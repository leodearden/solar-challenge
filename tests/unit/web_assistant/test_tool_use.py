# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the tool-use path of the AI assistant's chat.

That is the _TOOLS surface the chat offers the model, _dispatch_tool's routing to
the handlers, and the tool-use loop in POST /assistant/chat that runs the model's
tool calls.
"""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.jobs import JobManager

from tests._sse import parse_sse_events
from tests.unit.web_assistant._fakes import (
    FakeAnthropic,
    install_fake_anthropic,
    make_end_turn_stream,
    make_fake_stream,
    make_tool_use_stream,
    seed_run,
)


def dispatch_dependencies(tmp_path: Path, **overrides: Any) -> dict[str, Any]:
    """The db_path, job_manager and data_dir ``_dispatch_tool`` requires, rooted in *tmp_path*.

    For tests that do not care which values they pass; keyword *overrides*
    replace individual entries for those that do.
    """
    return {
        "db_path": tmp_path / "assistant.db",
        "job_manager": MagicMock(spec=JobManager),
        "data_dir": tmp_path,
        **overrides,
    }


@pytest.fixture
def sequence_mock_anthropic(monkeypatch: pytest.MonkeyPatch) -> FakeAnthropic:
    """Stand a FakeAnthropic in for the Anthropic API; each test scripts its replies with set_streams()."""
    return install_fake_anthropic(monkeypatch)


class TestToolSurface:
    """Tests for _TOOLS list and _dispatch_tool router."""

    def test_tools_fixed_order_for_cache_stability(self) -> None:
        """[t['name'] for t in _TOOLS] == 6-tool order (fixed, cache-safe)."""
        from solar_challenge.web.assistant import _TOOLS

        names = [t["name"] for t in _TOOLS]
        assert names == [
            "explain_metric",
            "suggest_config",
            "get_run_results",
            "list_recent_runs",
            "run_home_simulation",
            "run_fleet_simulation",
        ], (
            f"Expected fixed 6-tool order, got {names}"
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

    def test_dispatch_explain_metric(self, tmp_path: Path) -> None:
        """_dispatch_tool('explain_metric', {...}) returns the same dict as explain_metric()."""
        from solar_challenge.web.assistant import _dispatch_tool, explain_metric

        result = _dispatch_tool(
            "explain_metric",
            {"metric": "self_consumption_ratio"},
            **dispatch_dependencies(tmp_path),
        )
        expected = explain_metric("self_consumption_ratio")
        assert result == expected, (
            f"_dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_dispatch_suggest_config(self, tmp_path: Path) -> None:
        """_dispatch_tool('suggest_config', {...}) returns the same dict as suggest_config()."""
        from solar_challenge.web.assistant import _dispatch_tool, suggest_config

        result = _dispatch_tool(
            "suggest_config",
            {"annual_consumption_kwh": 3100, "goal": "self_sufficiency"},
            **dispatch_dependencies(tmp_path),
        )
        expected = suggest_config(3100, "self_sufficiency")
        assert result == expected, (
            f"_dispatch_tool result mismatch: {result!r} vs {expected!r}"
        )

    def test_dispatch_unknown_returns_error_dict(self, tmp_path: Path) -> None:
        """_dispatch_tool with unknown name returns a dict with 'error' key, does NOT raise."""
        from solar_challenge.web.assistant import _dispatch_tool

        try:
            result = _dispatch_tool(
                "nonexistent_tool",
                {},
                **dispatch_dependencies(tmp_path),
            )
        except Exception as exc:
            raise AssertionError(
                f"_dispatch_tool should not raise for unknown tool; got: {exc!r}"
            ) from exc
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, f"Expected 'error' key in result: {result}"


class TestToolUseLoop:
    """Boundary and termination tests for the manual agentic tool-use loop."""

    def test_tool_sse_frame_emitted(
        self,
        client: FlaskClient,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """A tool_use response causes a 'tool' SSE frame with the tool name."""
        TOOL_ID = "toolu_explain_001"

        sequence_mock_anthropic.set_streams([
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

    def test_stream_called_twice_and_tool_result_has_canonical_band(
        self,
        client: FlaskClient,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """stream() called twice; 2nd call's messages[-1] contains the canonical band string."""
        from solar_challenge.web.assistant import _METRIC_TABLE
        TOOL_ID = "toolu_explain_002"
        CANONICAL_BAND = _METRIC_TABLE["self_consumption_ratio"]["uk_benchmark_band"]

        sequence_mock_anthropic.set_streams([
            make_tool_use_stream(TOOL_ID, "explain_metric", {"metric": "self_consumption_ratio"}),
            make_end_turn_stream(["Result follows."]),
        ])

        resp = client.post("/assistant/chat", json={"message": "what is self-consumption ratio?"})
        assert resp.status_code == 200
        resp.get_data(as_text=True)

        call_kwargs_list = sequence_mock_anthropic.calls
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

    def test_tools_param_present_and_ordered(
        self,
        client: FlaskClient,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """stream() kwargs carry 'tools' with 6-tool names in fixed order."""
        sequence_mock_anthropic.set_streams([
            make_end_turn_stream(["reply"]),
        ])

        client.post("/assistant/chat", json={"message": "ping"})

        call_kwargs_list = sequence_mock_anthropic.calls
        assert call_kwargs_list, "Expected at least one stream() call"
        first_kwargs = call_kwargs_list[0]
        assert "tools" in first_kwargs, f"Expected 'tools' in stream() kwargs: {first_kwargs.keys()}"
        tool_names = [t["name"] for t in first_kwargs["tools"]]
        assert tool_names == [
            "explain_metric",
            "suggest_config",
            "get_run_results",
            "list_recent_runs",
            "run_home_simulation",
            "run_fleet_simulation",
        ], (
            f"Expected 6-tool order, got {tool_names}"
        )

    def test_done_frame_terminates_stream(
        self,
        client: FlaskClient,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """After a tool_use + end_turn, the SSE stream ends with a 'done' frame."""
        TOOL_ID = "toolu_explain_003"

        sequence_mock_anthropic.set_streams([
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
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """A model that always returns tool_use is bounded by _MAX_TOOL_ITERATIONS."""
        from solar_challenge.web.assistant import _MAX_TOOL_ITERATIONS

        # Build an infinite sequence of tool_use streams
        TOOL_ID_PREFIX = "toolu_inf_"
        infinite_streams = [
            make_tool_use_stream(
                f"{TOOL_ID_PREFIX}{i}",
                "explain_metric",
                {"metric": "self_consumption_ratio"},
            )
            for i in range(_MAX_TOOL_ITERATIONS + 10)  # more than the cap
        ]
        sequence_mock_anthropic.set_streams(infinite_streams)

        resp = client.post("/assistant/chat", json={"message": "explain forever"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        # stream() should be called exactly _MAX_TOOL_ITERATIONS times
        call_count = len(sequence_mock_anthropic.calls)
        assert call_count == _MAX_TOOL_ITERATIONS, (
            f"Expected exactly {_MAX_TOOL_ITERATIONS} stream() calls (loop cap), "
            f"got {call_count}"
        )

        # Stream must still terminate cleanly (done or error frame, no hang)
        events = parse_sse_events(body)
        event_types = [e.event for e in events]
        assert "done" in event_types or "error" in event_types, (
            f"Expected stream to terminate with done or error frame; got: {event_types}"
        )

    def test_final_message_without_stop_reason_streams_reply(
        self,
        client: FlaskClient,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """A final message with no stop_reason, as make_fake_stream builds it,
        still yields delta frames and a done frame."""
        sequence_mock_anthropic.set_streams([
            make_fake_stream(["Hello", " world"]),
        ])

        resp = client.post("/assistant/chat", json={"message": "hi"})
        assert resp.status_code == 200
        body = resp.get_data(as_text=True)

        events = parse_sse_events(body)
        event_types = [e.event for e in events]
        assert "delta" in event_types, f"Expected delta frames; got: {event_types}"
        assert "done" in event_types, f"Expected done frame; got: {event_types}"
        assert "error" not in event_types, f"Unexpected error frame; got: {event_types}"


class TestRunLookupToolSurface:
    """get_run_results and list_recent_runs as the chat registers, dispatches and calls them."""

    def test_run_lookup_tools_input_schema_is_object_with_required(self) -> None:
        """get_run_results and list_recent_runs have type 'object' and non-empty required."""
        from solar_challenge.web.assistant import _TOOLS

        run_lookup_tools = {t["name"]: t for t in _TOOLS if t["name"] in ("get_run_results", "list_recent_runs")}
        assert "get_run_results" in run_lookup_tools, "get_run_results missing from _TOOLS"
        assert "list_recent_runs" in run_lookup_tools, "list_recent_runs missing from _TOOLS"

        for name, tool in run_lookup_tools.items():
            schema = tool["input_schema"]
            assert schema.get("type") == "object", f"{name}: input_schema.type must be 'object'"
            required = schema.get("required", [])
            assert required, f"{name}: required list must be non-empty"

        # Specific required fields
        grr_required = run_lookup_tools["get_run_results"]["input_schema"]["required"]
        assert "run_id_or_name" in grr_required, (
            f"get_run_results must require 'run_id_or_name'; got {grr_required}"
        )
        lrr_required = run_lookup_tools["list_recent_runs"]["input_schema"]["required"]
        assert "limit" in lrr_required, (
            f"list_recent_runs must require 'limit'; got {lrr_required}"
        )

    def test_dispatch_get_run_results_with_db_path(self, tmp_path: Path) -> None:
        """_dispatch_tool('get_run_results', {...}, db_path) returns same dict as handler."""
        from solar_challenge.web.assistant import _dispatch_tool, get_run_results

        db_path = tmp_path / "disp_grr_test.db"
        seed_run(
            db_path,
            run_id="disp-run-001",
            name="dispatch-run",
            status="completed",
            created_at="2026-04-01T10:00:00+00:00",
            summary={"total_generation_kwh": 500.0},
        )

        result = _dispatch_tool(
            "get_run_results",
            {"run_id_or_name": "disp-run-001"},
            **dispatch_dependencies(tmp_path, db_path=str(db_path)),
        )
        expected = get_run_results("disp-run-001", db_path)

        assert result == expected, f"dispatch result mismatch: {result!r} vs {expected!r}"

    def test_dispatch_list_recent_runs_with_db_path(self, tmp_path: Path) -> None:
        """_dispatch_tool('list_recent_runs', {'limit': 5}, db_path) returns same dict as handler."""
        from solar_challenge.web.assistant import _dispatch_tool, list_recent_runs

        db_path = tmp_path / "disp_lrr_test.db"
        seed_run(
            db_path,
            run_id="disp-lrr-001",
            name="lrr-dispatch-run",
            status="completed",
            created_at="2026-04-01T11:00:00+00:00",
            summary={"self_consumption_ratio": 0.55},
        )

        result = _dispatch_tool(
            "list_recent_runs",
            {"limit": 5},
            **dispatch_dependencies(tmp_path, db_path=str(db_path)),
        )
        expected = list_recent_runs(5, db_path)

        assert result == expected, f"dispatch result mismatch: {result!r} vs {expected!r}"

    def test_end_to_end_get_run_results_tool_use_signal(
        self,
        client: FlaskClient,
        app: Flask,
        sequence_mock_anthropic: FakeAnthropic,
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
        sequence_mock_anthropic.set_streams([
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
        call_kwargs_list = sequence_mock_anthropic.calls
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

    def test_six_tools_fixed_order(self) -> None:
        """_TOOLS has exactly 6 tools in the fixed cache-stable order."""
        from solar_challenge.web.assistant import _TOOLS

        names = [t["name"] for t in _TOOLS]
        assert names == [
            "explain_metric",
            "suggest_config",
            "get_run_results",
            "list_recent_runs",
            "run_home_simulation",
            "run_fleet_simulation",
        ], f"Expected 6-tool order; got {names}"

    def test_run_home_simulation_schema(self) -> None:
        """run_home_simulation has object input_schema with pv_kw required."""
        from solar_challenge.web.assistant import _TOOLS

        tool = next((t for t in _TOOLS if t["name"] == "run_home_simulation"), None)
        assert tool is not None, "run_home_simulation missing from _TOOLS"
        schema = tool["input_schema"]
        assert schema.get("type") == "object", (
            f"run_home_simulation input_schema.type must be 'object'; got {schema.get('type')!r}"
        )
        required = schema.get("required", [])
        assert required, "run_home_simulation input_schema.required must be non-empty"
        assert "pv_kw" in required, (
            f"run_home_simulation must require 'pv_kw'; got {required}"
        )

    def test_run_fleet_simulation_schema(self) -> None:
        """run_fleet_simulation has object input_schema with n_homes required."""
        from solar_challenge.web.assistant import _TOOLS

        tool = next((t for t in _TOOLS if t["name"] == "run_fleet_simulation"), None)
        assert tool is not None, "run_fleet_simulation missing from _TOOLS"
        schema = tool["input_schema"]
        assert schema.get("type") == "object", (
            f"run_fleet_simulation input_schema.type must be 'object'; got {schema.get('type')!r}"
        )
        required = schema.get("required", [])
        assert required, "run_fleet_simulation input_schema.required must be non-empty"
        assert "n_homes" in required, (
            f"run_fleet_simulation must require 'n_homes'; got {required}"
        )

    def test_dispatch_run_home_simulation(self, tmp_path: Path) -> None:
        """_dispatch_tool('run_home_simulation', {...}, job_manager=mock) returns handler result."""
        from solar_challenge.web.assistant import _dispatch_tool, run_home_simulation

        jm = MagicMock()
        jm.submit_home_job.return_value = ("job-h", "run-h")

        params = {"pv_kw": 4, "battery_kwh": 5, "days": 7, "location": "bristol"}
        direct = run_home_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm2 = MagicMock()
        jm2.submit_home_job.return_value = ("job-h", "run-h")
        via_dispatch = _dispatch_tool(
            "run_home_simulation",
            params,
            db_path=str(tmp_path / "t.db"),
            job_manager=jm2,
            data_dir=str(tmp_path),
        )

        assert direct == via_dispatch, (
            f"Expected dispatch result to match handler result; got {via_dispatch!r} vs {direct!r}"
        )

    def test_dispatch_run_fleet_simulation(self, tmp_path: Path) -> None:
        """_dispatch_tool('run_fleet_simulation', {...}, job_manager=mock) returns handler result."""
        from solar_challenge.web.assistant import _dispatch_tool, run_fleet_simulation

        params = {"n_homes": 2, "pv_kw": 4, "location": "bristol", "days": 7}

        jm = MagicMock()
        jm.submit_fleet_job.return_value = ("job-f", "run-f")
        direct = run_fleet_simulation(params, jm, str(tmp_path / "t.db"), str(tmp_path))

        jm2 = MagicMock()
        jm2.submit_fleet_job.return_value = ("job-f", "run-f")
        via_dispatch = _dispatch_tool(
            "run_fleet_simulation",
            params,
            db_path=str(tmp_path / "t.db"),
            job_manager=jm2,
            data_dir=str(tmp_path),
        )

        assert direct == via_dispatch, (
            f"Expected dispatch result to match handler result; got {via_dispatch!r} vs {direct!r}"
        )


class TestSimulationToolUseSignal:
    """E2E boundary tests: mock Anthropic + mock JobManager across the tool_result seam."""

    def test_run_home_simulation_tool_use_signal(
        self,
        client: FlaskClient,
        app: Flask,
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """run_home_simulation: tool SSE frame emitted; submit_home_job called with correct config
        against the app's DATABASE and DATA_DIR; tool_result contains /results/home/<run_id>."""
        RUN_ID = "run-home-001"
        JOB_ID = "job-home-001"
        TOOL_ID = "toolu_rhs_e2e_001"

        # Install mock JobManager with submit_home_job return value
        jm = MagicMock()
        jm.submit_home_job.return_value = (JOB_ID, RUN_ID)
        app.extensions["job_manager"] = jm

        sequence_mock_anthropic.set_streams([
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
        call_kwargs_list = sequence_mock_anthropic.calls
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
        sequence_mock_anthropic: FakeAnthropic,
    ) -> None:
        """run_fleet_simulation: submit_fleet_job receives 3-home configs list against the app's
        DATABASE and DATA_DIR; tool_result contains /results/fleet/<run_id>."""
        RUN_ID = "run-fleet-001"
        JOB_ID = "job-fleet-001"
        TOOL_ID = "toolu_rfs_e2e_001"

        jm = MagicMock()
        jm.submit_fleet_job.return_value = (JOB_ID, RUN_ID)
        app.extensions["job_manager"] = jm

        sequence_mock_anthropic.set_streams([
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
        call_kwargs_list = sequence_mock_anthropic.calls
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
