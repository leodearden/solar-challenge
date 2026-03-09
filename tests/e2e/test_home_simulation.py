"""End-to-end tests for the Single Home Simulation page (/simulate/home).

Verifies form defaults, tab navigation, battery toggle, preset selector,
submit button, and detects Bug B4 (buildPayload missing form fields).
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# ── Form defaults ─────────────────────────────────────────────────────


def test_form_loads_with_defaults(page: Page, live_server: str) -> None:
    """PV capacity defaults to 4 (or 4.0) and consumption to 3500."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    # PV input is on the default PV tab, so it is visible
    pv_input = page.locator("#pv_kw")
    expect(pv_input).to_be_visible()
    pv_value = pv_input.input_value()
    assert pv_value in ("4", "4.0"), f"Expected PV default '4' or '4.0', got '{pv_value}'"

    # Consumption input is on the Load tab -- navigate there first
    load_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Load",
    )
    load_tab.click()
    page.wait_for_timeout(300)

    consumption_input = page.locator("#consumption_kwh")
    expect(consumption_input).to_be_visible()
    consumption_value = consumption_input.input_value()
    assert consumption_value == "3500", (
        f"Expected consumption default '3500', got '{consumption_value}'"
    )


# ── Preset selector ──────────────────────────────────────────────────


def test_preset_selector_loads(page: Page, live_server: str) -> None:
    """The preset <select> dropdown exists and has at least the default option."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    preset_select = page.locator("#preset_select")
    expect(preset_select).to_be_visible()

    # The default "-- No preset --" option should always be present
    options = preset_select.locator("option")
    assert options.count() >= 1, "Preset selector should have at least the default option"


# ── Bug B4: buildPayload missing form fields ─────────────────────────


def test_all_form_fields_in_payload(page: Page, live_server: str) -> None:
    """buildPayload() should include azimuth, tilt, battery charge/discharge
    rates, efficiency, and stochastic flag.  Currently these are omitted.
    """
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine.js to fully initialise the component
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    payload = page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        const data = Alpine.$data(el);
        return data.buildPayload();
    }""")

    missing_keys = []
    for key in ("azimuth", "tilt", "max_charge_kw", "max_discharge_kw",
                "efficiency_pct", "stochastic"):
        if key not in payload:
            missing_keys.append(key)

    assert not missing_keys, (
        f"buildPayload() is missing keys: {missing_keys}.  "
        f"Payload keys returned: {sorted(payload.keys())}"
    )


# ── Tab navigation ───────────────────────────────────────────────────


def test_tab_navigation(page: Page, live_server: str) -> None:
    """Clicking each tab (PV, Battery, Load, Location, Period) activates it."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    tab_labels = ["PV", "Battery", "Load", "Location", "Period"]

    for label in tab_labels:
        tab_btn = page.locator(
            'nav[aria-label="Configuration tabs"] button',
            has_text=label,
        )
        tab_btn.click()
        page.wait_for_timeout(200)

        # The active tab should have aria-selected="true"
        selected = tab_btn.get_attribute("aria-selected")
        assert selected == "true", (
            f"Tab '{label}' should be selected (aria-selected='true'), "
            f"got '{selected}'"
        )


# ── Battery tab enable/disable ───────────────────────────────────────


def test_battery_tab_enable_disable(page: Page, live_server: str) -> None:
    """Toggling the battery switch shows/hides the battery configuration fields."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    # Navigate to the Battery tab
    battery_tab = page.locator(
        'nav[aria-label="Configuration tabs"] button',
        has_text="Battery",
    )
    battery_tab.click()
    page.wait_for_timeout(300)

    # The battery toggle switch (role="switch")
    toggle = page.locator('button[role="switch"]')
    expect(toggle).to_be_visible()

    # Battery is disabled by default (formData.battery_enabled = false)
    battery_fields = page.locator("#battery_kwh")

    # Verify fields are hidden initially
    expect(battery_fields).not_to_be_visible()

    # Enable battery
    toggle.click()
    page.wait_for_timeout(400)

    # Battery capacity slider should now be visible
    expect(battery_fields).to_be_visible()

    # Disable battery again
    toggle.click()
    page.wait_for_timeout(400)

    # Fields should be hidden again
    expect(battery_fields).not_to_be_visible()


# ── Submit button ────────────────────────────────────────────────────


def test_submit_button_exists(page: Page, live_server: str) -> None:
    """The 'Run Simulation' submit button exists and is not disabled by default."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    submit_btn = page.locator("button[type='submit']")
    expect(submit_btn).to_be_visible()
    expect(submit_btn).to_be_enabled()

    # Verify button text
    btn_text = submit_btn.text_content() or ""
    assert "Run Simulation" in btn_text, (
        f"Expected button text to contain 'Run Simulation', got '{btn_text}'"
    )


# ── Form validation (PV range) ──────────────────────────────────────


def test_form_validation_pv_range(page: Page, live_server: str) -> None:
    """The PV capacity input enforces min/max constraints via HTML attributes."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    pv_input = page.locator("#pv_kw")
    expect(pv_input).to_be_visible()

    # Check that the range input has min/max constraints
    min_val = pv_input.get_attribute("min")
    max_val = pv_input.get_attribute("max")

    assert min_val is not None, "PV input should have a 'min' attribute"
    assert max_val is not None, "PV input should have a 'max' attribute"
    assert float(min_val) >= 0.5, f"PV min should be >= 0.5, got {min_val}"
    assert float(max_val) <= 20, f"PV max should be <= 20, got {max_val}"
