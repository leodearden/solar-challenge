"""End-to-end tests for the Parameter Sweep page (/scenarios/sweep).

Verifies page loading, form elements, preview calculations, that submitting
a sweep returns one background job per sweep point, and detects Bug B1
(Alpine race condition with external JS).
"""

import pytest
from playwright.sync_api import ConsoleMessage, Page, expect

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


def test_sweep_no_js_errors(page: Page, live_server: str) -> None:
    """The sweep page should load without JavaScript console errors.

    The ``parameterSweep()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Depending on script
    execution order, Alpine.js may try to evaluate the ``x-data``
    attribute before the component function is registered, causing a
    console error.
    """
    errors: list[str] = []

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)
    page.goto(live_server + "/scenarios/sweep")
    # Give deferred scripts time to load and Alpine to initialise
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.remove_listener("console", _on_console)

    assert errors == [], f"Console errors on /scenarios/sweep: {errors}"


# -- Sweep configuration form elements ------------------------------------


def test_sweep_configuration_form(page: Page, live_server: str) -> None:
    """The sweep form has parameter dropdown, min/max/steps inputs, and
    linear/geometric radio buttons.
    """
    page.goto(live_server + "/scenarios/sweep")
    page.wait_for_load_state("networkidle")

    # Parameter dropdown (select with x-model="parameter")
    param_select = page.locator('select[x-model="parameter"]')
    expect(param_select).to_be_attached()

    # Min Value input
    min_input = page.locator('input[x-model="minVal"]')
    expect(min_input).to_be_attached()

    # Max Value input
    max_input = page.locator('input[x-model="maxVal"]')
    expect(max_input).to_be_attached()

    # Steps input
    steps_input = page.locator('input[x-model="steps"]')
    expect(steps_input).to_be_attached()

    # Linear radio button
    linear_radio = page.locator('input[type="radio"][value="linear"]')
    expect(linear_radio).to_be_attached()

    # Geometric radio button
    geometric_radio = page.locator('input[type="radio"][value="geometric"]')
    expect(geometric_radio).to_be_attached()


# -- Preview updates when inputs change ------------------------------------


def test_sweep_preview_updates(page: Page, live_server: str) -> None:
    """Filling in min=1, max=10, steps=5 previews the five linear sweep values from 1 to 10."""
    page.goto(live_server + "/scenarios/sweep")

    page.locator('input[x-model="minVal"]').fill("1")
    page.locator('input[x-model="maxVal"]').fill("10")
    page.locator('input[x-model="steps"]').fill("5")

    expect(page.get_by_text("5 values will be tested", exact=True)).to_be_visible()
    expect(page.locator(".flex.flex-wrap.gap-2 span.rounded-full")).to_have_text(
        ["1", "3.25", "5.5", "7.75", "10"]
    )


# -- Sweep submission: one background home job per sweep point ------------


def test_sweep_submit_returns_201_with_job_ids(page: Page, live_server: str) -> None:
    """Submitting a 3-point sweep via the form button returns 201 with a
    sweep id, the sweep values and one distinct background home-job id per
    sweep point.
    """
    page.goto(live_server + "/scenarios/sweep")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine.js to initialise
    page.wait_for_timeout(1000)

    # Set valid sweep parameters so the submit button is enabled.
    page.evaluate("""() => {
        const el = document.querySelector('[x-data="parameterSweep()"]');
        const data = Alpine.$data(el);
        data.minVal = 2;
        data.maxVal = 8;
        data.steps = 3;
        data.mode = 'linear';
    }""")
    page.wait_for_timeout(500)

    # Intercept the API call and click the submit button
    with page.expect_response("**/api/simulate/sweep") as response_info:
        page.get_by_role("button", name="Run Parameter Sweep").click()

    response = response_info.value
    assert response.status == 201

    data = response.json()
    assert data["sweep_id"]
    assert data["values"] == [2.0, 5.0, 8.0]

    job_ids = data["job_ids"]
    assert len(job_ids) == 3
    assert len(set(job_ids)) == 3
    assert all(job_ids)
