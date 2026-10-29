"""End-to-end tests for the Parameter Sweep page (/scenarios/sweep).

Verifies page loading, that each form control is found by role and by the name
its label gives it, that the radio group named "Sweep Mode" holds the Linear
and Geometric radios and the group named "Base Configuration" holds the
Battery (kWh), Location and Days controls, preview calculations (the preview
lists its values in the list named "Sweep values"), that submitting a sweep
filled into the form returns one background job per sweep point, and detects
Bug B1 (Alpine race condition with external JS).

Also verifies that each sweep point's row shows how its own job ended, that
its status badge takes the classes the server draws for that status, that the
table's header names the parameter the sweep ran, not one selected since, that
running a sweep drops the requests the sweep before it still has in flight and
opens no stream for the points that sweep had yet to follow, that an earlier
sweep's results, arriving after a later sweep's rows show, fill none of them,
and that the page says why when it loses track of a sweep. A point whose job
is cancelled, or which the server no longer tracks, shows that in its row, and
the page goes on to follow the next point. A point whose progress stream
disconnects keeps its status, and the page follows it alone while the browser
reopens the stream; its job's completion on the reopened stream fills its row,
and a reopened stream the server refuses fails it, as does a stream that stays
broken past the page's reconnect limit. A point whose progress stream times
out while its job runs keeps showing running while the browser reopens the
stream, and the page follows it alone until its job ends; once the sweep's
other point fails and it completes, the page draws the charts of its run.

Once every point of a sweep has ended, the page posts the finished points to
POST /scenarios/sweep/chart, labelled with the parameter the sweep ran, and
shows the chart panels it answers in the region named "Sweep charts", or why
it could not draw them; a sweep run after it drops that request and clears the
region.

Last, verifies that another tab loads Run History while the jobs of an
8-point sweep run, and that each point's row then shows its results, and that
a real three-point sweep draws one chart per metric from its points' runs.

Each faked progress stream is answered with frames the server's own encoder
builds from its catalogue (tests/e2e/_job_requests.py).
"""

import itertools
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import BrowserContext, Locator, Page, Request, Route, expect

from tests._server_drawn_badges import server_drawn_classes
from tests.e2e._job_requests import (
    DISCONNECTED_REQUEST_CONSOLE_ERROR,
    HeldJobRequests,
    a_job_state,
    fast_forward_by_the_reconnect_limit,
    is_job_request,
    job_state_frame,
    timeout_frame,
    untracked_frame,
)
from tests.e2e._run_badges import classes_of_each


# -- Page loading ----------------------------------------------------------


