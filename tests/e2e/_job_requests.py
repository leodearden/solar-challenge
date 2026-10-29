# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold the requests a page makes about a background job, /api/jobs/<job_id>/<endpoint>, until the test answers that job, answers its next request once, or disconnects its requests.

The frames a test answers a progress stream with are the server's own: sse_frame
builds each from web/sse.py's catalogue, with the retry of JobStreamPolicy(), the
policy create_app serves. a_job_state gives the JobState a frame carries.

Also disconnects a single request, as a route handler, and fast-forwards a page by the time it waits for a broken progress stream to reconnect.
"""

import functools
import re
from collections.abc import Callable, Mapping
from dataclasses import replace
from types import MappingProxyType
from urllib.parse import urlsplit

from playwright.sync_api import Error, Page, Request, Route

from solar_challenge.web.jobs import JobState, JobStatus
from solar_challenge.web.sse import (
    JOB_STATE_EVENTS,
    JOB_STREAM_TIMED_OUT,
    JOB_UNTRACKED,
    JobStreamPolicy,
    JobUntracked,
    StreamTimedOut,
    sse_frame,
)

_JOB_REQUEST_PATH = re.compile(r"/api/jobs/(?P<job_id>[^/]+)/[^/]+")

# How disconnect_request fails a request: a reset connection, net::ERR_CONNECTION_RESET, which Chromium logs as this console error
_DISCONNECT_ERROR_CODE = "connectionreset"
DISCONNECTED_REQUEST_CONSOLE_ERROR = (
    "Failed to load resource: net::ERR_CONNECTION_RESET"
)

_SERVED_POLICY = JobStreamPolicy()

_CREATED_AT = "2026-01-01T09:00:00+00:00"

_PROGRESS_STEP_AND_MESSAGE_OF_EACH_STATUS: Mapping[JobStatus, tuple[float, str, str]] = MappingProxyType(
    {
        "queued": (0.0, "Queued", "Waiting to start..."),
        "running": (20.0, "Simulating", "Running home simulation..."),
        "completed": (100.0, "Done", "Simulation completed successfully"),
        "failed": (20.0, "Simulating", "The simulation raised an error"),
        "cancelled": (20.0, "Simulating", "Cancelled: its run was deleted"),
    }
)
"""A plausible progress, step and message for a faked home job in each status, which web/jobs.py's own may differ from: a failed or cancelled job keeps the progress and step it was simulating at."""


def disconnect_request(route: Route) -> None:
    """Fail the route's request as a reset connection does, so Chromium logs DISCONNECTED_REQUEST_CONSOLE_ERROR for it."""
    route.abort(_DISCONNECT_ERROR_CODE)


def a_job_state(job_id: str, run_id: str, status: JobStatus, **changes: object) -> JobState:
    """The state of job job_id, of run run_id, in status, with a plausible progress, step and message for a home job in that status and a fixed created_at; changes replaces any of its fields."""
    progress_pct, current_step, message = _PROGRESS_STEP_AND_MESSAGE_OF_EACH_STATUS[status]
    state = JobState(
        job_id=job_id,
        run_id=run_id,
        status=status,
        progress_pct=progress_pct,
        current_step=current_step,
        message=message,
        created_at=_CREATED_AT,
    )
    return replace(state, **changes)


def job_state_frame(state: JobState, *, version: int) -> str:
    """The frame the server sends state in as the job's state at version: its status's event, with version as its id."""
    return sse_frame(JOB_STATE_EVENTS[state.status], state, event_id=version, retry_ms=_SERVED_POLICY.retry_ms)


def timeout_frame() -> str:
    """The frame that ends a progress stream open past the served policy's limit, while its job goes on."""
    return sse_frame(
        JOB_STREAM_TIMED_OUT, StreamTimedOut(_SERVED_POLICY.limit_seconds), retry_ms=_SERVED_POLICY.retry_ms
    )


def untracked_frame(job_id: str) -> str:
    """The frame that ends the progress stream of a job job_id the server does not track."""
    return sse_frame(JOB_UNTRACKED, JobUntracked(job_id), retry_ms=_SERVED_POLICY.retry_ms)


