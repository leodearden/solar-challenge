# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the economy rate inputs of either simulate form, as a user would, and name the tariff the form then sends.

Both forms label their Tariff Type select and rate inputs alike. Each economy type keeps its
own rate pair, starting at tariff.PRESET_RATES' pair for the type, and the rate inputs show
and edit the selected type's pair.

Usage::

    from tests.e2e._economy_rates import (
        ECONOMY_7_AT_THE_TYPED_PEAK_RATE,
        type_a_peak_rate_under_economy_7_then_visit_economy_10,
    )

    page.get_by_role("switch", name="Enable Tariff", exact=True).click()
    type_a_peak_rate_under_economy_7_then_visit_economy_10(page)
    assert sent["tariff"] == ECONOMY_7_AT_THE_TYPED_PEAK_RATE
"""

from playwright.sync_api import Page, expect

from solar_challenge.tariff import PRESET_RATES

_TYPED_PEAK_RATE = 0.4

ECONOMY_7_AT_THE_TYPED_PEAK_RATE = {
    "type": "economy_7",
    "peak_rate": _TYPED_PEAK_RATE,
    "off_peak_rate": PRESET_RATES["economy_7"].off_peak_rate,
}
"""The tariff a form sends after type_a_peak_rate_under_economy_7_then_visit_economy_10: Economy 7 at the typed peak rate and its preset off-peak rate."""


def type_a_peak_rate_under_economy_7_then_visit_economy_10(page: Page) -> None:
    """Select Economy 7, type a peak rate, select Economy 10, then Economy 7 again, expecting each type's own rates at each step.

    The form's tariff must be enabled and its Tariff Type select shown. Economy 7 first shows
    its preset pair; Economy 10 then shows its own preset peak rate, not the typed one; and
    Economy 7 shows the typed rate again.
    """
    tariff_type = page.get_by_role("combobox", name="Tariff Type", exact=True)
    peak_rate = page.get_by_role("spinbutton", name="Peak Rate (£/kWh)", exact=True)
    off_peak_rate = page.get_by_role("spinbutton", name="Off-peak Rate (£/kWh)", exact=True)

    tariff_type.select_option(label="Economy 7")
    expect(peak_rate).to_have_value(str(PRESET_RATES["economy_7"].peak_rate))
    expect(off_peak_rate).to_have_value(str(PRESET_RATES["economy_7"].off_peak_rate))
    peak_rate.fill(str(_TYPED_PEAK_RATE))
    tariff_type.select_option(label="Economy 10")
    expect(peak_rate).to_have_value(str(PRESET_RATES["economy_10"].peak_rate))
    tariff_type.select_option(label="Economy 7")
    expect(peak_rate).to_have_value(str(_TYPED_PEAK_RATE))
