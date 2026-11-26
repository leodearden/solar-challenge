"""The page_errors fixture holds the error each 'no JS errors' test exists to catch."""

import pytest
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


LATER_REJECTION = "a later rejection"


@pytest.mark.parametrize(
    ("js_reason", "expected_texts"),
    [
        pytest.param("new Error('boom')", ["boom"], id="error"),
        pytest.param("({ isFromCancelledTransition: false })", ["Object"], id="near_miss_sentinel"),
        pytest.param("({ isFromCancelledTransition: 1 })", ["Object"], id="truthy_sentinel"),
        pytest.param("({ isFromCancelledTransition: true })", [], id="alpines_sentinel"),
    ],
)
def test_page_errors_holds_a_rejection_the_page_leaves_unhandled_whatever_its_reason_but_alpines_cancelled_transition(
    page: Page, live_server: str, page_errors: list[str], js_reason: str, expected_texts: list[str]
) -> None:
    """A promise the page rejects and never handles reaches page_errors, unless its reason is Alpine's cancelled-transition sentinel itself.

    The browser reports unhandled rejections in the order they happen, so once a later one has reached page_errors, the row's own has too, or never will.
    """
    open_once_alpine_has_started(page, live_server + "/simulate/fleet")

    with page.expect_event("pageerror", predicate=lambda error: str(error) == LATER_REJECTION):
        page.evaluate(
            f"() => {{ Promise.reject({js_reason}); Promise.reject(new Error('{LATER_REJECTION}')); }}"
        )

    assert page_errors == [*expected_texts, LATER_REJECTION]
