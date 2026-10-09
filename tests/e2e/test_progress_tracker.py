"""End-to-end tests for the progress tracker that /simulate/home and /simulate/fleet share.

Verifies, on each page, that the tracker follows the latest run. A run started
while an earlier one still runs is the run it follows: the page drops the
earlier run's progress stream, so the earlier run's end, completed or failed,
does not show. A run started after a completed one starts its tracker afresh.
"""

import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Request, Route, expect

pytestmark = pytest.mark.e2e


@dataclass(frozen=True)
class _SimulatePage:
    """A page that shows the tracker: its path, its Run button's name, the route glob of the POST its Run sends, and the path prefix of a completed run's results."""

    path: str
    run_button: str
    submission: str
    results: str


@pytest.fixture(
    params=[
        pytest.param(
            _SimulatePage(
                "/simulate/home", "Run Simulation", "**/api/simulate/home", "/results/home/"
            ),
            id="home",
        ),
        pytest.param(
            _SimulatePage(
                "/simulate/fleet",
                "Run Fleet Simulation",
                "**/api/simulate/fleet-from-distribution",
                "/results/fleet/",
            ),
            id="fleet",
        ),
    ]
)
def simulate_page(request: pytest.FixtureRequest) -> _SimulatePage:
    """Each simulate page that shows the shared progress tracker."""
    return request.param


def _answer(route: Route, sse_body: str) -> None:
    route.fulfill(content_type="text/event-stream", body=sse_body)


def _wait_until_received_or_dropped(request: Request) -> None:
    """Return once the page has received the whole answer to request, or at once if it dropped the request unanswered."""
    response = request.response()
    if response is not None:
        response.body()


def _is_progress_stream_of(job_id: str) -> Callable[[Request], bool]:
    """Whether a request is the progress stream of the job job_id."""
    return lambda request: urlsplit(request.url).path == f"/api/jobs/{job_id}/progress"


class _RunningJobs:
    """The jobs of the runs the page submits, each running until the test ends it: until then its progress stream stays open, unanswered."""

    def __init__(self) -> None:
        self._endings: dict[str, str] = {}
        self._open_streams: dict[str, list[Route]] = {}

    def stream(self, route: Route) -> None:
        """Answer a job's progress stream with the job's ending if the test has ended the job, else hold it open."""
        job_id = urlsplit(route.request.url).path.split("/")[-2]
        if job_id in self._endings:
            _answer(route, self._endings[job_id])
        else:
            self._open_streams.setdefault(job_id, []).append(route)

    def end(self, job_id: str, event: str, data: dict[str, Any]) -> None:
        """End the job with one event carrying data, answering its open streams; return once the page has received or dropped each."""
        self._endings[job_id] = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        for route in self._open_streams.pop(job_id, []):
            _answer(route, self._endings[job_id])
            _wait_until_received_or_dropped(route.request)

    def abort_open_streams(self) -> None:
        """Abort every progress stream still held open."""
        for routes in self._open_streams.values():
            for route in routes:
                route.abort()


@pytest.fixture
def running_jobs(page: Page, simulate_page: _SimulatePage) -> Iterator[_RunningJobs]:
    """Accept the page's Nth run as job-N of run-N, so no run reaches the live server's JobManager, and keep each job running until the test ends it; abort the streams still open at teardown."""
    jobs = _RunningJobs()
    run_numbers = itertools.count(1)

    def _accept(route: Route) -> None:
        n = next(run_numbers)
        route.fulfill(status=201, json={"job_id": f"job-{n}", "run_id": f"run-{n}"})

    page.route(simulate_page.submission, _accept)
    page.route("**/api/jobs/*/progress", lambda route: jobs.stream(route))
    yield jobs
    jobs.abort_open_streams()


@pytest.mark.parametrize(
    ("event", "data", "outcome_text"),
    [
        pytest.param(
            "complete",
            {"status": "completed", "run_id": "run-1"},
            "Simulation completed successfully!",
            id="completed",
        ),
        pytest.param(
            "error",
            {"status": "failed", "message": "Run 1 failed"},
            "Simulation Failed",
            id="failed",
        ),
    ],
)
def test_a_run_started_while_another_runs_is_the_run_the_tracker_follows(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: _RunningJobs,
    page_errors: list[str],
    event: str,
    data: dict[str, Any],
    outcome_text: str,
) -> None:
    """Run, then Run again while job-1 still runs: the page drops job-1's progress stream, so job-1's later end, completed or failed, does not show on the tracker, and job-2's completion shows run-2's results link."""
    page.goto(live_server + simulate_page.path)
    run = page.get_by_role("button", name=simulate_page.run_button, exact=True)
    with page.expect_request("**/api/jobs/job-1/progress"):
        run.click()
    with (
        page.expect_request("**/api/jobs/job-2/progress"),
        page.expect_event("requestfailed", predicate=_is_progress_stream_of("job-1")),
    ):
        run.click()

    running_jobs.end("job-1", event, data)
    expect(page.get_by_text(outcome_text, exact=True)).to_have_count(0)

    running_jobs.end("job-2", "complete", {"status": "completed", "run_id": "run-2"})
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", simulate_page.results + "run-2"
    )
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_after_a_completed_run_starts_its_tracker_afresh(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: _RunningJobs,
    page_errors: list[str],
) -> None:
    """Run again after job-1 completed: while job-2 waits, the tracker shows 'Queued' and 'Waiting to start...', not job-1's last step and message, and no results link."""
    running_jobs.end(
        "job-1",
        "complete",
        {
            "status": "completed",
            "progress_pct": 100.0,
            "current_step": "Done",
            "message": "Run 1 is done",
            "run_id": "run-1",
        },
    )
    page.goto(live_server + simulate_page.path)
    run = page.get_by_role("button", name=simulate_page.run_button, exact=True)
    results_link = page.get_by_role("link", name="View Results", exact=True)
    run.click()
    expect(results_link).to_have_attribute("href", simulate_page.results + "run-1")

    with page.expect_request("**/api/jobs/job-2/progress"):
        run.click()

    expect(page.get_by_text("Queued", exact=True)).to_be_visible()
    expect(page.get_by_text("Waiting to start...", exact=True)).to_be_visible()
    expect(results_link).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"
