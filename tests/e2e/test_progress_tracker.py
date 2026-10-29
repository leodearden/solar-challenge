"""End-to-end tests for the progress tracker that /simulate/home and /simulate/fleet share.

Verifies, on each page, that the tracker follows the latest run. A run started
while an earlier one still runs is the run it follows: the page drops the
earlier run's progress stream, so the earlier run's end, completed or failed,
does not show. A run started after a completed one starts its tracker afresh.
A run whose job fails shows the job's message; one whose job is cancelled
because its run was deleted shows the cancellation, not a failure; and one
whose job the server no longer tracks says so, not that it failed. A run
whose final state the page cannot read is shown lost, not left running.

A run whose progress stream times out, as the server ends a stream open past
its limit while the job goes on, follows the job on the stream the browser
reopens without showing it reconnecting, though a reopen left unanswered past
the page's reconnect limit still fails the run; on the live server, a run
follows its job through several timeouts to its results. A run whose progress
stream disconnects shows it is reconnecting until the stream the browser
reopens reaches the server, which goes on to report the run's progress and
end. A reopened stream the server refuses fails the run, as does a stream that
stays broken past the page's reconnect limit.

Each faked stream is answered with frames the server's own encoder builds from
its catalogue (tests/e2e/_job_requests.py).
"""

import itertools
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Response, Route, expect

