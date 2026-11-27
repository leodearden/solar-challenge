"""End-to-end tests for the Compare page (/history/compare).

Verifies page loading, metrics table, delta columns, color coding,
the comparison charts, and the empty state shown when no IDs are given.
The charts are the Energy Totals bar chart and the Efficiency Ratios
radar chart, each in a tab of its own. The bar chart's tab is shown on
load, so the bar chart is drawn by the page's load event, and is as
wide as its container; the radar chart's tab is hidden on load, so its
chart is drawn only once the tab is shown, and then fills its
container; both charts draw without errors, with titles and legends
legible in light and dark mode, and the radar chart's tick labels
legible on its disc. A drawn chart in a shown tab is recoloured as a
theme change is announced.
Uses seeded run pair fixtures.
"""

import re
from collections.abc import Sequence

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._chart_tabs import show_chart_tab
from tests.e2e._chart_widths import charts_not_as_wide_as_their_containers

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
# The radar's radial tick labels, each with its fill and the disc it sits on as the disc shows: its fill at
# its fill-opacity over the first opaque background behind the chart. Plotly paints a transparent disc as
# fill rgb(0, 0, 0) with fill-opacity 0.
_RADIAL_TICK_LABELS_ON_THE_DISC = r"""chart => {
    const channels = colour => colour.match(/[\d.]+/g).map(Number);
    let backdrop = null;
    for (let el = chart.querySelector('.main-svg'); el && !backdrop; el = el.parentElement) {
        const rgba = channels(getComputedStyle(el).backgroundColor);
        if (rgba.length === 3 || rgba[3] === 1) backdrop = rgba.slice(0, 3);
    }
    if (!backdrop) throw new Error(`No opaque background lies behind #${chart.id}`);
    const discStyle = getComputedStyle(chart.querySelector('.plotbg path'));
    const [red, green, blue, alpha = 1] = channels(discStyle.fill);
    const opacity = alpha * Number(discStyle.fillOpacity);
    const disc = [red, green, blue].map((channel, i) => channel * opacity + backdrop[i] * (1 - opacity));
    return [...chart.querySelectorAll('.radial-axis text')].map(label => ({
        text: label.textContent,
        fill: channels(getComputedStyle(label).fill).slice(0, 3),
        disc,
    }));
}"""


def _relative_luminance(rgb: Sequence[float]) -> float:
    """The WCAG 2 relative luminance of the sRGB colour whose red, green and blue, each 0 to 255, are rgb."""
    linear = (c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in (channel / 255 for channel in rgb))
    return sum(weight * channel for weight, channel in zip(_LUMINANCE_WEIGHTS, linear))


