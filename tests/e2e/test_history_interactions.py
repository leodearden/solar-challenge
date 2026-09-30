"""End-to-end tests for History page interactive features (/history/runs).

Verifies search filtering, type dropdown filtering, multi-select compare,
delete confirmation, inline rename, pagination controls, and that a late
superseded list request cannot replace search results.
Uses seeded data fixtures.
"""

from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


# -- Search filter updates table -------------------------------------------


def test_search_filter_updates_table(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Type run name -> row visible; type nonsense -> 'No simulation runs found'."""
    _, run_name = seeded_home_run
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    search_input = page.locator("#filter-search")
    expect(search_input).to_be_visible()

    # Search for the seeded run name
    search_input.fill(run_name)
    page.wait_for_timeout(1000)

    # The seeded run should be visible
    row = page.locator("td", has_text=run_name)
    expect(row.first).to_be_visible()

    # Clear and search for nonsense
    search_input.fill("zzz-nonexistent-run-xyz-12345")
    page.wait_for_timeout(1000)

    # Should show empty state
    empty_msg = page.locator("text=No simulation runs found")
    expect(empty_msg).to_be_visible()


# -- Type filter dropdown filters ------------------------------------------


def test_type_filter_dropdown_filters(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Select 'home' -> seeded run visible; select 'fleet' -> empty state."""
    _, run_name = seeded_home_run
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    type_select = page.locator("#filter-type")
    expect(type_select).to_be_visible()

    # Filter by "home" type - seeded run should appear
    type_select.select_option(value="home")
    page.wait_for_timeout(1000)

    row = page.locator("td", has_text=run_name)
    expect(row.first).to_be_visible()

    # Filter by "fleet" type - should show empty state (only home runs seeded)
    type_select.select_option(value="fleet")
    page.wait_for_timeout(1000)

    empty_msg = page.locator("text=No simulation runs found")
    expect(empty_msg).to_be_visible()


# -- Select runs shows compare button --------------------------------------


def test_select_runs_shows_compare_button(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Check 2 checkboxes -> 'Compare Selected' link visible."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    # Find checkboxes in the table rows
    checkboxes = page.locator("tbody input[type='checkbox']")

    if checkboxes.count() < 2:
        pytest.skip(f"Expected at least 2 checkboxes, found {checkboxes.count()}")

    # Check the first two checkboxes
    checkboxes.nth(0).check()
    page.wait_for_timeout(200)
    checkboxes.nth(1).check()
    page.wait_for_timeout(500)

    # The "Compare Selected" link should now be visible
    compare_btn = page.locator("a", has_text="Compare Selected")
    expect(compare_btn).to_be_visible()


# -- Delete run with confirmation ------------------------------------------


def test_delete_run_with_confirmation(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click delete -> confirm dialog shows; click Cancel -> dialog closes."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    delete_btn = page.locator('button[title="Delete"]')
    if delete_btn.count() == 0:
        pytest.skip("No delete buttons found in history table")

    delete_btn.first.click()
    page.wait_for_timeout(500)

    # Confirm dialog should appear
    dialog_title = page.locator("h3", has_text="Delete Run")
    expect(dialog_title).to_be_visible()

    # Cancel button should be present
    cancel_btn = page.locator("button", has_text="Cancel")
    expect(cancel_btn).to_be_visible()

    # Click Cancel -> dialog should close
    cancel_btn.click()
    page.wait_for_timeout(500)
    expect(dialog_title).not_to_be_visible()


# -- Rename run inline -----------------------------------------------------


def test_rename_run_inline(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click rename -> input[x-model='editName'] visible."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(2000)

    rename_btn = page.locator('button[title="Rename"]')
    if rename_btn.count() == 0:
        pytest.skip("No rename buttons found in history table")

    rename_btn.first.click()
    page.wait_for_timeout(500)

    # An inline edit input should appear
    edit_input = page.locator('input[x-model="editName"]')
    expect(edit_input).to_be_visible()


# -- Pagination controls exist ---------------------------------------------


def test_pagination_controls_exist(
    page: Page,
    live_server: str,
) -> None:
    """'Prev' and 'Next' buttons attached in DOM."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    prev_btn = page.locator("button", has_text="Prev")
    next_btn = page.locator("button", has_text="Next")

    # Pagination buttons should exist in the DOM
    assert prev_btn.count() > 0, "Expected 'Prev' pagination button in DOM"
    assert next_btn.count() > 0, "Expected 'Next' pagination button in DOM"

    expect(prev_btn.first).to_be_attached()
    expect(next_btn.first).to_be_attached()


# -- Late superseded request does not replace search results ---------------


def _is_unfiltered_runs_request(url: str) -> bool:
    parts = urlsplit(url)
    return parts.path == "/api/history/runs" and "q" not in parse_qs(parts.query)


@pytest.mark.usefixtures("seeded_home_runs_pair")
@pytest.mark.parametrize(
    "settle_superseded_request",
    [Route.continue_, Route.abort],
    ids=["lands-late", "fails-late"],
)
def test_late_superseded_request_does_not_replace_search_results(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    settle_superseded_request: Callable[[Route], None],
) -> None:
    """The initial list request, answered or failed after the search's, leaves the search results showing.

    The seeded pair puts runs the search excludes in the unfiltered list, so a stale list is observable.
    """
    run_id, run_name = seeded_home_run
    held_requests: list[Route] = []

    def hold(route: Route) -> None:
        held_requests.append(route)

    page.route(_is_unfiltered_runs_request, hold)
    page.goto(live_server + "/history/runs")
    page.get_by_label("Search", exact=True).fill(run_name)

    result_links = page.get_by_role("link", name="View results")
    expect(result_links).to_have_count(1)

    (superseded_request,) = held_requests
    settle_superseded_request(superseded_request)
    # networkidle cannot fire while the held request is in flight, and fires 500 ms after it settles
    page.wait_for_load_state("networkidle")

    expect(result_links).to_have_count(1)
    expect(result_links).to_have_attribute("href", f"/results/home/{run_id}")
