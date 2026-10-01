"""End-to-end tests for the Single Home Simulation page (/simulate/home).

Verifies form defaults, tab navigation, preset selector, submit button,
detects Bug B4 (buildPayload missing form fields), and checks that the
server accepts what the form submits with each optional setting on: the
battery and its dispatch strategies, the heat pump, the import tariff and
SEG export pricing.
"""

import re
from dataclasses import dataclass

import pytest
from playwright.sync_api import Page, expect

from solar_challenge.seg import SEG_PRESETS
from tests.e2e._home_form import open_tab, submit_two_day_run

pytestmark = pytest.mark.e2e


# ── Form defaults ─────────────────────────────────────────────────────


def test_form_loads_with_defaults(page: Page, live_server: str) -> None:
    """PV capacity defaults to 4 (or 4.0) and consumption to 3500."""
    page.goto(live_server + "/simulate/home")

    # PV input is on the default PV tab, so it is visible
    pv_input = page.locator("#pv_kw")
    expect(pv_input).to_be_visible()
    expect(pv_input).to_have_value(re.compile(r"^4(\.0)?$"))

    # Consumption input is on the Load tab -- navigate there first
    open_tab(page, "Load")

    consumption_input = page.locator("#consumption_kwh")
    expect(consumption_input).to_be_visible()
    expect(consumption_input).to_have_value("3500")


# ── Preset selector ──────────────────────────────────────────────────


def test_preset_selector_loads(page: Page, live_server: str) -> None:
    """The preset <select> dropdown exists and has at least the default option."""
    page.goto(live_server + "/simulate/home")

    preset_select = page.locator("#preset_select")
    expect(preset_select).to_be_visible()

    # The default "-- No preset --" option should always be present
    options = preset_select.locator("option")
    assert options.count() >= 1, "Preset selector should have at least the default option"


# ── Bug B4: buildPayload missing form fields ─────────────────────────


def test_all_form_fields_in_payload(page: Page, live_server: str) -> None:
    """The body the form submits, built by buildPayload(), includes azimuth,
    tilt, battery charge/discharge rates, efficiency, and stochastic flag.
    """
    page.goto(live_server + "/simulate/home")
    payload = submit_two_day_run(page).request.post_data_json

    missing_keys = []
    for key in ("azimuth", "tilt", "max_charge_kw", "max_discharge_kw",
                "efficiency_pct", "stochastic"):
        if key not in payload:
            missing_keys.append(key)

    assert not missing_keys, (
        f"The submitted payload is missing keys: {missing_keys}.  "
        f"Payload keys sent: {sorted(payload.keys())}"
    )


# ── Submissions with optional settings on are accepted by the server ────


def _switch_on(page: Page, tab: str, switch_name: str) -> None:
    open_tab(page, tab)
    switch = page.get_by_role("switch", name=switch_name, exact=True)
    switch.click()
    expect(switch).to_be_checked()


def test_battery_on_form_submission_is_accepted(page: Page, live_server: str) -> None:
    """Run with the battery switch on: /api/simulate/home accepts what the form sends (201)."""
    page.goto(live_server + "/simulate/home")
    _switch_on(page, "Battery", "Enable Battery")
    response = submit_two_day_run(page)

    assert response.request.post_data_json["battery_kwh"] > 0, (
        "The submitted payload carries no battery, so the server never built one "
        "and a 201 would say nothing about the battery path."
    )
    assert response.status == 201, response.text()


@dataclass(frozen=True)
class _OptionalBlock:
    """A block buildPayload() sends only while a switch is on, and the accessible name of the select that picks its variant."""

    tab: str
    switch_name: str
    variant_select_name: str
    payload_key: str
    variant_key: str


def _choose_variant(page: Page, block: _OptionalBlock, variant: str) -> None:
    select = page.get_by_role("combobox", name=block.variant_select_name, exact=True)
    select.select_option(value=variant)


_HEAT_PUMP = _OptionalBlock(
    "Heat Pump", "Enable Heat Pump", "Heat Pump Type", "heat_pump", "type"
)
_TARIFF = _OptionalBlock("Tariff", "Enable Tariff", "Tariff Type", "tariff", "type")
_SEG = _OptionalBlock(
    "Tariff", "Enable SEG Export Pricing", "Supplier Preset", "seg", "preset"
)
_DISPATCH_STRATEGY = _OptionalBlock(
    "Battery",
    "Enable Battery",
    "Dispatch Strategy",
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
        # Ids contain no spaces: the offline lane reads a failing node id only up to its first space.
        *(
            pytest.param(_SEG, preset, id=f"seg-{preset.replace(' ', '_')}")
            for preset in SEG_PRESETS
        ),
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
    _choose_variant(page, block, variant)
    response = submit_two_day_run(page)

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
    _choose_variant(page, _SEG, "custom")
    page.locator("#seg_rate_pence_per_kwh").fill("5.5")
    response = submit_two_day_run(page)

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

    tab_labels = ["PV", "Battery", "Load", "Location", "Period"]

    for label in tab_labels:
        open_tab(page, label)

        # The active tab should be the one tab with aria-selected="true"
        expect(page.get_by_role("tab", selected=True)).to_have_text(label)


# ── Submit button ────────────────────────────────────────────────────


def test_submit_button_exists(page: Page, live_server: str) -> None:
    """The 'Run Simulation' submit button exists and is not disabled by default."""
    page.goto(live_server + "/simulate/home")

    submit_btn = page.locator("button[type='submit']")
    expect(submit_btn).to_be_visible()
    expect(submit_btn).to_be_enabled()
    expect(submit_btn).to_contain_text("Run Simulation")


# ── Form validation (PV range) ──────────────────────────────────────


def test_form_validation_pv_range(page: Page, live_server: str) -> None:
    """The PV capacity input enforces min/max constraints via HTML attributes."""
    page.goto(live_server + "/simulate/home")

    pv_input = page.locator("#pv_kw")
    expect(pv_input).to_be_visible()

    # Check that the range input has min/max constraints
    min_val = pv_input.get_attribute("min")
    max_val = pv_input.get_attribute("max")

    assert min_val is not None, "PV input should have a 'min' attribute"
    assert max_val is not None, "PV input should have a 'max' attribute"
    assert float(min_val) >= 0.5, f"PV min should be >= 0.5, got {min_val}"
    assert float(max_val) <= 20, f"PV max should be <= 20, got {max_val}"
