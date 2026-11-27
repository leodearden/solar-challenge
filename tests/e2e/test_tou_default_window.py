# SPDX-License-Identifier: AGPL-3.0-or-later
"""End-to-end tests that each simulate form's default Time-of-Use peak window builds under every tariff type it offers.

A tou_optimized peak window that reaches a cheap minute of the home's tariff is refused as
the home is built (TOUOptimizedStrategy), so the window a form starts at must lie in the
expensive minutes of each tariff its Tariff Type select offers: Economy 10's cheap
20:00-22:00 is why the forms no longer start at 16:00-21:00. Each test leaves the window as
the form starts it, picks Time-of-Use dispatch, turns the tariff on, and sends the form at
each tariff type the select offers: /simulate/home's Run Simulation is answered 201, and
/simulate/fleet's Export YAML, which builds the homes its Run would without starting a job,
200. A further test reads the home form's tariff types while each animation frame comes late,
as on a loaded host, because Enable Tariff shows the Tariff Type select only at the next frame.
"""

from typing import Any

from playwright.sync_api import Locator, Page, expect

from tests.e2e._animation_frames import delay_animation_frames
from tests.e2e._home_form import open_tab, submit_two_day_run


def _switch_on(page: Page, switch_name: str) -> None:
    switch = page.get_by_role("switch", name=switch_name, exact=True)
    switch.click()
    expect(switch).to_be_checked()


def _choose_tou_dispatch(page: Page) -> None:
    page.get_by_role("combobox", name="Dispatch Strategy", exact=True).select_option(value="tou_optimized")


def _offered_values(select: Locator) -> list[str]:
    """The value of each option *select* offers, in page order, read once *select* is shown, as Enable Tariff shows it only at the next animation frame and a role locator does not match a hidden select; fails when it offers none, which would leave nothing to send."""
    expect(select).to_be_visible()
    values: list[str] = select.locator("option").evaluate_all("options => options.map(option => option.value)")
    assert values, "the Tariff Type select offers no option, so no tariff type is sent"
    return values


def _expect_tou_dispatch_on(sent: dict[str, Any], tariff_type: str) -> None:
    """Fail unless the form *sent* tou_optimized dispatch with a peak window, on a tariff of *tariff_type*, so its answer is about that pair."""
    dispatch = sent.get("dispatch_strategy") or {}
    tariff = sent.get("tariff") or {}
    assert (dispatch.get("strategy_type"), "peak_hours" in dispatch, tariff.get("type")) == (
        "tou_optimized",
        True,
        tariff_type,
    ), f"the form sent dispatch_strategy {dispatch} and tariff {tariff}, not its default peak window on {tariff_type!r}"


def test_the_home_forms_default_peak_window_builds_under_each_tariff_type_it_offers(
    page: Page, live_server: str
) -> None:
    page.goto(live_server + "/simulate/home")
    open_tab(page, "Battery")
    _switch_on(page, "Enable Battery")
    _choose_tou_dispatch(page)
    open_tab(page, "Tariff")
    _switch_on(page, "Enable Tariff")
    tariff_type = page.get_by_role("combobox", name="Tariff Type", exact=True)

    refused: dict[str, str] = {}
    for offered in _offered_values(tariff_type):
        open_tab(page, "Tariff")
        tariff_type.select_option(value=offered)
        response = submit_two_day_run(page)
        _expect_tou_dispatch_on(response.request.post_data_json, offered)
        if response.status != 201:
            refused[offered] = response.text()

    assert refused == {}, f"/api/simulate/home refused the form's default peak window on: {refused}"


def test_the_home_forms_offered_tariff_types_are_read_once_a_late_frame_shows_its_tariff_type_select(
    page: Page, live_server: str
) -> None:
    delay_animation_frames(page, 1000)
    page.goto(live_server + "/simulate/home")
    open_tab(page, "Tariff")
    _switch_on(page, "Enable Tariff")
    tariff_type = page.get_by_role("combobox", name="Tariff Type", exact=True)
    _offered_values(tariff_type)


def test_the_fleet_forms_default_peak_window_builds_under_each_tariff_type_it_offers(
    page: Page, live_server: str
) -> None:
    page.goto(live_server + "/simulate/fleet")
    _choose_tou_dispatch(page)
    _switch_on(page, "Enable Tariff")
    tariff_type = page.get_by_role("combobox", name="Tariff Type", exact=True)

    refused: dict[str, str] = {}
    for offered in _offered_values(tariff_type):
        tariff_type.select_option(value=offered)
        with page.expect_response("**/api/fleet/export-yaml") as answer:
            page.get_by_role("button", name="Export YAML", exact=True).click()
        _expect_tou_dispatch_on(answer.value.request.post_data_json, offered)
        if answer.value.status != 200:
            refused[offered] = answer.value.text()

    assert refused == {}, f"/api/fleet/export-yaml refused the form's default peak window on: {refused}"
