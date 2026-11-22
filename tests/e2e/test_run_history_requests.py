# SPDX-License-Identifier: AGPL-3.0-or-later
"""hold_requests (tests/e2e/_run_history_requests.py) holds each request a page makes that a predicate matches until answer_each answers it, however late Playwright hands the request over to this process."""

from urllib.parse import urlsplit

from playwright.sync_api import Page, Route

from tests.e2e._run_history_requests import hold_requests

_ANSWER = {"answered_by": "answer_each"}


def _is_presets_request(url: str) -> bool:
    """Whether url asks for the presets; the dashboard starts no fetch of its own, so the test's fetch is the only one."""
    return urlsplit(url).path == "/api/presets"


def _answer(route: Route) -> None:
    route.fulfill(json=_ANSWER)


def test_a_request_the_page_makes_once_answer_each_has_been_called_is_answered_with_it(
    page: Page, live_server: str
) -> None:
    """The page makes its request only after answer_each has been called."""
    held_requests = hold_requests(page, _is_presets_request)
    page.goto(live_server + "/")

    held_requests.answer_each(_answer)

    assert page.evaluate("() => fetch('/api/presets').then(response => response.json())") == _ANSWER


def test_a_request_the_page_made_before_answer_each_but_playwright_hands_over_only_after_it_is_answered_with_it(
    page: Page, live_server: str
) -> None:
    """The page makes its request before answer_each is called, but Playwright hands it to hold_requests only after."""
    held_requests = hold_requests(page, _is_presets_request)

    def hand_over_once_released(route: Route) -> None:
        """Make Playwright hand the request to hold_requests only once the test releases it."""
        page.wait_for_function("() => window.handOverReleased === true", polling=50)
        route.fallback()

    page.route(_is_presets_request, hand_over_once_released)
    page.goto(live_server + "/")
    page.evaluate("() => { window.presetsAnswer = fetch('/api/presets').then(response => response.json()); }")

    held_requests.answer_each(_answer)
    page.evaluate("() => { window.handOverReleased = true; }")

    assert page.evaluate("() => window.presetsAnswer") == _ANSWER
