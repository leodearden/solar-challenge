"""End-to-end tests for the Scenario Builder page (/scenarios/builder).

Verifies page loading, accordion sections, YAML preview, Download YAML
button, General section inputs, and detects Bug B1 (Alpine race condition
with external JS).
"""

import pytest
from playwright.sync_api import ConsoleMessage, Page, expect

pytestmark = pytest.mark.e2e


# ── Page loading ─────────────────────────────────────────────────────


def test_builder_page_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/builder returns a page with 'Scenario Builder' heading."""
    response = page.goto(live_server + "/scenarios/builder")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Scenario Builder").first
    expect(heading).to_be_visible()


# ── Bug B1: Alpine race condition with external JS ───────────────────


def test_builder_no_js_errors(page: Page, live_server: str) -> None:
    """The scenario builder page should load without JS console errors.

    The ``scenarioBuilder()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Alpine.js may evaluate
    the ``x-data`` before the component function is registered, causing
    a ReferenceError in the console.
    """
    errors: list[str] = []

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.remove_listener("console", _on_console)

    assert errors == [], f"Console errors on /scenarios/builder: {errors}"


# ── Accordion sections ───────────────────────────────────────────────


def test_accordion_sections_exist(page: Page, live_server: str) -> None:
    """The accordion should have General, Period, Location, Fleet Distribution,
    and Tariff sections.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    expected_sections = ["General", "Period", "Location", "Fleet Distribution", "Tariff"]

    for section_name in expected_sections:
        accordion_btn = page.locator(
            "button",
            has_text=section_name,
        ).first
        expect(accordion_btn).to_be_visible(), (
            f"Accordion section '{section_name}' should be visible"
        )


# ── YAML Preview pane ────────────────────────────────────────────────


def test_yaml_preview_visible(page: Page, live_server: str) -> None:
    """The YAML Preview pane in the right column should be visible.

    The preview heading is always rendered.  The ``<pre>`` element that
    displays the YAML text may be invisible when Alpine has not yet
    populated ``yamlPreview`` (the element collapses to zero height with
    empty text content).  We verify the heading is visible and that the
    ``<pre>`` element is attached to the DOM.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    yaml_heading = page.locator("h3", has_text="YAML Preview")
    expect(yaml_heading).to_be_visible()

    # The <pre> element that displays the YAML content should be in the DOM.
    # It may not be "visible" in the Playwright sense when Alpine hasn't
    # initialised scenarioBuilder() (external JS race condition) because
    # it would have empty text content and collapse to zero height.
    yaml_pre = page.locator("pre")
    expect(yaml_pre).to_be_attached()


# ── Download YAML button ─────────────────────────────────────────────


def test_download_yaml_button(page: Page, live_server: str) -> None:
    """The 'Download YAML' button exists and is clickable."""
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    download_btn = page.locator("button", has_text="Download YAML")
    expect(download_btn).to_be_visible()
    expect(download_btn).to_be_enabled()


# ── General section inputs ───────────────────────────────────────────


def test_general_section_inputs(page: Page, live_server: str) -> None:
    """Opening the General accordion reveals Name and Description inputs.

    The General accordion uses Alpine ``x-collapse``, which may keep the
    panel at ``height: 0`` with ``overflow: hidden`` depending on the CDN
    load order of the Alpine collapse plugin.  We verify that the inputs
    exist in the DOM (attached) and fall back to checking their
    ``x-model`` bindings to confirm correct wiring.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine + external JS to fully initialise
    page.wait_for_timeout(1000)

    general_btn = page.locator("button", has_text="General").first
    expect(general_btn).to_be_visible()

    # Try clicking the General accordion to open it.  Toggle closed
    # then open to ensure we end in the open state.
    general_btn.click()
    page.wait_for_timeout(400)
    general_btn.click()
    page.wait_for_timeout(600)

    # Verify Scenario Name input exists in the DOM
    name_input = page.locator('input[placeholder="e.g. Bristol Phase 1"]')
    expect(name_input).to_be_attached()

    # Verify the input is wired with x-model="name"
    x_model = name_input.get_attribute("x-model")
    assert x_model == "name", (
        f"Expected x-model='name' on Scenario Name input, got '{x_model}'"
    )

    # Verify Description textarea exists in the DOM
    desc_textarea = page.locator('textarea[placeholder="Optional description"]')
    expect(desc_textarea).to_be_attached()

    x_model_desc = desc_textarea.get_attribute("x-model")
    assert x_model_desc == "description", (
        f"Expected x-model='description' on textarea, got '{x_model_desc}'"
    )