def test_sweep_page_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/sweep returns a page with 'Parameter Sweep' heading."""
    response = page.goto(live_server + "/scenarios/sweep")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Parameter Sweep").first
    expect(heading).to_be_visible()


# -- Bug B1: Alpine race condition with external JS -----------------------


def test_sweep_no_js_errors(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """The sweep page should load without JavaScript errors.

    The ``parameterSweep()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Depending on script
    execution order, Alpine.js may try to evaluate the ``x-data``
    attribute before the component function is registered, which throws
    an uncaught ReferenceError.
    """
    page.goto(live_server + "/scenarios/sweep")
    page.wait_for_load_state("networkidle")

    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


# -- Sweep configuration form controls -------------------------------------


_SWEEP_FORM_CONTROLS = (
    pytest.param("combobox", "Parameter to Sweep", id="parameter"),
    pytest.param("spinbutton", "Min Value", id="min"),
    pytest.param("spinbutton", "Max Value", id="max"),
    pytest.param("spinbutton", "Steps", id="steps"),
    pytest.param("radio", "Linear", id="linear"),
    pytest.param("radio", "Geometric", id="geometric"),
    pytest.param("spinbutton", "Battery (kWh)", id="battery_kwh"),
    pytest.param("combobox", "Location", id="location"),
    pytest.param("spinbutton", "Days", id="days"),
)


@pytest.mark.parametrize(("role", "label"), _SWEEP_FORM_CONTROLS)
def test_sweep_form_control_is_named_by_its_label(
    page: Page, live_server: str, role: str, label: str
) -> None:
    """Each sweep form control is found by role and by the accessible name its label gives it."""
    page.goto(live_server + "/scenarios/sweep")

    expect(page.get_by_role(role, name=label, exact=True)).to_be_visible()


# -- Sweep form control groups ---------------------------------------------


def test_sweep_mode_radio_group_holds_the_linear_and_geometric_radios(
    page: Page, live_server: str
) -> None:
    """The radio group named "Sweep Mode" holds exactly two radios, Linear and Geometric."""
    page.goto(live_server + "/scenarios/sweep")

    sweep_mode = page.get_by_role("radiogroup", name="Sweep Mode", exact=True)
    expect(sweep_mode.get_by_role("radio")).to_have_count(2)
    expect(sweep_mode.get_by_role("radio", name="Linear", exact=True)).to_be_visible()
    expect(
        sweep_mode.get_by_role("radio", name="Geometric", exact=True)
    ).to_be_visible()


def test_base_configuration_group_holds_the_battery_location_and_days_controls(
    page: Page, live_server: str
) -> None:
    """The group named "Base Configuration" holds exactly two spinbuttons, Battery (kWh) and Days, and one combobox, Location."""
    page.goto(live_server + "/scenarios/sweep")

    base_configuration = page.get_by_role(
        "group", name="Base Configuration", exact=True
    )
    expect(base_configuration.get_by_role("spinbutton")).to_have_count(2)
    expect(base_configuration.get_by_role("combobox")).to_have_count(1)
    expect(
        base_configuration.get_by_role("spinbutton", name="Battery (kWh)", exact=True)
    ).to_be_visible()
    expect(
        base_configuration.get_by_role("combobox", name="Location", exact=True)
    ).to_be_visible()
    expect(
        base_configuration.get_by_role("spinbutton", name="Days", exact=True)
    ).to_be_visible()


# -- Preview updates when inputs change ------------------------------------


def test_sweep_preview_updates(page: Page, live_server: str) -> None:
    """Filling in min=1, max=10, steps=5 previews the five linear sweep values from 1 to 10, listed in the list named "Sweep values"."""
    page.goto(live_server + "/scenarios/sweep")

    page.get_by_label("Min Value", exact=True).fill("1")
    page.get_by_label("Max Value", exact=True).fill("10")
    page.get_by_label("Steps", exact=True).fill("5")

    expect(page.get_by_text("5 values will be tested", exact=True)).to_be_visible()
    sweep_values = page.get_by_role("list", name="Sweep values", exact=True)
    expect(sweep_values.get_by_role("listitem")).to_have_text(
        ["1", "3.25", "5.5", "7.75", "10"]
    )


# -- Sweep submission: one background home job per sweep point ------------


def test_sweep_submit_returns_201_with_job_ids(page: Page, live_server: str) -> None:
    """Filling the form with a 3-point geometric sweep from 1 to 9 and clicking its
    button returns 201 with the geometric sweep values and one distinct
    background home-job id per sweep point.

    Min, max, steps and mode are all moved off their defaults, so the response's
    values prove that each filled control reached the request.
    """
    page.goto(live_server + "/scenarios/sweep")

    page.get_by_label("Min Value", exact=True).fill("1")
    page.get_by_label("Max Value", exact=True).fill("9")
    page.get_by_label("Steps", exact=True).fill("3")
    page.get_by_role("radio", name="Geometric", exact=True).check()

    # Intercept the API call and click the submit button
    with page.expect_response("**/api/simulate/sweep") as response_info:
        page.get_by_role("button", name="Run Parameter Sweep").click()

    response = response_info.value
    assert response.status == 201

    data = response.json()
    assert data["values"] == [1.0, 3.0, 9.0]

    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3
    assert all(job_ids)


# -- Each point's row follows its own sweep's job, the header its parameter --


_SWEEP_CHARTS_URL = "**/scenarios/sweep/chart"


@dataclass(frozen=True)
class _SweepJobs:
    """The jobs of the sweeps the page submits: each job's progress stream, and once it completes its results, held until the test answers them."""

    progress: HeldJobRequests
    results: HeldJobRequests


