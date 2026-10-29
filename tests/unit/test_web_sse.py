# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for web/sse.py: the encoder, the event catalogue, and the job progress stream of the dashboard's event streams with the policy that paces it.

The job progress stream's tests run job_progress_frames on a _ScriptedJob, which stands in
for a JobManager's job_snapshot, under a JobStreamPolicy that never sleeps: each sleep is
recorded, or moves the policy's ManualClock on, and the clock stands still otherwise.
"""

import dataclasses
import math
import re
from collections.abc import Iterable, Iterator
from typing import Any, get_args

import pytest

pytest.importorskip("flask")

from solar_challenge.web import sse
from solar_challenge.web.jobs import JobSnapshot, JobState, JobStatus
from solar_challenge.web.sse import (
    CHAT_DELTA,
    CHAT_DONE,
    CHAT_FAILED,
    CHAT_TOOL,
    HEARTBEAT,
    JOB_CANCELLED,
    JOB_COMPLETED,
    JOB_FAILED,
    JOB_PROGRESS,
    JOB_STATE_EVENTS,
    JOB_STREAM_TIMED_OUT,
    JOB_UNTRACKED,
    ChatDelta,
    ChatDone,
    ChatFailed,
    ChatToolCall,
    JobStreamPolicy,
    JobUntracked,
    SseEvent,
    StreamTimedOut,
    event_stream,
    job_progress_frames,
    parse_last_event_id,
    sse_frame,
)
from tests._manual_clock import ManualClock
from tests._sse import SseFrame, parse_sse_events

_AWKWARD_TEXT = 'Hel\nlo "wörld"\r\n  done'
"""Line breaks json.dumps must escape for the data to stay on one line, a quote, and non-ASCII text."""

_A_RUNNING_JOB = JobState(
    job_id="job-1",
    run_id="run-2",
    status="running",
    progress_pct=20.0,
    current_step="Simulating",
    message="Running home simulation...",
    created_at="2026-10-26T09:00:00+00:00",
)
"""A job inside its simulation, as a JobManager reports it."""

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
    pytest.param(
        JOB_PROGRESS,
        _A_RUNNING_JOB,
        SseFrame(
            "progress",
            {
                "job_id": "job-1",
                "run_id": "run-2",
                "status": "running",
                "progress_pct": 20.0,
                "current_step": "Simulating",
                "message": "Running home simulation...",
                "created_at": "2026-10-26T09:00:00+00:00",
            },
        ),
        id="job-progress",
    ),
    pytest.param(
        JOB_COMPLETED,
        dataclasses.replace(
            _A_RUNNING_JOB,
            status="completed",
            progress_pct=100.0,
            current_step="Done",
            message="Simulation completed successfully",
        ),
        SseFrame(
            "completed",
            {
                "job_id": "job-1",
                "run_id": "run-2",
                "status": "completed",
                "progress_pct": 100.0,
                "current_step": "Done",
                "message": "Simulation completed successfully",
                "created_at": "2026-10-26T09:00:00+00:00",
            },
        ),
        id="job-completed",
    ),
    pytest.param(
        JOB_FAILED,
        dataclasses.replace(_A_RUNNING_JOB, status="failed", message=_AWKWARD_TEXT),
        SseFrame(
            "failed",
            {
                "job_id": "job-1",
                "run_id": "run-2",
                "status": "failed",
                "progress_pct": 20.0,
                "current_step": "Simulating",
                "message": _AWKWARD_TEXT,
                "created_at": "2026-10-26T09:00:00+00:00",
            },
        ),
        id="job-failed",
    ),
    pytest.param(
        JOB_CANCELLED,
        dataclasses.replace(_A_RUNNING_JOB, status="cancelled", message="Cancelled: its run was deleted"),
        SseFrame(
            "cancelled",
            {
                "job_id": "job-1",
                "run_id": "run-2",
                "status": "cancelled",
                "progress_pct": 20.0,
                "current_step": "Simulating",
                "message": "Cancelled: its run was deleted",
                "created_at": "2026-10-26T09:00:00+00:00",
            },
        ),
        id="job-cancelled",
    ),
    pytest.param(
        JOB_STREAM_TIMED_OUT,
        StreamTimedOut(600.0),
        SseFrame("timeout", {"limit_seconds": 600.0}),
        id="job-stream-timed-out",
    ),
    pytest.param(
        JOB_UNTRACKED,
        JobUntracked("job-1"),
        SseFrame("untracked", {"job_id": "job-1"}),
        id="job-untracked",
    ),
]
"""Each catalogue event, a sample payload, and the frame the reader must return for it.

