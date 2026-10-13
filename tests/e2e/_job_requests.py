# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold the requests a page makes about a background job, /api/jobs/<job_id>/<endpoint>, until the test answers that job or disconnects its requests.

Also fast-forwards a page past the time it waits for a disconnected progress stream to reconnect.
"""

import json
import re
from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from playwright.sync_api import Error, Page, Request, Route

_JOB_REQUEST_PATH = re.compile(r"/api/jobs/(?P<job_id>[^/]+)/[^/]+")

# How disconnect fails a request: a reset connection, net::ERR_CONNECTION_RESET, which Chromium logs as this console error
_DISCONNECT_ERROR_CODE = "connectionreset"
DISCONNECTED_REQUEST_CONSOLE_ERROR = (
    "Failed to load resource: net::ERR_CONNECTION_RESET"
)


def sse_event(event: str, data: Mapping[str, object]) -> str:
    """The text of one server-sent event named event, carrying data as JSON."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


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
    """A page's requests to one job endpoint, each held unanswered until the test answers or disconnects its job; a request about a job already answered is answered at once."""

    def __init__(self, content_type: str) -> None:
        self._content_type = content_type
        self._answers: dict[str, tuple[int, str]] = {}
        self._held: dict[str, list[Route]] = {}
        self._to_disconnect: set[str] = set()

    def handle(self, route: Route) -> None:
        """Fail the request as a reset connection does if the test disconnected its job before it came, else answer it with its job's answer if the test has answered the job, else hold it; raise ValueError if it is not a request about a job."""
        job_id = _job_id_of(route.request)
        if job_id in self._to_disconnect:
            self._to_disconnect.remove(job_id)
            route.abort(_DISCONNECT_ERROR_CODE)
        elif job_id in self._answers:
            status, body = self._answers[job_id]
            route.fulfill(status=status, content_type=self._content_type, body=body)
        else:
            self._held.setdefault(job_id, []).append(route)

    def answer(self, job_id: str, body: str, *, status: int = 200) -> None:
        """Answer the job's requests with status and body, those held now and those to come; return once the page has received or dropped each held one."""
        self._answers[job_id] = (status, body)
        for route in self._held.pop(job_id, []):
            route.fulfill(status=status, content_type=self._content_type, body=body)
            _wait_until_received_or_dropped(route.request)

    def disconnect(self, job_id: str) -> None:
        """Fail the job's held requests as a reset connection does, or its next request if none is held yet, since a request page.expect_request has seen can reach handle only later; its requests after that are held, or answered once the test answers the job."""
        routes = self._held.pop(job_id, [])
        if not routes:
            self._to_disconnect.add(job_id)
        for route in routes:
            route.abort(_DISCONNECT_ERROR_CODE)

    def abort_held(self) -> None:
        """Abort every request still held, including any the page makes while the others are aborted."""
        while self._held:
            _, routes = self._held.popitem()
            for route in routes:
                route.abort()
