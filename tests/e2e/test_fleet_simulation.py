"""End-to-end tests for the Fleet Simulation page (/simulate/fleet).

Verifies page loading, n_homes controls, distribution cards, that the
fleet-wide Dispatch Strategy select is named by its label, and detects
Bug B1 (Alpine race condition) and Bug B2 (wrong results URL).
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Page loading ─────────────────────────────────────────────────────


def test_fleet_page_loads(page: Page, live_server: str) -> None:
    """GET /simulate/fleet returns a page with 'Fleet Simulation' heading."""
    response = page.goto(live_server + "/simulate/fleet")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Fleet Simulation").first
    expect(heading).to_be_visible()


# ── Bug B1: Alpine race condition with external JS ───────────────────


def test_fleet_page_no_js_errors(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """The fleet page should load without JavaScript errors.

    The ``fleetSimulator()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Depending on script
    execution order, Alpine.js may try to evaluate the ``x-data``
    attribute before the component function is registered, which throws
    an uncaught ReferenceError.
    """
    page.goto(live_server + "/simulate/fleet")
    # Give deferred scripts time to load and Alpine to initialise
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    assert page_errors == [], f"Errors on /simulate/fleet: {page_errors}"


# ── Fleet size controls ──────────────────────────────────────────────


def test_fleet_n_homes_slider(page: Page, live_server: str) -> None:
    """The n_homes range slider and number input both exist on the page."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")

    # Range slider
    range_input = page.locator("#n_homes_range")
    expect(range_input).to_be_visible()
    assert range_input.get_attribute("type") == "range"

    # Number input
    number_input = page.locator("#n_homes")
    expect(number_input).to_be_visible()
    assert number_input.get_attribute("type") == "number"


# ── Distribution cards ───────────────────────────────────────────────


def test_fleet_distribution_cards(page: Page, live_server: str) -> None:
    """PV Capacity, Battery Capacity, and Annual Consumption cards are present."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")

    # PV distribution card (amber accent)
    pv_card = page.locator("h3", has_text="PV Capacity")
    expect(pv_card).to_be_visible()

    # Battery distribution card (teal accent)
    battery_card = page.locator("h3", has_text="Battery Capacity")
    expect(battery_card).to_be_visible()

    # Load distribution card (red accent)
    load_card = page.locator("h3", has_text="Annual Consumption")
    expect(load_card).to_be_visible()


# ── Fleet-wide dispatch strategy ─────────────────────────────────────


def test_fleet_dispatch_strategy_select_is_named_by_its_label(
    page: Page, live_server: str
) -> None:
    """The Dispatch Strategy select is found by the name its "Dispatch Strategy" label gives it.

    It shows only while the battery is enabled, which it is by default.
    """
    page.goto(live_server + "/simulate/fleet")

    dispatch_select = page.get_by_role("combobox", name="Dispatch Strategy", exact=True)
    expect(dispatch_select).to_be_visible()


# ── Bug B2: fleet results URL points to wrong path ───────────────────


def test_fleet_completed_results_url(page: Page, live_server: str) -> None:
    """The 'View Results' link template should point to /results/fleet/<id>,
    not /results?run_id=<id>.

    We inspect the page source for the buggy URL pattern rather than
    running a full simulation.
    """
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")

    content = page.content()

    # The buggy pattern: '/results?run_id=' + completedRunId
    assert "'/results?run_id='" not in content, (
        "Bug B2: fleet 'View Results' link uses wrong URL pattern "
        "('/results?run_id=<id>' instead of '/results/fleet/<id>')"
    )
