# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_sse.py, the shared reader of Server-Sent Events response bodies."""

from tests._sse import SseFrame, parse_sse_events


def test_multi_frame_body_parses_to_its_frames_in_stream_order() -> None:
    body = (
        'event: delta\ndata: {"text": "Hel"}\n\n'
        'event: delta\ndata: {"text": "lo"}\n\n'
        "event: done\ndata: {}\n\n"
    )

    assert parse_sse_events(body) == [
        SseFrame(event="delta", data={"text": "Hel"}),
        SseFrame(event="delta", data={"text": "lo"}),
        SseFrame(event="done", data={}),
    ]


def test_frame_without_a_data_line_has_none_data() -> None:
    """The next frame's data must not attach to the frame that has none."""
    body = "event: ping\n\nevent: done\ndata: {}\n\n"

    assert parse_sse_events(body) == [
        SseFrame(event="ping", data=None),
        SseFrame(event="done", data={}),
    ]


def test_non_json_data_is_kept_as_the_raw_string() -> None:
    body = "event: error\ndata: not json\n\n"

    assert parse_sse_events(body) == [SseFrame(event="error", data="not json")]


def test_block_naming_no_event_yields_no_frame() -> None:
    """web/api.py's job-progress stream emits `:heartbeat` comment blocks like this one."""
    body = ':heartbeat\n\nevent: tool\ndata: {"name": "explain_metric"}\n\n'

    assert parse_sse_events(body) == [SseFrame(event="tool", data={"name": "explain_metric"})]
