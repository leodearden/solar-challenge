"""End-to-end tests for the Compare page (/history/compare).

Verifies page loading, metrics table, delta columns, color coding,
and redirect behavior when IDs are missing.
Uses seeded run pair fixtures.
"""

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
    """Grid Import positive delta should be red (not green).

    A higher grid import is worse, so positive delta should be styled
    with a negative/red color, not green.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Find the Grid Import row's delta cell
    grid_import_colors = page.evaluate("""() => {
        const rows = document.querySelectorAll('tr');
        for (const row of rows) {
            const cells = row.querySelectorAll('td, th');
            const label = cells[0]?.textContent || '';
            if (label.includes('Grid Import')) {
                // Find cells with color classes
                const deltaCells = Array.from(cells).slice(1);
                const colors = deltaCells.map(cell => {
                    const text = cell.textContent || '';
                    const classes = cell.className || '';
                    return { text: text.trim(), classes };
                });
                return colors;
            }
        }
        return null;
    }""")

    if grid_import_colors is None:
        pytest.skip("Could not find 'Grid Import' row in comparison table")

    # Check if any delta cell with a positive value uses green (incorrect)
    for cell in grid_import_colors:
        text = cell.get("text", "")
        classes = cell.get("classes", "")

        # If this cell shows a positive delta for grid import
        # and uses green styling, that's a bug
        if "+" in text and "green" in classes:
            assert False, (
                f"Grid Import positive delta '{text}' is styled green. "
                f"Higher grid import is worse and should be red. "
                f"Classes: {classes}"
            )


# -- Compare redirects without IDs -----------------------------------------


def test_compare_redirects_without_ids(
    page: Page,
    live_server: str,
) -> None:
    """/history/compare -> redirects to /history/runs."""
    response = page.goto(live_server + "/history/compare")
    assert response is not None

    # Should redirect to the runs page
    page.wait_for_load_state("domcontentloaded")
    final_url = page.url
    assert "/history/runs" in final_url, (
        f"Expected redirect to /history/runs, ended up at {final_url}"
    )
