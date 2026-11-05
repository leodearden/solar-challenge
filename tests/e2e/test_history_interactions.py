"""End-to-end tests for History page interactive features (/history/runs).

Verifies search filtering, type dropdown filtering, multi-select compare,
delete confirmation, inline rename, pagination controls, and that a late
superseded list request cannot replace search results.
Uses seeded data fixtures.
"""

from collections.abc import Callable
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Locator, Page, Route, expect


# -- The list a search leaves ----------------------------------------------


def _expect_search_listed_only_one_run(page: Page) -> Locator:
    """Wait until the open Run History page lists one run, and return that run's 'View results' link.

    A list of one run is the search's, not the unfiltered list, only if the unfiltered list holds more than one,
    so a test calling this requests seeded_home_runs_pair beside the run it searches for.
    """
    result_link = page.get_by_role("link", name="View results")
    expect(result_link).to_have_count(1)
    return result_link


# -- Search filter updates table -------------------------------------------


@pytest.mark.usefixtures("seeded_home_runs_pair")
def test_search_filter_updates_table(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Type run name -> row visible; type nonsense -> 'No simulation runs found'."""
    _, run_name = seeded_home_run
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    search_input = page.locator("#filter-search")
    expect(search_input).to_be_visible()

    # Search for the seeded run name
    search_input.fill(run_name)
    _expect_search_listed_only_one_run(page)

    # The seeded run is the only run listed
    row = page.locator("td", has_text=run_name)
    expect(row.first).to_be_visible()

    # Clear and search for nonsense
    search_input.fill("zzz-nonexistent-run-xyz-12345")

    # Should show empty state
    empty_msg = page.locator("text=No simulation runs found")
    expect(empty_msg).to_be_visible()


# -- Type filter lists a run only under its own type -----------------------


@pytest.mark.parametrize(
    ("seeded_run", "run_type", "other_type"),
    [("seeded_home_run", "home", "fleet"), ("seeded_fleet_run", "fleet", "home")],
    ids=["home", "fleet"],
)
def test_type_filter_lists_a_seeded_run_only_under_its_own_type(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    seeded_run: str,
    run_type: str,
    other_type: str,
) -> None:
    """Searched by name, a seeded run is listed under its own type's filter and not under the other's.

    The search narrows the list to that run, whatever else the shared session DB holds.
    The other type is selected first, so the run's row can reappear only from its own type's list.
    """
    _, run_name = request.getfixturevalue(seeded_run)
    page.goto(live_server + "/history/runs")
    page.get_by_label("Search", exact=True).fill(run_name)
    type_filter = page.get_by_label("Type", exact=True)

    type_filter.select_option(value=other_type)
    expect(page.get_by_text("No simulation runs found")).to_be_visible()

    type_filter.select_option(value=run_type)
    expect(page.get_by_role("row").filter(has_text=run_name)).to_be_visible()


# -- Finding a seeded run --------------------------------------------------


def _search_for_run_row(page: Page, run_name: str) -> Locator:
    """Search the open Run History page for run_name and return that run's table row once it shows.

    A search lists the run on the first page, whatever else the shared session DB holds.
    """
    page.get_by_label("Search", exact=True).fill(run_name)
    run_row = page.get_by_role("row").filter(has_text=run_name)
    expect(run_row).to_be_visible()
    return run_row


# -- Select runs shows compare button --------------------------------------


def test_select_runs_shows_compare_button(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Checking two runs' boxes shows the 'Compare Selected' link to their comparison.

    Each run is found by searching its name; the first stays selected through the second search.
    """
    (id_a, _), (id_b, _) = seeded_home_runs_pair
    page.goto(live_server + "/history/runs")

    for _, run_name in seeded_home_runs_pair:
        _search_for_run_row(page, run_name).get_by_role("checkbox").check()

    compare_link = page.get_by_role("link", name="Compare Selected")
    expect(compare_link).to_be_visible()
    expect(compare_link).to_have_attribute("href", f"/history/compare?ids={id_a},{id_b}")


# -- Delete run with confirmation ------------------------------------------


def test_delete_run_with_confirmation(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click a run's delete -> the 'Delete Run' dialog shows; click Cancel -> it closes."""
    _, run_name = seeded_home_run
    page.goto(live_server + "/history/runs")

    _search_for_run_row(page, run_name).get_by_role("button", name="Delete").click()

    dialog_title = page.get_by_role("heading", name="Delete Run")
    expect(dialog_title).to_be_visible()
    page.get_by_role("button", name="Cancel").click()
    expect(dialog_title).to_be_hidden()


# -- Rename run inline -----------------------------------------------------


def test_rename_run_inline(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click a run's rename -> an inline input holding its name replaces the name."""
    _, run_name = seeded_home_run
    page.goto(live_server + "/history/runs")

    _search_for_run_row(page, run_name).get_by_role("button", name="Rename").click()

    edit_input = page.locator('input[x-model="editName"]')
    expect(edit_input).to_be_visible()
    expect(edit_input).to_have_value(run_name)


# -- Pagination controls exist ---------------------------------------------


def test_pagination_controls_exist(
    page: Page,
    live_server: str,
) -> None:
    """'Prev' and 'Next' buttons attached in DOM."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

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
    """The initial list request, answered or failed after the search's, leaves the search results showing."""
    run_id, run_name = seeded_home_run
    held_requests: list[Route] = []

    def hold(route: Route) -> None:
        held_requests.append(route)

    page.route(_is_unfiltered_runs_request, hold)
    page.goto(live_server + "/history/runs")
    page.get_by_label("Search", exact=True).fill(run_name)
    _expect_search_listed_only_one_run(page)

    (superseded_request,) = held_requests
    settle_superseded_request(superseded_request)
    # networkidle cannot fire while the held request is in flight, and fires 500 ms after it settles
    page.wait_for_load_state("networkidle")

    result_link = _expect_search_listed_only_one_run(page)
    expect(result_link).to_have_attribute("href", f"/results/{run_id}")
