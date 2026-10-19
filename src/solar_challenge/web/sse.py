# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-Sent Events: the encoder ``sse_frame``, the events it frames, and the response that sends them.

Each ``SseEvent`` binds an event name to its one payload type, a dataclass whose
fields are the frame's JSON data. The chat stream's events are its catalogue:
``CHAT_DELTA``, ``CHAT_TOOL``, ``CHAT_DONE`` and ``CHAT_FAILED``. ``HEARTBEAT`` is
the comment a stream sends between events, and ``event_stream`` the response that
sends a stream's frames. docs/prds/job-events-and-sse-framing.md §4 states the
contract.
"""

import json
from collections.abc import Iterable
from dataclasses import Field, asdict, dataclass
from typing import Any, ClassVar, Final, Generic, Protocol, TypeVar

from flask import Response


class _DataclassInstance(Protocol):
    """An instance of any dataclass: what ``dataclasses.asdict`` accepts."""

    __dataclass_fields__: ClassVar[dict[str, Field[Any]]]


P = TypeVar("P", bound=_DataclassInstance)

_CHARACTERS_NO_EVENT_NAME_HOLDS = frozenset("\r\n:")


@dataclass(frozen=True)
class SseEvent(Generic[P]):
    """An event a stream sends: its name and the one type of payload it carries."""

    name: str
    payload_type: type[P]

    def __post_init__(self) -> None:
        if not self.name or _CHARACTERS_NO_EVENT_NAME_HOLDS.intersection(self.name):
            raise ValueError(
                f"An SSE event name must be non-empty and hold no CR, LF or ':'; got {self.name!r}"
            )


def sse_frame(
    event: SseEvent[P], payload: P, *, event_id: int | None = None, retry_ms: int | None = None
) -> str:
    """Return the SSE frame that sends *event* with *payload*'s fields as its JSON data.

    *event_id* and *retry_ms*, when given, become the frame's ``id`` and ``retry`` lines.

    Raises:
        TypeError: *payload* is not an instance of *event*'s payload type.
        ValueError: *retry_ms* is negative, a retry EventSource ignores.
    """
    if not isinstance(payload, event.payload_type):
        raise TypeError(
            f"The SSE event {event.name!r} carries a {event.payload_type.__name__}; "
            f"got a {type(payload).__name__}"
        )
    if retry_ms is not None and retry_ms < 0:
        raise ValueError(
            f"An SSE retry must be a non-negative number of milliseconds; got {retry_ms}"
        )
    id_line = "" if event_id is None else f"id: {event_id}\n"
    retry_line = "" if retry_ms is None else f"retry: {retry_ms}\n"
    return f"event: {event.name}\n{id_line}{retry_line}data: {json.dumps(asdict(payload))}\n\n"


HEARTBEAT: Final = ":heartbeat\n\n"


def event_stream(frames: Iterable[str]) -> Response:
    """Return the 200 ``text/event-stream`` response sending *frames*, neither cached nor buffered by a proxy."""
    return Response(
        frames,
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@dataclass(frozen=True)
class ChatDelta:
    """The next piece of the assistant's reply."""

    text: str


@dataclass(frozen=True)
class ChatToolCall:
    """The assistant called the tool *name* while composing its reply."""

    name: str


@dataclass(frozen=True)
class ChatDone:
    """The assistant's reply is complete."""


@dataclass(frozen=True)
class ChatFailed:
    """The chat turn failed; *message* is the notice the page shows."""

    message: str


CHAT_DELTA: Final = SseEvent("delta", ChatDelta)
CHAT_TOOL: Final = SseEvent("tool", ChatToolCall)
CHAT_DONE: Final = SseEvent("done", ChatDone)
CHAT_FAILED: Final = SseEvent("failed", ChatFailed)
