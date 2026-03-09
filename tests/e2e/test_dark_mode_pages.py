"""End-to-end tests for dark mode class propagation across pages.

Verifies that setting localStorage theme=dark and reloading causes
<html class="dark"> on every main page.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e


def _enable_dark_mode_and_reload(page: Page, url: str) -> None:
    """Navigate to url, set localStorage theme to dark, then reload."""
    page.goto(url)
    page.wait_for_load_state("domcontentloaded")
    page.evaluate("() => localStorage.setItem('theme', 'dark')")
    page.reload()
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)


def _assert_dark_class_on_html(page: Page, page_name: str) -> None:
    """Assert that <html> element has the 'dark' class."""
    html_class = page.evaluate("() => document.documentElement.classList.contains('dark')")
    assert html_class is True, (
        f"Expected <html class='dark'> on {page_name}, "
        f"but dark class is missing"
    )


# -- Dark mode on /simulate/home -------------------------------------------


def test_dark_mode_simulate_home(page: Page, live_server: str) -> None:
    """Set localStorage theme=dark, reload -> <html class='dark'>."""
    _enable_dark_mode_and_reload(page, live_server + "/simulate/home")
    _assert_dark_class_on_html(page, "/simulate/home")


# -- Dark mode on /simulate/fleet ------------------------------------------


def test_dark_mode_simulate_fleet(page: Page, live_server: str) -> None:
    """Same check on /simulate/fleet."""
    _enable_dark_mode_and_reload(page, live_server + "/simulate/fleet")
    _assert_dark_class_on_html(page, "/simulate/fleet")


# -- Dark mode on /scenarios/builder ----------------------------------------


def test_dark_mode_scenario_builder(page: Page, live_server: str) -> None:
    """Same check on /scenarios/builder."""
    _enable_dark_mode_and_reload(page, live_server + "/scenarios/builder")
    _assert_dark_class_on_html(page, "/scenarios/builder")


# -- Dark mode on /history/runs --------------------------------------------


def test_dark_mode_history_page(page: Page, live_server: str) -> None:
    """Same check on /history/runs."""
    _enable_dark_mode_and_reload(page, live_server + "/history/runs")
    _assert_dark_class_on_html(page, "/history/runs")


# -- Dark mode on results page charts --------------------------------------


def test_dark_mode_results_page_charts(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Plotly chart backgrounds should not be white (#ffffff) in dark mode."""
    run_id, _ = seeded_home_run
    _enable_dark_mode_and_reload(page, live_server + f"/results/home/{run_id}")
    _assert_dark_class_on_html(page, f"/results/home/{run_id}")

    # Wait for Plotly charts to render
    page.wait_for_timeout(2000)

    # Check Plotly .bg rect fill color
    bg_fill = page.evaluate("""() => {
        const bgRect = document.querySelector('.plot-container .bg');
        if (!bgRect) return null;
        return bgRect.getAttribute('fill');
    }""")

    if bg_fill is None:
        pytest.skip("No Plotly .bg element found on results page")

    # In dark mode the chart background should NOT be pure white
    assert bg_fill.lower() not in ("#ffffff", "#fff", "rgb(255, 255, 255)", "white"), (
        f"Plotly chart background is white ({bg_fill}) in dark mode. "
        f"Charts should use a dark background color when dark mode is active."
    )
