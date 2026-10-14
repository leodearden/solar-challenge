"""End-to-end tests for dark mode class propagation across pages.

Verifies that setting localStorage theme=dark and reloading causes
<html class="dark"> on every main page.
The module also toggles the theme live on a results page, to check what the toggle does to the page's charts.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

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


# The paper colour chart-renderer.js paints a chart in each theme: the computed
# background-color of the chart's first .main-svg, as _plotly_background_colors reads it.
_PAPER_COLOURS = {"light": "rgb(255, 255, 255)", "dark": "rgb(30, 41, 59)"}


def _open_in_theme(page: Page, url: str, theme: str) -> None:
    """Open url in theme: base.html's inline script reads localStorage before first paint."""
    page.add_init_script(f"localStorage.setItem('theme', '{theme}')")
    page.goto(url)


def _show_tab(page: Page, name: str) -> None:
    """Click the tab named name."""
    page.get_by_role("tab", name=name, exact=True).click()


def _toggle_theme(page: Page) -> None:
    """Click the theme toggle. The mobile sidebar's copy is display:none, so only the desktop sidebar's matches."""
    page.get_by_role("button", name="Toggle dark mode").click()


def _paper(page: Page, chart_id: str) -> Locator:
    """The element whose background-color is the paper colour of the chart in the container chart_id."""
    return page.locator(f"#{chart_id} .main-svg").first


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


# -- Toggling the theme live on a results page -----------------------------


@pytest.mark.parametrize(
    ("starting_theme", "toggled_theme"),
    [("light", "dark"), ("dark", "light")],
    ids=["light-to-dark", "dark-to-light"],
)
def test_toggling_the_theme_recolours_a_chart_whose_tab_is_hidden_once_its_tab_is_shown(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    starting_theme: str,
    toggled_theme: str,
) -> None:
    """chart-power-flow, drawn and then hidden with its tab, takes the toggled theme's colours once its tab is shown again.

    The shown tab's chart-daily-balance takes them at the toggle.
    """
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", starting_theme)

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS[starting_theme])

    _show_tab(page, "Overview")
    expect(page.locator("#chart-power-flow")).to_be_hidden()

    _toggle_theme(page)
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS[toggled_theme])

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS[toggled_theme])
