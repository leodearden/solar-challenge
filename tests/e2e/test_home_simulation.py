"""End-to-end tests for the Single Home Simulation page (/simulate/home).

Verifies form defaults, tab navigation, preset selector, submit button,
detects Bug B4 (buildPayload missing form fields), and checks that the
server accepts what the form submits with the battery switch on.
"""

from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, Response, expect

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
    rates, efficiency, and stochastic flag.
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


# ── Submissions with optional settings on are accepted by the server ────


def _switch_on(page: Page, tab: str, switch_name: str) -> None:
    page.get_by_role("tab", name=tab, exact=True).click()
    switch = page.get_by_role("switch", name=switch_name, exact=True)
    switch.click()
    expect(switch).to_be_checked()


def _submit_one_day_run(page: Page) -> Response:
    """Submit the form for a one-day run and return the server's answer."""
    # No preset button is shorter than 7 days; one day keeps this submission's job short.
    page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        Alpine.$data(el).formData.period_days = 1;
    }""")
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation").click()
    return submission.value


def test_battery_on_form_submission_is_accepted(page: Page, live_server: str) -> None:
    """Run with the battery switch on: /api/simulate/home accepts what the form sends (201)."""
    page.goto(live_server + "/simulate/home")
    _switch_on(page, "Battery", "Enable Battery")
    response = _submit_one_day_run(page)

    assert response.request.post_data_json["battery_kwh"] > 0, (
        "The submitted payload carries no battery, so the server never built one "
        "and a 201 would say nothing about the battery path."
    )
    assert response.status == 201, response.text()


@dataclass(frozen=True)
class _OptionalBlock:
    """A block buildPayload() sends only while a switch is on, and the select that picks its variant."""

    tab: str
    switch_name: str
    variant_select: str
    payload_key: str
    variant_key: str


_HEAT_PUMP = _OptionalBlock(
    "Heat Pump", "Enable Heat Pump", "#heat_pump_type", "heat_pump", "type"
)
_TARIFF = _OptionalBlock("Tariff", "Enable Tariff", "#tariff_type", "tariff", "type")
_SEG = _OptionalBlock(
    "Tariff", "Enable SEG Export Pricing", "#seg_preset", "seg", "preset"
)
_DISPATCH_STRATEGY = _OptionalBlock(
    "Battery",
    "Enable Battery",
    "#dispatch_strategy_type",
    "dispatch_strategy",
    "strategy_type",
)


@pytest.mark.parametrize(
    ("block", "variant"),
    [
        pytest.param(_HEAT_PUMP, "ASHP", id="heat_pump-ASHP"),
        pytest.param(_HEAT_PUMP, "GSHP", id="heat_pump-GSHP"),
        pytest.param(_TARIFF, "flat_rate", id="tariff-flat_rate"),
        pytest.param(_TARIFF, "economy_7", id="tariff-economy_7"),
        pytest.param(_TARIFF, "economy_10", id="tariff-economy_10"),
        pytest.param(_SEG, "Octopus", id="seg-Octopus"),
        pytest.param(_DISPATCH_STRATEGY, "tou_optimized", id="dispatch-tou_optimized"),
        pytest.param(_DISPATCH_STRATEGY, "peak_shaving", id="dispatch-peak_shaving"),
    ],
)
def test_optional_block_form_submission_is_accepted(
    page: Page, live_server: str, block: _OptionalBlock, variant: str
) -> None:
    """Run with an optional block on and a variant picked: /api/simulate/home accepts what the form sends (201)."""
    page.goto(live_server + "/simulate/home")
    _switch_on(page, block.tab, block.switch_name)
    page.locator(block.variant_select).select_option(value=variant)
    response = _submit_one_day_run(page)

    sent_block = response.request.post_data_json.get(block.payload_key) or {}
    assert sent_block.get(block.variant_key) == variant, (
        f"The submitted payload's {block.payload_key!r} block does not carry "
        f"{block.variant_key}={variant!r}, so a 201 would say nothing about that variant."
    )
    assert response.status == 201, response.text()


def test_seg_custom_rate_form_submission_is_accepted(
    page: Page, live_server: str
) -> None:
    """Run with SEG export pricing on at a typed custom rate: /api/simulate/home accepts what the form sends (201)."""
    page.goto(live_server + "/simulate/home")
    _switch_on(page, _SEG.tab, _SEG.switch_name)
    page.locator(_SEG.variant_select).select_option(value="custom")
    page.locator("#seg_rate_pence_per_kwh").fill("5.5")
    response = _submit_one_day_run(page)

    sent_seg = response.request.post_data_json.get(_SEG.payload_key) or {}
    assert sent_seg.get("rate_pence_per_kwh") == 5.5, (
        "The submitted 'seg' block does not carry the typed custom rate, "
        "so a 201 would say nothing about the custom-rate path."
    )
    assert response.status == 201, response.text()


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
