"""End-to-end tests for toast notifications.

Verifies toast success/error appearance, auto-dismiss and manual dismiss.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Toast success appears and dismisses ------------------------------------


def test_toast_success_appears_and_dismisses(page: Page, live_server: str) -> None:
    """.success(msg) shows the message, then the toast dismisses itself without a click."""
    page.goto(live_server + "/")

    page.evaluate("() => Alpine.store('toast').success('Test success message')")

    toast_message = page.get_by_text("Test success message", exact=True)
    expect(toast_message).to_be_visible()
    expect(toast_message).to_be_hidden(timeout=10_000)


# -- Toast error appears ----------------------------------------------------


def test_toast_error_appears(page: Page, live_server: str) -> None:
    """.error(msg) shows the message in a toast styled red."""
    page.goto(live_server + "/")

    page.evaluate("() => Alpine.store('toast').error('Something went wrong')")

    toast_message = page.get_by_text("Something went wrong", exact=True)
    expect(toast_message).to_be_visible()
    toast = toast_message.locator("..")
    expect(toast).to_have_class(re.compile(r"\bbg-red-"))


# -- Toast dismiss on click -------------------------------------------------


def test_toast_dismiss_on_click(page: Page, live_server: str) -> None:
    """Clicking a toast's Dismiss button hides it long before its 30 s duration ends."""
    page.goto(live_server + "/")

    page.evaluate("() => Alpine.store('toast').success('Dismiss me', 30000)")

    toast_message = page.get_by_text("Dismiss me", exact=True)
    expect(toast_message).to_be_visible()
    toast = toast_message.locator("..")
    dismiss_button = toast.get_by_role("button", name="Dismiss", exact=True)
    expect(dismiss_button).to_be_visible()
    dismiss_button.click()
    expect(toast_message).to_be_hidden()
