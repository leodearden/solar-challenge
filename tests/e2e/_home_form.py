# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the single-home simulation form at /simulate/home through its UI, as a user would, and read back its Alpine formData."""

from playwright.sync_api import Page, Response

FIRST_DAY = "2024-06-01"
SECOND_DAY = "2024-06-02"


def form_data(page: Page) -> dict[str, object]:
    """The home form's Alpine formData, as the page holds it now."""
    snapshot: dict[str, object] = page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        return { ...Alpine.$data(el).formData };
    }""")
    return snapshot


def open_tab(page: Page, name: str) -> None:
    """Open the form's tab labelled `name`, such as "Battery"."""
    page.get_by_role("tab", name=name, exact=True).click()


def open_location_tab(page: Page) -> None:
    """Open the form's Location tab, where the simulated site is chosen."""
    open_tab(page, "Location")


def choose_location(page: Page, location: str) -> None:
    """Open the Location tab and select the #location option whose value is `location`."""
    open_location_tab(page)
    page.locator("#location").select_option(value=location)


def open_period_tab(page: Page) -> None:
    """Open the form's Period tab, where the simulated dates are chosen."""
    open_tab(page, "Period")


def choose_custom_range(page: Page) -> None:
    """Open the Period tab and check its "Custom range" radio, which reveals #start_date and #end_date."""
    open_period_tab(page)
    page.get_by_role("radio", name="Custom range", exact=True).check()


def submit_custom_range(page: Page, first_day: str, last_day: str) -> Response:
    """Choose the custom range first_day to last_day on the Period tab, click Run Simulation and return the server's answer."""
    choose_custom_range(page)
    page.locator("#start_date").fill(first_day)
    page.locator("#end_date").fill(last_day)
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation").click()
    response = submission.value
    sent = response.request.post_data_json or {}
    sent_period = {key: sent.get(key) for key in ("days", "start", "end")}
    chosen_period = {"days": None, "start": first_day, "end": last_day}
    assert sent_period == chosen_period, (
        f"The form sent the period {sent_period}, not the range {chosen_period} "
        "chosen on the Period tab, so the server's answer is not about that range."
    )
    return response


def submit_two_day_run(page: Page) -> Response:
    """Submit the two-day custom range FIRST_DAY to SECOND_DAY with submit_custom_range and return the server's answer."""
    return submit_custom_range(page, FIRST_DAY, SECOND_DAY)
