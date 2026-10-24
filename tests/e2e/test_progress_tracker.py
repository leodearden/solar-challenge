"""End-to-end tests for the progress tracker that /simulate/home and /simulate/fleet share.

Verifies, on each page, that the tracker follows the latest run. A run started
while an earlier one still runs is the run it follows: the page drops the
earlier run's progress stream, so the earlier run's end, completed or failed,
does not show. A run started after a completed one starts its tracker afresh.
A run whose progress stream disconnects shows it is reconnecting until the
stream the browser reopens reaches the server, which goes on to report the
run's progress and end. A reopened stream the server refuses fails the run,
as does a stream that stays broken past the page's reconnect limit. A run
whose job is cancelled because its run was deleted shows the cancellation,
not a failure.
"""

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e._job_requests import (
    DISCONNECTED_REQUEST_CONSOLE_ERROR,
    HeldJobRequests,
    disconnect_request,
    fast_forward_by_the_reconnect_limit,
    is_job_request,
    sse_event,
)


@dataclass(frozen=True)
class _SimulatePage:
    """A page that shows the tracker: its path, its Run button's name, and the route glob of the POST its Run sends."""

    path: str
    run_button: str
    submission: str


@pytest.fixture(
    params=[
        pytest.param(
            _SimulatePage(
                "/simulate/home",
                "Run Simulation",
                "**/api/simulate/home",
            ),
            id="home",
        ),
        pytest.param(
            _SimulatePage(
                "/simulate/fleet",
                "Run Fleet Simulation",
                "**/api/simulate/fleet-from-distribution",
            ),
            id="fleet",
        ),
    ]
)
def simulate_page(request: pytest.FixtureRequest) -> _SimulatePage:
    """Each simulate page that shows the shared progress tracker."""
    return request.param


@pytest.fixture
def running_jobs(page: Page, simulate_page: _SimulatePage) -> Iterator[HeldJobRequests]:
    """Accept the page's Nth run as job-N of run-N, whose results_url is /results/run-N as the server answers it, so no run reaches the live server's JobManager, and hold each job's progress stream open until the test answers it with the job's end; abort the streams still held at teardown."""
    jobs = HeldJobRequests("text/event-stream")
    run_numbers = itertools.count(1)

    def _accept(route: Route) -> None:
        n = next(run_numbers)
        route.fulfill(
            status=201,
            json={"job_id": f"job-{n}", "run_id": f"run-{n}", "results_url": f"/results/run-{n}"},
        )

    page.route(simulate_page.submission, _accept)
    page.route("**/api/jobs/*/progress", jobs.handle)
    yield jobs
    jobs.abort_held()


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
    running_jobs: HeldJobRequests,
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
        page.expect_event(
            "requestfailed", predicate=is_job_request("job-1", "progress")
        ),
    ):
        run.click()

    running_jobs.answer("job-1", sse_event(event, data))
    expect(page.get_by_text(outcome_text, exact=True)).to_have_count(0)

    running_jobs.answer(
        "job-2", sse_event("complete", {"status": "completed", "run_id": "run-2"})
    )
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", "/results/run-2"
    )
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_after_a_completed_run_starts_its_tracker_afresh(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run again after job-1 completed: while job-2 waits, the tracker shows 'Queued' and 'Waiting to start...', not job-1's last step and message, and no results link."""
    running_jobs.answer(
        "job-1",
        sse_event(
            "complete",
            {
                "status": "completed",
                "progress_pct": 100.0,
                "current_step": "Done",
                "message": "Run 1 is done",
                "run_id": "run-1",
            },
        ),
    )
    page.goto(live_server + simulate_page.path)
    run = page.get_by_role("button", name=simulate_page.run_button, exact=True)
    results_link = page.get_by_role("link", name="View Results", exact=True)
    run.click()
    expect(results_link).to_have_attribute("href", "/results/run-1")

    with page.expect_request("**/api/jobs/job-2/progress"):
        run.click()

    expect(page.get_by_text("Queued", exact=True)).to_be_visible()
    expect(page.get_by_text("Waiting to start...", exact=True)).to_be_visible()
    expect(results_link).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_whose_progress_stream_disconnects_shows_it_reconnecting_then_completes(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then disconnect job-1's progress stream while it runs: the tracker shows 'Reconnecting to server...', not 'Simulation Failed', and job-1's completion on the stream the browser reopens shows run-1's results link."""
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()
    reconnecting = page.get_by_text("Reconnecting to server...", exact=True)
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/job-1/progress"):
        running_jobs.disconnect("job-1")
        expect(reconnecting).to_be_visible()
        expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)

    running_jobs.answer(
        "job-1", sse_event("complete", {"status": "completed", "run_id": "run-1"})
    )
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", "/results/run-1"
    )
    expect(reconnecting).to_be_hidden()
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on {simulate_page.path}: {page_errors}"
    )


