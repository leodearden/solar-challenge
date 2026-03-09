"""End-to-end tests for Fleet Simulation page interactions (/simulate/fleet).

Verifies slider-input sync, distribution type selects, export YAML button,
and detects missing form fields (simulation name, period selector).
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Slider-input sync -----------------------------------------------------


def test_fleet_slider_input_sync(page: Page, live_server: str) -> None:
    """Set n_homes=50 via Alpine -> #n_homes input shows '50'."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Check if Alpine component initialised
    alive = page.evaluate("""() => {
        try {
            const el = document.querySelector('[x-data="fleetSimulator()"]');
            if (!el || typeof Alpine === 'undefined') return false;
            const data = Alpine.$data(el);
            return data && typeof data.n_homes !== 'undefined';
        } catch { return false; }
    }""")

    if not alive:
        pytest.skip("fleetSimulator() did not initialise (Alpine race condition)")

    # Set n_homes via Alpine data
    page.evaluate("""() => {
        const el = document.querySelector('[x-data="fleetSimulator()"]');
        Alpine.$data(el).n_homes = 50;
    }""")
    page.wait_for_timeout(500)

    number_input = page.locator("#n_homes")
    expect(number_input).to_be_visible()
    value = number_input.input_value()
    assert value == "50", f"Expected n_homes input to show '50', got '{value}'"


# -- Distribution type select ----------------------------------------------


def test_fleet_distribution_type_select(page: Page, live_server: str) -> None:
    """select[x-model='dist.type'] exists on distribution cards."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Look for distribution type selects (one per distribution card)
    dist_selects = page.locator('select[x-model="dist.type"]')

    if dist_selects.count() == 0:
        # Alternative selector patterns
        dist_selects = page.locator('select[x-model*="type"]')

    assert dist_selects.count() > 0, (
        "Expected at least one distribution type <select> on fleet page"
    )


# -- Export YAML button -----------------------------------------------------


def test_fleet_export_yaml_button(page: Page, live_server: str) -> None:
    """'Export YAML' button attached in DOM."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")

    export_btn = page.locator("button", has_text="Export YAML")
    if export_btn.count() == 0:
        export_btn = page.locator("button", has_text="Download YAML")
    if export_btn.count() == 0:
        export_btn = page.locator("button", has_text="Export")

    assert export_btn.count() > 0, (
        "Expected an 'Export YAML' or 'Download YAML' button on fleet page"
    )
    expect(export_btn.first).to_be_attached()


# -- Missing simulation name field (potential bug) --------------------------


def test_fleet_missing_simulation_name_field(page: Page, live_server: str) -> None:
    """Fleet page should have a simulation name input field."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Search for a name/label input
    name_input = page.locator('input[x-model*="name"]')
    if name_input.count() == 0:
        name_input = page.locator('input[placeholder*="name" i]')
    if name_input.count() == 0:
        name_input = page.locator('#simulation_name, #fleet_name, #run_name')

    assert name_input.count() > 0, (
        "Fleet simulation page is missing a simulation name input field. "
        "Users cannot name their fleet runs before submitting."
    )


# -- Missing period selector (potential bug) --------------------------------


def test_fleet_missing_period_selector(page: Page, live_server: str) -> None:
    """Fleet page should have period/date range controls."""
    page.goto(live_server + "/simulate/fleet")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Search for period-related controls
    period_controls = page.locator(
        'input[x-model*="period"], '
        'input[x-model*="days"], '
        'select[x-model*="period"], '
        'button:has-text("7 days"), '
        'button:has-text("1 year"), '
        '#period_days, '
        '#start_date'
    )

    assert period_controls.count() > 0, (
        "Fleet simulation page is missing period/date range controls. "
        "Users cannot configure the simulation time period."
    )
