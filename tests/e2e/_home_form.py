# SPDX-License-Identifier: AGPL-3.0-or-later
"""Submit the single-home simulation form at /simulate/home through its UI, as a user would."""

from playwright.sync_api import Page, Response

_FIRST_DAY = "2024-06-01"
_LAST_DAY = "2024-06-02"


def submit_two_day_run(page: Page) -> Response:
    """Choose a two-day custom range on the Period tab, click Run Simulation and return the server's answer.

    Two days is the shortest run the form offers: its quick presets start at 7 days, and a
    custom range needs an end date after its start date.
    """
    page.get_by_role("tab", name="Period", exact=True).click()
    page.get_by_role("radio", name="Custom range", exact=True).check()
    page.locator("#start_date").fill(_FIRST_DAY)
    page.locator("#end_date").fill(_LAST_DAY)
    with page.expect_response("**/api/simulate/home") as submission:
        page.get_by_role("button", name="Run Simulation").click()
    response = submission.value
    sent = response.request.post_data_json
    sent_period = {key: sent.get(key) for key in ("days", "start", "end")}
    chosen_period = {"days": None, "start": _FIRST_DAY, "end": _LAST_DAY}
    assert sent_period == chosen_period, (
        f"The form sent the period {sent_period}, not the two-day range {chosen_period} "
        "chosen on the Period tab, so the job it started is not a two-day run."
    )
    return response
