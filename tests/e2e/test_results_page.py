"""End-to-end tests for the Results page (/results/home/<id>).

Uses seeded data fixtures (no live simulation needed) to verify
page rendering, chart containers, tab switching, stat cards,
download links, and error handling.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Results page loads with seeded data ------------------------------------


def test_results_page_loads(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """GET /results/home/<id> returns 200, and the page's h1 is the run's name."""
    run_id, run_name = seeded_home_run
    response = page.goto(live_server + f"/results/home/{run_id}")
    assert response is not None
    assert response.status == 200

    expect(page.get_by_role("heading", level=1)).to_have_text(run_name)


# -- Chart containers exist ------------------------------------------------


def test_results_chart_containers_exist(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Overview tab shows both chart containers: #chart-sankey, #chart-daily-balance."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for chart_id in ("#chart-sankey", "#chart-daily-balance"):
        expect(page.locator(chart_id)).to_be_visible()


# -- Tab switching ----------------------------------------------------------


def test_results_tab_switching(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Clicking each chart tab makes it the only selected tab.

    Overview is selected on load, so it is clicked last: only then does
    its click have to move the selection.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for name in ("Power Flow", "Battery & Finance", "Analysis", "Overview"):
        page.get_by_role("tab", name=name, exact=True).click()
        expect(page.get_by_role("tab", selected=True)).to_have_accessible_name(name)


# -- Stat card labels not truncated ----------------------------------------


def test_results_stat_card_labels_not_truncated(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """The seeded run's stat card labels are all visible, and none is cut short.

    The stat_card macro titles each label with its text; no other <p> here has a title.
    The seed's battery_config adds the battery cards; the expected count includes them.
    A label is cut short when its text needs more room than its box, across or down.
    """
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    stat_card_labels = page.locator("p[title]").filter(visible=True)
    expect(stat_card_labels).to_have_count(12)

    cut_short = stat_card_labels.evaluate_all("""labels => labels
        .filter(label => label.scrollWidth > label.clientWidth
            || label.scrollHeight > label.clientHeight)
        .map(label => ({
            label: label.textContent.trim(),
            text_size: [label.scrollWidth, label.scrollHeight],
            box_size: [label.clientWidth, label.clientHeight],
        }))""")
    assert cut_short == [], f"Stat card labels are cut short: {cut_short}"


# -- Download CSV returns 200 ----------------------------------------------


def test_results_download_csv_returns_200(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Follow CSV link -> status 200, content-type text/csv."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    csv_link = page.get_by_role("link", name="Download CSV", exact=True)
    expect(csv_link).to_be_visible()

    href = csv_link.get_attribute("href") or ""
    assert href, "CSV download link has no href"

    # Fetch the URL directly
    csv_url = href if href.startswith("http") else live_server + href
    response = page.request.get(csv_url)
    assert response.status == 200, f"CSV download returned {response.status}"
    content_type = response.headers.get("content-type", "")
    assert "text/csv" in content_type, f"Expected text/csv, got '{content_type}'"


# -- Download YAML returns 200 ---------------------------------------------


def test_results_download_yaml_returns_200(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Follow YAML link -> status 200."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    yaml_link = page.get_by_role("link", name="Download Config (YAML)", exact=True)
    expect(yaml_link).to_be_visible()

    href = yaml_link.get_attribute("href") or ""
    assert href, "YAML download link has no href"

    yaml_url = href if href.startswith("http") else live_server + href
    response = page.request.get(yaml_url)
    assert response.status == 200, f"YAML download returned {response.status}"


# -- Nonexistent run returns error -----------------------------------------


def test_results_nonexistent_run_returns_error(
    page: Page,
    live_server: str,
) -> None:
    """/results/home/nonexistent -> redirect to dashboard."""
    response = page.goto(live_server + "/results/home/nonexistent-run-id-xyz")
    assert response is not None

    # Should redirect to dashboard (status 200 after redirect, or 302)
    # The route flashes an error and redirects to main.index
    final_url = page.url
    # After redirect we should be on the dashboard or root
    assert "/results/home/nonexistent" not in final_url, (
        f"Expected redirect away from nonexistent results page, still at {final_url}"
    )
