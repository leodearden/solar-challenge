"""End-to-end tests for the full simulation submit-to-results lifecycle.

Verifies API submission, progress tracker appearance, completion, navigation
to results, and stat cards.
"""

from playwright.sync_api import Page, expect

from tests.e2e._home_form import submit_two_day_run


# -- Submit home simulation via API ----------------------------------------


def test_submit_home_simulation_via_api(
    page: Page,
    live_server: str,
) -> None:
    """POST to /api/simulate/home via fetch returns 201 with a job_id and a run_id."""
    page.goto(live_server + "/simulate/home")

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

    assert status == 201, f"Expected 201, got {status}: {body}"
    assert body.get("job_id"), f"Expected a job_id in the response, got {body}"
    assert body.get("run_id"), f"Expected a run_id in the response, got {body}"


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


# -- Simulation completes and shows View Results ---------------------------


def test_simulation_completes_and_shows_view_results(
    page: Page,
    live_server: str,
) -> None:
    """'View Results' link appears once the run's job completes."""
    page.goto(live_server + "/simulate/home")
    response = submit_two_day_run(page)
    assert response.status == 201, response.text()

    # Wait for "View Results" link to appear
    view_results = page.locator("a", has_text="View Results")
    expect(view_results).to_be_visible(timeout=120_000)


# -- View Results link navigates to results page ---------------------------


def test_view_results_link_navigates_to_results_page(
    page: Page,
    live_server: str,
) -> None:
    """Click 'View Results' -> the URL is the run's results page, /results/<run_id>."""
    page.goto(live_server + "/simulate/home")
    response = submit_two_day_run(page)
    assert response.status == 201, response.text()
    # Read before the click: the browser drops this page's response bodies when it navigates away
    run_id = response.json()["run_id"]

    # Wait for "View Results" link
    view_results = page.locator("a", has_text="View Results")
    expect(view_results).to_be_visible(timeout=120_000)

    view_results.click()
    page.wait_for_load_state("domcontentloaded")

    assert page.url == f"{live_server}/results/{run_id}"


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