@pytest.fixture
def sweep_jobs(page: Page) -> Iterator[_SweepJobs]:
    """Accept the page's Nth sweep with two points, N and N + 10, which run as the jobs sweep-N-point-1 and sweep-N-point-2, so no point reaches the live server's JobManager; abort the requests still held at teardown.

    The page's requests for a sweep's charts are held too, so no faked point's run id reaches the live server, whose
    400 would log a console error. A test that needs the charts answered routes their URL itself; Playwright consults
    the newer route first.
    """
    sweep_numbers = itertools.count(1)

    def _accept(route: Route) -> None:
        n = next(sweep_numbers)
        route.fulfill(
            status=201,
            json={
                "parameter": "pv_capacity_kw",
                "values": [float(n), float(n + 10)],
                "job_ids": [f"sweep-{n}-point-1", f"sweep-{n}-point-2"],
            },
        )

    jobs = _SweepJobs(
        HeldJobRequests("text/event-stream"), HeldJobRequests("application/json")
    )
    held_chart_requests: list[Route] = []

    def _hold(route: Route) -> None:
        held_chart_requests.append(route)

    page.route("**/api/simulate/sweep", _accept)
    page.route("**/api/jobs/*/progress", jobs.progress.handle)
    page.route("**/api/jobs/*/results", jobs.results.handle)
    page.route(_SWEEP_CHARTS_URL, _hold)
    yield jobs
    jobs.progress.abort_held()
    jobs.results.abort_held()
    while held_chart_requests:
        held_chart_requests.pop().abort()


def _completion(job_id: str) -> str:
    """The frame that ends job_id's progress stream with its completed state, of the run run-of-<job_id>."""
    return job_state_frame(a_job_state(job_id, f"run-of-{job_id}", "completed"), version=5)


def _failure(job_id: str, message: str) -> str:
    """The frame that ends job_id's progress stream with its failed state, of the run run-of-<job_id>, naming message."""
    return job_state_frame(a_job_state(job_id, f"run-of-{job_id}", "failed", message=message), version=4)


def _results(
    generation_kwh: float, self_consumption_ratio: float, grid_import_kwh: float
) -> str:
    """A completed job's results, carrying the summary figures a sweep row shows."""
    return json.dumps(
        {
            "summary": {
                "total_generation_kwh": generation_kwh,
                "self_consumption_ratio": self_consumption_ratio,
                "total_grid_import_kwh": grid_import_kwh,
            }
        }
    )


def _result_rows(page: Page) -> Locator:
    """The Sweep Results table's rows, one per sweep point: its rows of cells, which leaves out the header row."""
    return page.get_by_role("row").filter(has=page.get_by_role("cell"))


