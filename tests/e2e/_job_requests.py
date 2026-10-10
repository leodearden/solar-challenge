# SPDX-License-Identifier: AGPL-3.0-or-later
"""Hold the requests a page makes about a background job, /api/jobs/<job_id>/<endpoint>, until the test answers that job."""

import json
from collections.abc import Mapping
from urllib.parse import urlsplit

from playwright.sync_api import Request, Route


def sse_event(event: str, data: Mapping[str, object]) -> str:
    """The text of one server-sent event named event, carrying data as JSON."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _wait_until_received_or_dropped(request: Request) -> None:
    """Return once the page has received the whole answer to request, or at once if it dropped the request unanswered."""
    response = request.response()
    if response is not None:
        response.body()


class HeldJobRequests:
    """A page's requests to one job endpoint, each held unanswered until the test answers its job; a request about a job already answered is answered at once."""

    def __init__(self, content_type: str) -> None:
        self._content_type = content_type
        self._answers: dict[str, str] = {}
        self._held: dict[str, list[Route]] = {}

    def handle(self, route: Route) -> None:
        """Answer the request with its job's answer if the test has answered the job, else hold it."""
        job_id = urlsplit(route.request.url).path.split("/")[-2]
        if job_id in self._answers:
            route.fulfill(content_type=self._content_type, body=self._answers[job_id])
        else:
            self._held.setdefault(job_id, []).append(route)

    def answer(self, job_id: str, body: str) -> None:
        """Answer the job's requests with body, those held now and those to come; return once the page has received or dropped each held one."""
        self._answers[job_id] = body
        for route in self._held.pop(job_id, []):
            route.fulfill(content_type=self._content_type, body=body)
            _wait_until_received_or_dropped(route.request)

    def abort_held(self) -> None:
        """Abort every request still held."""
        for routes in self._held.values():
            for route in routes:
                route.abort()
