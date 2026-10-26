# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for web/sse.py: the encoder, the event catalogue and the job progress stream of the dashboard's event streams.

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
    JOB_COMPLETE,
    JOB_ERROR,
    JOB_PROGRESS,
    JOB_STATE_EVENTS,
    ChatDelta,
    ChatDone,
    ChatFailed,
    ChatToolCall,
    JobStreamPolicy,
    SseEvent,
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
        JOB_COMPLETE,
        dataclasses.replace(
            _A_RUNNING_JOB,
            status="completed",
            progress_pct=100.0,
            current_step="Done",
            message="Simulation completed successfully",
        ),
        SseFrame(
            "complete",
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
        id="job-complete",
    ),
    pytest.param(
        JOB_ERROR,
        dataclasses.replace(_A_RUNNING_JOB, status="failed", message=_AWKWARD_TEXT),
        SseFrame(
            "error",
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
        id="job-error",
    ),
]
"""Each catalogue event, a sample payload, and the frame the reader must return for it.

The expected names and keys are literals, not read back from the catalogue: they are
the wire contract the pages read, web/static/js/assistant.js the chat's, and
web/static/js/job-progress-stream.js, progress-tracker.js and parameter-sweep.js the
job stream's.
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
    "completed": "complete",
    "failed": "error",
    "cancelled": "error",
}
"""The event a frame of each job status names, as the pages read it until docs/prds/job-events-and-sse-framing.md's δ renames them.

A cancelled job's frame is the error event, as a failed one's is.
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
    """Stands in for one job's JobManager.job_snapshot: snapshot() answers the job's current JobSnapshot, or None once forget() is called.

    move(**changes) replaces the job's state with the state so changed, at the next version.
    """

    def __init__(self, snapshot: JobSnapshot) -> None:
        self._current: JobSnapshot | None = snapshot

    def snapshot(self) -> JobSnapshot | None:
        return self._current

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
    """The policy of the stream under test: each sleep is recorded in sleeps, not slept, and its limit is timed on clock."""
    return JobStreamPolicy(sleep=sleeps.append, clock=clock)


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


def _frame_of(snapshot: JobSnapshot) -> SseFrame:
    """The frame a reader must take for *snapshot*: its status's event, its state's fields as data, and its version as id."""
    return SseFrame(JOB_STATE_EVENTS[snapshot.state.status].name, dataclasses.asdict(snapshot.state), id=snapshot.version)


_JOB_NOT_FOUND_FRAME = 'event: error\ndata: {"error": "Job not found"}\n\n'
_TIMED_OUT_FRAME = 'event: error\ndata: {"error": "SSE stream timed out after 10 minutes"}\n\n'


@pytest.mark.parametrize("status", ["queued", "running"])
def test_a_stream_sends_an_unfinished_jobs_state_on_open_then_only_heartbeats_while_the_job_is_unchanged(
    status: JobStatus, sleeps: list[float], policy: JobStreamPolicy
) -> None:
    state = dataclasses.replace(_A_RUNNING_JOB, status=status)
    stream = job_progress_frames(_ScriptedJob(JobSnapshot(3, state)).snapshot, last_event_id=None, policy=policy)

    first_poll = _read(_next_poll(stream))

    assert first_poll == [
        SseFrame(JOB_STATE_EVENTS[status].name, dataclasses.asdict(state), id=3, retry=None),
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

    stream = job_progress_frames(_ScriptedJob(final).snapshot, last_event_id=last_event_id, policy=policy)

    assert _read(stream) == [_frame_of(final)]
    assert sleeps == []


def test_a_stream_reopened_at_the_jobs_version_sends_no_state_until_the_job_moves_on(policy: JobStreamPolicy) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, last_event_id=3, policy=policy)

    assert _next_poll(stream) == [HEARTBEAT]

    saving = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(saving), HEARTBEAT]


def test_a_stream_reopened_at_an_earlier_version_sends_the_jobs_current_state_on_open(policy: JobStreamPolicy) -> None:
    current = JobSnapshot(3, _A_RUNNING_JOB)

    stream = job_progress_frames(_ScriptedJob(current).snapshot, last_event_id=2, policy=policy)

    assert _read(_next_poll(stream)) == [_frame_of(current), HEARTBEAT]


def test_the_states_a_job_moves_through_between_two_polls_collapse_into_the_newest(policy: JobStreamPolicy) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, last_event_id=None, policy=policy)
    _next_poll(stream)

    job.move(progress_pct=50.0, message="Halfway through the simulation...")
    newest = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(newest), HEARTBEAT]
    assert newest.version == 5


def test_a_stream_on_a_job_its_source_does_not_track_sends_only_the_not_found_frame(policy: JobStreamPolicy) -> None:
    assert list(job_progress_frames(lambda: None, last_event_id=None, policy=policy)) == [_JOB_NOT_FOUND_FRAME]


def test_a_stream_whose_job_stops_being_tracked_ends_with_the_not_found_frame(policy: JobStreamPolicy) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(job.snapshot, last_event_id=None, policy=policy)
    _next_poll(stream)

    job.forget()

    assert list(stream) == [_JOB_NOT_FOUND_FRAME]


_TEN_MINUTES = 600.0
_JUST_OVER_TEN_MINUTES = math.nextafter(_TEN_MINUTES, math.inf)
"""The first time after ten minutes that a clock reading float seconds can show."""


def _a_policy_whose_every_sleep_lasts(seconds: float, clock: ManualClock) -> JobStreamPolicy:
    """A policy whose every sleep moves *clock* on by *seconds* at once, whatever heartbeat it sleeps for."""
    return JobStreamPolicy(sleep=lambda _heartbeat_seconds: clock.advance(seconds), clock=clock)


def test_a_stream_open_for_exactly_ten_minutes_still_sends_the_jobs_next_state(clock: ManualClock) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(
        job.snapshot, last_event_id=None, policy=_a_policy_whose_every_sleep_lasts(_TEN_MINUTES, clock)
    )
    _next_poll(stream)

    saving = job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert _read(_next_poll(stream)) == [_frame_of(saving), HEARTBEAT]


def test_a_stream_open_for_more_than_ten_minutes_sends_the_timed_out_frame_and_ends_without_the_jobs_state(
    clock: ManualClock,
) -> None:
    job = _ScriptedJob(JobSnapshot(3, _A_RUNNING_JOB))
    stream = job_progress_frames(
        job.snapshot, last_event_id=None, policy=_a_policy_whose_every_sleep_lasts(_JUST_OVER_TEN_MINUTES, clock)
    )
    _next_poll(stream)

    job.move(progress_pct=90.0, current_step="Saving", message="Persisting results to storage...")

    assert list(stream) == [_TIMED_OUT_FRAME]


@pytest.mark.parametrize(("header", "version"), [("0", 0), ("17", 17)])
def test_a_last_event_id_of_ascii_digits_names_that_version(header: str, version: int) -> None:
    assert parse_last_event_id(header) == version


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