The expected names and keys are literals, not read back from the catalogue: they are
the wire contract the pages read, web/static/js/assistant.js the chat's, and
web/static/js/job-progress-stream.js the job stream's.
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


_EVENT_NAME_OF_EACH_JOB_STATUS: dict[JobStatus, str] = {
    "queued": "progress",
    "running": "progress",
    "completed": "completed",
    "failed": "failed",
    "cancelled": "cancelled",
}
"""The event a frame of each job status names, as web/static/js/job-progress-stream.js reads it.

Each terminal status names its own event (docs/prds/job-events-and-sse-framing.md D-S20-1).
"""


def test_each_job_status_names_the_event_its_frames_carry() -> None:
    assert sorted(JOB_STATE_EVENTS) == sorted(get_args(JobStatus))
    assert {status: event.name for status, event in JOB_STATE_EVENTS.items()} == _EVENT_NAME_OF_EACH_JOB_STATUS
    assert {event.payload_type for event in JOB_STATE_EVENTS.values()} == {JobState}


def test_a_payload_that_is_not_its_event_s_payload_type_is_refused_naming_both() -> None:
    with pytest.raises(TypeError, match=r"'delta'.*ChatDelta.*ChatFailed"):
        sse_frame(CHAT_DELTA, ChatFailed("boom"))


def test_a_negative_retry_is_refused() -> None:
    """EventSource ignores a retry that is not all digits, so it would never see this one."""
    with pytest.raises(ValueError, match="-1"):
        sse_frame(CHAT_DONE, ChatDone(), retry_ms=-1)


@pytest.mark.parametrize(
    "name",
    ["", "fail\ned", "fail\red", "fail:ed", "failed ", " failed", "fail ed"],
    ids=["empty", "lf", "cr", "colon", "trailing-space", "leading-space", "inner-space"],
)
def test_an_event_name_that_is_empty_or_holds_whitespace_or_a_colon_is_refused(name: str) -> None:
    with pytest.raises(ValueError, match=re.escape(repr(name))):
        SseEvent(name, ChatDone)


def test_event_stream_serves_its_frames_as_an_uncached_unbuffered_200_event_stream() -> None:
    frames = [sse_frame(CHAT_DELTA, ChatDelta("Hel")), HEARTBEAT, sse_frame(CHAT_DONE, ChatDone())]

    response = event_stream(iter(frames))

    assert response.status_code == 200
    assert response.mimetype == "text/event-stream"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.headers["X-Accel-Buffering"] == "no"
    assert parse_sse_events(response.get_data(as_text=True)) == [
        SseFrame("delta", {"text": "Hel"}),
        SseFrame("done", {}),
    ]


def test_the_heartbeat_is_an_sse_comment() -> None:
    assert HEARTBEAT.startswith(":")
    assert parse_sse_events(HEARTBEAT) == []


class _ScriptedJob:
    """Stands in for JobManager.job_snapshot on one job: snapshot(job_id) answers the job's current JobSnapshot for the job's own id, and None for any other id or once forget() is called.

    move(**changes) replaces the job's state with the state so changed, at the next version.
    """

    def __init__(self, snapshot: JobSnapshot) -> None:
        self._job_id = snapshot.state.job_id
        self._current: JobSnapshot | None = snapshot

    def snapshot(self, job_id: str) -> JobSnapshot | None:
        return self._current if job_id == self._job_id else None

    def move(self, **changes: Any) -> JobSnapshot:
        current = self._current
        assert current is not None, "a job no longer tracked does not move"
        self._current = JobSnapshot(current.version + 1, dataclasses.replace(current.state, **changes))
        return self._current

    def forget(self) -> None:
        self._current = None


@pytest.fixture
def sleeps() -> list[float]:
    """The seconds of each sleep the stream under test took, in order."""
    return []


@pytest.fixture
def clock() -> ManualClock:
    """The clock the stream under test times its limit on."""
    return ManualClock()


@pytest.fixture
def policy(sleeps: list[float], clock: ManualClock) -> JobStreamPolicy:
    """The policy of the stream under test: each sleep is recorded in sleeps, not slept, and its limit is timed on clock.

    Its retry is not the default one, so a frame that carries it took it from the policy.
    """
    return JobStreamPolicy(sleep=sleeps.append, clock=clock, retry_ms=1500)


def _next_poll(stream: Iterator[str]) -> list[str]:
    """The chunks *stream* sends in its next poll: up to and including its next HEARTBEAT, or to its end."""
    chunks: list[str] = []
    for chunk in stream:
        chunks.append(chunk)
        if chunk == HEARTBEAT:
            break
    return chunks