def _contrast_ratio(foreground: Sequence[float], background: Sequence[float]) -> float:
    """The WCAG 2 contrast ratio of two sRGB colours, each given as its red, green and blue, 0 to 255."""
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_the_energy_totals_chart_drawn_on_load_is_as_wide_as_its_container(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """The bar chart, drawn on load in Energy Totals, the tab shown on load, is as wide as its container."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()

    assert charts_not_as_wide_as_their_containers(page, [_BAR_CHART_ID]) == []


_RECORD_THE_CHARTS_DRAWN_BY_LOAD = """window.addEventListener('load', () => {
    window.__chartsDrawnByLoad = [...document.querySelectorAll('[data-chart-figure]')]
        .filter(container => container.classList.contains('js-plotly-plot'))
        .map(container => container.id);
});"""


def test_the_energy_totals_chart_in_the_tab_shown_on_load_is_drawn_by_the_pages_load_event(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """By the window's load event, which page.goto waits for, the bar chart in the tab shown on load is drawn, and the radar chart in the hidden tab is not."""
    page.add_init_script(_RECORD_THE_CHARTS_DRAWN_BY_LOAD)
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")

    assert page.evaluate("() => window.__chartsDrawnByLoad") == [_BAR_CHART_ID]


# Returns the title fill of the chart container it is called on, and records on window, from a theme-changed listener
# registered after chart-renderer.js's own, the title's fill and the container's colour as the change is announced.
_RECORD_THE_TITLE_AS_THE_THEME_CHANGE_IS_ANNOUNCED = """(container) => {
    const titleFill = () => getComputedStyle(container.querySelector('.gtitle')).fill;
    document.addEventListener('theme-changed', () => {
        window.__titleAsTheThemeChangeIsAnnounced = {fill: titleFill(), containerColour: getComputedStyle(container).color};
    });
    return titleFill();
}"""


def test_a_drawn_chart_in_a_shown_tab_is_recoloured_as_the_theme_change_is_announced(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """As the theme toggle announces theme-changed, the bar chart's title already takes its container's new colour."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()
    light_fill = page.locator(_BAR_CHART).evaluate(_RECORD_THE_TITLE_AS_THE_THEME_CHANGE_IS_ANNOUNCED)

    page.get_by_role("button", name="Toggle dark mode").filter(visible=True).click()

    announced = page.evaluate("() => window.__titleAsTheThemeChangeIsAnnounced")
    assert announced is not None, "the theme-changed listener registered after chart-renderer.js's own never ran"
    assert announced["fill"] == announced["containerColour"] != light_fill, (
        f"expected the title's fill, as theme-changed was announced, to be its container's colour then, "
        f"which differs from the light fill {light_fill!r}; read {announced}"
    )


def test_compare_radar_chart_in_a_hidden_tab_is_drawn_only_once_its_tab_is_shown_and_fills_its_container(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """The radar chart, in the Efficiency Ratios tab hidden on load, is not drawn until its tab is shown, and is then as wide as its container."""
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}", wait_until="domcontentloaded")
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


# The chart each tab shows, the tab selected on load last.
_CHART_IDS_BY_TAB = {
    "Efficiency Ratios": (_RADAR_CHART_ID,),
    "Energy Totals": (_BAR_CHART_ID,),
}


def test_compare_tabs_each_show_only_their_own_charts(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
) -> None:
    """Clicking each chart tab selects it alone and shows only its own chart, drawn by Plotly.

    Energy Totals is selected on load, so it is clicked last: only then does its click have to move
    the selection.
    """
    (id1, _), (id2, _) = seeded_home_runs_pair
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    selected_tab = page.get_by_role("tab", selected=True)
    last_listed_tab = list(_CHART_IDS_BY_TAB)[-1]
    expect(
        selected_tab,
        f"expected the tab selected on load to be {last_listed_tab!r}, the last in _CHART_IDS_BY_TAB",
    ).to_have_accessible_name(last_listed_tab)

    for tab_name, chart_ids in _CHART_IDS_BY_TAB.items():
        show_chart_tab(page, tab_name, chart_ids)
        expect(selected_tab).to_have_accessible_name(tab_name)
        expect(page.locator(".js-plotly-plot").filter(visible=True)).to_have_count(len(chart_ids))


# The themes a legibility check reads the charts in: dark mode on load, switched to dark mode once the
# first chart is drawn, or light throughout.
_IN_EACH_THEME = pytest.mark.parametrize(
    ("dark_on_load", "switched_to_dark"),
    [
        pytest.param(False, False, id="light"),
        pytest.param(True, False, id="dark-on-load"),
        pytest.param(False, True, id="switched-to-dark"),
    ],
)


def _show_both_charts(
    page: Page, live_server: str, runs: list[tuple[str, str]], dark_on_load: bool, switched_to_dark: bool
) -> None:
    """Open the compare page of runs and show the radar chart's tab, so both charts are drawn.

    The page is in dark mode when it loads if dark_on_load, and is switched to dark mode once the bar chart is drawn if switched_to_dark.
    """
    (id1, _), (id2, _) = runs
    page.goto(live_server + f"/history/compare?ids={id1},{id2}")
    if dark_on_load:
        page.evaluate("() => localStorage.setItem('theme', 'dark')")
        page.reload()
    expect(page.locator(f"{_BAR_CHART}.js-plotly-plot")).to_be_visible()
    if switched_to_dark:
        page.get_by_role("button", name="Toggle dark mode").filter(visible=True).click()
    show_chart_tab(page, "Efficiency Ratios", (_RADAR_CHART_ID,))


@_IN_EACH_THEME
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
    _show_both_charts(page, live_server, seeded_home_runs_pair, dark_on_load, switched_to_dark)

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


@_IN_EACH_THEME
def test_compare_radar_tick_labels_are_legible_on_its_disc(
    page: Page,
    live_server: str,
    seeded_home_runs_pair: list[tuple[str, str]],
    dark_on_load: bool,
    switched_to_dark: bool,
) -> None:
    """Each radial tick label reaches WCAG AA's 4.5:1 contrast with the disc it sits on, as the disc shows: its fill over the first opaque background behind the chart (task 737)."""
    _show_both_charts(page, live_server, seeded_home_runs_pair, dark_on_load, switched_to_dark)

    labels = page.locator(_RADAR_CHART).evaluate(_RADIAL_TICK_LABELS_ON_THE_DISC)

    assert [label["text"] for label in labels] == ["0", "20", "40", "60", "80", "100"], (
        f"Expected the radar's radial tick labels 0 to 100; read {labels}"
    )
    illegible = [
        (label["text"], label["fill"], [round(channel) for channel in label["disc"]], round(ratio, 2))
        for label in labels
        if (ratio := _contrast_ratio(label["fill"], label["disc"])) < _WCAG_AA_CONTRAST
    ]
    assert illegible == [], (
        f"These radial tick labels, as (text, fill, disc, contrast), fall short of WCAG AA's "
        f"{_WCAG_AA_CONTRAST}:1 contrast with the radar's disc: {illegible}"
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
