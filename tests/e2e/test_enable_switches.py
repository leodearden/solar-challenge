"""End-to-end tests for the dashboard's enable/disable switches.

Each switch is found by role and by the accessible name its label gives it,
and each one shows, then hides, the settings it enables.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


def _assert_switch_shows_and_hides(switch: Locator, settings: Locator) -> None:
    expect(switch).to_be_visible()
    expect(switch).not_to_be_checked()
    expect(settings).to_be_hidden()

    switch.click()
    expect(switch).to_be_checked()
    expect(settings).to_be_visible()

    switch.click()
    expect(switch).not_to_be_checked()
    expect(settings).to_be_hidden()


@pytest.mark.parametrize(
    ("tab", "switch_name", "settings_selector"),
    [
        pytest.param("Battery", "Enable Battery", "#battery_kwh", id="battery"),
        pytest.param("Heat Pump", "Enable Heat Pump", "#heat_pump_type", id="heat_pump"),
        pytest.param("Tariff", "Enable Tariff", "#tariff_type", id="tariff"),
        pytest.param("Tariff", "Enable SEG Export Pricing", "#seg_preset", id="seg"),
    ],
)
def test_home_switch_shows_and_hides_its_settings(
    page: Page, live_server: str, tab: str, switch_name: str, settings_selector: str
) -> None:
    page.goto(live_server + "/simulate/home")
    page.get_by_role("tab", name=tab, exact=True).click()

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name=switch_name, exact=True),
        page.locator(settings_selector),
    )


@pytest.mark.parametrize(
    ("switch_name", "settings_selector"),
    [
        pytest.param("Enable Tariff", "#fleet_tariff_type", id="tariff"),
        pytest.param("Enable SEG Export Pricing", "#fleet_seg_preset", id="seg"),
    ],
)
def test_fleet_switch_shows_and_hides_its_settings(
    page: Page, live_server: str, switch_name: str, settings_selector: str
) -> None:
    page.goto(live_server + "/simulate/fleet")

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name=switch_name, exact=True),
        page.locator(settings_selector),
    )
