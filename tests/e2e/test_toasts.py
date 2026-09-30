"""End-to-end tests for toast notifications.

Verifies toast success/error appearance, auto-dismiss and manual dismiss.
"""

import re
from typing import Literal

import pytest
from playwright.sync_api import Locator, Page, expect

pytestmark = pytest.mark.e2e


# -- Raising a toast --------------------------------------------------------


def _raise_toast(
    page: Page,
    kind: Literal["success", "error", "info"],
    message: str,
    *,
    duration_ms: int | None = None,
) -> Locator:
    """Raise a toast via Alpine.store('toast')[kind] and return it once message shows.

    Without duration_ms, the store's own default duration applies.
    """
    store_args = [message] if duration_ms is None else [message, duration_ms]
    page.evaluate(
        "([kind, args]) => Alpine.store('toast')[kind](...args)", [kind, store_args]
    )
    toast_message = page.get_by_text(message, exact=True)
    expect(toast_message).to_be_visible()
    return toast_message.locator("..")


# -- Toast success appears and dismisses ------------------------------------


def test_toast_success_appears_and_dismisses(page: Page, live_server: str) -> None:
    """.success(msg) shows the message, then the toast dismisses itself without a click."""
    page.goto(live_server + "/")

    toast = _raise_toast(page, "success", "Test success message")

    expect(toast).to_be_hidden(timeout=10_000)


# -- Toast error appears ----------------------------------------------------


def test_toast_error_appears(page: Page, live_server: str) -> None:
    """.error(msg) shows the message in a toast styled red."""
    page.goto(live_server + "/")

    toast = _raise_toast(page, "error", "Something went wrong")

    expect(toast).to_have_class(re.compile(r"\bbg-red-"))


# -- Toast dismiss on click -------------------------------------------------


def test_toast_dismiss_on_click(page: Page, live_server: str) -> None:
    """Clicking a toast's Dismiss button hides it long before its 30 s duration ends."""
    page.goto(live_server + "/")

    toast = _raise_toast(page, "success", "Dismiss me", duration_ms=30_000)

    dismiss_button = toast.get_by_role("button", name="Dismiss", exact=True)
    expect(dismiss_button).to_be_visible()
    dismiss_button.click()
    expect(toast).to_be_hidden()
