# SPDX-License-Identifier: AGPL-3.0-or-later
"""open_once_alpine_has_started (tests/e2e/_alpine_start.py) returns once every error Alpine's start threw has reached the page, whatever the network is doing; on a page where Alpine never starts it fails, naming the page and whether window.Alpine is defined."""

from collections.abc import Callable

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


_ALPINE_SCRIPT = "**/static/vendor/alpinejs/alpinejs-*.min.js"

_ALPINE_START_DOES_NOTHING = """Object.defineProperty(window, 'Alpine', {
    configurable: true,
    set(alpine) {
        alpine.start = () => {};
        Object.defineProperty(window, 'Alpine', {value: alpine});
    },
});"""


def _alpine_never_loads(page: Page) -> None:
    """Abort the page's request for Alpine's script."""
    page.route(_ALPINE_SCRIPT, lambda route: route.abort())


def _alpine_loads_but_never_starts(page: Page) -> None:
    """Let Alpine's own script run, as base.html's integrity attribute refuses any other body, but make its start() do nothing."""
    page.add_init_script(_ALPINE_START_DOES_NOTHING)


@pytest.mark.parametrize(
    ("keep_alpine_from_starting", "alpine_is_defined"),
    [
        pytest.param(_alpine_never_loads, False, id="alpine_never_loads"),
        pytest.param(_alpine_loads_but_never_starts, True, id="alpine_loads_but_never_starts"),
    ],
)
def test_opening_a_page_where_alpine_never_starts_fails_naming_the_page_and_whether_window_alpine_is_defined(
    page: Page, live_server: str, keep_alpine_from_starting: Callable[[Page], None], alpine_is_defined: bool
) -> None:
    """Where Alpine's script never loads, or loads but never starts, open_once_alpine_has_started fails naming the url, the event it waited for and whether window.Alpine is defined.

    Only the helper's wait for Alpine's start runs on the shortened default timeout: the navigation keeps Playwright's 30 s, so a page slowed by a loaded host cannot fail the test.
    """
    keep_alpine_from_starting(page)
    page.set_default_navigation_timeout(30_000)
    page.set_default_timeout(1000)
    url = live_server + "/scenarios/sweep"

    with pytest.raises(AssertionError) as failure:
        open_once_alpine_has_started(page, url)

    message = str(failure.value)
    assert url in message
    assert "alpine:initialized" in message
    assert f"window.Alpine defined: {alpine_is_defined}" in message
