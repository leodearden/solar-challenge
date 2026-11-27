# SPDX-License-Identifier: AGPL-3.0-or-later
"""Open a page and return once Alpine has started on it, whatever the network is doing.

Alpine's start() evaluates the page's expressions, dispatches alpine:initialized, and rethrows each expression error
from a 0 ms timer it queued while evaluating. A 0 ms timer queued at alpine:initialized runs after those, so by the
time it sets the mark every such error has reached the page. tests/e2e/test_alpine_start.py holds the contract.
"""

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

_MARK_ONCE_ALPINE_HAS_STARTED = """document.addEventListener('alpine:initialized', () => {
    setTimeout(() => { window.alpineHasStarted = true; }, 0);
});"""


def open_once_alpine_has_started(page: Page, url: str) -> None:
    """Open url in page; return once Alpine has started there and every error its start threw has reached the page. If Playwright's default timeout runs out first, fail naming url and whether window.Alpine is defined."""
    page.add_init_script(_MARK_ONCE_ALPINE_HAS_STARTED)
    page.goto(url)
    try:
        page.wait_for_function("() => window.alpineHasStarted === true")
    except PlaywrightTimeoutError as timeout:
        alpine_is_defined = page.evaluate("() => window.Alpine !== undefined")
        raise AssertionError(
            f"Alpine had not dispatched alpine:initialized on {url} (window.Alpine defined: {alpine_is_defined})"
        ) from timeout
