"""End-to-end tests of the chart tabs' colours on the pages whose tabs components/macros.html's chart_tabs draws.

No tab's colours fade in as the page loads, and a click still fades the selected
colours from the tab that had them to the clicked tab alone.
"""

from collections.abc import Callable
from typing import Any

import pytest
from playwright.sync_api import Page, expect


def _results_home_path(run: tuple[str, str]) -> str:
    run_id, _ = run
    return f"/results/home/{run_id}"


def _results_fleet_path(run: tuple[str, str]) -> str:
    run_id, _ = run
    return f"/results/fleet/{run_id}"


def _history_compare_path(runs: list[tuple[str, str]]) -> str:
    return "/history/compare?ids=" + ",".join(run_id for run_id, _ in runs)


# Each page with chart tabs: the fixture seeding the runs it shows, its path given that fixture's value, and its tabs'
# names, the opening tab first.
_PAGES_WITH_CHART_TABS = [
    pytest.param(
        "seeded_home_run",
        _results_home_path,
        ("Overview", "Power Flow", "Battery & Finance", "Analysis"),
        id="results-home",
    ),
    pytest.param(
        "seeded_fleet_run",
        _results_fleet_path,
        ("Aggregate", "Per-Home", "Distributions"),
        id="results-fleet",
    ),
    pytest.param(
        "seeded_home_runs_pair",
        _history_compare_path,
        ("Energy Totals", "Efficiency Ratios"),
        id="history-compare",
    ),
]

# An init script. window.tabProbe.colours() reads each chart tab's bottom border and text colour by tab name, and
# .fading() the CSS transitions running on the chart tabs. It records two readings in window.tabProbe.load:
# - colours_before_alpine, at readystatechange 'interactive', which fires before any deferred script, so before Alpine.
#   The read makes the browser compute the tabs' style, so any colour Alpine then changes starts a transition;
# - fading_as_alpine_starts, at Alpine's alpine:initialized event, once Alpine has applied every binding.
_RECORD_HOW_THE_CHART_TABS_LOAD = """(() => {
    const tabs = () => [...document.querySelectorAll('[role="tablist"][aria-label="Chart tabs"] [role="tab"]')];
    const name = tab => tab.textContent.trim();
    const colours = () => Object.fromEntries(tabs().map(tab => {
        const style = getComputedStyle(tab);
        return [name(tab), {border: style.borderBottomColor, text: style.color}];
    }));
    const fading = () => document.getAnimations()
        .filter(animation => animation instanceof CSSTransition && tabs().includes(animation.effect.target))
        .map(transition => ({tab: name(transition.effect.target), property: transition.transitionProperty}));
    window.tabProbe = {colours, fading, load: {}};
    document.addEventListener('readystatechange', () => {
        if (document.readyState === 'interactive') window.tabProbe.load.colours_before_alpine = colours();
    });
    document.addEventListener('alpine:initialized', () => {
        window.tabProbe.load.fading_as_alpine_starts = fading();
    });
})()"""

# For locator.evaluate: click the tab in the page and read the chart tabs' transitions. Alpine applies the click in a
# microtask, which runs before this await resumes, so the read falls in the click's own task, before a frame can end a fade.
_CLICK_AND_READ_THE_FADING = """async tab => {
    tab.click();
    await Promise.resolve();
    return window.tabProbe.fading();
}"""

_NO_CHART_TAB_FADING = "() => window.tabProbe.fading().length === 0"


def _open_with_the_chart_tabs_recorded(page: Page, url: str, opening_tab: str) -> None:
    """Open url with _RECORD_HOW_THE_CHART_TABS_LOAD installed; return once Alpine has selected opening_tab and no chart tab is fading."""
    page.add_init_script(_RECORD_HOW_THE_CHART_TABS_LOAD)
    page.goto(url)
    expect(page.get_by_role("tab", selected=True)).to_have_accessible_name(opening_tab)
    page.wait_for_function(_NO_CHART_TAB_FADING)


def _chart_tab_colours(page: Page) -> dict[str, dict[str, str]]:
    """Each chart tab's bottom border colour and text colour, keyed by the tab's name."""
    return page.evaluate("() => window.tabProbe.colours()")


@pytest.mark.parametrize(("seeding_fixture_name", "path_of", "tab_names"), _PAGES_WITH_CHART_TABS)
def test_a_page_paints_its_chart_tabs_in_their_colours_before_alpine_starts_so_none_fades_in(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    seeding_fixture_name: str,
    path_of: Callable[[Any], str],
    tab_names: tuple[str, ...],
) -> None:
    """Before Alpine starts, each chart tab already has the colours it keeps once the page has settled, and no tab's colours are fading as Alpine starts."""
    url = live_server + path_of(request.getfixturevalue(seeding_fixture_name))
    _open_with_the_chart_tabs_recorded(page, url, tab_names[0])
    assert page.evaluate("() => window.tabProbe.load") == {
        "colours_before_alpine": _chart_tab_colours(page),
        "fading_as_alpine_starts": [],
    }


@pytest.mark.parametrize(("seeding_fixture_name", "path_of", "tab_names"), _PAGES_WITH_CHART_TABS)
def test_a_click_on_a_chart_tab_fades_the_selected_colours_from_the_tab_that_had_them_to_it_alone(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    seeding_fixture_name: str,
    path_of: Callable[[Any], str],
    tab_names: tuple[str, ...],
) -> None:
    """Each click fades exactly two tabs, the one selected before and the one clicked, and leaves the clicked tab alone in the colours the opening tab loaded with. The opening tab is clicked last, so its click too has to move the selection. A ternary-string :class fails it: Alpine's string form adds and undoes only the classes it added itself, so it never removes one the server drew, while the object form chart_tabs binds removes a false key's classes."""
    url = live_server + path_of(request.getfixturevalue(seeding_fixture_name))
    opening_tab, *other_tabs = tab_names
    _open_with_the_chart_tabs_recorded(page, url, opening_tab)
    loaded = _chart_tab_colours(page)
    selected, unselected = loaded[opening_tab], loaded[other_tabs[0]]
    assert selected != unselected and all(loaded[name] == unselected for name in other_tabs), (
        f"expected the opening tab {opening_tab!r} alone in the selected colours on load: {loaded}"
    )
    previously_selected = opening_tab
    for clicked in (*other_tabs, opening_tab):
        fading = page.get_by_role("tab", name=clicked, exact=True).evaluate(_CLICK_AND_READ_THE_FADING)
        page.wait_for_function(_NO_CHART_TAB_FADING)
        assert ({transition["tab"] for transition in fading}, _chart_tab_colours(page)) == (
            {previously_selected, clicked},
            {name: selected if name == clicked else unselected for name in tab_names},
        ), f"after a click on the {clicked!r} tab"
        previously_selected = clicked