def test_a_sweep_point_whose_job_fails_shows_failed_in_its_own_row(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run a sweep whose first point's job fails while its second still runs: the first row shows failed, the second still pending."""
    sweep_jobs.progress.answer("sweep-1-point-1", _failure("sweep-1-point-1", "Point 1 failed"))
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(["1", "-", "-", "-", "failed"])
    expect(rows.nth(1).get_by_role("cell")).to_have_text(
        ["11", "-", "-", "-", "pending"]
    )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


@pytest.mark.parametrize(
    ("ending", "status"),
    [
        pytest.param(
            job_state_frame(a_job_state("sweep-1-point-1", "run-of-sweep-1-point-1", "cancelled"), version=4),
            "cancelled",
            id="cancelled",
        ),
        pytest.param(untracked_frame("sweep-1-point-1"), "untracked", id="untracked"),
    ],
)
def test_a_sweep_point_whose_job_is_cancelled_or_no_longer_tracked_shows_it_in_its_own_row(
    page: Page,
    live_server: str,
    sweep_jobs: _SweepJobs,
    page_errors: list[str],
    ending: str,
    status: str,
) -> None:
    """Run a sweep whose first point's progress stream ends with its job cancelled, or with the server no longer tracking the job: the first row shows that ending as its status, and the page goes on to follow the second point."""
    sweep_jobs.progress.answer("sweep-1-point-1", ending)
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-2/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    expect(_result_rows(page).nth(0).get_by_role("cell")).to_have_text(
        ["1", "-", "-", "-", status]
    )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def _status_badge(row: Locator) -> Locator:
    """The badge in a sweep row's last cell, which shows the status of its point's job."""
    return row.get_by_role("cell").last.locator("span")


def test_each_sweep_rows_status_badge_takes_the_classes_the_server_draws_for_its_status(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, dashboard_macros: Any
) -> None:
    """Run a sweep whose first point completes while its second is pending, then fail the second: each row's status badge carries exactly the classes run_status_badge draws on the server for its status.

    The Run History badge test covers 'running' through the same macro.
    """
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    rows = _result_rows(page)

    for row, status in ((rows.nth(0), "completed"), (rows.nth(1), "pending")):
        expect(_status_badge(row)).to_have_text(status)
        assert classes_of_each(_status_badge(row)) == [
            server_drawn_classes(dashboard_macros.run_status_badge(status))
        ], status

    sweep_jobs.progress.answer("sweep-1-point-2", _failure("sweep-1-point-2", "Point 2 failed"))

    expect(_status_badge(rows.nth(1))).to_have_text("failed")
    assert classes_of_each(_status_badge(rows.nth(1))) == [
        server_drawn_classes(dashboard_macros.run_status_badge("failed"))
    ]


def test_the_results_table_header_names_the_parameter_swept_not_the_one_selected_since(
    page: Page, live_server: str, sweep_jobs: _SweepJobs
) -> None:
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-2/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    expect(page.get_by_role("columnheader", name="PV Capacity (kW)", exact=True)).to_be_visible()

    page.get_by_role("combobox", name="Parameter to Sweep", exact=True).select_option(label="Battery Capacity (kWh)")

    expect(page.get_by_role("columnheader", name="PV Capacity (kW)", exact=True)).to_be_visible()
    expect(page.get_by_role("columnheader", name="Battery Capacity (kWh)", exact=True)).to_have_count(0)


def test_an_earlier_sweeps_late_results_fill_no_row_of_the_sweep_run_after_it(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run, then Run again while sweep-1's completed first point's results still load: those results, answered once sweep-2's rows show, fill no row of sweep-2's, neither its failed first point's nor its completed second point's, which shows its own."""
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    sweep_jobs.progress.answer("sweep-2-point-1", _failure("sweep-2-point-1", "Point 1 failed"))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    with page.expect_request("**/api/jobs/sweep-1-point-1/results"):
        run.click()
    with page.expect_request("**/api/jobs/sweep-2-point-2/progress"):
        run.click()
    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(["2", "-", "-", "-", "failed"])

    sweep_jobs.results.answer("sweep-1-point-1", _results(111.1, 0.25, 11.1))
    with page.expect_request("**/api/jobs/sweep-2-point-2/results"):
        sweep_jobs.progress.answer("sweep-2-point-2", _completion("sweep-2-point-2"))
    sweep_jobs.results.answer("sweep-2-point-2", _results(222.2, 0.5, 22.2))

    expect(rows.nth(1).get_by_role("cell")).to_have_text(
        ["12", "222.2", "50.0%", "22.2", "completed"]
    )
    expect(rows.nth(0).get_by_role("cell")).to_have_text(["2", "-", "-", "-", "failed"])
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_a_sweep_run_after_another_drops_the_earlier_sweeps_requests(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run, then Run again while sweep-1's completed first point's results still load and its second point still runs: the page drops both requests, the first point's results request and the second point's progress stream, and goes on to follow sweep-2's first point."""
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    with (
        page.expect_request("**/api/jobs/sweep-1-point-1/results"),
        page.expect_request("**/api/jobs/sweep-1-point-2/progress"),
    ):
        run.click()
    with (
        page.expect_event(
            "requestfailed", predicate=is_job_request("sweep-1-point-1", "results")
        ),
        page.expect_event(
            "requestfailed", predicate=is_job_request("sweep-1-point-2", "progress")
        ),
        page.expect_request("**/api/jobs/sweep-2-point-1/progress"),
    ):
        run.click()
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_a_sweep_run_after_another_opens_no_stream_for_the_earlier_sweeps_remaining_points(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run, then Run again while the page follows sweep-1's first point: the page goes on to follow sweep-2's first point, having opened no progress stream for sweep-1's second point."""
    requests_made: list[Request] = []
    page.on("request", lambda request: requests_made.append(request))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        run.click()
    with page.expect_request("**/api/jobs/sweep-2-point-1/progress"):
        run.click()

    opens_sweep_1_point_2 = is_job_request("sweep-1-point-2", "progress")
    assert [
        request.url for request in requests_made if opens_sweep_1_point_2(request)
    ] == []
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_the_page_says_why_it_lost_track_of_a_sweep_it_cannot_follow(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run a sweep in a browser whose EventSource constructor throws, as a real one does for a URL it cannot parse: the page says why it lost track of the sweep, and leaves no error uncaught."""
    page.add_init_script(
        "window.EventSource = class {"
        " constructor() { throw new Error('this browser opens no event streams'); } };"
    )
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    expect(
        page.get_by_text(
            "Lost track of the sweep: this browser opens no event streams", exact=True
        )
    ).to_be_visible()
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_a_sweep_point_whose_progress_stream_disconnects_shows_its_results_once_its_job_completes(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run a sweep, then disconnect its first point's progress stream while the job runs: the browser reopens the stream, the page still follows that point alone, its row still pending, not failed, and the job's completion on the reopened stream fills the row with its results."""
    requests_made: list[Request] = []
    page.on("request", lambda request: requests_made.append(request))
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        sweep_jobs.progress.disconnect("sweep-1-point-1")
    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["1", "-", "-", "-", "pending"]
    )
    opens_sweep_1_point_2 = is_job_request("sweep-1-point-2", "progress")
    assert [
        request.url for request in requests_made if opens_sweep_1_point_2(request)
    ] == []

    sweep_jobs.results.answer("sweep-1-point-1", _results(111.1, 0.25, 11.1))
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))

    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["1", "111.1", "25.0%", "11.1", "completed"]
    )
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on /scenarios/sweep: {page_errors}"
    )


