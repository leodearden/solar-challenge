# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to a Server-Sent Events response body.

Usage::

    from tests._sse import parse_sse_events

    frames = parse_sse_events(resp.get_data(as_text=True))
    assert [f.event for f in frames] == ["delta", "done"]
"""

import json
import re
from dataclasses import dataclass
from itertools import groupby
from typing import Any


@dataclass(frozen=True)
class SseFrame:
    """One Server-Sent Events frame: the event it names and its decoded data payload.

    ``id`` and ``retry`` are the integers on the frame's own ``id`` and ``retry`` lines,
    each None when the frame has no such line.
    """

    event: str
    data: Any
    id: int | None = None
    retry: int | None = None


def parse_sse_events(body: str) -> list[SseFrame]:
    """Return the frames in *body* that name an event, in stream order.

    Blank lines separate frames. In each frame the last ``event: `` line names the
    event, and its ``data: `` line carries the payload: JSON-decoded when it
    parses, the raw string when it does not, and None when the line is absent or
    empty. The frame's own last ``id: `` and ``retry: `` lines give its id and retry
    as integers, each None when the frame has none: unlike EventSource's
    lastEventId, an id does not carry over to later frames. A frame with no
    ``event: `` line, such as a ``:heartbeat`` comment, yields no SseFrame.

    Raises ValueError, rather than guess, on a frame that SSE readers decode
    differently: more than one ``data`` line (the spec joins them; the chat client
    in web/static/js/assistant.js keeps the last), a field line with no space
    after its colon (the spec accepts it; the chat client ignores it), or an ``id``
    or ``retry`` that is not all ASCII digits (int() reads ``+7`` and ``-1`` as
    numbers; EventSource ignores such a retry and keeps an id as its raw text).
    """
    runs = groupby(body.splitlines(), key=_is_blank)
    frames = (_read_frame(list(lines)) for blank, lines in runs if not blank)
    return [frame for frame in frames if frame is not None]


def _is_blank(line: str) -> bool:
    return not line.strip()


def _read_frame(lines: list[str]) -> SseFrame | None:
    events = _field_values(lines, "event")
    payloads = _field_values(lines, "data")
    if len(payloads) > 1:
        raise ValueError(
            f"Expected at most one data line per SSE frame; got {len(payloads)}: {lines!r}"
        )
    event_id = _integer_field(lines, "id")
    retry = _integer_field(lines, "retry")
    if not events:
        return None
    payload = payloads[0] if payloads else None
    return SseFrame(
        event=events[-1].strip(), data=_decode_payload(payload), id=event_id, retry=retry
    )


def _integer_field(lines: list[str], field: str) -> int | None:
    values = _field_values(lines, field)
    if not values:
        return None
    value = values[-1]
    if not re.fullmatch(r"[0-9]+", value):
        raise ValueError(
            f"Expected the SSE {field} line to carry only ASCII digits; got: {lines!r}"
        )
    return int(value)


def _field_values(lines: list[str], field: str) -> list[str]:
    prefix = f"{field}: "
    field_lines = [line for line in lines if _field_name(line) == field]
    malformed = [line for line in field_lines if not line.startswith(prefix)]
    if malformed:
        raise ValueError(
            f"Expected each SSE {field} line to start with {prefix!r}; got: {malformed!r}"
        )
    return [line.removeprefix(prefix) for line in field_lines]


def _field_name(line: str) -> str:
    return line.partition(":")[0]


def _decode_payload(payload: str | None) -> Any:
    if not payload:
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return payload
