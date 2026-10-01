"""End-to-end tests for the full simulation submit-to-results lifecycle.

Verifies API submission, progress tracker appearance, completion, navigation
to results, and stat cards.

Note: test_simulation_completes_and_shows_view_results makes a real
PVGIS API call and is marked slow.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._home_form import submit_two_day_run

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
                days: 1,
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


# -- Progress tracker appears after submit ---------------------------------


def test_progress_tracker_appears_after_submit(
    page: Page,
    live_server: str,
) -> None:
    """The 'Simulation Progress' tracker appears once the server accepts the run."""
    page.goto(live_server + "/simulate/home")
    response = submit_two_day_run(page)
    assert response.status == 201, response.text()

    expect(
        page.get_by_role("heading", name="Simulation Progress", exact=True)
    ).to_be_visible()


# -- Simulation completes and shows View Results (slow, real PVGIS) --------


@pytest.mark.slow
def test_simulation_completes_and_shows_view_results(
    page: Page,
    live_server: str,
) -> None:
    """'View Results' link appears within 120s (real PVGIS call)."""
    page.goto(live_server + "/simulate/home")
    response = submit_two_day_run(page)
    assert response.status == 201, response.text()

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
    response = submit_two_day_run(page)
    assert response.status == 201, response.text()

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
    """The results page shows the Total Generation and Total Demand stat cards."""
    run_id, _ = seeded_home_run
    page.goto(live_server + f"/results/home/{run_id}")

    for label in ("Total Generation", "Total Demand"):
        expect(page.get_by_text(label, exact=True)).to_be_visible()
