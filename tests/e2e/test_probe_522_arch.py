"""Throwaway probe for task 522's architect re-plan; delete after use."""

import pytest
from playwright.sync_api import Page, Response, expect

from tests.e2e._home_form import choose_custom_range

pytestmark = pytest.mark.e2e


def _submit_custom_range(page: Page, first_day: str, last_day: str) -> Response:
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


def test_probe_single_day(page: Page, live_server: str) -> None:
    page.goto(live_server + "/simulate/home")
    response = _submit_custom_range(page, "2024-06-01", "2024-06-01")
    assert response.status == 201, response.text()


def test_probe_reversed(page: Page, live_server: str) -> None:
    page.goto(live_server + "/simulate/home")
    response = _submit_custom_range(page, "2024-06-02", "2024-06-01")
    assert response.status == 400, response.text()
    expect(page.get_by_role("alert")).to_have_text(response.json()["error"])
