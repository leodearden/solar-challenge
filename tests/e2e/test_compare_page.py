"""End-to-end tests for the Compare page (/history/compare).

Verifies page loading, metrics table, delta columns, color coding,
the comparison charts, and the empty state shown when no IDs are given.
The charts are the Energy Totals bar chart and the Efficiency Ratios
radar chart, each in a tab of its own. The bar chart's tab is shown on
load, and the bar chart ends as wide as its container once the page
settles; the radar chart's tab is hidden on load, so its chart is drawn
only once the tab is shown, and then fills its container; both charts
draw without errors, with titles and legends legible in light and dark
mode.
Uses seeded run pair fixtures.
"""

import re
from collections.abc import Sequence

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._chart_tabs import show_chart_tab
from tests.e2e._chart_widths import charts_not_as_wide_as_their_containers

pytestmark = pytest.mark.e2e

_BAR_CHART_ID = "chart-comparison-bar"
_BAR_CHART = f"#{_BAR_CHART_ID}"
_RADAR_CHART_ID = "chart-comparison-radar"
_RADAR_CHART = f"#{_RADAR_CHART_ID}"


# -- Compare page loads with valid IDs --------------------------------------


def test_compare_page_loads_with_valid_ids(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """/history/compare?ids=id1,id2 -> 200, 'Compare Runs' heading."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    response = page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("h1, h2", has_text="Compare")
    expect(heading.first).to_be_visible()


# -- Compare page shows metrics table --------------------------------------


def test_compare_page_shows_metrics_table(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """The 'Key Metrics' heading and the Total Generation, Total Demand and Self-Consumption rows are shown."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")

    expect(page.get_by_role("heading", name="Key Metrics", exact=True)).to_be_visible()
    for metric in ("Total Generation", "Total Demand", "Self-Consumption"):
        expect(page.get_by_role("cell", name=metric, exact=True)).to_be_visible()


# -- Delta column exists ---------------------------------------------------


def test_compare_page_delta_column_exists(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Comparing two runs shows both a 'Delta' and a '% Change' column header."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")

    for header in ("Delta", "% Change"):
        expect(
            page.get_by_role("columnheader", name=header, exact=True)
        ).to_be_visible()


# -- Compare delta coloring direction (potential bug) -----------------------


def test_compare_delta_coloring_direction(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Grid Import's positive Delta and % Change are styled red: a higher grid import is worse.

    The seeded pair's grid import rises from its first run to its second, so both cells are positive.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")

    grid_import_row = page.get_by_role("row").filter(has_text="Grid Import")
    positive_deltas = grid_import_row.get_by_role("cell").filter(has_text="+")
    expect(positive_deltas).to_have_count(2)
    for delta in positive_deltas.all():
        expect(delta).to_have_class(re.compile(r"\btext-red-"))


# -- The comparison charts ----------------------------------------------------

_WCAG_AA_CONTRAST = 4.5
_LUMINANCE_WEIGHTS = (0.2126, 0.7152, 0.0722)
_TITLES_AND_LEGENDS_WITH_THEIR_BACKDROPS = r"""charts => charts.flatMap(chart => {
    let backdrop = null;
    for (let el = chart.querySelector('.main-svg'); el && !backdrop; el = el.parentElement) {
        const rgba = getComputedStyle(el).backgroundColor.match(/[\d.]+/g).map(Number);
        if (rgba.length === 3 || rgba[3] === 1) backdrop = rgba.slice(0, 3);
    }
    return [...chart.querySelectorAll('.gtitle, .legendtext')].map(text => ({
        chart: '#' + chart.id,
        text: text.textContent,
        fill: getComputedStyle(text).fill.match(/[\d.]+/g).map(Number).slice(0, 3),
        backdrop,
    }));
})"""


def _relative_luminance(rgb: Sequence[float]) -> float:
    """The WCAG 2 relative luminance of the sRGB colour whose red, green and blue, each 0 to 255, are rgb."""
    linear = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (channel / 255 for channel in rgb))
    return sum(weight * channel for weight, channel in zip(_LUMINANCE_WEIGHTS, linear))


