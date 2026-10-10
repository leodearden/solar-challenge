"""End-to-end tests for the Parameter Sweep page (/scenarios/sweep).

Verifies page loading, that each form control is found by role and by the name
its label gives it, that the radio group named "Sweep Mode" holds the Linear
and Geometric radios and the group named "Base Configuration" holds the
Battery (kWh), Location and Days controls, preview calculations (the preview
lists its values in the list named "Sweep values"), that submitting a sweep
filled into the form returns one background job per sweep point, and detects
Bug B1 (Alpine race condition with external JS).

Also verifies that each sweep point's row shows how its own job ended, that
running a sweep drops the requests the sweep before it still has in flight,
and that an earlier sweep's results, arriving after a later sweep's rows show,
fill none of them.
"""

import itertools
import json
from collections.abc import Iterator
from dataclasses import dataclass

import pytest
from playwright.sync_api import Locator, Page, Route, expect

from tests.e2e._job_requests import HeldJobRequests, is_job_request, sse_event

pytestmark = pytest.mark.e2e


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
    button returns 201 with a sweep id, the geometric sweep values and one
    distinct background home-job id per sweep point.

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
    assert data["sweep_id"]
    assert data["values"] == [1.0, 3.0, 9.0]

    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3
    assert all(job_ids)


# -- Each point's row follows its own sweep's job --------------------------


@dataclass(frozen=True)
class _SweepJobs:
    """The jobs of the sweeps the page submits: each job's progress stream, and once it completes its results, held until the test answers them."""

    progress: HeldJobRequests
    results: HeldJobRequests


@pytest.fixture
def sweep_jobs(page: Page) -> Iterator[_SweepJobs]:
    """Accept the page's Nth sweep as sweep-N, whose two points, N and N + 10, run as the jobs sweep-N-point-1 and sweep-N-point-2, so no point reaches the live server's JobManager; abort the requests still held at teardown."""
    sweep_numbers = itertools.count(1)

    def _accept(route: Route) -> None:
        n = next(sweep_numbers)
        route.fulfill(
            status=201,
            json={
                "sweep_id": f"sweep-{n}",
                "parameter": "pv_capacity_kw",
                "values": [float(n), float(n + 10)],
                "job_ids": [f"sweep-{n}-point-1", f"sweep-{n}-point-2"],
            },
        )

    jobs = _SweepJobs(
        HeldJobRequests("text/event-stream"), HeldJobRequests("application/json")
    )
    page.route("**/api/simulate/sweep", _accept)
    page.route("**/api/jobs/*/progress", jobs.progress.handle)
    page.route("**/api/jobs/*/results", jobs.results.handle)
    yield jobs
    jobs.progress.abort_held()
    jobs.results.abort_held()


def _completion(job_id: str) -> str:
    """The progress event that completes job_id with the run run-of-<job_id>."""
    return sse_event("complete", {"status": "completed", "run_id": f"run-of-{job_id}"})


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
    sweep_jobs.progress.answer(
        "sweep-1-point-1",
        sse_event("error", {"status": "failed", "message": "Point 1 failed"}),
    )
    page.goto(live_server + "/scenarios/sweep")
    page.get_by_role("button", name="Run Parameter Sweep", exact=True).click()

    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(["1", "-", "-", "-", "failed"])
    expect(rows.nth(1).get_by_role("cell")).to_have_text(
        ["11", "-", "-", "-", "pending"]
    )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_an_earlier_sweeps_late_results_fill_no_row_of_the_sweep_run_after_it(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run, then Run again while sweep-1's completed first point's results still load: those results, answered once sweep-2's rows show, fill no row of sweep-2's, while sweep-2's completed second point shows its own."""
    sweep_jobs.progress.answer("sweep-1-point-1", _completion("sweep-1-point-1"))
    page.goto(live_server + "/scenarios/sweep")
    run = page.get_by_role("button", name="Run Parameter Sweep", exact=True)
    with page.expect_request("**/api/jobs/sweep-1-point-1/results"):
        run.click()
    with page.expect_request("**/api/jobs/sweep-2-point-2/progress"):
        run.click()
    rows = _result_rows(page)
    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["2", "-", "-", "-", "pending"]
    )

    sweep_jobs.results.answer("sweep-1-point-1", _results(111.1, 0.25, 11.1))
    with page.expect_request("**/api/jobs/sweep-2-point-2/results"):
        sweep_jobs.progress.answer("sweep-2-point-2", _completion("sweep-2-point-2"))
    sweep_jobs.results.answer("sweep-2-point-2", _results(222.2, 0.5, 22.2))

    expect(rows.nth(1).get_by_role("cell")).to_have_text(
        ["12", "222.2", "50.0%", "22.2", "completed"]
    )
    expect(rows.nth(0).get_by_role("cell")).to_have_text(
        ["2", "-", "-", "-", "pending"]
    )
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"


def test_a_sweep_run_after_another_drops_the_earlier_sweeps_requests(
    page: Page, live_server: str, sweep_jobs: _SweepJobs, page_errors: list[str]
) -> None:
    """Run, then Run again while sweep-1's completed first point's results still load and its second point still runs: the page drops both requests, the first point's results request and the second point's progress stream, and goes on to follow sweep-2's jobs."""
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
        page.expect_request("**/api/jobs/sweep-2-point-2/progress"),
    ):
        run.click()
    assert page_errors == [], f"Errors on /scenarios/sweep: {page_errors}"
