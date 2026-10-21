"""End-to-end tests for dark mode class propagation across pages.

Verifies that setting localStorage theme=dark and reloading causes
<html class="dark"> on every main page.
The module also toggles the theme live on a results page, to check what the toggle does to the page's charts.
It checks that every grid, zero and polar axis line of each chart on the results and compare pages takes the
dark theme's grid colour, whether the page loads dark or is switched to dark.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._chart_tabs import open_chart_tab

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


@dataclass(frozen=True)
class _Chrome:
    """The colours of a chart's chrome: text, for its titles, legends and tick labels, and grid, for its grid, zero and polar axis lines."""

    text: str
    grid: str


# The chrome each theme draws a chart in: the color and --chart-grid of chart_panel's container,
# as getComputedStyle reads them in that theme from the chart's texts and lines.
_CHROME = {
    "light": _Chrome(text="rgb(30, 41, 59)", grid="rgb(226, 232, 240)"),
    "dark": _Chrome(text="rgb(226, 232, 240)", grid="rgb(51, 65, 85)"),
}


def _open_in_theme(page: Page, url: str, theme: str) -> None:
    """Open url in theme: base.html's inline script reads localStorage before first paint."""
    page.add_init_script(f"localStorage.setItem('theme', '{theme}')")
    page.goto(url)


def _toggle_theme(page: Page) -> None:
    """Click the theme toggle. The mobile sidebar's copy is display:none, so only the desktop sidebar's matches."""
    page.get_by_role("button", name="Toggle dark mode").click()


def _expect_drawn_in(page: Page, chart_id: str, theme: str) -> None:
    """Wait until the chart in the container chart_id shows theme's chrome: its title in the text colour and its first y grid line in the grid colour."""
    chrome = _CHROME[theme]
    expect(page.locator(f"#{chart_id} .gtitle")).to_have_css("fill", chrome.text)
    expect(page.locator(f"#{chart_id} path.ygrid").first).to_have_css("stroke", chrome.grid)


def _layout_features(page: Page, chart_id: str) -> dict[str, object]:
    """What a theme toggle must leave as it was in the chart in the container chart_id.

    These are its axis titles' texts in document order, the font family of its first x tick label
    and its number of range sliders.
    """
    features: dict[str, object] = page.locator(f"#{chart_id}").evaluate("""chart => {
        const tickLabel = chart.querySelector('.xtick text');
        if (!tickLabel) throw new Error(`Plotly chart #${chart.id} has no x tick label`);
        return {
            axis_titles: [...chart.querySelectorAll('.xtitle, .ytitle')].map(title => title.textContent),
            tick_label_font: getComputedStyle(tickLabel).fontFamily,
            range_sliders: chart.querySelectorAll('.rangeslider-container').length,
        };
    }""")
    return features


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
        "Charts leave their paper and plot area transparent, so the dark card shows through."
    )


# -- Every line of each chart in the dark theme ----------------------------

# Each grid, zero and polar axis line of each chart: the line's class, or its layer's for a line that has
# none, such as the angular axis line, and its stroke as getComputedStyle reads it.
_EVERY_GRID_AND_ZERO_LINE = r"""charts => charts.flatMap(chart => [...chart.querySelectorAll(
    '.gridlayer path, .zerolinelayer path, .radial-grid path, .angular-grid path, .angular-line path'
)].map(line => ({
    chart: chart.id,
    line: line.getAttribute('class') ?? line.parentElement.getAttribute('class'),
    stroke: getComputedStyle(line).stroke,
})))"""


@dataclass(frozen=True)
class _ChartPage:
    """A chart page of the runs a seeded-run fixture saves, and selectors of lines its charts must draw, so a check of every line cannot pass vacuously."""

    runs_fixture: str
    path: Callable[[Any], str]
    drawn_lines: tuple[str, ...]


