# SPDX-License-Identifier: AGPL-3.0-or-later
"""wait_until_the_page_has_handled_every_fetch_it_started (tests/e2e/_fetches_handled.py) returns once every error the page logged or threw handling the answers to its fetches is in page_errors; it fails naming each fetch the page has not handled, or the recorder the page was opened without."""

from collections.abc import Callable
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Route

from tests.e2e._alpine_start import open_once_alpine_has_started
from tests.e2e._fetches_handled import (
    record_fetches_started_and_handled,
    wait_until_the_page_has_handled_every_fetch_it_started,
)


def _is_runs_list_request(url: str) -> bool:
    return urlsplit(url).path == "/api/history/runs"


def _open_run_history_answering_its_runs_list_only_then(
    page: Page, live_server: str, answer: Callable[[Route], None]
) -> None:
    """Open Run History once Alpine has started, holding its runs-list request until then, then answer it with answer."""
    held_requests: list[Route] = []

    def hold(route: Route) -> None:
        held_requests.append(route)

    page.route(_is_runs_list_request, hold)
    open_once_alpine_has_started(page, live_server + "/history/runs")
    (runs_list_request,) = held_requests
    answer(runs_list_request)


def test_an_error_thrown_rendering_an_answer_the_page_requested_as_alpine_started_is_in_page_errors_once_every_fetch_is_handled(
    page: Page, live_server: str, page_errors: list[str], seeded_home_run: tuple[str, str]
) -> None:
    """Run History's runs list lists the seeded run with its total generation as a string, on which the run's row calls toFixed as Alpine renders it.

    The runs-list answer is held until the page has opened, so it reaches the page only after
    open_once_alpine_has_started has returned.
    """
    listed = page.request.get(
        live_server + "/api/history/runs",
        params={"q": seeded_home_run[1]},
        fail_on_status_code=True,
    ).json()
    record_fetches_started_and_handled(page)
    _open_run_history_answering_its_runs_list_only_then(
        page,
        live_server,
        lambda route: route.fulfill(json={**listed, "runs": [{**listed["runs"][0], "total_generation_kwh": "12"}]}),
    )

    wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert "run.total_generation_kwh.toFixed is not a function" in page_errors, (
        f"page_errors once every fetch was handled: {page_errors}"
    )


def test_an_error_logged_handling_an_answer_the_page_requested_as_alpine_started_is_in_page_errors_once_every_fetch_is_handled(
    page: Page, live_server: str, page_errors: list[str]
) -> None:
    """Run History's runs list is answered with a body that is no JSON, which the page logs failing to read.

    The runs-list answer is held until the page has opened, so it reaches the page only after
    open_once_alpine_has_started has returned.
    """
    record_fetches_started_and_handled(page)
    _open_run_history_answering_its_runs_list_only_then(
        page,
        live_server,
        lambda route: route.fulfill(body="not json", content_type="application/json"),
    )

    wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert any(error.startswith("Failed to fetch runs:") for error in page_errors), (
        f"page_errors once every fetch was handled: {page_errors}"
    )


@pytest.mark.parametrize("reader", ["arrayBuffer", "blob", "bytes", "formData", "json", "text"])
def test_a_fetch_is_handled_once_the_page_reads_its_body(page: Page, live_server: str, reader: str) -> None:
    """The dashboard starts no fetch of its own. formData() rejects on the presets' JSON body, which reads it all the same."""
    record_fetches_started_and_handled(page)
    page.goto(live_server + "/")
    page.evaluate("reader => fetch('/api/presets').then(response => response[reader]()).catch(() => {})", reader)

    wait_until_the_page_has_handled_every_fetch_it_started(page)


def test_a_fetch_is_handled_once_the_page_catches_its_failure(page: Page, live_server: str) -> None:
    """The presets request is aborted, as if the network were down."""
    page.route("**/api/presets", lambda route: route.abort())
    record_fetches_started_and_handled(page)
    page.goto(live_server + "/")
    page.evaluate("() => fetch('/api/presets').catch(() => {})")

    wait_until_the_page_has_handled_every_fetch_it_started(page)


def test_a_fetch_of_a_url_fetch_cannot_parse_still_rejects_and_is_handled_once_the_page_catches_it(
    page: Page, live_server: str
) -> None:
    """fetch() rejects with a TypeError, rather than throwing one, when it cannot parse the URL it is given; the recorder leaves it so."""
    record_fetches_started_and_handled(page)
    page.goto(live_server + "/")

    rejection = page.evaluate("() => fetch('http://[').then(() => 'answered', error => error.name)")

    assert rejection == "TypeError"
    wait_until_the_page_has_handled_every_fetch_it_started(page)


@pytest.mark.parametrize(
    ("leave_a_rejection_unhandled", "message_part"),
    [
        pytest.param("() => { fetch('/api/presets'); }", "Failed to fetch", id="fetch-fails"),
        pytest.param("() => fetch('/').then(response => { response.json(); })", "JSON", id="json-of-html"),
    ],
)
def test_a_rejection_the_page_leaves_unhandled_is_still_an_uncaught_error(
    page: Page, live_server: str, leave_a_rejection_unhandled: str, message_part: str
) -> None:
    """The recorder watches each fetch's answer and body without handling the promises the page is given, so the page's own unhandled rejection still reaches page_errors.

    The presets request is aborted, as if the network were down, and the dashboard's HTML is no JSON.
    """
    page.route("**/api/presets", lambda route: route.abort())
    record_fetches_started_and_handled(page)
    page.goto(live_server + "/")

    with page.expect_event("pageerror") as uncaught:
        page.evaluate(leave_a_rejection_unhandled)

    assert message_part in uncaught.value.message, f"the uncaught error: {uncaught.value}"


@pytest.mark.usefixtures("runs_api_never_answers")
def test_waiting_fails_naming_a_fetch_whose_answer_never_comes(page: Page, live_server: str) -> None:
    """Run History's x-init starts its runs-list request; the fixture holds it unanswered.

    Only the wait runs on the shortened default timeout: the page opens on Playwright's 30 s.
    """
    record_fetches_started_and_handled(page)
    open_once_alpine_has_started(page, live_server + "/history/runs")
    page.set_default_timeout(1000)

    with pytest.raises(AssertionError) as failure:
        wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert live_server + "/api/history/runs?" in str(failure.value)


def test_waiting_fails_naming_a_fetch_whose_body_the_page_never_reads(page: Page, live_server: str) -> None:
    """The page takes the presets' answer and never reads its body."""
    record_fetches_started_and_handled(page)
    page.goto(live_server + "/")
    page.evaluate("() => fetch('/api/presets').then(() => {})")
    page.set_default_timeout(1000)

    with pytest.raises(AssertionError) as failure:
        wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert live_server + "/api/presets" in str(failure.value)


def test_waiting_on_a_page_opened_without_the_recorder_fails_naming_it(page: Page, live_server: str) -> None:
    page.goto(live_server + "/")

    with pytest.raises(AssertionError) as failure:
        wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert "record_fetches_started_and_handled" in str(failure.value)