def test_a_sweep_point_whose_reopened_progress_stream_is_refused_shows_failed(
    page: Page, live_server: str, sweep_jobs: _SweepJobs
) -> None:
    """Run a sweep, disconnect its first point's progress stream, and answer the stream the browser reopens with HTTP 503: the browser gives the stream up, so the row shows failed and the page goes on to follow the second point."""
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        sweep_jobs.progress.disconnect("sweep-1-point-1")

    with page.expect_request("**/api/jobs/sweep-1-point-2/progress"):
        sweep_jobs.progress.answer("sweep-1-point-1", "", status=503)
    expect(_result_rows(page).nth(0).get_by_role("cell")).to_have_text(
        ["1", "-", "-", "-", "failed"]
    )


def test_a_sweep_point_whose_progress_stream_stays_broken_past_the_reconnect_limit_shows_failed(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run a sweep, disconnect its first point's progress stream, and leave the stream the browser reopens unanswered: once the page's reconnect limit has passed, the row shows failed and the page goes on to follow the second point."""
    page.clock.install()
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    # The browser reopens the stream it lost
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        sweep_jobs.progress.disconnect("sweep-1-point-1")

    with page.expect_request("**/api/jobs/sweep-1-point-2/progress"):
        fast_forward_by_the_reconnect_limit(page)
    expect(_result_rows(page).nth(0).get_by_role("cell")).to_have_text(
        ["1", "-", "-", "-", "failed"]
    )
    assert page_errors == [DISCONNECTED_REQUEST_CONSOLE_ERROR], (
        f"Errors on /scenarios/sweep: {page_errors}"
    )


# -- The sweep's charts, once every point has ended -------------------------


def _is_the_sweep_charts_request(request: Request) -> bool:
    return request.url.endswith("/scenarios/sweep/chart")


def _sweep_charts(page: Page) -> Locator:
    """The region the sweep page shows the chart panels of its last sweep in."""
    return page.get_by_role("region", name="Sweep charts", exact=True)


def test_once_every_point_has_ended_the_page_posts_the_finished_points_labelled_with_the_parameter_swept(
    page: Page, live_server: str, sweep_jobs: _SweepJobs
) -> None:
    """The failed second point is left out, and the label is the parameter the sweep ran, not the one selected since."""
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-2/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    page.get_by_role("combobox", name="Parameter to Sweep", exact=True).select_option(label="Battery Capacity (kWh)")

    with page.expect_request(_SWEEP_CHARTS_URL) as charts_request:
        sweep_jobs.progress.answer("sweep-1-point-2", _failure("sweep-1-point-2", "Point 2 failed"))

    assert charts_request.value.post_data_json == {
        "parameter_label": "PV Capacity (kW)",
        "points": [{"value": 1, "run_id": "run-of-sweep-1-point-1"}],
    }


def test_a_sweep_run_after_another_drops_the_earlier_sweeps_charts_request(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    sweep_jobs.progress.answer("sweep-1-point-2", _completion("sweep-1-point-2"))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    with page.expect_request(_SWEEP_CHARTS_URL):
        run.click()

    with page.expect_event("requestfailed", predicate=_is_the_sweep_charts_request):
        run.click()

    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_a_sweep_run_after_another_clears_the_earlier_sweeps_charts(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    page.route(
        _SWEEP_CHARTS_URL,
        lambda route: route.fulfill(
            status=200, content_type="text/html", body="<p id=\"chart-sweep-generation\">The first sweep's charts</p>"
        ),
    )
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    sweep_jobs.progress.answer("sweep-1-point-2", _completion("sweep-1-point-2"))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    run.click()
    expect(_sweep_charts(page).get_by_text("The first sweep's charts", exact=True)).to_be_visible()

    run.click()

    expect(page.get_by_text("The first sweep's charts", exact=True)).to_have_count(0)
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


@pytest.mark.parametrize(
    ("answer", "why"),
    [
        pytest.param(
            {"status": 400, "json": {"error": "Run 'run-of-sweep-1-point-1' is unknown"}},
            "Run 'run-of-sweep-1-point-1' is unknown",
            id="a-refusal-naming-its-error",
        ),
        pytest.param(
            {"status": 500, "content_type": "text/html", "body": "<h1>Internal Server Error</h1>"},
            "HTTP 500",
            id="an-error-page-that-is-not-json",
        ),
    ],
)
def test_the_page_says_why_it_could_not_draw_the_sweep_charts(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, answer: dict[str, Any], why: str
) -> None:
    """A refusal is named by its error, and an answer that is not JSON, such as the app's HTML 500 page, by its status.

    The failed answer is a console error Chromium logs, so this test does not read the page's errors.
    """
    page.route(_SWEEP_CHARTS_URL, lambda route: route.fulfill(**answer))
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    sweep_jobs.progress.answer("sweep-1-point-2", _completion("sweep-1-point-2"))
    page.goto(live_server + "/scenarios/sweep")

    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    expect(page.get_by_text(f"Could not draw the sweep charts: {why}", exact=True)).to_be_visible()


def test_a_sweep_point_whose_progress_stream_times_out_keeps_running_until_its_job_completes_and_the_sweep_draws_its_run(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run a two-point sweep, then end its first point's progress stream with the job's running state and a timeout, as the server ends a stream open past its limit while the job goes on: while the stream the browser reopens is held, the first row still shows running and the page has opened no stream for the second point. Once the second point's job fails and the first's completes on the reopened stream, the first row shows its results, the second failed, and the charts region shows the panel the page is answered with for the first point's run alone."""
    page.route(
        _SWEEP_CHARTS_URL,
        lambda route: route.fulfill(status=200, content_type="text/html", body="<p>The sweep's charts</p>"),
    )
    requests_made: list[Request] = []
    page.on("request", lambda request: requests_made.append(request))
    page.goto(live_server + "/scenarios/sweep")
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    # The browser reopens the stream that timed out
    with page.expect_request("**/api/jobs/sweep-1-point-1/progress"):
        sweep_jobs.progress.answer_once(
            "sweep-1-point-1",
            job_state_frame(a_job_state("sweep-1-point-1", "run-of-sweep-1-point-1", "running"), version=3)
            + timeout_frame(),
        )
    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["1", "-", "-", "-", "running"]
    )
    opens_sweep_1_point_2 = is_job_request("sweep-1-point-2", "progress")
    assert [
        request.url for request in requests_made if opens_sweep_1_point_2(request)
    ] == []

    sweep_jobs.progress.answer("sweep-1-point-2", _failure("sweep-1-point-2", "Point 2 failed"))
    sweep_jobs.results.answer("sweep-1-point-1", _results(111.1, 0.25, 11.1))
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))

    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["1", "111.1", "25.0%", "11.1", "completed"]
    )
    expect(rows.nth(1).get_by_role("cell")).to_have_text(
        ["11", "-", "-", "-", "failed"]
    )
    expect(_sweep_charts(page).get_by_text("The sweep's charts", exact=True)).to_be_visible()
    assert [
        request.post_data_json for request in requests_made if _is_the_sweep_charts_request(request)
    ] == [
        {
            "parameter_label": "PV Capacity (kW)",
            "points": [{"value": 1, "run_id": "run-of-sweep-1-point-1"}],
        }
    ]
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


