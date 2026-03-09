"""End-to-end tests for the full simulation submit-to-results lifecycle.

Verifies API submission, progress bar appearance, completion, navigation
to results, stat cards, and download buttons.

Note: test_simulation_completes_and_shows_view_results makes a real
PVGIS API call and is marked slow.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


# -- Submit home simulation via API ----------------------------------------


def test_submit_home_simulation_via_api(
    page: Page,
    live_server: str,
) -> None:
    """POST to /api/simulate/home via fetch returns 201 with job_id/run_id."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")

    result = page.evaluate("""async () => {
        const resp = await fetch('/api/simulate/home', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                pv_kw: 4.0,
                consumption_kwh: 3200,
                occupants: 3,
                location: 'bristol',
                period_days: 1,
                battery_enabled: false,
            }),
        });
        return { status: resp.status, body: await resp.json() };
    }""")

    status = result["status"]
    body = result["body"]

    # Should return 201 (created) or 200
    assert status in (200, 201), f"Expected 200/201, got {status}: {body}"
    assert "run_id" in body or "job_id" in body, (
        f"Expected run_id or job_id in response, got keys: {list(body.keys())}"
    )


# -- Progress bar appears after submit ------------------------------------


def test_progress_bar_appears_after_submit(
    page: Page,
    live_server: str,
) -> None:
    """'Simulation Progress' heading visible after clicking Run."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Click the Run Simulation button
    submit_btn = page.locator("button[type='submit']")
    expect(submit_btn).to_be_visible()
    submit_btn.click()

    # Wait for the progress section to appear
    page.wait_for_timeout(2000)

    # Look for progress-related UI elements
    progress_heading = page.locator("text=Simulation Progress")
    progress_bar = page.locator('[role="progressbar"]')
    running_text = page.locator("text=Running")
    simulating_text = page.locator("text=Simulating")

    has_progress = (
        progress_heading.count() > 0
        or progress_bar.count() > 0
        or running_text.count() > 0
        or simulating_text.count() > 0
    )

    assert has_progress, (
        "Expected progress indicator (heading, bar, or status text) "
        "after clicking 'Run Simulation'"
    )


# -- Simulation completes and shows View Results (slow, real PVGIS) --------


@pytest.mark.slow
def test_simulation_completes_and_shows_view_results(
    page: Page,
    live_server: str,
) -> None:
    """'View Results' link appears within 120s (real PVGIS call)."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    # Set to 1-day simulation for speed
    page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        const data = Alpine.$data(el);
        data.formData.period_days = 1;
    }""")
    page.wait_for_timeout(300)

    submit_btn = page.locator("button[type='submit']")
    submit_btn.click()

    # Wait for "View Results" link to appear (up to 120s for PVGIS)
    view_results = page.locator("a", has_text="View Results")
    expect(view_results).to_be_visible(timeout=120_000)


# -- View Results link navigates to results page ---------------------------


@pytest.mark.slow
def test_view_results_link_navigates_to_results_page(
    page: Page,
    live_server: str,
) -> None:
    """Click 'View Results' -> URL contains /results/home/."""
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1500)

    page.evaluate("""() => {
        const el = document.querySelector('[x-data="homeSimulator()"]');
        const data = Alpine.$data(el);
        data.formData.period_days = 1;
    }""")
    page.wait_for_timeout(300)

    submit_btn = page.locator("button[type='submit']")
    submit_btn.click()

    # Wait for "View Results" link
    view_results = page.locator("a", has_text="View Results")
    expect(view_results).to_be_visible(timeout=120_000)

    view_results.click()
    page.wait_for_load_state("domcontentloaded")

    assert "/results/home/" in page.url, (
        f"Expected URL to contain '/results/home/', got '{page.url}'"
    )


# -- Results page has stat cards (seeded) -----------------------------------


def test_results_page_has_stat_cards(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Stat cards visible on seeded results page."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)

    # Stat cards should show key metrics
    generation_card = page.locator("text=Total Generation")
    demand_card = page.locator("text=Total Demand")

    expect(generation_card.first).to_be_visible()
    expect(demand_card.first).to_be_visible()


# -- Results page has download buttons (seeded) -----------------------------


def test_results_page_has_download_buttons(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """'Download CSV' and 'Download Config' links visible."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")
    page.wait_for_load_state("networkidle")

    csv_link = page.locator("a", has_text="Download CSV")
    if csv_link.count() == 0:
        csv_link = page.locator("a", has_text="CSV")

    config_link = page.locator("a", has_text="Download Config")
    if config_link.count() == 0:
        config_link = page.locator("a", has_text="YAML")
    if config_link.count() == 0:
        config_link = page.locator("a", has_text="Config")

    assert csv_link.count() > 0, "Expected a 'Download CSV' link on results page"
    assert config_link.count() > 0, "Expected a 'Download Config' link on results page"

    expect(csv_link.first).to_be_visible()
    expect(config_link.first).to_be_visible()
