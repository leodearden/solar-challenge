# SPDX-License-Identifier: AGPL-3.0-or-later
"""runs_api_never_answers (tests/e2e/conftest.py) passes a test whose page made a runs-list request, however late Playwright hands that request over to the fixture."""

import pytest
from playwright.sync_api import Page, Route, expect

from tests.e2e._run_history_requests import is_runs_list_request


def _keep_unanswered(route: Route) -> None:
    """Neither answer nor fall back, so no handler registered before this one is handed the request."""


@pytest.mark.usefixtures("runs_api_never_answers")
def test_a_runs_list_request_playwright_hands_over_only_after_the_test_has_ended_satisfies_the_fixture(
    page: Page, live_server: str
) -> None:
    """The test's own later route keeps the request, so the fixture is handed it only after the test ends."""
    page.route(is_runs_list_request, _keep_unanswered)

    page.goto(live_server + "/history/runs")

    expect(page.get_by_text("Loading runs...")).to_be_visible()
