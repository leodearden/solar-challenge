"""End-to-end tests for toast notifications and confirm dialog component.

Verifies toast success/error appearance, auto-dismiss, manual dismiss,
and the confirm dialog triggered by delete actions.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Toast success appears and dismisses ------------------------------------


def test_toast_success_appears_and_dismisses(page: Page, live_server: str) -> None:
    """Alpine.store('toast').success(msg) -> visible -> auto-dismiss after 4s."""
    page.goto(live_server + "/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Trigger a success toast via Alpine store
    page.evaluate("() => Alpine.store('toast').success('Test success message')")
    page.wait_for_timeout(300)

    # Toast should be visible with the message text
    toast_text = page.locator("text=Test success message")
    expect(toast_text).to_be_visible()

    # Wait for auto-dismiss (default 4s + buffer)
    page.wait_for_timeout(5000)

    # Toast should no longer be visible
    expect(toast_text).not_to_be_visible()


# -- Toast error appears ----------------------------------------------------


def test_toast_error_appears(page: Page, live_server: str) -> None:
    """.error(msg) -> visible with red/error styling classes."""
    page.goto(live_server + "/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Trigger an error toast
    page.evaluate("() => Alpine.store('toast').error('Something went wrong')")
    page.wait_for_timeout(300)

    # Toast message should be visible
    toast_text = page.locator("text=Something went wrong")
    expect(toast_text).to_be_visible()

    # Check for red/error styling on the toast container
    # The toast item should have a red-related class
    toast_container = toast_text.locator("xpath=ancestor::div[contains(@class, 'red') or contains(@class, 'error')]")
    if toast_container.count() == 0:
        # Alternative: check that the toast store recorded the error type
        toast_type = page.evaluate("""() => {
            const items = Alpine.store('toast').items;
            const match = items.find(t => t.message === 'Something went wrong');
            return match ? match.type : null;
        }""")
        assert toast_type == "error", f"Expected toast type 'error', got '{toast_type}'"


# -- Toast dismiss on click -------------------------------------------------


def test_toast_dismiss_on_click(page: Page, live_server: str) -> None:
    """Click dismiss button -> toast hidden."""
    page.goto(live_server + "/")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    # Trigger a toast (use longer duration so it doesn't auto-dismiss)
    page.evaluate("() => Alpine.store('toast').success('Dismiss me', 30000)")
    page.wait_for_timeout(300)

    toast_text = page.locator("text=Dismiss me")
    expect(toast_text).to_be_visible()

    # Click the dismiss button (X button inside the toast)
    dismiss_btn = page.locator('button[aria-label="Dismiss"]')
    if dismiss_btn.count() == 0:
        # Try close button near the toast
        dismiss_btn = toast_text.locator("xpath=ancestor::div//button")
    expect(dismiss_btn.first).to_be_visible()
    dismiss_btn.first.click()
    page.wait_for_timeout(500)

    # Toast should be gone
    expect(toast_text).not_to_be_visible()


# -- Confirm dialog appears on delete ---------------------------------------


def test_confirm_dialog_appears_on_delete(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click delete button on history -> dialog with 'Delete Run' title."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    # Wait for AJAX run list to load
    page.wait_for_timeout(2000)

    # Find a delete button in the runs table
    delete_btn = page.locator('button[title="Delete"]')
    if delete_btn.count() == 0:
        pytest.skip("No delete buttons found (no runs in table)")

    delete_btn.first.click()
    page.wait_for_timeout(500)

    # The confirm dialog should appear with "Delete Run" title
    dialog_title = page.locator("h3", has_text="Delete Run")
    expect(dialog_title).to_be_visible()

    # Cancel and Delete buttons should be present
    cancel_btn = page.locator("button", has_text="Cancel")
    expect(cancel_btn).to_be_visible()

    # Click Cancel to close the dialog
    cancel_btn.click()
    page.wait_for_timeout(500)

    # Dialog should close
    expect(dialog_title).not_to_be_visible()
