# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-Sent Events: the encoder ``sse_frame``, the events it frames, the response that sends them, and the job progress stream.

Each ``SseEvent`` binds an event name to its one payload type, a dataclass whose
fields are the frame's JSON data. The chat stream's events are its catalogue:
``CHAT_DELTA``, ``CHAT_TOOL``, ``CHAT_DONE`` and ``CHAT_FAILED``. The job stream's
are ``JOB_PROGRESS``, ``JOB_COMPLETE`` and ``JOB_ERROR``, which ``JOB_STATE_EVENTS``
names by job status. ``HEARTBEAT`` is the comment a stream sends between events,
and ``event_stream`` the response that sends a stream's frames. The job stream's
frames come from ``job_progress_frames``, paced by a ``JobStreamPolicy``.
docs/prds/job-events-and-sse-framing.md §4 states the contract.
"""

import json
import time
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Final, Generic, TypeVar

from flask import Response

from solar_challenge.dataclass_instance import DataclassInstance
from solar_challenge.web.jobs import TERMINAL_JOB_STATUSES, JobSnapshot, JobState, JobStatus

P = TypeVar("P", bound=DataclassInstance)


@dataclass(frozen=True)
class SseEvent(Generic[P]):
    """An event a stream sends: its name and the one type of payload it carries."""

    name: str
    payload_type: type[P]

    def __post_init__(self) -> None:
        if not self.name or ":" in self.name or any(c.isspace() for c in self.name):
            raise ValueError(
                f"An SSE event name must be non-empty and hold no whitespace or ':'; got {self.name!r}"
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

JOB_PROGRESS: Final = SseEvent("progress", JobState)
JOB_COMPLETE: Final = SseEvent("complete", JobState)
JOB_ERROR: Final = SseEvent("error", JobState)

JOB_STATE_EVENTS: Mapping[JobStatus, SseEvent[JobState]] = MappingProxyType(
    {
        "queued": JOB_PROGRESS,
        "running": JOB_PROGRESS,
        "completed": JOB_COMPLETE,
        "failed": JOB_ERROR,
        "cancelled": JOB_ERROR,
    }
)
"""The event that sends a job's state, by the job's status.

These are the names the pages read until docs/prds/job-events-and-sse-framing.md §11 δ
renames them: a cancelled job's frame is the error event, as a failed one's is (§11 γ).
"""


@dataclass(frozen=True)
class JobStreamPolicy:
    """How a job progress stream is paced: it sleeps *heartbeat_seconds* on *sleep* between two polls, and times its limit on *clock*."""

    heartbeat_seconds: float = 2.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep


_LAST_EVENT_ID_MAX_DIGITS: Final = 18


def parse_last_event_id(header: str | None) -> int | None:
    """Return the version a reopened job stream's ``Last-Event-ID`` header names: the number its ASCII digits spell.

    A stream writes each state's version as its frame's ``id``, so any other header, or
    none, names no version and is read as None: an empty one, or one with a sign, a space,
    a decimal point, a digit that is not ASCII, or more than _LAST_EVENT_ID_MAX_DIGITS
    digits, more than a job's version ever has.
    """
    if header is None or not (header.isascii() and header.isdigit()) or len(header) > _LAST_EVENT_ID_MAX_DIGITS:
        return None
    return int(header)


_STREAM_LIMIT_SECONDS: Final = 600.0
_STREAM_TIMED_OUT_FRAME: Final = 'event: error\ndata: {"error": "SSE stream timed out after 10 minutes"}\n\n'
_JOB_NOT_FOUND_FRAME: Final = 'event: error\ndata: {"error": "Job not found"}\n\n'


def job_progress_frames(
    read_snapshot: Callable[[], JobSnapshot | None], *, last_event_id: int | None, policy: JobStreamPolicy
) -> Iterator[str]:
    """Yield the frames of a job's progress stream, polling *read_snapshot* for the job's snapshot.

    The stream keeps its own cursor, the version of the last state it sent, which starts at
    *last_event_id*. Each poll sends the job's state when the cursor is None or the state's
    version is newer, then a ``HEARTBEAT``, and the stream sleeps policy.heartbeat_seconds
    before the next poll. So a stream opened afresh sends the job's current state at once, a
    reopened one resumes after the version its ``Last-Event-ID`` names, and the states a job
    moves through between two polls collapse into the newest. The stream ends with exactly one
    of three frames:

    - a terminal state's frame, sent whatever the cursor, so a reopened stream on a finished
      job ends at once;
    - the "Job not found" error, once *read_snapshot* answers None;
    - the "SSE stream timed out after 10 minutes" error, once the stream has been open longer
      than that on policy.clock.
    """
    started = policy.clock()
    cursor = last_event_id
    while True:
        if policy.clock() - started > _STREAM_LIMIT_SECONDS:
            yield _STREAM_TIMED_OUT_FRAME
            return
        current = read_snapshot()
        if current is None:
            yield _JOB_NOT_FOUND_FRAME
            return
        if current.state.status in TERMINAL_JOB_STATUSES:
            yield _job_state_frame(current)
            return
        if cursor is None or current.version > cursor:
            yield _job_state_frame(current)
            cursor = current.version
        yield HEARTBEAT
        policy.sleep(policy.heartbeat_seconds)


def _job_state_frame(snapshot: JobSnapshot) -> str:
    """The frame that sends *snapshot*'s state: its status's event, with its version as id."""
    return sse_frame(JOB_STATE_EVENTS[snapshot.state.status], snapshot.state, event_id=snapshot.version)
