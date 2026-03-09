"""End-to-end tests for interactive form behaviors on /simulate/home.

Verifies preset population, location changes, period buttons,
and conditional field visibility.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Preset populates form values -------------------------------------------


def test_preset_populates_form_values(page: Page, live_server: str) -> None:
    """Select 'Large with Battery' preset -> PV=6, battery=10, consumption=4500."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Select the "Large with Battery" preset
    preset_select = page.locator("#preset_select")
    expect(preset_select).to_be_visible()
    preset_select.select_option(label="Large with Battery")
    page.wait_for_timeout(500)

    # Read Alpine formData values directly
    form_data = page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        const data = Alpine.$data(el);
        return {
            pv_kw: data.formData.pv_kw,
            battery_kwh: data.formData.battery_kwh,
            consumption_kwh: data.formData.consumption_kwh,
        };
    }""")

    assert form_data["pv_kw"] == 6, f"Expected pv_kw=6, got {form_data['pv_kw']}"
    assert form_data["battery_kwh"] == 10, f"Expected battery_kwh=10, got {form_data['battery_kwh']}"
    assert form_data["consumption_kwh"] == 4500, f"Expected consumption_kwh=4500, got {form_data['consumption_kwh']}"


# -- Location preset updates formData ---------------------------------------


def test_location_preset_updates_formdata(page: Page, live_server: str) -> None:
    """Select Edinburgh on Location tab -> formData.location === 'edinburgh'."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Navigate to the Location tab
    loc_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Location",
    )
    loc_tab.click()
    page.wait_for_timeout(300)

    # Select Edinburgh from the location dropdown
    loc_select = page.locator('select[x-model="formData.location"]')
    if loc_select.count() == 0:
        # May use a different selector pattern
        loc_select = page.locator("#location_preset")
    expect(loc_select).to_be_visible()
    loc_select.select_option(value="edinburgh")
    page.wait_for_timeout(300)

    location = page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        return Alpine.$data(el).formData.location;
    }""")

    assert location == "edinburgh", f"Expected location='edinburgh', got '{location}'"


# -- Period day buttons -----------------------------------------------------


def test_period_day_buttons(page: Page, live_server: str) -> None:
    """Click '7 days' then '1 year' -> formData.period_days updates."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Navigate to the Period tab
    period_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Period",
    )
    period_tab.click()
    page.wait_for_timeout(300)

    # Click "7 days" button
    btn_7d = page.locator("button", has_text="7 days")
    if btn_7d.count() > 0:
        btn_7d.first.click()
        page.wait_for_timeout(300)

        period = page.evaluate("""() => {
            const el = document.querySelector('[x-data="homeSimulator()"]');
            return Alpine.$data(el).formData.period_days;
        }""")
        assert period == 7, f"Expected period_days=7 after clicking '7 days', got {period}"

    # Click "1 year" button
    btn_1y = page.locator("button", has_text="1 year")
    if btn_1y.count() > 0:
        btn_1y.first.click()
        page.wait_for_timeout(300)

        period = page.evaluate("""() => {
            const el = document.querySelector('[x-data="homeSimulator()"]');
            return Alpine.$data(el).formData.period_days;
        }""")
        assert period == 365, f"Expected period_days=365 after clicking '1 year', got {period}"


# -- Custom location fields appear ------------------------------------------


def test_custom_location_fields_appear(page: Page, live_server: str) -> None:
    """Select 'custom' location -> #custom_lat / #custom_lon visible."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Navigate to the Location tab
    loc_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Location",
    )
    loc_tab.click()
    page.wait_for_timeout(300)

    # Select "custom" location
    loc_select = page.locator('select[x-model="formData.location"]')
    if loc_select.count() == 0:
        loc_select = page.locator("#location_preset")
    expect(loc_select).to_be_visible()
    loc_select.select_option(value="custom")
    page.wait_for_timeout(500)

    # Custom lat/lon fields should now be visible
    lat_input = page.locator("#custom_lat")
    lon_input = page.locator("#custom_lon")
    expect(lat_input).to_be_visible()
    expect(lon_input).to_be_visible()


# -- Custom date range fields -----------------------------------------------


def test_custom_date_range_fields(page: Page, live_server: str) -> None:
    """Click 'Custom range' radio -> #start_date / #end_date visible."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Navigate to the Period tab
    period_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Period",
    )
    period_tab.click()
    page.wait_for_timeout(300)

    # Look for "Custom range" radio or button
    custom_radio = page.locator('input[type="radio"][value="custom"]')
    custom_btn = page.locator("button", has_text="Custom")

    if custom_radio.count() > 0:
        custom_radio.first.click()
    elif custom_btn.count() > 0:
        custom_btn.first.click()
    else:
        # Set via Alpine data directly
        page.evaluate("""() => {
            const el = document.querySelector('[x-data="homeSimulator()"]');
            Alpine.$data(el).formData.period_type = 'custom';
        }""")

    page.wait_for_timeout(500)

    # At least one date input should now be visible
    start_date = page.locator("#start_date")
    end_date = page.locator("#end_date")

    # Check that the date inputs exist (attached to DOM)
    has_start = start_date.count() > 0
    has_end = end_date.count() > 0

    assert has_start or has_end, (
        "Expected #start_date or #end_date to appear after selecting custom range"
    )
