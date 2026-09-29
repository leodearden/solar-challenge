# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to a Server-Sent Events response body.

Usage::

    from tests._sse import parse_sse_events

    frames = parse_sse_events(resp.get_data(as_text=True))
    assert [f.event for f in frames] == ["delta", "done"]
"""

import json
from dataclasses import dataclass
from itertools import groupby
from typing import Any


@dataclass(frozen=True)
class SseFrame:
    """One Server-Sent Events frame: the event it names and its decoded data payload."""

    event: str
    data: Any


def parse_sse_events(body: str) -> list[SseFrame]:
    """Return the frames in *body* that name an event, in stream order.

    Blank lines separate frames. In each frame the last ``event: `` line names the
    event, and the last ``data: `` line carries the payload: JSON-decoded when it
    parses, the raw string when it does not, and None when the line is absent or
    empty. A frame with no ``event: `` line, such as a ``:heartbeat`` comment,
    yields no SseFrame.
    """
    runs = groupby(body.splitlines(), key=_is_blank)
    frames = (_read_frame(list(lines)) for blank, lines in runs if not blank)
    return [frame for frame in frames if frame is not None]


def _is_blank(line: str) -> bool:
    return not line.strip()


def _read_frame(lines: list[str]) -> SseFrame | None:
    event = _last_prefixed_value(lines, "event: ")
    if event is None:
        return None
    payload = _last_prefixed_value(lines, "data: ")
    return SseFrame(event=event.strip(), data=_decode_payload(payload))


def _last_prefixed_value(lines: list[str], prefix: str) -> str | None:
    values = [line.removeprefix(prefix) for line in lines if line.startswith(prefix)]
    return values[-1] if values else None


def _decode_payload(payload: str | None) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload
