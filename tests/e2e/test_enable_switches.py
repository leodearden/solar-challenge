"""End-to-end tests for the dashboard's enable/disable switches.

Each switch shows, then hides, the settings it enables, among them the select
that picks their variant. The switch and that select are each found by role
and by the accessible name its label gives it. Clicking a switch's label flips
it just as clicking the switch does.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


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
    page.get_by_role("tab", name=tab, exact=True).click()

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


def test_clicking_a_switch_label_flips_the_switch(page: Page, live_server: str) -> None:
    page.goto(live_server + "/simulate/home")
    page.get_by_role("tab", name="Battery", exact=True).click()

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name="Enable Battery", exact=True),
        page.locator("#battery_kwh"),
        flipped_by=page.get_by_text("Enable Battery", exact=True),
    )