def _read(chunks: Iterable[str]) -> list[SseFrame | str]:
    """*chunks* as a reader takes them: HEARTBEAT as itself, and any other chunk as the one frame it holds."""
    read: list[SseFrame | str] = []
    for chunk in chunks:
        if chunk == HEARTBEAT:
            read.append(chunk)
        else:
            [frame] = parse_sse_events(chunk)
            read.append(frame)
    return read


def _frame_of(snapshot: JobSnapshot, policy: JobStreamPolicy) -> SseFrame:
    """The frame a reader must take for *snapshot* on a stream under *policy*: its status's event, its state's fields as data, its version as id and the policy's retry."""
    return SseFrame(
        JOB_STATE_EVENTS[snapshot.state.status].name,
        dataclasses.asdict(snapshot.state),
        id=snapshot.version,
        retry=policy.retry_ms,
    )


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_stream_sends_an_unfinished_jobs_state_on_open_then_only_heartbeats_while_the_job_is_unchanged(
    status: JobStatus, sleeps: list[float], policy: JobStreamPolicy
) -> None:
    state = dataclasses.replace(_A_RUNNING_JOB, status=status)
    stream = job_progress_frames(
        _ScriptedJob(JobSnapshot(3, state)).snapshot, "job-1", last_event_id=None, policy=policy
    )

    first_poll = _read(_next_poll(stream))

    assert first_poll == [
        SseFrame(JOB_STATE_EVENTS[status].name, dataclasses.asdict(state), id=3, retry=policy.retry_ms),
        HEARTBEAT,
    ]
    assert list(first_poll[0].data) == [field.name for field in dataclasses.fields(JobState)]
    assert sleeps == []
    assert _next_poll(stream) == [HEARTBEAT]
    assert sleeps == [2.0]


@pytest.mark.parametrize("last_event_id", [None, 5], ids=["opened", "reopened-at-its-version"])
@pytest.mark.parametrize("status", ["completed", "failed", "cancelled"])
def test_a_finished_jobs_stream_sends_its_final_state_once_and_ends(
    status: JobStatus, last_event_id: int | None, sleeps: list[float], policy: JobStreamPolicy
) -> None:
    final = JobSnapshot(5, dataclasses.replace(_A_RUNNING_JOB, status=status))

    stream = job_progress_frames(_ScriptedJob(final).snapshot, "job-1", last_event_id=last_event_id, policy=policy)

    assert _read(stream) == [_frame_of(final, policy)]
    assert sleeps == []


def test_a_stream_reopened_at_the_jobs_version_sends_no_state_until_the_job_moves_on(policy: JobStreamPolicy) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, "job-1", last_event_id=3, policy=policy)

    assert _next_poll(stream) == [HEARTBEAT]

    saving = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(saving, policy), HEARTBEAT]


def test_a_stream_reopened_at_an_earlier_version_sends_the_jobs_current_state_on_open(policy: JobStreamPolicy) -> None:
    current = JobSnapshot(3, _A_RUNNING_JOB)

    stream = job_progress_frames(_ScriptedJob(current).snapshot, "job-1", last_event_id=2, policy=policy)

    assert _read(_next_poll(stream)) == [_frame_of(current, policy), HEARTBEAT]


def test_the_states_a_job_moves_through_between_two_polls_collapse_into_the_newest(policy: JobStreamPolicy) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, "job-1", last_event_id=None, policy=policy)
    _next_poll(stream)

    job.move(progress_pct=50.0, message="Halfway through the simulation...")
    newest = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(newest, policy), HEARTBEAT]
    assert newest.version == 5


def test_a_stream_on_a_job_its_source_does_not_track_sends_only_the_untracked_frame_naming_the_job(
    policy: JobStreamPolicy,
) -> None:
    stream = job_progress_frames(lambda _job_id: None, "job-9", last_event_id=None, policy=policy)

    assert _read(stream) == [SseFrame("untracked", {"job_id": "job-9"}, id=None, retry=policy.retry_ms)]


def test_a_stream_whose_job_stops_being_tracked_ends_with_the_untracked_frame_naming_the_job(
    policy: JobStreamPolicy,
) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, "job-1", last_event_id=None, policy=policy)
    _next_poll(stream)

    job.forget()

    assert _read(stream) == [SseFrame("untracked", {"job_id": "job-1"}, id=None, retry=policy.retry_ms)]


_TEN_MINUTES = 600.0
"""D21's limit on a job progress stream, the default policy's."""

