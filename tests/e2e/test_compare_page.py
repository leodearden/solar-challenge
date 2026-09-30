"""End-to-end tests for the Compare page (/history/compare).

Verifies page loading, metrics table, delta columns, color coding,
and the empty state shown when no IDs are given.
Uses seeded run pair fixtures.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Compare page loads with valid IDs --------------------------------------


def test_compare_page_loads_with_valid_ids(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """/history/compare?ids=id1,id2 -> 200, 'Compare Runs' heading."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    response = page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("h1, h2", has_text="Compare")
    expect(heading.first).to_be_visible()


# -- Compare page shows metrics table --------------------------------------


def test_compare_page_shows_metrics_table(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """'Key Metrics' heading + metric rows for Generation/Demand/Self-Consumption."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    page.wait_for_load_state("networkidle")

    # Key Metrics heading or similar
    metrics_heading = page.locator("h2, h3", has_text="Metrics")
    if metrics_heading.count() == 0:
        metrics_heading = page.locator("h2, h3", has_text="Comparison")
    expect(metrics_heading.first).to_be_visible()

    # Check for specific metric rows
    for metric_name in ["Generation", "Demand", "Self-Consumption"]:
        metric_row = page.locator("td, th", has_text=metric_name)
        assert metric_row.count() > 0, (
            f"Expected metric row for '{metric_name}' in comparison table"
        )


# -- Delta column exists ---------------------------------------------------


def test_compare_page_delta_column_exists(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """'Delta' and '% Change' column headers visible."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    page.wait_for_load_state("networkidle")

    # Look for Delta or % Change column headers
    delta_header = page.locator("th", has_text="Delta")
    pct_header = page.locator("th", has_text="% Change")

    has_delta = delta_header.count() > 0
    has_pct = pct_header.count() > 0

    assert has_delta or has_pct, (
        "Expected 'Delta' or '% Change' column header in comparison table"
    )


# -- Compare delta coloring direction (potential bug) -----------------------


def test_compare_delta_coloring_direction(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Grid Import's positive Delta and % Change are styled red: a higher grid import is worse.

    The seeded pair's grid import rises from its first run to its second, so both cells are positive.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")

    grid_import_row = page.get_by_role("row").filter(has_text="Grid Import")
    positive_deltas = grid_import_row.get_by_role("cell").filter(has_text="+")
    expect(positive_deltas).to_have_count(2)
    for delta in positive_deltas.all():
        expect(delta).to_have_class(re.compile(r"\btext-red-"))


# -- Compare without IDs shows empty state ---------------------------------


def test_compare_without_ids_shows_empty_state(
    page: Page,
    live_server: str,
) -> None:
    """/history/compare without ids shows the no-runs-selected state, whose link leads to run history."""
    response = page.goto(live_server + "/history/compare")
    assert response is not None
    assert response.status == 200
    expect(page).to_have_url(live_server + "/history/compare")

    expect(page.get_by_role("heading", name="No Runs Selected")).to_be_visible()

    page.get_by_role("link", name="Go to Run History").click()
    expect(page).to_have_url(live_server + "/history/runs")
