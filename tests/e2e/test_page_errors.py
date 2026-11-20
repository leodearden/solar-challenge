"""The page_errors fixture holds the error each 'no JS errors' test exists to catch."""

from playwright.sync_api import Page

from tests.e2e._alpine_start import open_once_alpine_has_started


def test_page_errors_holds_the_reference_error_bug_b1_raises(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """Bug B1: Alpine evaluates x-data="fleetSimulator()" before fleet-simulator.js has registered fleetSimulator.

    Serving that script empty leaves fleetSimulator unregistered, as the race does.
    """
    page.route(
        "**/static/js/fleet-simulator.js",
        lambda route: route.fulfill(body="", content_type="text/javascript"),
    )

    open_once_alpine_has_started(page, live_server + "/simulate/fleet")

    assert "fleetSimulator is not defined" in page_errors