from tests.e2e._job_requests import (
    DISCONNECTED_REQUEST_CONSOLE_ERROR,
    HeldJobRequests,
    a_job_state,
    disconnect_request,
    fast_forward_by_the_reconnect_limit,
    is_job_request,
    job_state_frame,
    timeout_frame,
    unreadable_final_state_frame,
    untracked_frame,
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
    ("job_1_end", "outcome_text"),
    [
        pytest.param(
            job_state_frame(a_job_state("job-1", "run-1", "completed"), version=5),
            "Simulation completed successfully!",
            id="completed",
        ),
        pytest.param(
            job_state_frame(a_job_state("job-1", "run-1", "failed", message="Run 1 failed"), version=4),
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
    job_1_end: str,
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

    running_jobs.answer("job-1", job_1_end)
    expect(page.get_by_text(outcome_text, exact=True)).to_have_count(0)

    running_jobs.answer(
        "job-2", job_state_frame(a_job_state("job-2", "run-2", "completed"), version=5)
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
        job_state_frame(a_job_state("job-1", "run-1", "completed", message="Run 1 is done"), version=5),
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
        "job-1", job_state_frame(a_job_state("job-1", "run-1", "completed"), version=5)
    )
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", "/results/run-1"
    )
    expect(reconnecting).to_be_hidden()
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on {simulate_page.path}: {page_errors}"
    )


def test_a_run_whose_progress_stream_times_out_follows_its_job_on_the_reopened_stream_without_showing_it_reconnecting(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then end job-1's progress stream with its running state and a timeout, as the server ends a stream open past its limit while the job goes on: while the stream the browser reopens is held, the tracker still shows the job's progress, and neither 'Reconnecting to server...' nor 'Simulation Failed', and job-1's completion on the reopened stream shows run-1's results link."""
    running = a_job_state("job-1", "run-1", "running")
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()
    # The browser reopens the stream that timed out
    with page.expect_request("**/api/jobs/job-1/progress"):
        running_jobs.answer_once("job-1", job_state_frame(running, version=3) + timeout_frame())

    expect(page.get_by_text(running.message, exact=True)).to_be_visible()
    expect(page.get_by_text("Reconnecting to server...", exact=True)).to_be_hidden()
    expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)

    running_jobs.answer(
        "job-1", job_state_frame(a_job_state("job-1", "run-1", "completed"), version=5)
    )
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", "/results/run-1"
    )
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_whose_progress_stream_times_out_and_whose_reopen_stays_unanswered_past_the_reconnect_limit_is_shown_failed(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, end job-1's progress stream with its running state and a timeout, and leave the stream the browser reopens unanswered: once the page's reconnect limit has passed, the page drops the stream, and the tracker shows 'Simulation Failed' with 'Lost connection to server'."""
    page.clock.install()
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()
    # The browser reopens the stream that timed out
    with page.expect_request("**/api/jobs/job-1/progress"):
        running_jobs.answer_once(
            "job-1",
            job_state_frame(a_job_state("job-1", "run-1", "running"), version=3) + timeout_frame(),
        )

    with page.expect_event(
        "requestfailed", predicate=is_job_request("job-1", "progress")
    ):
        fast_forward_by_the_reconnect_limit(page)
    expect(page.get_by_text("Simulation Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("Lost connection to server", exact=True)).to_be_visible()
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


# How long a test waits for each progress stream the browser reopens after a timeout: a stream lasts 1 to 1.25 s
# under job_streams_time_out_after_a_second and the browser reopens it a retry, 1 s, later
_A_TIMEOUT_AND_REOPEN_WITH_MARGIN_MS = 10_000


def _is_a_progress_stream(response: Response) -> bool:
    """Whether response answers a request for a job's progress stream, /api/jobs/<job_id>/progress."""
    path = urlsplit(response.url).path
    return path.startswith("/api/jobs/") and path.endswith("/progress")


def _wait_until_received(page: Page, responses: list[Response], count: int) -> None:
    """Return once responses, which a listener on the page fills with the progress streams it receives, holds count of them, waiting up to _A_TIMEOUT_AND_REOPEN_WITH_MARGIN_MS for each."""
    while len(responses) < count:
        page.wait_for_event(
            "response", predicate=_is_a_progress_stream, timeout=_A_TIMEOUT_AND_REOPEN_WITH_MARGIN_MS
        )


@pytest.mark.usefixtures("job_streams_time_out_after_a_second")
def test_a_run_whose_progress_streams_time_out_follows_its_job_through_each_reopen_to_its_results(
    page: Page,
    live_server: str,
    release_held_simulations: Callable[[], None],
    page_errors: list[str],
) -> None:
    """Run on /simulate/home while the live server holds the job running and ends each of its progress streams with a timeout about a second after it opens: the tracker follows the job through at least two timeouts, each stream the browser reopens reaching the server, shows neither 'Reconnecting to server...' once each reopen lands nor 'Simulation Failed', and shows the results link the server answered the submission with once the job is released."""
    progress_streams: list[Response] = []
    page.on(
        "response",
        lambda response: progress_streams.append(response) if _is_a_progress_stream(response) else None,
    )
    page.goto(live_server + "/simulate/home")
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation", exact=True).click()
    reconnecting = page.get_by_text("Reconnecting to server...", exact=True)
    failed = page.get_by_text("Simulation Failed", exact=True)
    # The first stream, then the two reopens after its timeout and the next
    for streams_received in (2, 3):
        _wait_until_received(page, progress_streams, streams_received)
        expect(reconnecting).to_be_hidden()
        expect(failed).to_have_count(0)

    release_held_simulations()
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_attribute(
        "href", submission.value.json()["results_url"]
    )
    assert page_errors == [], f"Errors on /simulate/home: {page_errors}"


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


def test_a_run_whose_job_fails_shows_the_jobs_message(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then answer job-1's progress stream with its running state and then its failed state: the tracker shows 'Simulation Failed' and the job's message, once, beside the job's last progress message, and no results link."""
    running = a_job_state("job-1", "run-1", "running")
    running_jobs.answer(
        "job-1",
        job_state_frame(running, version=3)
        + job_state_frame(a_job_state("job-1", "run-1", "failed", message="Run 1 failed"), version=4),
    )
    page.goto(live_server + simulate_page.path)
    page.get_by_role("button", name=simulate_page.run_button, exact=True).click()

    expect(page.get_by_text("Simulation Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("Run 1 failed", exact=True)).to_be_visible()
    expect(page.get_by_text(running.message, exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_whose_job_is_cancelled_shows_its_cancellation_not_a_failure(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then answer job-1's progress stream with the cancelled state of a job whose run was deleted: the tracker shows its 'Cancelled' heading and the job's message, not 'Simulation Failed', and no results link."""
    cancelled = a_job_state("job-1", "run-1", "cancelled")
    page.goto(live_server + simulate_page.path)
    with page.expect_request("**/api/jobs/job-1/progress"):
        page.get_by_role("button", name=simulate_page.run_button, exact=True).click()

    running_jobs.answer("job-1", job_state_frame(cancelled, version=4))

    expect(page.get_by_text(cancelled.message, exact=True)).to_be_visible()
    expect(page.get_by_text("Cancelled", exact=True)).to_be_visible()
    expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_whose_job_the_server_no_longer_tracks_says_so_not_that_it_failed(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then answer job-1's progress stream with the untracked event of a job the server does not track: the tracker says the server no longer tracks the job and that its run is in Run History, not 'Simulation Failed', and shows no results link."""
    running_jobs.answer("job-1", untracked_frame("job-1"))
    page.goto(live_server + simulate_page.path)
    page.get_by_role("button", name=simulate_page.run_button, exact=True).click()

    expect(
        page.get_by_text(
            "The server no longer tracks this job. Its run is in Run History.", exact=True
        )
    ).to_be_visible()
    expect(page.get_by_text("Simulation Failed", exact=True)).to_have_count(0)
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on {simulate_page.path}: {page_errors}"


def test_a_run_whose_final_state_the_page_cannot_read_is_shown_lost_not_left_running(
    page: Page,
    live_server: str,
    simulate_page: _SimulatePage,
    running_jobs: HeldJobRequests,
    page_errors: list[str],
) -> None:
    """Run, then end job-1's progress stream with a final state the page cannot read: the tracker shows 'Simulation Failed' with 'Lost connection to server' and no results link, and the page reports the frame it could not read as an uncaught error."""
    running_jobs.answer("job-1", unreadable_final_state_frame("job-1", "run-1"))
    page.goto(live_server + simulate_page.path)
    page.get_by_role("button", name=simulate_page.run_button, exact=True).click()

    expect(page.get_by_text("Simulation Failed", exact=True)).to_be_visible()
    expect(page.get_by_text("Lost connection to server", exact=True)).to_be_visible()
    expect(page.get_by_role("link", name="View Results", exact=True)).to_have_count(0)
    assert len(page_errors) == 1 and "JSON" in page_errors[0], (
        f"Errors on {simulate_page.path}: {page_errors}"
    )


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
