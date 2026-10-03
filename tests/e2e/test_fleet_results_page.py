"""End-to-end tests for the Fleet Results page (/results/fleet/<id>).

Uses the seeded_fleet_run fixture (no live simulation needed) to verify
the page's title, its action links, its chart tabs, and that it renders
without errors.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- The page's chart tabs --------------------------------------------------


_CHART_IDS_BY_TAB = {
    "Per-Home": ("chart-heatmap", "chart-box-plots"),
    "Distributions": ("chart-distribution-histograms",),
    "Aggregate": ("chart-aggregate-timeline", "chart-grid-impact"),
}


def _show_tab(page: Page, tab_name: str) -> None:
    """Click tab_name's tab and wait until Plotly has drawn each of its charts, visible."""
    page.get_by_role("tab", name=tab_name, exact=True).click()
    for chart_id in _CHART_IDS_BY_TAB[tab_name]:
        expect(page.locator(f"#{chart_id}.js-plotly-plot")).to_be_visible()


# -- The page is titled with the run's name ---------------------------------


def test_fleet_results_page_is_titled_with_the_run_name(
    page: Page,
    live_server: str,
    seeded_fleet_run: tuple[str, str],
) -> None:
    """GET /results/fleet/<id> returns 200, and the page's h1 is the run's name."""
    run_id, run_name = seeded_fleet_run
    response = page.goto(live_server + f"/results/fleet/{run_id}")
    assert response is not None
    assert response.status == 200

    expect(page.get_by_role("heading", level=1)).to_have_text(run_name)


# -- Action links answer 200 ------------------------------------------------


@pytest.mark.parametrize(
    ("link_name", "content_type"),
    [
        ("Download CSV", "text/csv"),
        ("Download Config (YAML)", "text/yaml"),
        ("New Fleet Simulation", "text/html"),
    ],
    ids=["csv", "yaml", "new-fleet-simulation"],
)
def test_fleet_results_action_link_answers_200(
    page: Page,
    live_server: str,
    seeded_fleet_run: tuple[str, str],
    link_name: str,
    content_type: str,
) -> None:
    """Each action link's target answers 200 with the content type it serves.

    The links are fetched, not clicked: the downloads are served as attachments.
    """
    run_id, _ = seeded_fleet_run
    page.goto(live_server + f"/results/fleet/{run_id}")

    link = page.get_by_role("link", name=link_name, exact=True)
    expect(link).to_be_visible()
    href = link.get_attribute("href") or ""
    assert href.startswith("/"), f"{link_name!r} links to {href!r}, not to a path on this site"

    response = page.request.get(live_server + href)
    assert response.status == 200, f"{link_name!r} ({href}) answered {response.status}"
    served_type = response.headers.get("content-type", "")
    assert served_type.startswith(content_type), (
        f"{link_name!r} ({href}) served content type {served_type!r}, not {content_type}"
    )


# -- Each tab shows only its own charts -------------------------------------


def test_fleet_results_tabs_each_show_only_their_own_charts(
    page: Page,
    live_server: str,
    seeded_fleet_run: tuple[str, str],
) -> None:
    """Clicking each chart tab selects it alone and shows only its own charts, drawn by Plotly.

    Aggregate is selected on load, so it is clicked last: only then does
    its click have to move the selection.
    """
    run_id, _ = seeded_fleet_run
    page.goto(live_server + f"/results/fleet/{run_id}")

    for tab_name, chart_ids in _CHART_IDS_BY_TAB.items():
        _show_tab(page, tab_name)
        expect(page.get_by_role("tab", selected=True)).to_have_accessible_name(tab_name)
        expect(page.locator(".js-plotly-plot").filter(visible=True)).to_have_count(len(chart_ids))


# -- Showing every tab logs no errors ---------------------------------------


def test_fleet_results_page_shows_every_tab_without_errors(
    page: Page,
    live_server: str,
    seeded_fleet_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Loading the page and showing each of its tabs logs no console error and throws no uncaught exception.

    chart-renderer.js draws a hidden tab's charts only once the tab is shown, so every tab is shown.
    """
    run_id, _ = seeded_fleet_run
    response = page.goto(live_server + f"/results/fleet/{run_id}")
    assert response is not None
    assert response.status == 200
    for tab_name in _CHART_IDS_BY_TAB:
        _show_tab(page, tab_name)

    assert page_errors == [], f"Errors on /results/fleet/{run_id}: {page_errors}"
