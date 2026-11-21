# SPDX-License-Identifier: AGPL-3.0-or-later
"""Record each fetch a page starts, and wait until the page has handled every one.

A fetch is handled once it fails, or once the page has read its answer's body with arrayBuffer(), blob(), bytes(),
formData(), json() or text(). fetch() and those readers give the page promises chained on the browser's own, so the
recorder handles none of the page's promises, and a rejection the page leaves unhandled is still uncaught. fetch() still
rejects, rather than throws, on a URL it cannot parse.

The mark is set from a 0 ms timer queued from a 0 ms timer queued as the fetch fails or the body settles. The first
timer runs after every microtask chained from the settle, which includes the page's code awaiting it and the Alpine
re-render that code schedules. Alpine rethrows an expression error from a 0 ms timer it queues during that re-render,
so only the second timer is sure to run after every such error has reached the page.

A fetch whose body the page reads through response.body or a clone, or never reads, is never handled, so the wait
fails naming it. tests/e2e/test_fetches_handled.py holds the contract.
"""

from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

_RECORD_FETCHES_STARTED_AND_HANDLED = """(() => {
    window.fetchesStarted = [];
    const markHandledAfterTwoTimers = (entry) => setTimeout(() => setTimeout(() => { entry.handled = true; }, 0), 0);
    const fetchOf = new WeakMap();
    const urlOf = (resource) => {
        try {
            return resource instanceof Request ? resource.url : new URL(resource, location.href).href;
        } catch {
            return String(resource);
        }
    };
    const originalFetch = window.fetch;
    window.fetch = function (resource, options) {
        const entry = {url: urlOf(resource), handled: false};
        window.fetchesStarted.push(entry);
        return originalFetch.call(this, resource, options).then(
            (response) => { fetchOf.set(response, entry); return response; },
            (error) => { markHandledAfterTwoTimers(entry); throw error; },
        );
    };
    for (const reader of ['arrayBuffer', 'blob', 'bytes', 'formData', 'json', 'text']) {
        const originalRead = Response.prototype[reader];
        Response.prototype[reader] = function () {
            const entry = fetchOf.get(this);
            const body = originalRead.call(this);
            if (entry === undefined) return body;
            return body.then(
                (value) => { markHandledAfterTwoTimers(entry); return value; },
                (error) => { markHandledAfterTwoTimers(entry); throw error; },
            );
        };
    }
})();"""


class FetchesLeftUnhandled(AssertionError):
    """The page had not handled the fetch of each URL in unhandled when the wait ran out; it had handled each in handled."""

    def __init__(self, page_url: str, unhandled: tuple[str, ...], handled: tuple[str, ...]) -> None:
        super().__init__(
            f"{page_url} had not handled the failure or the body of the fetches of {list(unhandled)} "
            f"(it had handled those of {list(handled)})"
        )
        self.unhandled = unhandled
        self.handled = handled


def record_fetches_started_and_handled(page: Page) -> None:
    """Record, in each document page opens from now on, every fetch the document starts and when it has handled it; call it before the page opens."""
    page.add_init_script(_RECORD_FETCHES_STARTED_AND_HANDLED)


def wait_until_the_page_has_handled_every_fetch_it_started(page: Page) -> None:
    """Return once page has handled every fetch it has started by the time of the check, so a fetch started while handling another is waited for too.

    If Playwright's default timeout runs out first, raise FetchesLeftUnhandled naming the URL of each fetch the page had
    not handled and of each it had. On a page opened without record_fetches_started_and_handled, fail at once naming it.
    """
    if not page.evaluate("() => Array.isArray(window.fetchesStarted)"):
        raise AssertionError(
            f"{page.url} was opened without record_fetches_started_and_handled, so it records no fetch to wait for"
        )
    try:
        page.wait_for_function("() => window.fetchesStarted.every(entry => entry.handled)")
    except PlaywrightTimeoutError as timeout:
        started = page.evaluate("() => window.fetchesStarted")
        raise FetchesLeftUnhandled(
            page.url,
            unhandled=tuple(entry["url"] for entry in started if not entry["handled"]),
            handled=tuple(entry["url"] for entry in started if entry["handled"]),
        ) from timeout
