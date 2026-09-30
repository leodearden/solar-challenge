"""End-to-end tests for interactive form behaviors on /simulate/home.

Verifies preset population, location changes, period buttons,
and conditional field visibility.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._home_form import choose_custom_range, open_period_tab

pytestmark = pytest.mark.e2e


def _form_data(page: Page) -> dict[str, object]:
    """The home form's Alpine formData, as the page holds it now."""
    return page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        return { ...Alpine.$data(el).formData };
    }""")


def _open_location_tab(page: Page) -> None:
    """Open the form's Location tab, where the simulated site is chosen."""
    page.get_by_role("tab", name="Location", exact=True).click()


def _choose_location(page: Page, location: str) -> None:
    """Open the Location tab and select the #location option whose value is `location`."""
    _open_location_tab(page)
    page.locator("#location").select_option(value=location)


# -- Preset populates form values -------------------------------------------


def test_preset_populates_form_values(page: Page, live_server: str) -> None:
    """Select 'Large with Battery' preset -> PV=6, battery=10, consumption=4500."""
    page.goto(live_server + "/simulate/home")

    # Select the "Large with Battery" preset
    preset_select = page.locator("#preset_select")
    expect(preset_select).to_be_visible()
    preset_select.select_option(label="Large with Battery")

    form_data = _form_data(page)

    assert form_data["pv_kw"] == 6, f"Expected pv_kw=6, got {form_data['pv_kw']}"
    assert form_data["battery_kwh"] == 10, f"Expected battery_kwh=10, got {form_data['battery_kwh']}"
    assert form_data["consumption_kwh"] == 4500, f"Expected consumption_kwh=4500, got {form_data['consumption_kwh']}"


# -- Location preset updates formData ---------------------------------------


def test_location_preset_updates_formdata(page: Page, live_server: str) -> None:
    """Select Edinburgh on Location tab -> formData.location === 'edinburgh'."""
    page.goto(live_server + "/simulate/home")
    _choose_location(page, "edinburgh")

    location = _form_data(page)["location"]
    assert location == "edinburgh", f"Expected location='edinburgh', got '{location}'"


# -- Period day buttons -----------------------------------------------------


def test_period_day_buttons(page: Page, live_server: str) -> None:
    """Click '7 days' then '1 year' -> formData.period_days updates."""
    page.goto(live_server + "/simulate/home")
    open_period_tab(page)

    for label, days in (("7 days", 7), ("1 year", 365)):
        page.get_by_role("button", name=label, exact=True).click()
        period_days = _form_data(page)["period_days"]
        assert period_days == days, (
            f"Expected period_days={days} after clicking {label!r}, got {period_days}"
        )


# -- Custom location fields appear ------------------------------------------


def test_custom_location_fields_appear(page: Page, live_server: str) -> None:
    """Select the 'custom' location -> #custom_lat and #custom_lon, hidden until then, become visible."""
    page.goto(live_server + "/simulate/home")
    _open_location_tab(page)
    coordinate_inputs = [page.locator("#custom_lat"), page.locator("#custom_lon")]
    for coordinate_input in coordinate_inputs:
        expect(coordinate_input).to_be_hidden()

    _choose_location(page, "custom")

    for coordinate_input in coordinate_inputs:
        expect(coordinate_input).to_be_visible()


# -- Custom date range fields -----------------------------------------------


def test_custom_date_range_fields(page: Page, live_server: str) -> None:
    """Check the 'Custom range' radio -> #start_date and #end_date, hidden until then, become visible."""
    page.goto(live_server + "/simulate/home")
    open_period_tab(page)
    date_inputs = [page.locator("#start_date"), page.locator("#end_date")]
    for date_input in date_inputs:
        expect(date_input).to_be_hidden()

    choose_custom_range(page)

    for date_input in date_inputs:
        expect(date_input).to_be_visible()
