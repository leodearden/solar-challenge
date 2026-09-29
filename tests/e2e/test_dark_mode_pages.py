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


def _plotly_background_colors(page: Page) -> list[str]:
    """Collect each Plotly chart's painted paper color and every .bg rect fill."""
    colors: list[str] = page.evaluate("""() => {
        const colors = [];
        for (const chart of document.querySelectorAll('.js-plotly-plot')) {
            const paper = chart.querySelector('.main-svg');
            if (!paper) throw new Error(`Plotly chart #${chart.id} has no .main-svg`);
            colors.push(getComputedStyle(paper).backgroundColor);
            for (const rect of chart.querySelectorAll('.bg')) {
                colors.push(getComputedStyle(rect).fill);
            }
        }
        return colors;
    }""")
    return colors


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
    """No Plotly chart on the results page's opening tab is painted white in dark mode.

    chart-renderer.js defers the other tabs' charts until shown, so they are not checked.
    """
    run_id, _ = seeded_home_run
    _enable_dark_mode_and_reload(page, live_server + f"/results/home/{run_id}")
    _assert_dark_class_on_html(page, f"/results/home/{run_id}")

    expect(page.locator(".plot-container .bg").first).to_be_attached()

    backgrounds = _plotly_background_colors(page)

    # In dark mode no chart background should be pure white
    assert "rgb(255, 255, 255)" not in backgrounds, (
        f"Plotly chart background is white in dark mode: {backgrounds}. "
        f"Charts should use a dark background color when dark mode is active."
    )
