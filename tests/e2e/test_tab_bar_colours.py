"""End-to-end tests of the tabs' colours on the pages whose tab bars components/macros.html's tab_bar draws.

No tab's colours fade in as the page loads, and a click still fades the selected
colours from the tab that had them to the clicked tab alone.
"""

import pytest
from playwright.sync_api import Page, expect

from tests.e2e._tab_bar_pages import PAGES_WITH_TAB_BARS, TabBarPage

# An init script. window.tabProbe.colours() reads each tab's bottom border and text colour by tab name, .fading() the
# CSS transitions running on the tabs, and .finishFading() finishes those transitions, which moves each tab to the
# colours it settles in without waiting for frames; each page has one tablist.
# It records two readings in window.tabProbe.load:
# - colours_before_alpine, at readystatechange 'interactive', which fires before any deferred script, so before Alpine.
#   The read makes the browser compute the tabs' style, so any colour Alpine then changes starts a transition;
# - fading_as_alpine_starts, at Alpine's alpine:initialized event, once Alpine has applied every binding.
_RECORD_HOW_THE_TABS_LOAD = """(() => {
    const tabs = () => [...document.querySelectorAll('[role="tablist"] [role="tab"]')];
    const name = tab => tab.textContent.trim();
    const colours = () => Object.fromEntries(tabs().map(tab => {
        const style = getComputedStyle(tab);
        return [name(tab), {border: style.borderBottomColor, text: style.color}];
    }));
    const tabTransitions = () => document.getAnimations()
        .filter(animation => animation instanceof CSSTransition && tabs().includes(animation.effect.target));
    const fading = () => tabTransitions()
        .map(transition => ({tab: name(transition.effect.target), property: transition.transitionProperty}));
    const finishFading = () => tabTransitions().forEach(transition => transition.finish());
    window.tabProbe = {colours, fading, finishFading, load: {}};
    document.addEventListener('readystatechange', () => {
        if (document.readyState === 'interactive') window.tabProbe.load.colours_before_alpine = colours();
    });
    document.addEventListener('alpine:initialized', () => {
        window.tabProbe.load.fading_as_alpine_starts = fading();
    });
})()"""

# For locator.evaluate: click the tab in the page and read the tabs' transitions. Alpine applies the click in a
# microtask, which runs before this await resumes, so the read falls in the click's own task, before a frame can end a fade.
_CLICK_AND_READ_THE_FADING = """async tab => {
    tab.click();
    await Promise.resolve();
    return window.tabProbe.fading();
}"""


def _open_with_the_tabs_recorded(page: Page, url: str, opening_tab: str) -> None:
    """Open url with _RECORD_HOW_THE_TABS_LOAD installed; return once opening_tab is the selected tab."""
    page.add_init_script(_RECORD_HOW_THE_TABS_LOAD)
    page.goto(url)
    expect(page.get_by_role("tab", selected=True)).to_have_accessible_name(opening_tab)


def _finish_the_fading_and_read_the_tab_colours(page: Page) -> dict[str, dict[str, str]]:
    """Finish every CSS transition on a tab, then return each tab's bottom border colour and text colour, keyed by the tab's name. Finishing moves a fade under way to its end colours, so the read needs none of the frames a loaded host can withhold."""
    return page.evaluate("() => { window.tabProbe.finishFading(); return window.tabProbe.colours(); }")


@pytest.mark.parametrize("tab_bar_page", PAGES_WITH_TAB_BARS)
def test_a_page_paints_its_tabs_in_their_colours_before_alpine_starts_so_none_fades_in(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    tab_bar_page: TabBarPage,
) -> None:
    """Before Alpine starts, each tab already has the colours it keeps once the page has settled, and no tab's colours are fading as Alpine starts."""
    url = live_server + tab_bar_page.path_of(request)
    _open_with_the_tabs_recorded(page, url, tab_bar_page.tab_names[0])
    assert page.evaluate("() => window.tabProbe.load") == {
        "colours_before_alpine": _finish_the_fading_and_read_the_tab_colours(page),
        "fading_as_alpine_starts": [],
    }


@pytest.mark.parametrize("tab_bar_page", PAGES_WITH_TAB_BARS)
def test_a_click_on_a_tab_fades_the_selected_colours_from_the_tab_that_had_them_to_it_alone(
    page: Page,
    live_server: str,
    request: pytest.FixtureRequest,
    tab_bar_page: TabBarPage,
) -> None:
    """Each click fades exactly two tabs, the one selected before and the one clicked, and leaves the clicked tab alone in the colours the opening tab loaded with. The opening tab is clicked last, so its click too has to move the selection. A ternary-string :class fails it: Alpine's string form adds and undoes only the classes it added itself, so it never removes one the server drew, while the object form tab_bar binds removes a false key's classes."""
    url = live_server + tab_bar_page.path_of(request)
    opening_tab, *other_tabs = tab_bar_page.tab_names
    _open_with_the_tabs_recorded(page, url, opening_tab)
    loaded = _finish_the_fading_and_read_the_tab_colours(page)
    selected, unselected = loaded[opening_tab], loaded[other_tabs[0]]
    assert selected != unselected and all(loaded[name] == unselected for name in other_tabs), (
        f"expected the opening tab {opening_tab!r} alone in the selected colours on load: {loaded}"
    )
    previously_selected = opening_tab
    for clicked in (*other_tabs, opening_tab):
        fading = page.get_by_role("tab", name=clicked, exact=True).evaluate(_CLICK_AND_READ_THE_FADING)
        settled_colours = _finish_the_fading_and_read_the_tab_colours(page)
        assert ({transition["tab"] for transition in fading}, settled_colours) == (
            {previously_selected, clicked},
            {name: selected if name == clicked else unselected for name in tab_bar_page.tab_names},
        ), f"after a click on the {clicked!r} tab"
        previously_selected = clicked
