"""End-to-end tests for the dashboard's enable/disable switches.

Each switch is found by role and by the accessible name its label gives it,
and each one shows, then hides, the settings it enables. The Battery switch's
Dispatch Strategy select is found the same way, by role and by the accessible
name its label gives it. Clicking a switch's label flips it just as clicking
the switch does.
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


def test_battery_switch_shows_and_hides_the_dispatch_strategy_select(
    page: Page, live_server: str
) -> None:
    """The select the Battery switch reveals is found by role and by the name its "Dispatch Strategy" label gives it."""
    page.goto(live_server + "/simulate/home")
    page.get_by_role("tab", name="Battery", exact=True).click()

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name="Enable Battery", exact=True),
        page.get_by_role("combobox", name="Dispatch Strategy", exact=True),
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


def test_clicking_a_switch_label_flips_the_switch(page: Page, live_server: str) -> None:
    page.goto(live_server + "/simulate/home")
    page.get_by_role("tab", name="Battery", exact=True).click()

    _assert_switch_shows_and_hides(
        page.get_by_role("switch", name="Enable Battery", exact=True),
        page.locator("#battery_kwh"),
        flipped_by=page.get_by_text("Enable Battery", exact=True),
    )