def test_a_run_whose_reopened_progress_stream_reaches_the_server_no_longer_shows_it_reconnecting(
    page: Page,
    live_server: str,
    release_held_simulations: Callable[[], None],
    page_errors: list[str],
) -> None:
    """Run on /simulate/home while the live server holds the job running, its first progress stream disconnected: once the stream the browser reopens reaches the server, the tracker shows the job's progress and no longer 'Reconnecting to server...', and it still follows the job past the page's reconnect limit, so the job's completion, once released, shows the results link."""
    page.clock.install()
    page.route("**/api/jobs/*/progress", disconnect_request, times=1)
    page.goto(live_server + "/simulate/home")
    with page.expect_request("**/api/jobs/*/progress"):
        page.get_by_role("button", name="Run Simulation", exact=True).click()
    reconnecting = page.get_by_text("Reconnecting to server...", exact=True)
    # The browser reopens the stream it lost, and the server answers it
    with page.expect_response("**/api/jobs/*/progress"):
        expect(reconnecting).to_be_visible()

    expect(page.get_by_text("Running home simulation...", exact=True)).to_be_visible()
    expect(reconnecting).to_be_hidden()
    fast_forward_by_the_reconnect_limit(page)

    release_held_simulations()
    expect(page.get_by_role("link", name="View Results", exact=True)).to_be_visible()
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on /simulate/home: {page_errors}"
    )


def test_a_run_whose_reopened_progress_stream_is_refused_is_shown_failed(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
) -> None:
    """Run, disconnect job-1's progress stream, and answer the stream the browser reopens with HTTP 503: the browser gives the stream up, so the tracker shows 'Simulation Failed' with 'Lost connection to server', and no longer 'Reconnecting to server...'."""
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()
    reconnecting = page.get_by_text("Reconnecting to server...", exact=True)
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/job-1/progress"):
        running_jobs.disconnect("job-1")
        expect(reconnecting).to_be_visible()

    running_jobs.answer("job-1", "", status=503)
    expect(page.get_by_text("Simulation Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("Lost connection to server", exact=True)).to_be_visible()
    expect(reconnecting).to_be_hidden()


def test_a_run_whose_progress_stream_stays_broken_past_the_reconnect_limit_is_shown_failed(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, disconnect job-1's progress stream, and leave the stream the browser reopens unanswered: once the page's reconnect limit has passed, the page drops the stream, and the tracker shows 'Simulation Failed' with 'Lost connection to server', and no longer 'Reconnecting to server...'."""
    page.clock.install()
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()
    reconnecting = page.get_by_text("Reconnecting to server...", exact=True)
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/job-1/progress"):
        running_jobs.disconnect("job-1")
        expect(reconnecting).to_be_visible()

    with page.expect_event(
        "requestfailed", predicate=is_job_request("job-1", "progress")
    ):
        fast_forward_by_the_reconnect_limit(page)
    expect(page.get_by_text("Simulation Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("Lost connection to server", exact=True)).to_be_visible()
    expect(reconnecting).to_be_hidden()
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on {simulate_page.path}: {page_errors}"
    )


def test_a_run_whose_job_is_cancelled_shows_its_cancellation_not_a_failure(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then answer job-1's progress stream with the error event of a job cancelled because its run was deleted: the tracker shows the step 'Cancelled' and the server's message, not 'Simulation Failed', and no results link."""
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()

    running_jobs.answer(
        "job-1",
        sse_event("error", {"status": "cancelled", "message": "Cancelled: its run was deleted"}),
    )

    expect(page.get_by_text("Cancelled: its run was deleted", exact=True)).to_be_visible()
    expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()
    expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_deleted_while_its_job_runs_on_the_server_shows_its_job_cancelled(
    page: Page,
    live_server: str,
    release_held_simulations: Callable[[], None],
    page_errors: list[str],
) -> None:
    """Run on /simulate/home while the live server holds the job in its simulation, then delete its run, as Run History's Delete does: once the job is released, the tracker shows its cancellation, not 'Simulation Failed', and no results link."""
    page.goto(live_server + "/simulate/home")
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation", exact=True).click()
    run_id = submission.value.json()["run_id"]
    expect(page.get_by_text("Running home simulation...", exact=True)).to_be_visible()

    response = page.request.delete(f"{live_server}/api/history/runs/{run_id}")
    assert response.status == 200
    release_held_simulations()

    expect(page.get_by_text("Cancelled: its run was deleted", exact=True)).to_be_visible()
    expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on /simulate/home: {page_errors}"