# -- Other requests still load while a large sweep runs --------------------


def test_another_tab_loads_run_history_while_an_eight_point_sweep_runs(
    page: Page,
    context: BrowserContext,
    live_server: str,
    release_held_simulations: Callable[[], None],
    page_errors: list[str],
) -> None:
    """Run an 8-point sweep whose jobs the live server holds running: another tab still loads Run History, and once the jobs are released each point's row shows its results.

    Over HTTP/1.1 Chromium keeps at most 6 connections per host, shared by all its tabs, and a progress stream holds one for as long as its job is queued or running.

    So the page follows its points one at a time, in the order the server queues their jobs. The cost: a row shows 'pending' until the page follows its point, even if that point's job is running or done by then, and the rows after a point wait for its job to end.
    """
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_label("Min Value", exact=True).fill("1")
    page.get_by_label("Max Value", exact=True).fill("8")
    page.get_by_label("Steps", exact=True).fill("8")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()
    rows = _result_rows(page)
    expect(_status_badge(rows.first)).to_have_text("running")

    run_history = context.new_page()
    run_history.goto(live_server + "/history/runs")
    expect(
        run_history.get_by_role("heading", name="Run History", exact=True)
    ).to_be_visible()

    release_held_simulations()
    for n in range(1, 9):
        expect(rows.nth(n - 1).get_by_role("cell")).to_have_text(
            [str(n), "72.0", "33.3%", "12.0", "completed"]
        )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


# -- A real sweep's charts, drawn from its points' runs ---------------------


def test_a_three_point_sweep_draws_one_chart_per_metric_from_its_points_runs(
    page: Page,
    live_server: str,
    release_held_simulations: Callable[[], None],
    page_errors: list[str],
) -> None:
    """The jobs are released before Run, so each point's job ends at once, saving its run through the live server's RunStorage (B12, task 135)."""
    release_held_simulations()
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_label("Steps", exact=True).fill("3")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    rows = _result_rows(page)
    for n in range(3):
        expect(_status_badge(rows.nth(n))).to_have_text("completed")
    charts = _sweep_charts(page)
    expect(charts.locator(".js-plotly-plot")).to_have_count(3)
    expect(charts.get_by_role("heading")).to_have_text(
        [
            "Generation (kWh) vs PV Capacity (kW)",
            "Self-Consumption (%) vs PV Capacity (kW)",
            "Grid Import (kWh) vs PV Capacity (kW)",
        ]
    )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"
