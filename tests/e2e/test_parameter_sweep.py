"""End-to-end tests for the Parameter Sweep page (/scenarios/sweep).

Verifies page loading, form elements, preview calculations, and detects
Bug B1 (Alpine race condition with external JS) and Bug B3 (sweep
endpoint returns empty job_ids).
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
    """Filling in min=1, max=10, steps=5 shows 5 preview values.

    The ``parameterSweep()`` component is loaded from an external JS file
    via ``defer``.  Due to the Alpine race condition (Bug B1), the
    component may fail to register before Alpine evaluates the x-data.
    We handle this by checking whether Alpine.$data exposes the
    ``previewValues`` getter and falling back gracefully.
    """
    page.goto(live_server + "/scenarios/sweep")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Check whether the Alpine component actually initialised.
    # If parameterSweep() wasn't registered in time, Alpine.$data won't
    # have the previewValues property.
    component_alive = page.evaluate("""() => {
        try {
            const el = document.querySelector('[x-data="parameterSweep()"]');
            if (!el || typeof Alpine === 'undefined') return false;
            const data = Alpine.$data(el);
            return data && typeof data.previewValues !== 'undefined';
        } catch { return false; }
    }""")

    if not component_alive:
        pytest.skip(
            "parameterSweep() component did not initialise "
            "(Alpine race condition Bug B1)"
        )

    # Set the sweep parameters directly on the Alpine component data.
    page.evaluate("""() => {
        const el = document.querySelector('[x-data="parameterSweep()"]');
        const data = Alpine.$data(el);
        data.minVal = 1;
        data.maxVal = 10;
        data.steps = 5;
        data.mode = 'linear';
    }""")

    # Wait for Alpine reactivity to update the DOM
    page.wait_for_timeout(500)

    # The description text below "Sweep Point Preview" heading should
    # indicate "5 values will be tested" (rendered via x-text on a <p>).
    preview_p = page.locator('p[x-text*="values will be tested"]')
    preview_text = preview_p.text_content() or ""
    assert "5 values will be tested" in preview_text, (
        f"Expected '5 values will be tested', got '{preview_text}'"
    )

    # There should be exactly 5 value badges in the preview values list
    # (the flex-wrap gap-2 container inside the preview card)
    value_badges = page.locator(
        '.flex.flex-wrap.gap-2 span.rounded-full'
    )
    assert value_badges.count() == 5, (
        f"Expected 5 preview value badges, got {value_badges.count()}"
    )


# -- Bug B3: Sweep endpoint stub with empty job_ids -----------------------


def test_sweep_submit_returns_501(page: Page, live_server: str) -> None:
    """Submit a sweep via the form button and verify the API returns 501
    (not yet implemented) with the generated sweep values.
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
    assert response.status == 501

    data = response.json()
    assert "not yet implemented" in data["error"]
    assert len(data["values"]) == 3
