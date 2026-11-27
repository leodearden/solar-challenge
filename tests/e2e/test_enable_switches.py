"""End-to-end tests for the dashboard's enable/disable switches.

Each switch shows, then hides, the settings it enables, among them the select
that picks their variant; so does the fleet page's battery control, a checkbox
that starts checked. The switch and that select are each found by role and by
the accessible name its label gives it. Clicking a switch's label flips it
just as clicking the switch does. Each simulate page's Enable Tariff shows its
flat rate at the flat rate every form starts at.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

from solar_challenge.web.fleet_components import page_limits
from tests.e2e._home_form import open_tab


def _assert_switch_shows_and_hides(
    switch: Locator, settings: Locator, *, flipped_by: Locator | None = None
) -> None:
    flipper = switch if flipped_by is None else flipped_by

    expect(switch).to_be_visible()
    expect(switch).not_to_be_checked()
    expect(settings).to_be_hidden()

    flipper.click()
    expect(switch).to_be_checked()
    expect(settings).to_be_visible()

    flipper.click()
    expect(switch).not_to_be_checked()
    expect(settings).to_be_hidden()


@pytest.mark.parametrize(
    ("tab", "switch_name", "variant_select_name"),
    [
        pytest.param("Battery", "Enable Battery", "Dispatch Strategy", id="battery"),
        pytest.param("Heat Pump", "Enable Heat Pump", "Heat Pump Type", id="heat_pump"),
        pytest.param("Tariff", "Enable Tariff", "Tariff Type", id="tariff"),
        pytest.param("Tariff", "Enable SEG Export Pricing", "Supplier Preset", id="seg"),
    ],
)
def test_home_switch_shows_and_hides_its_settings(
    page: Page, live_server: str, tab: str, switch_name: str, variant_select_name: str
) -> None:
    page.goto(live_server + "/simulate/home")
    open_tab(page, tab)

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name=switch_name, exact=True),
        page.get_by_role("combobox", name=variant_select_name, exact=True),
    )


@pytest.mark.parametrize(
    ("switch_name", "variant_select_name"),
    [
        pytest.param("Enable Tariff", "Tariff Type", id="tariff"),
        pytest.param("Enable SEG Export Pricing", "Supplier Preset", id="seg"),
    ],
)
def test_fleet_switch_shows_and_hides_its_settings(
    page: Page, live_server: str, switch_name: str, variant_select_name: str
) -> None:
    page.goto(live_server + "/simulate/fleet")

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name=switch_name, exact=True),
        page.get_by_role("combobox", name=variant_select_name, exact=True),
    )


def test_fleet_battery_checkbox_shows_and_hides_its_distribution_editor(
    page: Page, live_server: str
) -> None:
    page.goto(live_server + "/simulate/fleet")
    battery = page.get_by_role("checkbox", name="Enable Battery", exact=True)
    expect(battery).to_be_checked()
    battery.click()

    _assert_switch_shows_and_hides(
        battery,
        page.get_by_role("combobox", name="Battery Capacity Distribution Type", exact=True),
    )


def test_clicking_a_switch_label_flips_the_switch(page: Page, live_server: str) -> None:
    page.goto(live_server + "/simulate/home")
    open_tab(page, "Battery")

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name="Enable Battery", exact=True),
        page.locator("#battery_kwh"),
        flipped_by=page.get_by_text("Enable Battery", exact=True),
    )


@pytest.mark.parametrize("simulate_page", ["home", "fleet"])
def test_each_simulate_pages_flat_rate_starts_at_the_flat_rate_start(
    page: Page, live_server: str, simulate_page: str
) -> None:
    """Enable Tariff shows the flat rate at page_limits().flat_rate_start, on the home page's Tariff tab and on the fleet page."""
    page.goto(live_server + f"/simulate/{simulate_page}")
    if simulate_page == "home":
        open_tab(page, "Tariff")

    page.get_by_role("switch", name="Enable Tariff", exact=True).click()

    expect(page.get_by_role("spinbutton", name="Rate (£/kWh)", exact=True)).to_have_value(
        str(page_limits().flat_rate_start)
    )
