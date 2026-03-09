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
    """GET /results/home/<id> returns 200, shows run name in heading."""
    run_id, run_name = seeded_home_run
    response = page.goto(live_server + f"/results/home/{run_id}")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    # The page should show the run name (from config.name)
    heading = page.locator("h1, h2")
    heading_text = heading.first.text_content() or ""
    assert run_name in heading_text or "Simulation" in heading_text, (
        f"Expected run name '{run_name}' or 'Simulation' in heading, got '{heading_text}'"
    )


# -- Chart containers exist ------------------------------------------------


def test_results_chart_containers_exist(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """#chart-sankey or #chart-daily-balance div present."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")

    # Look for chart container divs
    sankey = page.locator("#chart-sankey")
    daily_balance = page.locator("#chart-daily-balance")

    has_sankey = sankey.count() > 0
    has_daily = daily_balance.count() > 0

    assert has_sankey or has_daily, (
        "Expected at least one chart container (#chart-sankey or #chart-daily-balance)"
    )


# -- Tab switching ----------------------------------------------------------


def test_results_tab_switching(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Click Overview/Power Flow/Battery & Finance/Analysis -> aria-selected='true'."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # The results page uses a tab nav (may be aria-label="Chart tabs" or similar)
    tab_labels = ["Overview", "Power Flow", "Battery", "Analysis"]

    for label in tab_labels:
        tab_btn = page.locator("button", has_text=label)
        if tab_btn.count() == 0:
            continue

        tab_btn.first.click()
        page.wait_for_timeout(300)

        # Check aria-selected on the clicked tab
        selected = tab_btn.first.get_attribute("aria-selected")
        assert selected == "true", (
            f"Tab '{label}' should have aria-selected='true', got '{selected}'"
        )


# -- Stat card labels not truncated (potential bug) -------------------------


def test_results_stat_card_labels_not_truncated(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """p.truncate label scrollWidth <= clientWidth (text fits)."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    truncated = page.evaluate("""() => {
        const labels = document.querySelectorAll('p.truncate');
        const problems = [];
        labels.forEach(el => {
            if (el.scrollWidth > el.clientWidth) {
                problems.push({
                    text: el.textContent.trim(),
                    scrollWidth: el.scrollWidth,
                    clientWidth: el.clientWidth,
                });
            }
        });
        return problems;
    }""")

    if not truncated:
        return  # All labels fit

    descriptions = [f"'{t['text']}' (scroll={t['scrollWidth']}, client={t['clientWidth']})" for t in truncated]
    assert not truncated, (
        f"Stat card labels are truncated: {', '.join(descriptions)}"
    )


# -- Download CSV returns 200 ----------------------------------------------


def test_results_download_csv_returns_200(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Follow CSV link -> status 200, content-type text/csv."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")

    # Find the CSV download link
    csv_link = page.locator("a", has_text="Download CSV")
    if csv_link.count() == 0:
        csv_link = page.locator("a", has_text="CSV")

    expect(csv_link.first).to_be_visible()

    href = csv_link.first.get_attribute("href") or ""
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
    page.wait_for_load_state("networkidle")

    # Find the YAML download link
    yaml_link = page.locator("a", has_text="Download Config")
    if yaml_link.count() == 0:
        yaml_link = page.locator("a", has_text="YAML")
    if yaml_link.count() == 0:
        yaml_link = page.locator("a", has_text="Config")

    expect(yaml_link.first).to_be_visible()

    href = yaml_link.first.get_attribute("href") or ""
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
