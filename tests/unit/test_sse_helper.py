# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_sse.py, the shared reader of Server-Sent Events response bodies."""

import pytest

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


def test_a_frame_s_id_and_retry_lines_are_read_as_integers() -> None:
    body = 'event: progress\nid: 7\nretry: 1500\ndata: {"status": "running"}\n\n'

    assert parse_sse_events(body) == [
        SseFrame(event="progress", data={"status": "running"}, id=7, retry=1500)
    ]


def test_a_frame_without_id_or_retry_lines_has_none_for_both_even_after_a_frame_with_them() -> None:
    """A frame's id and retry are its own lines, not EventSource's lastEventId, which persists."""
    body = (
        'event: progress\nid: 7\nretry: 1500\ndata: {"status": "running"}\n\n'
        "event: done\ndata: {}\n\n"
    )

    assert parse_sse_events(body)[1] == SseFrame(event="done", data={}, id=None, retry=None)


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ("event: delta\nid: seven\ndata: {}\n\n", "id"),
        ("event: delta\nretry: soon\ndata: {}\n\n", "retry"),
        ("event: delta\nid: +7\ndata: {}\n\n", "id"),
        ("event: delta\nretry: -1\ndata: {}\n\n", "retry"),
        ("event: delta\nretry: 1_500\ndata: {}\n\n", "retry"),
        ("event: delta\nid:  7\ndata: {}\n\n", "id"),
        ("event: delta\nid: \uff17\ndata: {}\n\n", "id"),
    ],
    ids=[
        "id-word",
        "retry-word",
        "id-plus-sign",
        "retry-minus-sign",
        "retry-underscore",
        "id-leading-space",
        "id-fullwidth-digit",
    ],
)
def test_an_id_or_retry_that_is_not_all_ascii_digits_is_rejected(body: str, field: str) -> None:
    """EventSource reads only ASCII digits as a retry, and keeps an id as its raw text."""
    with pytest.raises(ValueError, match=f"SSE {field} line to carry only ASCII digits"):
        parse_sse_events(body)


def test_block_naming_no_event_yields_no_frame() -> None:
    """web/api.py's job-progress stream emits `:heartbeat` comment blocks like this one."""
    body = ':heartbeat\n\nevent: tool\ndata: {"name": "explain_metric"}\n\n'

    assert parse_sse_events(body) == [SseFrame(event="tool", data={"name": "explain_metric"})]


def test_frame_with_more_than_one_data_line_is_rejected() -> None:
    """The SSE spec joins a frame's data lines; the chat client keeps only the last."""
    body = 'event: delta\ndata: {"text": "Hel"}\ndata: {"text": "lo"}\n\n'

    with pytest.raises(ValueError, match="at most one data line"):
        parse_sse_events(body)


@pytest.mark.parametrize(
    "line",
    ["event: delta ", "event:  delta"],
    ids=["trailing", "leading"],
)
def test_event_name_with_surrounding_whitespace_is_rejected(line: str) -> None:
    """EventSource dispatches the name verbatim; the chat client trims it."""
    with pytest.raises(ValueError, match="no leading or trailing whitespace") as raised:
        parse_sse_events(f"{line}\ndata: {{}}\n\n")

    assert repr(line) in str(raised.value)


def test_event_name_with_an_inner_space_is_kept_as_written() -> None:
    """EventSource and the chat client both keep an inner space, so the reader does not refuse it.

    web/sse.py's SseEvent refuses any whitespace in a name it writes. The reader refuses
    only what clients decode differently, not everything the encoder would not write.
    """
    body = "event: fail ed\ndata: {}\n\n"

    assert parse_sse_events(body) == [SseFrame(event="fail ed", data={})]


@pytest.mark.parametrize(
    ("body", "field"),
    [
        ("event:delta\ndata: {}\n\n", "event"),
        ("event: delta\ndata:{}\n\n", "data"),
        ("event: delta\nid:7\ndata: {}\n\n", "id"),
        ("event: delta\nretry:7\ndata: {}\n\n", "retry"),
    ],
    ids=["event", "data", "id", "retry"],
)
def test_field_written_without_a_space_after_its_colon_is_rejected(body: str, field: str) -> None:
    """The SSE spec makes that space optional; the chat client requires it."""
    with pytest.raises(ValueError, match=f"'{field}: '"):
        parse_sse_events(body)