def is_job_request(job_id: str, endpoint: str) -> Callable[[Request], bool]:
    """Whether a request is the job job_id's request to endpoint, /api/jobs/<job_id>/<endpoint>."""
    return lambda request: (
        urlsplit(request.url).path == f"/api/jobs/{job_id}/{endpoint}"
    )


def fast_forward_by_the_reconnect_limit(page: Page) -> None:
    """Fast-forward the page's clock, which the test installed before the page loaded, by the time the page waits for a broken progress stream to reconnect before it gives the stream up."""
    page.clock.fast_forward(page.evaluate("JOB_PROGRESS_RECONNECT_LIMIT_MS"))


def _wait_until_received_or_dropped(request: Request) -> None:
    """Return once the page has received the whole answer to request, or once it has dropped the request, before the answer or while receiving it."""
    response = request.response()
    if response is None:
        return
    try:
        response.body()
    except Error:
        if request.failure is None:
            raise


def _job_id_of(request: Request) -> str:
    """The job_id of the request's path, /api/jobs/<job_id>/<endpoint>; raise ValueError, naming the URL, if the path has another form."""
    match = _JOB_REQUEST_PATH.fullmatch(urlsplit(request.url).path)
    if match is None:
        raise ValueError(
            f"{request.url} is not a request about a job: its path is not /api/jobs/<job_id>/<endpoint>"
        )
    return match["job_id"]


class HeldJobRequests:
    """A page's requests to one job endpoint, each held unanswered until the test answers or disconnects its job, or answers its next request once; a request about a job already answered is answered at once."""

    def __init__(self, content_type: str) -> None:
        self._content_type = content_type
        self._answers: dict[str, tuple[int, str]] = {}
        self._held: dict[str, list[Route]] = {}
        self._next_request_actions: dict[str, Callable[[Route], None]] = {}

    def handle(self, route: Route) -> None:
        """Act on the request as the test said its job's next request is acted on, if it did, else answer it with its job's answer if the test has answered the job, else hold it; raise ValueError if it is not a request about a job."""
        job_id = _job_id_of(route.request)
        next_request_action = self._next_request_actions.pop(job_id, None)
        if next_request_action is not None:
            next_request_action(route)
        elif job_id in self._answers:
            status, body = self._answers[job_id]
            self._fulfill(route, status=status, body=body)
        else:
            self._held.setdefault(job_id, []).append(route)

    def answer(self, job_id: str, body: str, *, status: int = 200) -> None:
        """Answer the job's requests with status and body, those held now and those to come; return once the page has received or dropped each held one."""
        self._answers[job_id] = (status, body)
        for route in self._held.pop(job_id, []):
            self._fulfill(route, status=status, body=body)
            _wait_until_received_or_dropped(route.request)

    def answer_once(self, job_id: str, body: str, *, status: int = 200) -> None:
        """Answer the job's held requests with status and body, or its next request if none is held yet; its requests after that are held, or answered once the test answers the job. Return once the page has received or dropped each held one."""
        answer = functools.partial(self._fulfill, status=status, body=body)
        for route in self._act_on_held_or_next(job_id, answer):
            _wait_until_received_or_dropped(route.request)

    def disconnect(self, job_id: str) -> None:
        """Fail the job's held requests as a reset connection does, or its next request if none is held yet; its requests after that are held, or answered once the test answers the job."""
        self._act_on_held_or_next(job_id, disconnect_request)

    def abort_held(self) -> None:
        """Abort every request still held, including any the page makes while the others are aborted."""
        while self._held:
            _, routes = self._held.popitem()
            for route in routes:
                route.abort()

    def _act_on_held_or_next(self, job_id: str, act: Callable[[Route], None]) -> list[Route]:
        """Act on the job's held requests, or on its next request if none is held yet, since a request page.expect_request has seen can reach handle only later; return the held requests acted on."""
        routes = self._held.pop(job_id, [])
        if not routes:
            self._next_request_actions[job_id] = act
        for route in routes:
            act(route)
        return routes

    def _fulfill(self, route: Route, *, status: int, body: str) -> None:
        route.fulfill(status=status, content_type=self._content_type, body=body)
