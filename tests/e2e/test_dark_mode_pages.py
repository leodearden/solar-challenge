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

    The shown tab's chart-daily-balance, drawn in the starting theme, takes them at the toggle.
    """
    run_id, _ = seeded_home_run
    _open_in_theme(page, live_server + f"/results/home/{run_id}", starting_theme)

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS[starting_theme])

    _show_tab(page, "Overview")
    expect(page.locator("#chart-power-flow")).to_be_hidden()
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS[starting_theme])

    _toggle_theme(page)
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS[toggled_theme])

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS[toggled_theme])


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

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS["light"])
    power_flow_before = _layout_features(page, "chart-power-flow")

    _show_tab(page, "Overview")
    daily_balance_before = _layout_features(page, "chart-daily-balance")
    assert daily_balance_before["axis_titles"] and power_flow_before["range_sliders"] == 1, (
        f"the charts have no titles or range slider to keep: {daily_balance_before}, {power_flow_before}"
    )

    _toggle_theme(page)
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS["dark"])
    daily_balance_after = _layout_features(page, "chart-daily-balance")

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS["dark"])
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
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS["light"])
    release_drawings = page.evaluate_handle(_HOLD_EVERY_DRAWING_UNTIL_RELEASED)

    _show_tab(page, "Power Flow")
    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS["light"])
    _toggle_theme(page)
    release_drawings.evaluate("release => release()")

    expect(_paper(page, "chart-power-flow")).to_have_css("background-color", _PAPER_COLOURS["dark"])


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
    expect(_paper(page, "chart-daily-balance")).to_have_css("background-color", _PAPER_COLOURS["light"])
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
