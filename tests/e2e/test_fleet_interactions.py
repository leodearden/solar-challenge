"""End-to-end tests for Fleet Simulation page interactions (/simulate/fleet).

Verifies slider-input sync, distribution type selects, export YAML button,
that the simulation name reaches the submitted run, and detects a missing
period selector.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Slider-input sync -----------------------------------------------------


def test_fleet_slider_input_sync(page: Page, live_server: str) -> None:
    """Moving the Number of Homes slider to 50 shows 50 in the number input beside it."""
    page.goto(live_server + "/simulate/fleet")

    page.locator("#n_homes_range").fill("50")

    expect(page.get_by_label("Number of Homes", exact=True)).to_have_value("50")


# -- Distribution type select ----------------------------------------------


def test_fleet_distribution_type_select(page: Page, live_server: str) -> None:
    """The PV, battery and consumption cards each show a distribution-type select offering 'Normal (Gaussian)'."""
    page.goto(live_server + "/simulate/fleet")

    distribution_type_selects = page.get_by_role("combobox").filter(
        has=page.get_by_role("option", name="Normal (Gaussian)", exact=True)
    )
    expect(distribution_type_selects).to_have_count(3)


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


# -- Simulation name reaches the submitted run -----------------------------


def test_fleet_simulation_name_is_submitted(page: Page, live_server: str) -> None:
    """The name typed into 'Simulation Name' is the name the fleet run is submitted under."""
    # Abort the submission so no fleet job ever reaches the server's JobManager.
    page.route("**/api/simulate/fleet-from-distribution", lambda route: route.abort())
    page.goto(live_server + "/simulate/fleet")

    run_button = page.get_by_role("button", name="Run Fleet Simulation")
    expect(run_button).to_be_visible()

    page.get_by_label("Simulation Name", exact=True).fill("Bristol Fleet Trial")
    with page.expect_request("**/api/simulate/fleet-from-distribution") as submission:
        run_button.click()

    assert submission.value.post_data_json["name"] == "Bristol Fleet Trial"


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