def _contrast_ratio(foreground: Sequence[float], background: Sequence[float]) -> float:
    """The WCAG 2 contrast ratio of two sRGB colours, each given as its red, green and blue, 0 to 255."""
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_energy_totals_chart_is_as_wide_as_its_container_once_the_page_settles(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """The bar chart, in Energy Totals, the tab shown on load, is drawn while base.html's main column slides in, and ends as wide as its container."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()

    assert charts_not_as_wide_as_their_containers(page, [_BAR_CHART_ID]) == []


def test_compare_radar_chart_in_a_hidden_tab_is_drawn_only_once_its_tab_is_shown_and_fills_its_container(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """The radar chart, in the Efficiency Ratios tab hidden on load, is not drawn until its tab is shown, and is then as wide as its container."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()
    expect(page.locator(f"{_RADAR_CHART}.js-plotly-plot")).to_have_count(0)

    show_chart_tab(page, "Efficiency Ratios", (_RADAR_CHART_ID,))

    assert charts_not_as_wide_as_their_containers(page, [_RADAR_CHART_ID]) == []


def test_compare_page_shows_both_chart_tabs_without_errors(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
    page_errors: list[str],
) -> None:
    """Loading the page and showing each of its chart tabs logs no console error and throws no uncaught exception.

    chart-renderer.js draws the radar chart only once its tab is shown, so both tabs are shown.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    url = f"/history/compare?ids={id1},{id2}"
    page.goto(live_server + url)
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()
    show_chart_tab(page, "Efficiency Ratios", (_RADAR_CHART_ID,))
    show_chart_tab(page, "Energy Totals", (_BAR_CHART_ID,))

    assert page_errors == [], f"Errors on {url}: {page_errors}"


@pytest.mark.parametrize(
    ("dark_on_load", "switched_to_dark"),
    [
        pytest.param(False, False, id="light"),
        pytest.param(True, False, id="dark-on-load"),
        pytest.param(False, True, id="switched-to-dark"),
    ],
)
def test_compare_chart_titles_and_legends_are_legible(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
    dark_on_load: bool,
    switched_to_dark: bool,
) -> None:
    """Each chart's title and legend texts reach WCAG AA's 4.5:1 contrast with the first opaque background behind the chart.

    The page is in dark mode when it loads, or is switched to dark mode once its first chart is drawn, or stays light.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    if dark_on_load:
        page.evaluate("() => localStorage.setItem('theme', 'dark')")
        page.reload()
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()
    if switched_to_dark:
        page.get_by_role("button", name="Toggle dark mode").filter(visible=True).click()
    show_chart_tab(page, "Efficiency Ratios", (_RADAR_CHART_ID,))

    texts = page.locator(".js-plotly-plot").evaluate_all(_TITLES_AND_LEGENDS_WITH_THEIR_BACKDROPS)

    assert {text["chart"] for text in texts} >= {_BAR_CHART, _RADAR_CHART}, (
        f"Expected title or legend texts in both charts; read {texts}"
    )
    charts_without_a_backdrop = sorted({text["chart"] for text in texts if text["backdrop"] is None})
    assert charts_without_a_backdrop == [], (
        f"No opaque background lies behind these charts, so their texts' contrast cannot be measured: "
        f"{charts_without_a_backdrop}"
    )
    illegible = [
        (text["chart"], text["text"], text["fill"], text["backdrop"], round(ratio, 2))
        for text in texts
        if (ratio := _contrast_ratio(text["fill"], text["backdrop"])) < _WCAG_AA_CONTRAST
    ]
    assert illegible == [], (
        f"These chart texts, as (chart, text, fill, backdrop, contrast), fall short of WCAG AA's "
        f"{_WCAG_AA_CONTRAST}:1 contrast with the background behind their chart: {illegible}"
    )


# -- Compare without IDs shows empty state ---------------------------------


def test_compare_without_ids_shows_empty_state(
    page: Page,
    live_server: str,
) -> None:
    """/history/compare without ids shows the no-runs-selected state, whose link leads to run history."""
    response = page.goto(live_server + "/history/compare")
    assert response is not None
    assert response.status == 200
    expect(page).to_have_url(live_server + "/history/compare")

    expect(page.get_by_role("heading", name="No Runs Selected")).to_be_visible()

    page.get_by_role("link", name="Go to Run History").click()
    expect(page).to_have_url(live_server + "/history/runs")
