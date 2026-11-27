"""Smoke tests: verify every page loads without server errors.

Each test navigates to a route and checks the HTTP status and basic
content expectations.  These are intentionally lightweight -- they catch
regressions in routing, template rendering, and static-asset delivery.
"""

import pytest
from playwright.sync_api import Page

from tests.e2e._alpine_start import open_once_alpine_has_started
from tests.e2e._fetches_handled import (
    record_fetches_started_and_handled,
    wait_until_the_page_has_handled_every_fetch_it_started,
)


# ── Individual page-load tests ─────────────────────────────────────────


def test_dashboard_loads(page: Page, live_server: str) -> None:
    """GET / returns 200 and contains the app title."""
    response = page.goto(live_server + "/")
    assert response is not None
    assert response.status == 200
    assert page.locator("text=Solar Challenge").first.is_visible()


def test_simulate_home_loads(page: Page, live_server: str) -> None:
    """GET /simulate/home returns 200."""
    response = page.goto(live_server + "/simulate/home")
    assert response is not None
    assert response.status == 200


def test_simulate_fleet_loads(page: Page, live_server: str) -> None:
    """GET /simulate/fleet returns 200."""
    response = page.goto(live_server + "/simulate/fleet")
    assert response is not None
    assert response.status == 200


def test_scenario_builder_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/builder returns 200."""
    response = page.goto(live_server + "/scenarios/builder")
    assert response is not None
    assert response.status == 200


def test_parameter_sweep_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/sweep returns 200."""
    response = page.goto(live_server + "/scenarios/sweep")
    assert response is not None
    assert response.status == 200


def test_history_runs_loads(page: Page, live_server: str) -> None:
    """GET /history/runs returns 200."""
    response = page.goto(live_server + "/history/runs")
    assert response is not None
    assert response.status == 200


def test_404_page(page: Page, live_server: str) -> None:
    """GET /nonexistent returns the custom 404 page."""
    response = page.goto(live_server + "/nonexistent")
    assert response is not None
    assert response.status == 404
    # The custom 404 template contains both "404" and "Page Not Found"
    page.wait_for_load_state("domcontentloaded")
    text = page.text_content("body") or ""
    assert "404" in text or "Page Not Found" in text


# ── Static-asset delivery ──────────────────────────────────────────────


def test_all_pages_have_css(page: Page, live_server: str) -> None:
    """Every main page includes the compiled Tailwind stylesheet."""
    pages_to_check = ["/", "/simulate/home", "/simulate/fleet"]
    for path in pages_to_check:
        page.goto(live_server + path)
        page.wait_for_load_state("domcontentloaded")
        css_links = page.locator('link[href*="dist/style.css"]')
        assert css_links.count() > 0, (
            f"Page {path} is missing <link> to dist/style.css"
        )


# ── JS-error checks ───────────────────────────────────────────────────


@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/", id="dashboard"),
        pytest.param("/simulate/home", id="simulate-home"),
        pytest.param("/history/runs", id="history-runs"),
    ],
)
def test_page_loads_without_js_errors(
    page: Page, live_server: str, page_errors: list[str], path: str
) -> None:
    """By the time the page has loaded and Alpine has started on it, it has logged no console error and thrown no uncaught exception, each error Alpine's start threw included.

    It also waits until the page has handled the answer to each fetch it started, so an error logged or thrown handling one is read too.
    /simulate/fleet, /scenarios/sweep and /scenarios/builder are checked by the no-JS-errors tests in their own e2e files.
    """
    record_fetches_started_and_handled(page)
    open_once_alpine_has_started(page, live_server + path)
    wait_until_the_page_has_handled_every_fetch_it_started(page)

    assert page_errors == [], f"Errors on {path}: {page_errors}"
