"""End-to-end tests for the dashboard page (/)."""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def test_ctrl_clicking_a_recent_run_opens_its_results_in_a_new_tab_and_leaves_the_dashboard_open(
    page: Page, live_server: str, newest_home_run: tuple[str, str]
) -> None:
    """Ctrl/Cmd-clicking a run's name in Recent Runs opens that run's results page in a new tab, and the dashboard tab stays on the dashboard."""
    run_id, run_name = newest_home_run
    page.goto(live_server + "/")

    with page.context.expect_page() as new_tab:
        page.get_by_role("link", name=run_name, exact=True).click(modifiers=["ControlOrMeta"])

    expect(new_tab.value).to_have_url(f"{live_server}/results/home/{run_id}")
    expect(page).to_have_url(f"{live_server}/")
