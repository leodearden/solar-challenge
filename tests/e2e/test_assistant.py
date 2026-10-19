"""End-to-end tests for the AI assistant page's chat.

Verifies that a chat answer that failed shows its message as the page's notice.
"""

import pytest
from playwright.sync_api import Page, Route, expect

from solar_challenge.web.sse import CHAT_FAILED, ChatFailed, sse_frame

pytestmark = pytest.mark.e2e


def test_a_chat_answer_that_failed_shows_its_message_as_the_page_s_notice(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """The fake answer is built by sse_frame from the server's chat catalogue, so a page
    that listens for an event name the server never sends fails here."""
    notice = "Streaming error: overloaded_error: Overloaded"

    def answer_failed(route: Route) -> None:
        route.fulfill(
            status=200,
            content_type="text/event-stream",
            body=sse_frame(CHAT_FAILED, ChatFailed(notice)),
        )

    page.route("**/assistant/chat", answer_failed)
    page.goto(live_server + "/assistant")
    page.get_by_placeholder("Ask a question about your solar system…").fill("hi")
    page.get_by_role("button", name="Send", exact=True).click()

    expect(page.locator("#chat-messages").get_by_text(f"⚠ {notice}", exact=True)).to_be_visible()
    assert page_errors == [], f"Errors on /assistant: {page_errors}"
