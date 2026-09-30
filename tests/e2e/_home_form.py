# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the single-home simulation form at /simulate/home through its UI, as a user would, and read back its Alpine formData."""

from playwright.sync_api import Page, Response

_FIRST_DAY = "2024-06-01"
_LAST_DAY = "2024-06-02"


def form_data(page: Page) -> dict[str, object]:
    """The home form's Alpine formData, as the page holds it now."""
    return page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        return { ...Alpine.$data(el).formData };
    }""")


def open_location_tab(page: Page) -> None:
    """Open the form's Location tab, where the simulated site is chosen."""
    page.get_by_role("tab", name="Location", exact=True).click()


def choose_location(page: Page, location: str) -> None:
    """Open the Location tab and select the #location option whose value is `location`."""
    open_location_tab(page)
    page.locator("#location").select_option(value=location)


def open_period_tab(page: Page) -> None:
    """Open the form's Period tab, where the simulated dates are chosen."""
    page.get_by_role("tab", name="Period", exact=True).click()


def choose_custom_range(page: Page) -> None:
    """Open the Period tab and check its "Custom range" radio, which reveals #start_date and #end_date."""
    open_period_tab(page)
    page.get_by_role("radio", name="Custom range", exact=True).check()


def submit_two_day_run(page: Page) -> Response:
    """Choose a two-day custom range on the Period tab, click Run Simulation and return the server's answer.

    Two days is the shortest run the form offers: its quick presets start at 7 days, and a
    custom range needs an end date after its start date.
    """
    choose_custom_range(page)
    page.locator("#start_date").fill(_FIRST_DAY)
    page.locator("#end_date").fill(_LAST_DAY)
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation").click()
    response = submission.value
    sent = response.request.post_data_json or {}
    sent_period = {key: sent.get(key) for key in ("days", "start", "end")}
    chosen_period = {"days": None, "start": _FIRST_DAY, "end": _LAST_DAY}
    assert sent_period == chosen_period, (
        f"The form sent the period {sent_period}, not the two-day range {chosen_period} "
        "chosen on the Period tab, so the job it started is not a two-day run."
    )
    return response