def _show_each_chart_tab(page: Page, theme: str) -> None:
    """Show each chart tab of the page in turn, waiting until each chart in its panel has its title in theme's text colour.

    A tab's panel is an x-show child of chart_tabs' root, one per tab in the tabs' order. Alpine shows and hides
    the panels an animation frame after a tab is selected, so the panel being shown, not the tab being selected,
    says that the tab's charts are shown.
    """
    tablist = page.get_by_role("tablist", name="Chart tabs")
    panels = tablist.locator("xpath=../../*[@x-show]")
    for tab, panel in zip(tablist.get_by_role("tab").all(), panels.all(), strict=True):
        tab.click()
        expect(panel).to_be_visible()
        for chart in panel.locator("[data-chart-figure]").all():
            expect(chart.locator(".gtitle")).to_have_css("fill", _CHROME[theme].text)


@pytest.mark.parametrize("switched_to_dark", [False, True], ids=["dark-on-load", "switched-to-dark"])
@pytest.mark.parametrize(
    "chart_page",
    [
        pytest.param(
            _ChartPage(
                "seeded_home_run",
                lambda run: f"/results/home/{run[0]}",
                ("#chart-financial path.y2grid", "#chart-financial path.yzl", "#chart-financial path.y2zl"),
            ),
            id="home-results",
        ),
        pytest.param(
            _ChartPage(
                "seeded_fleet_run",
                lambda run: f"/results/fleet/{run[0]}",
                ("#chart-distribution-histograms path.y2grid", "#chart-distribution-histograms path.y3grid"),
            ),
            id="fleet-results",
        ),
        pytest.param(
            _ChartPage(
                "seeded_home_runs_pair",
                lambda runs: f"/history/compare?ids={runs[0][0]},{runs[1][0]}",
                ("#chart-comparison-radar .radial-grid path", "#chart-comparison-radar .angular-grid path"),
            ),
            id="compare",
        ),
    ],
)
def test_every_grid_and_zero_line_of_each_chart_takes_the_dark_themes_grid_colour(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    chart_page: _ChartPage,
    switched_to_dark: bool,
) -> None:
    """Secondary axes and the radar's polar grid included (tasks 735 and 737), whether the page loads dark or is switched to dark once each chart is drawn."""
    url = live_server + chart_page.path(request.getfixturevalue(chart_page.runs_fixture))
    _open_in_theme(page, url, "light" if switched_to_dark else "dark")
    if switched_to_dark:
        _show_each_chart_tab(page, "light")
        _toggle_theme(page)
    _show_each_chart_tab(page, "dark")
    for selector in chart_page.drawn_lines:
        expect(page.locator(selector).first).to_be_attached()

    lines = page.locator(".js-plotly-plot").evaluate_all(_EVERY_GRID_AND_ZERO_LINE)

    off_theme = [line for line in lines if line["stroke"] != _CHROME["dark"].grid]
    assert off_theme == [], (
        f"These chart lines are not in the dark theme's grid colour {_CHROME['dark'].grid}: {off_theme}"
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

    The shown tab's chart-daily-balance, drawn in the starting theme, takes them at the toggle.
    """
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", starting_theme)

    open_chart_tab(page, "Power Flow")
    _expect_drawn_in(page, "chart-power-flow", starting_theme)

    open_chart_tab(page, "Overview")
    expect(page.locator("#chart-power-flow")).to_be_hidden()
    _expect_drawn_in(page, "chart-daily-balance", starting_theme)

    _toggle_theme(page)
    _expect_drawn_in(page, "chart-daily-balance", toggled_theme)

    open_chart_tab(page, "Power Flow")
    _expect_drawn_in(page, "chart-power-flow", toggled_theme)


def test_toggling_the_theme_leaves_the_rest_of_each_drawn_charts_layout_as_it_was(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """A theme toggle changes only a drawn chart's colours, whether the chart is recoloured at the toggle or when its tab is next shown.

    chart-daily-balance is shown at the toggle and chart-power-flow is hidden at it, so both recolours are read.
    Each chart is compared with itself before the toggle, so the test names no title text of charts.py's.
    """
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", "light")

    open_chart_tab(page, "Power Flow")
    _expect_drawn_in(page, "chart-power-flow", "light")
    power_flow_before = _layout_features(page, "chart-power-flow")

    open_chart_tab(page, "Overview")
    daily_balance_before = _layout_features(page, "chart-daily-balance")
    assert daily_balance_before["axis_titles"] and power_flow_before["range_sliders"] == 1, (
        f"the charts have no titles or range slider to keep: {daily_balance_before}, {power_flow_before}"
    )

    _toggle_theme(page)
    _expect_drawn_in(page, "chart-daily-balance", "dark")
    daily_balance_after = _layout_features(page, "chart-daily-balance")

    open_chart_tab(page, "Power Flow")
    _expect_drawn_in(page, "chart-power-flow", "dark")
    power_flow_after = _layout_features(page, "chart-power-flow")

    assert (daily_balance_after, power_flow_after) == (daily_balance_before, power_flow_before)


# A drawing that finishes late: from now on, each Plotly.newPlot paints its chart at once but holds the
# promise chart-renderer.js waits for until the function this snippet returns is called.
_HOLD_EVERY_DRAWING_UNTIL_RELEASED = """() => {
    const newPlot = Plotly.newPlot;
    const releases = [];
    Plotly.newPlot = function () {
        return newPlot.apply(this, arguments).then(chart => new Promise(resolve => releases.push(() => resolve(chart))));
    };
    return () => releases.forEach(release => release());
}"""


def test_toggling_the_theme_while_a_chart_is_still_drawing_recolours_it_once_the_drawing_finishes(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """chart-power-flow, painted in the starting theme but still drawing at the toggle, takes the toggled theme's colours once the drawing finishes.

    The toggle recolours only the charts chart-renderer.js has finished drawing, so a chart still drawing at it must be recoloured once drawn.
    """
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", "light")
    _expect_drawn_in(page, "chart-daily-balance", "light")
    release_drawings = page.evaluate_handle(_HOLD_EVERY_DRAWING_UNTIL_RELEASED)

    open_chart_tab(page, "Power Flow")
    _expect_drawn_in(page, "chart-power-flow", "light")
    _toggle_theme(page)
    release_drawings.evaluate("release => release()")

    _expect_drawn_in(page, "chart-power-flow", "dark")


_FAILED_RECOLOURING = "the recolouring failed after Plotly.relayout returned"
_REJECT_THE_RECOLOURING_OF = """([chartId, failure]) => {
    const relayout = Plotly.relayout;
    Plotly.relayout = function (container) {
        if (container.id === chartId) return Promise.reject(new Error(failure));
        return relayout.apply(this, arguments);
    };
}"""


def test_a_chart_whose_recolouring_fails_after_plotly_relayout_returns_logs_one_error_naming_its_id(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
    page_errors: list[str],
) -> None:
    """Plotly.relayout returns a promise, which rejects when a recolouring fails; that failure is one error naming the chart, not an uncaught rejection."""
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", "light")
    _expect_drawn_in(page, "chart-daily-balance", "light")
    page.evaluate(_REJECT_THE_RECOLOURING_OF, ["chart-daily-balance", _FAILED_RECOLOURING])

    with page.expect_console_message(lambda message: "chart-daily-balance" in message.text, timeout=5_000):
        _toggle_theme(page)

    errors_naming_the_chart = [error for error in page_errors if "chart-daily-balance" in error]
    uncaught_failures = [
        error for error in page_errors if _FAILED_RECOLOURING in error and "chart-daily-balance" not in error
    ]
    assert (len(errors_naming_the_chart), uncaught_failures) == (1, []), (
        f"expected one error naming 'chart-daily-balance' and no other carrying {_FAILED_RECOLOURING!r}, "
        f"but the page logged: {page_errors}"
    )
