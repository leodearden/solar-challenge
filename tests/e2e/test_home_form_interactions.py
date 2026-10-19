"""End-to-end tests for interactive form behaviors on /simulate/home.

Verifies preset population, including a preset select that lists each
preset once and applies the built-in one when a saved home preset holds a
built-in preset's name, location changes, period buttons, and conditional
field visibility.
"""

from urllib.parse import quote

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._home_form import (
    choose_custom_range,
    choose_location,
    form_data,
    open_location_tab,
    open_period_tab,
)

pytestmark = pytest.mark.e2e


# -- Preset populates form values -------------------------------------------


def test_preset_populates_form_values(page: Page, live_server: str) -> None:
    """Select 'Large with Battery' preset -> PV=6, battery=10, consumption=4500."""
    page.goto(live_server + "/simulate/home")

    # Select the "Large with Battery" preset
    preset_select = page.locator("#preset_select")
    expect(preset_select).to_be_visible()
    preset_select.select_option(label="Large with Battery")

    form_values = form_data(page)

    assert form_values["pv_kw"] == 6, f"Expected pv_kw=6, got {form_values['pv_kw']}"
    assert form_values["battery_kwh"] == 10, f"Expected battery_kwh=10, got {form_values['battery_kwh']}"
    assert form_values["consumption_kwh"] == 4500, f"Expected consumption_kwh=4500, got {form_values['consumption_kwh']}"


def test_preset_select_lists_each_preset_once_when_a_saved_one_has_a_builtin_ones_name(
    page: Page,
    live_server: str,
    page_errors: list[str],
    home_preset_saved_under_a_builtin_name: dict[str, object],
) -> None:
    """A saved home preset named 'Small Urban' leaves the select listing every preset once, and choosing 'Small Urban' applies the built-in one."""
    page.goto(live_server + "/simulate/home")
    names = [p["name"] for p in page.request.get(live_server + "/api/presets").json()]

    expect(page.locator("#preset_select option")).to_have_text(["-- No preset --", *names])
    assert names.count("Small Urban") == 1
    page.locator("#preset_select").select_option(label="Small Urban")

    builtin = page.request.get(live_server + "/api/presets/" + quote("Small Urban")).json()
    assert builtin["source"] == "builtin"
    form_values = form_data(page)
    applied = {key: form_values[key] for key in ("pv_kw", "battery_kwh", "consumption_kwh")}
    assert applied == {key: builtin[key] for key in ("pv_kw", "battery_kwh", "consumption_kwh")}
    assert form_values["battery_enabled"] is False
    assert page_errors == []


# -- Location preset updates formData ---------------------------------------


def test_location_preset_updates_formdata(page: Page, live_server: str) -> None:
    """Select Edinburgh on Location tab -> formData.location === 'edinburgh'."""
    page.goto(live_server + "/simulate/home")
    choose_location(page, "edinburgh")

    location = form_data(page)["location"]
    assert location == "edinburgh", f"Expected location='edinburgh', got '{location}'"


# -- Period day buttons -----------------------------------------------------


def test_period_day_buttons(page: Page, live_server: str) -> None:
    """Click '7 days' then '1 year' -> formData.period_days updates."""
    page.goto(live_server + "/simulate/home")
    open_period_tab(page)

    for label, days in (("7 days", 7), ("1 year", 365)):
        page.get_by_role("button", name=label, exact=True).click()
        period_days = form_data(page)["period_days"]
        assert period_days == days, (
            f"Expected period_days={days} after clicking {label!r}, got {period_days}"
        )


# -- Custom location fields appear ------------------------------------------


def test_custom_location_fields_appear(page: Page, live_server: str) -> None:
    """Select the 'custom' location -> #custom_lat and #custom_lon, hidden until then, become visible."""
    page.goto(live_server + "/simulate/home")
    open_location_tab(page)
    coordinate_inputs = [page.locator("#custom_lat"), page.locator("#custom_lon")]
    for coordinate_input in coordinate_inputs:
        expect(coordinate_input).to_be_hidden()

    choose_location(page, "custom")

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
