# SPDX-License-Identifier: AGPL-3.0-or-later
"""open_once_alpine_has_started (tests/e2e/_alpine_start.py) returns once every error Alpine's start threw has reached the page, whatever the network is doing."""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._alpine_start import open_once_alpine_has_started


def test_every_error_alpine_throws_as_it_starts_is_in_page_errors_once_the_page_opens(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """Bug B1, with parameter-sweep.js served empty as the race leaves it."""
    page.route(
        "**/static/js/parameter-sweep.js",
        lambda route: route.fulfill(body="", content_type="text/javascript"),
    )

    open_once_alpine_has_started(page, live_server + "/scenarios/sweep")

    assert "parameterSweep is not defined" in page_errors, f"page_errors once the page opened: {page_errors}"


@pytest.mark.usefixtures("runs_api_never_answers")
def test_a_page_opens_while_a_request_it_made_as_alpine_started_is_unanswered(page: Page, live_server: str) -> None:
    """Run History's x-init starts its runs-list request; the fixture holds it unanswered."""
    open_once_alpine_has_started(page, live_server + "/history/runs")

    expect(page.get_by_text("Loading runs...")).to_be_visible()
