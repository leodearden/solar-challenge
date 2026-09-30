"""End-to-end tests for the Run History page (/history/runs).

Verifies page loading, table structure, loading and empty states, filter
controls, type filter options, column sorting, and compare button visibility.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Page loading ----------------------------------------------------------


def test_history_page_loads(page: Page, live_server: str) -> None:
    """GET /history/runs returns a page with 'Run History' heading."""
    response = page.goto(live_server + "/history/runs")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Run History").first
    expect(heading).to_be_visible()


# -- Table structure -------------------------------------------------------


@pytest.mark.usefixtures("seeded_home_run")
def test_history_table_exists(page: Page, live_server: str) -> None:
    """With runs to list, the runs table shows the expected column headers."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    # The table should be present on the page
    table = page.locator("table")
    expect(table).to_be_visible()

    # Verify expected column headers in the <thead>
    expected_headers = [
        "Name",
        "Type",
        "Date",
        "Duration",
        "Generation",
        "Self-Cons.",
        "Status",
        "Actions",
    ]

    thead = page.locator("thead")
    for header in expected_headers:
        th = thead.locator("th", has_text=header)
        assert th.count() > 0, (
            f"Expected table header '{header}' not found in <thead>"
        )


# -- Loading and empty states ----------------------------------------------


@pytest.mark.usefixtures("runs_api_returns_no_runs")
def test_history_empty_state(page: Page, live_server: str) -> None:
    """'No simulation runs found' shows in place of the runs table when the runs API returns no runs.

    The API is stubbed, so this holds whatever runs the shared session DB has accumulated.
    """
    page.goto(live_server + "/history/runs")

    expect(page.get_by_text("No simulation runs found")).to_be_visible()
    expect(page.locator("table")).to_be_hidden()


@pytest.mark.usefixtures("runs_api_never_answers")
def test_history_loading_state(page: Page, live_server: str) -> None:
    """'Loading runs...' shows in place of the runs table while the runs API has not answered."""
    page.goto(live_server + "/history/runs")

    expect(page.get_by_text("Loading runs...")).to_be_visible()
    expect(page.locator("table")).to_be_hidden()


# -- Filter controls -------------------------------------------------------


def test_filter_controls_exist(page: Page, live_server: str) -> None:
    """Verify Type dropdown, Search input, and From/To date inputs exist."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    # Type filter dropdown
    type_select = page.locator("#filter-type")
    expect(type_select).to_be_visible()

    # Search input
    search_input = page.locator("#filter-search")
    expect(search_input).to_be_visible()

    # From date input
    date_from = page.locator("#filter-date-from")
    expect(date_from).to_be_visible()

    # To date input
    date_to = page.locator("#filter-date-to")
    expect(date_to).to_be_visible()


# -- Type filter dropdown options ------------------------------------------


def test_type_filter_dropdown(page: Page, live_server: str) -> None:
    """The Type filter has options: All, Home, Fleet, Sweep."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    type_select = page.locator("#filter-type")

    # Verify each expected option exists
    expected_options = [
        ("", "All"),
        ("home", "Home"),
        ("fleet", "Fleet"),
        ("sweep", "Sweep"),
    ]

    options = type_select.locator("option")
    assert options.count() == len(expected_options), (
        f"Expected {len(expected_options)} options in Type filter, "
        f"got {options.count()}"
    )

    for value, label in expected_options:
        option = type_select.locator(f'option[value="{value}"]')
        assert option.count() == 1, (
            f"Expected option with value='{value}' (label='{label}') "
            f"in Type filter"
        )
        option_text = option.text_content() or ""
        assert label in option_text, (
            f"Expected option label '{label}', got '{option_text}'"
        )


# -- Column sorting --------------------------------------------------------


@pytest.mark.usefixtures("seeded_home_run")
def test_sort_columns(page: Page, live_server: str) -> None:
    """Click the 'Name' column header and verify a sort indicator appears."""
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine to initialise the runBrowser component
    page.wait_for_timeout(500)

    # Click the "Name" column header (it has @click="toggleSort('name')")
    name_header = page.locator('th', has_text="Name").first
    name_header.click()

    # Wait for Alpine reactivity
    page.wait_for_timeout(300)

    # After clicking Name, the sort indicator span with text " ^" or " v"
    # should become visible (it uses x-show="sort === 'name'")
    sort_indicator = name_header.locator("span.text-amber-500")
    expect(sort_indicator).to_be_visible()

    # The indicator should contain a caret character (^ or v)
    indicator_text = sort_indicator.text_content() or ""
    assert "^" in indicator_text or "v" in indicator_text, (
        f"Expected sort indicator '^' or 'v', got '{indicator_text}'"
    )


# -- Compare button visibility --------------------------------------------


def test_compare_button_hidden_by_default(page: Page, live_server: str) -> None:
    """The 'Compare Selected' button is hidden when no runs are selected.

    The button container uses ``x-show="selectedIds.length >= 2"``
    with ``x-cloak``, so it should not be visible initially.
    """
    page.goto(live_server + "/history/runs")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine to initialise
    page.wait_for_timeout(500)

    # The compare button link has text "Compare Selected"
    compare_btn = page.locator("a", has_text="Compare Selected")

    # It should exist in the DOM (it's rendered but hidden via x-show)
    expect(compare_btn).to_be_attached()

    # It should not be visible because selectedIds is empty
    expect(compare_btn).not_to_be_visible()
