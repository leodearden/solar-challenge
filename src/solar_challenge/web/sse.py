# SPDX-License-Identifier: AGPL-3.0-or-later
"""Server-Sent Events: the encoder ``sse_frame``, the events it frames, the response that sends them, and the job progress stream.

Each ``SseEvent`` binds an event name to its one payload type, a dataclass whose
fields are the frame's JSON data. The chat stream's events are its catalogue:
``CHAT_DELTA``, ``CHAT_TOOL``, ``CHAT_DONE`` and ``CHAT_FAILED``. The job stream's
are ``JOB_PROGRESS``, ``JOB_COMPLETED``, ``JOB_FAILED`` and ``JOB_CANCELLED``, which
send a job's state and which ``JOB_STATE_EVENTS`` names by job status, and the two
endings that send none, ``JOB_STREAM_TIMED_OUT`` and ``JOB_UNTRACKED``.
``HEARTBEAT`` is the comment a stream sends between events, and ``event_stream`` the
response that sends a stream's frames. The job stream's frames come from
``job_progress_frames``, paced and bounded by a ``JobStreamPolicy``.
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
JOB_COMPLETED: Final = SseEvent("completed", JobState)
JOB_FAILED: Final = SseEvent("failed", JobState)
JOB_CANCELLED: Final = SseEvent("cancelled", JobState)

JOB_STATE_EVENTS: Mapping[JobStatus, SseEvent[JobState]] = MappingProxyType(
    {
        "queued": JOB_PROGRESS,
        "running": JOB_PROGRESS,
        "completed": JOB_COMPLETED,
        "failed": JOB_FAILED,
        "cancelled": JOB_CANCELLED,
    }
)
"""The event that sends a job's state, by the job's status: progress while the job is unfinished, then its terminal status's own event."""


@dataclass(frozen=True)
class StreamTimedOut:
    """The stream has been open past its limit of *limit_seconds*; the job goes on."""

    limit_seconds: float


@dataclass(frozen=True)
class JobUntracked:
    """The server tracks no job *job_id*."""

    job_id: str


JOB_STREAM_TIMED_OUT: Final = SseEvent("timeout", StreamTimedOut)
JOB_UNTRACKED: Final = SseEvent("untracked", JobUntracked)


@dataclass(frozen=True)
class JobStreamPolicy:
    """How a job progress stream is paced and bounded.

    The stream sleeps *heartbeat_seconds* on *sleep* between two polls, ends once it has been
    open longer than *limit_seconds* on *clock*, and asks the browser, in every frame's retry,
    to wait *retry_ms* before it reopens the stream.

    Raises:
        ValueError: a field would break every stream: a *limit_seconds* that is not more
            than 0, a *heartbeat_seconds* that is not at least 0, or a negative *retry_ms*.
    """

    limit_seconds: float = 600.0
    heartbeat_seconds: float = 2.0
    retry_ms: int = 1000
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep

    def __post_init__(self) -> None:
        if not self.limit_seconds > 0:
            raise ValueError(f"A job stream's limit_seconds must be more than 0; got {self.limit_seconds!r}")
        if not self.heartbeat_seconds >= 0:
            raise ValueError(f"A job stream's heartbeat_seconds must be at least 0; got {self.heartbeat_seconds!r}")
        if self.retry_ms < 0:
            raise ValueError(f"A job stream's retry_ms must be at least 0; got {self.retry_ms!r}")


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


def job_progress_frames(
    job_snapshot: Callable[[str], JobSnapshot | None],
    job_id: str,
    *,
    last_event_id: int | None,
    policy: JobStreamPolicy,
) -> Iterator[str]:
    """Yield the frames of job *job_id*'s progress stream, polling *job_snapshot* for the job's snapshot.

    The stream keeps its own cursor, the version of the last state it sent, which starts at
    *last_event_id*. Each poll sends the job's state when the cursor is None or the state's
    version is newer, then a ``HEARTBEAT``, and the stream sleeps policy.heartbeat_seconds
    before the next poll. So a stream opened afresh sends the job's current state at once, a
    reopened one resumes after the version its ``Last-Event-ID`` names, and the states a job
    moves through between two polls collapse into the newest. Every frame carries
    policy.retry_ms as its retry, and only a state's frame carries an id, the state's version.
    The stream ends with exactly one of three frames:

    - a terminal state's frame, sent whatever the cursor, so a reopened stream on a finished
      job ends at once;
    - ``JOB_UNTRACKED``, naming the job, once *job_snapshot* answers None for it;
    - ``JOB_STREAM_TIMED_OUT``, naming the limit, at the first poll after the stream has been
      open longer than policy.limit_seconds on policy.clock. The job goes on, and a browser
      reopens the stream after the retry, resuming from the last state it was sent.
    """
    started = policy.clock()
    cursor = last_event_id
    while True:
        if policy.clock() - started > policy.limit_seconds:
            yield sse_frame(JOB_STREAM_TIMED_OUT, StreamTimedOut(policy.limit_seconds), retry_ms=policy.retry_ms)
            return
        current = job_snapshot(job_id)
        if current is None:
            yield sse_frame(JOB_UNTRACKED, JobUntracked(job_id), retry_ms=policy.retry_ms)
            return
        if current.state.status in TERMINAL_JOB_STATUSES:
            yield _job_state_frame(current, retry_ms=policy.retry_ms)
            return
        if cursor is None or current.version > cursor:
            yield _job_state_frame(current, retry_ms=policy.retry_ms)
            cursor = current.version
        yield HEARTBEAT
        policy.sleep(policy.heartbeat_seconds)


def _job_state_frame(snapshot: JobSnapshot, *, retry_ms: int) -> str:
    """The frame that sends *snapshot*'s state: its status's event, with its version as id and *retry_ms* as retry."""
    return sse_frame(
        JOB_STATE_EVENTS[snapshot.state.status], snapshot.state, event_id=snapshot.version, retry_ms=retry_ms
    )