_POLICIES_AND_THEIR_LIMITS = [
    pytest.param(JobStreamPolicy(), _TEN_MINUTES, id="the-default-policy"),
    pytest.param(JobStreamPolicy(limit_seconds=30.0), 30.0, id="a-policy-of-thirty-seconds"),
]
"""A policy and the limit in seconds a stream under it must keep: D21's ten minutes by default, or the policy's own."""


def _with_every_sleep_lasting(seconds: float, clock: ManualClock, policy: JobStreamPolicy) -> JobStreamPolicy:
    """*policy*, but timing its limit on *clock*, and with every sleep moving *clock* on by *seconds* at once, whatever heartbeat it sleeps for."""
    return dataclasses.replace(policy, sleep=lambda _heartbeat_seconds: clock.advance(seconds), clock=clock)


@pytest.mark.parametrize(("policy_of_its_limit", "limit_seconds"), _POLICIES_AND_THEIR_LIMITS)
def test_a_stream_open_for_exactly_its_limit_still_sends_the_jobs_next_state(
    policy_of_its_limit: JobStreamPolicy, limit_seconds: float, clock: ManualClock
) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    policy = _with_every_sleep_lasting(limit_seconds, clock, policy_of_its_limit)
    stream = job_progress_frames(job.snapshot, "job-1", last_event_id=None, policy=policy)
    _next_poll(stream)

    saving = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(saving, policy), HEARTBEAT]


@pytest.mark.parametrize(("policy_of_its_limit", "limit_seconds"), _POLICIES_AND_THEIR_LIMITS)
def test_a_stream_open_past_its_limit_sends_only_the_timeout_frame_naming_the_limit_and_ends_without_the_jobs_state(
    policy_of_its_limit: JobStreamPolicy, limit_seconds: float, clock: ManualClock
) -> None:
    """Each sleep lasts the least time past the limit that a clock reading float seconds can show."""
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    policy = _with_every_sleep_lasting(math.nextafter(limit_seconds, math.inf), clock, policy_of_its_limit)
    stream = job_progress_frames(job.snapshot, "job-1", last_event_id=None, policy=policy)
    _next_poll(stream)

    job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(stream) == [
        SseFrame("timeout", {"limit_seconds": limit_seconds}, id=None, retry=policy.retry_ms)
    ]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("limit_seconds", 0.0),
        ("limit_seconds", -1.0),
        ("limit_seconds", math.nan),
        ("heartbeat_seconds", -1.0),
        ("heartbeat_seconds", math.nan),
        ("retry_ms", -1),
    ],
    ids=[
        "no-limit",
        "a-negative-limit",
        "a-limit-that-is-not-a-number",
        "a-negative-heartbeat",
        "a-heartbeat-that-is-not-a-number",
        "a-negative-retry",
    ],
)
def test_a_policy_whose_field_would_break_every_stream_is_refused_naming_the_field_and_its_value(
    field: str, value: float
) -> None:
    """Each would break every stream: a limit of zero or less ends a stream at its first poll, a limit that is not a number never ends one, time.sleep raises on a negative or NaN heartbeat, and EventSource ignores a negative retry."""
    with pytest.raises(ValueError, match=rf"\b{field}\b.*{re.escape(repr(value))}"):
        JobStreamPolicy(**{field: value})


def test_a_policy_may_poll_without_pausing_and_ask_the_browser_to_reopen_at_once() -> None:
    policy = JobStreamPolicy(heartbeat_seconds=0.0, retry_ms=0)

    assert (policy.heartbeat_seconds, policy.retry_ms) == (0.0, 0)


@pytest.mark.parametrize(("header", "version"), [("0", 0), ("17", 17), ("9" * 18, 10**18 - 1)])
def test_a_last_event_id_of_ascii_digits_names_that_version(header: str, version: int) -> None:
    assert parse_last_event_id(header) == version


@pytest.mark.parametrize("header", ["9" * 19, "9" * 5000], ids=["one-digit-past-the-bound", "past-pythons-int-limit"])
def test_a_last_event_id_of_more_digits_than_a_version_has_names_no_version(header: str) -> None:
    assert parse_last_event_id(header) is None


@pytest.mark.parametrize(
    "header",
    [None, "", "abc", "-1", "+7", " 7", "7 ", "7.0", "٣"],
    ids=[
        "absent",
        "empty",
        "letters",
        "negative",
        "plus-signed",
        "leading-space",
        "trailing-space",
        "decimal",
        "arabic-indic-digit",
    ],
)
def test_a_last_event_id_that_is_absent_or_not_all_ascii_digits_names_no_version(header: str | None) -> None:
    assert parse_last_event_id(header) is None
