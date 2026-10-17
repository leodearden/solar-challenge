# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for web/sse.py, the encoder and event catalogue of the dashboard's event streams."""

import dataclasses
import re
from typing import Any

import pytest

pytest.importorskip("flask")

from solar_challenge.web import sse
from solar_challenge.web.sse import (
    CHAT_DELTA,
    CHAT_DONE,
    CHAT_FAILED,
    CHAT_TOOL,
    ChatDelta,
    ChatDone,
    ChatFailed,
    ChatToolCall,
    SseEvent,
    sse_frame,
)
from tests._sse import SseFrame, parse_sse_events

_AWKWARD_TEXT = 'Hel\nlo "wörld"\r\n  done'
"""Line breaks json.dumps must escape for the data to stay on one line, a quote, and non-ASCII text."""

_CATALOGUE_SAMPLES = [
    pytest.param(
        CHAT_DELTA,
        ChatDelta(_AWKWARD_TEXT),
        SseFrame("delta", {"text": _AWKWARD_TEXT}),
        id="delta",
    ),
    pytest.param(
        CHAT_TOOL,
        ChatToolCall("explain_metric"),
        SseFrame("tool", {"name": "explain_metric"}),
        id="tool",
    ),
    pytest.param(CHAT_DONE, ChatDone(), SseFrame("done", {}), id="done"),
    pytest.param(
        CHAT_FAILED,
        ChatFailed(_AWKWARD_TEXT),
        SseFrame("failed", {"message": _AWKWARD_TEXT}),
        id="failed",
    ),
]
"""Each catalogue event, a sample payload, and the frame the reader must return for it.

The expected names and keys are literals, not read back from the catalogue: they are
the wire contract web/static/js/assistant.js reads.
"""


@pytest.mark.parametrize(
    ("event_id", "retry_ms"), [(None, None), (7, 1500)], ids=["bare", "id-and-retry"]
)
@pytest.mark.parametrize(("event", "payload", "expected"), _CATALOGUE_SAMPLES)
def test_every_catalogue_event_round_trips_through_the_reader_with_its_id_and_retry(
    event: SseEvent[Any],
    payload: Any,
    expected: SseFrame,
    event_id: int | None,
    retry_ms: int | None,
) -> None:
    frame = sse_frame(event, payload, event_id=event_id, retry_ms=retry_ms)

    assert parse_sse_events(frame) == [dataclasses.replace(expected, id=event_id, retry=retry_ms)]


def test_the_round_trip_covers_every_event_sse_declares() -> None:
    """An event the catalogue gains fails this test until a sample of it joins the round trip."""
    declared = {value for value in vars(sse).values() if isinstance(value, SseEvent)}

    assert declared == {param.values[0] for param in _CATALOGUE_SAMPLES}


def test_a_payload_that_is_not_its_event_s_payload_type_is_refused_naming_both() -> None:
    with pytest.raises(TypeError, match=r"'delta'.*ChatDelta.*ChatFailed"):
        sse_frame(CHAT_DELTA, ChatFailed("boom"))


def test_a_negative_retry_is_refused() -> None:
    """EventSource ignores a retry that is not all digits, so it would never see this one."""
    with pytest.raises(ValueError, match="-1"):
        sse_frame(CHAT_DONE, ChatDone(), retry_ms=-1)


@pytest.mark.parametrize(
    "name", ["", "fail\ned", "fail\red", "fail:ed"], ids=["empty", "lf", "cr", "colon"]
)
def test_an_event_name_that_is_empty_or_holds_a_cr_lf_or_colon_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(name))):
        SseEvent(name, ChatDone)
