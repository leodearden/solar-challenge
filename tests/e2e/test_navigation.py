"""Navigation tests: sidebar links, breadcrumbs, dark mode, and collapse.

These tests exercise the interactive UI chrome that wraps every page:
sidebar navigation, theme toggle, and sidebar collapse/expand.  They run
against the live Flask server provided by the ``live_server`` fixture.
A page load lays the sidebar and the main column out in the sidebar state
localStorage stores, and draws the button of the sidebar group holding the
current page highlighted, all before Alpine starts, so nothing in the sidebar
or the main column transitions as Alpine starts; only the sidebar toggle slides
them.
"""

import pytest
from playwright.sync_api import Locator, Page, expect

# The desktop sidebar is only visible at lg breakpoint (>= 1024px).
# Playwright's default viewport (1280x720) satisfies this.

# ── Helpers ────────────────────────────────────────────────────────────


def _desktop_sidebar(page: Page):
    """Return a locator for the desktop sidebar <aside> (the one that is
    ``hidden lg:flex``).  We target the first <aside> that is visible on
    desktop viewports.
    """
    return page.locator("aside").first


def _expand_sidebar_group(page: Page, group_label: str) -> None:
    """Click the expandable group button in the desktop sidebar so that
    its child links become visible.

    The sidebar uses collapsible groups (Simulate, Scenarios, History)
    controlled by Alpine.js ``x-collapse``.
    """
    sidebar = _desktop_sidebar(page)
    group_btn = sidebar.locator("button", has_text=group_label)
    group_btn.click()
    # Wait for the collapse animation to finish
    page.wait_for_timeout(400)


def _click_sidebar_link(page: Page, link_text: str) -> None:
    """Click a visible link inside the desktop sidebar."""
    sidebar = _desktop_sidebar(page)
    link = sidebar.locator("a", has_text=link_text)
    link.first.click()
    page.wait_for_load_state("domcontentloaded")


# ── Sidebar link navigation ───────────────────────────────────────────


def test_sidebar_dashboard_link(page: Page, live_server: str) -> None:
    """Click 'Dashboard' in the sidebar and verify navigation to /."""
    # Start on a different page so the click actually navigates
    page.goto(live_server + "/simulate/home")
    page.wait_for_load_state("domcontentloaded")

    _click_sidebar_link(page, "Dashboard")

    assert page.url.rstrip("/") == live_server.rstrip("/") or page.url == live_server + "/"


def test_sidebar_simulate_home_link(page: Page, live_server: str) -> None:
    """Click 'Single Home' in the sidebar and verify navigation."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    _expand_sidebar_group(page, "Simulate")
    _click_sidebar_link(page, "Single Home")

    assert "/simulate/home" in page.url


def test_sidebar_fleet_link(page: Page, live_server: str) -> None:
    """Click 'Fleet' in the sidebar and verify navigation."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    _expand_sidebar_group(page, "Simulate")
    _click_sidebar_link(page, "Fleet")

    assert "/simulate/fleet" in page.url


def test_sidebar_builder_link(page: Page, live_server: str) -> None:
    """Click 'Builder' in the sidebar and verify navigation."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    _expand_sidebar_group(page, "Scenarios")
    _click_sidebar_link(page, "Builder")

    assert "/scenarios/builder" in page.url


def test_sidebar_sweep_link(page: Page, live_server: str) -> None:
    """Click 'Sweeps' in the sidebar and verify navigation."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    _expand_sidebar_group(page, "Scenarios")
    _click_sidebar_link(page, "Sweeps")

    assert "/scenarios/sweep" in page.url


def test_sidebar_history_link(page: Page, live_server: str) -> None:
    """Click 'Runs' (Run History) in the sidebar and verify navigation."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    _expand_sidebar_group(page, "History")
    _click_sidebar_link(page, "Runs")

    assert "/history/runs" in page.url


def test_sidebar_shows_the_group_of_the_current_page_open(page: Page, live_server: str) -> None:
    """On the fleet page the desktop sidebar shows the Simulate group's links without a click, and keeps the Scenarios group's links hidden."""
    page.goto(live_server + "/simulate/fleet")

    sidebar = _desktop_sidebar(page)
    expect(sidebar.get_by_role("link", name="Fleet", exact=True)).to_be_visible()
    expect(sidebar.get_by_role("link", name="Builder", exact=True)).to_be_hidden()


# ── Breadcrumb dead-link detection ─────────────────────────────────────


def test_breadcrumbs_no_dead_hash_links(page: Page, live_server: str) -> None:
    """Pages with breadcrumbs should not contain dead ``<a href="#">`` links.

    Currently /simulate/fleet, /scenarios/builder, and /scenarios/sweep
    have breadcrumb parent links pointing to ``#`` which makes them
    non-functional.  This test is expected to FAIL until the bug is fixed.
    """
    pages_with_bad_breadcrumbs = [
        "/simulate/fleet",
        "/scenarios/builder",
        "/scenarios/sweep",
    ]

    for path in pages_with_bad_breadcrumbs:
        page.goto(live_server + path)
        page.wait_for_load_state("domcontentloaded")

        breadcrumb_nav = page.locator('nav[aria-label="Breadcrumb"]')
        # There should be a breadcrumb nav on these pages
        assert breadcrumb_nav.count() > 0, (
            f"Page {path} has no breadcrumb navigation"
        )

        # Check for dead hash links inside the breadcrumb area
        dead_links = breadcrumb_nav.locator('a[href="#"]')
        assert dead_links.count() == 0, (
            f"Page {path} has {dead_links.count()} dead href='#' link(s) in breadcrumbs"
        )


# ── Dark mode toggle ──────────────────────────────────────────────────


def test_dark_mode_toggle(page: Page, live_server: str) -> None:
    """Clicking the dark-mode toggle adds the 'dark' class to <html>."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    html_el = page.locator("html")

    # Ensure we start in light mode by clearing any persisted preference
    page.evaluate("localStorage.removeItem('theme')")
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    # Verify starting state is light (no 'dark' class)
    html_classes = html_el.get_attribute("class") or ""
    starts_dark = "dark" in html_classes.split()

    # Click the theme toggle button (in the desktop sidebar footer)
    toggle_btn = _desktop_sidebar(page).locator('button[aria-label="Toggle dark mode"]')
    toggle_btn.click()
    page.wait_for_timeout(300)

    # After clicking, the dark class should be toggled
    html_classes_after = html_el.get_attribute("class") or ""
    ends_dark = "dark" in html_classes_after.split()

    if starts_dark:
        assert not ends_dark, "Toggle should have removed 'dark' class"
    else:
        assert ends_dark, "Toggle should have added 'dark' class"


# ── Sidebar collapse / expand ──────────────────────────────────────────


def test_sidebar_collapse_expand(page: Page, live_server: str) -> None:
    """Clicking the collapse toggle shrinks the sidebar from w-64 to w-16."""
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    sidebar = _desktop_sidebar(page)

    # Ensure sidebar starts expanded by setting localStorage
    page.evaluate("localStorage.setItem('sidebarOpen', 'true')")
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")
    sidebar = _desktop_sidebar(page)

    # Expanded sidebar should have w-64 (256px width)
    initial_width = sidebar.evaluate("el => el.getBoundingClientRect().width")
    assert initial_width > 200, f"Sidebar should start expanded (width={initial_width})"

    # Click the collapse toggle (aria-label="Toggle sidebar")
    collapse_btn = sidebar.locator('button[aria-label="Toggle sidebar"]')
    collapse_btn.click()
    # Wait for the CSS transition (duration-300 = 300ms)
    page.wait_for_timeout(400)

    collapsed_width = sidebar.evaluate("el => el.getBoundingClientRect().width")
    assert collapsed_width < 100, (
        f"Sidebar should be collapsed (width={collapsed_width})"
    )

    # Click again to re-expand
    collapse_btn.click()
    page.wait_for_timeout(400)

    expanded_width = sidebar.evaluate("el => el.getBoundingClientRect().width")
    assert expanded_width > 200, (
        f"Sidebar should be expanded again (width={expanded_width})"
    )


# ── Sidebar state on load ──────────────────────────────────────────────

# The desktop sidebar's width and #main-content's left edge, in px, at pytest-playwright's default 1280x720 viewport (Tailwind lg).
_SIDEBAR_OPEN = {"sidebar_width": 256, "content_left": 256}
_SIDEBAR_COLLAPSED = {"sidebar_width": 64, "content_left": 64}

# Records in window.sidebarProbe.load how the sidebar and the main column load, at two moments:
# - before_alpine: what is drawn at readystatechange 'interactive'. That fires once the page is parsed,
#   before any deferred script runs, Alpine included. What is drawn is the layout, and the labels of the
#   desktop sidebar's group buttons drawn with a background, i.e. highlighted. Reading it there makes the
#   browser compute the page's style, so a later change Alpine makes to a transitioned property must
#   start a transition.
# - transitions_as_alpine_starts: the CSS transitions running at Alpine's alpine:initialized event, which
#   fires once Alpine has applied its bindings; a colour fade counts as much as a slide. Only transitions
#   on the desktop sidebar (the first <aside>, the element _desktop_sidebar locates) or anything in it,
#   or on #main-content or anything holding it, count.
_RECORD_HOW_THE_SIDEBAR_LOADS = r"""(() => {
    const sidebar = () => document.querySelector('aside');
    const content = () => document.getElementById('main-content');
    const drawn = () => ({
        layout: {
            sidebar_width: sidebar().getBoundingClientRect().width,
            content_left: content().getBoundingClientRect().left,
        },
        highlighted_groups: [...sidebar().querySelectorAll('nav button')]
            .filter(button => getComputedStyle(button).backgroundColor !== 'rgba(0, 0, 0, 0)')
            .map(button => button.textContent.trim()),
    });
    const describe = target => target === sidebar() ? 'sidebar'
        : target.contains(content()) ? 'main column'
        : `${target.tagName.toLowerCase()}.${(target.getAttribute('class') || '').trim().split(/\s+/).join('.')} in the sidebar`;
    const transitions = () => document.getAnimations()
        .filter(animation => animation instanceof CSSTransition)
        .filter(({effect: {target}}) => sidebar().contains(target) || target.contains(content()))
        .map(transition => `${describe(transition.effect.target)} ${transition.transitionProperty}`);
    window.sidebarProbe = {drawn, transitions, load: {}};
    document.addEventListener('readystatechange', () => {
        if (document.readyState === 'interactive') window.sidebarProbe.load.before_alpine = drawn();
    });
    document.addEventListener('alpine:initialized', () => {
        window.sidebarProbe.load.transitions_as_alpine_starts = transitions();
    });
})()"""

# Clicks the toggle in the page and returns the transitions one task later: the click's class changes
# have taken effect by then, and no 300 ms transition can have ended.
_CLICK_AND_READ_THE_TRANSITIONS = """async toggle => {
    toggle.click();
    await new Promise(resolve => setTimeout(resolve));
    return window.sidebarProbe.transitions();
}"""


def _sidebar_toggle(page: Page) -> Locator:
    """The desktop sidebar's collapse/expand button; the mobile sidebar has none."""
    return page.get_by_role("button", name="Toggle sidebar")


def _open_with_the_sidebar_stored(page: Page, url: str, stored_state: str | None) -> None:
    """Open url with localStorage's sidebarOpen set to stored_state (left unset if None), recording how the sidebar loads."""
    if stored_state is not None:
        page.add_init_script(f"localStorage.setItem('sidebarOpen', '{stored_state}')")
    page.add_init_script(_RECORD_HOW_THE_SIDEBAR_LOADS)
    page.goto(url)


def _how_the_sidebar_loaded(page: Page) -> tuple[dict[str, object], dict[str, object]]:
    """What the recorder saw as the page loaded, and what is drawn now; it reads load on its own because the probe holds functions."""
    return page.evaluate("() => window.sidebarProbe.load"), page.evaluate("() => window.sidebarProbe.drawn()")


def _highlighted_groups_once_nothing_transitions(page: Page) -> list[str]:
    """The labels of the desktop sidebar's highlighted group buttons, read once no transition is running, so a colour fade under way is not read as a highlight half drawn."""
    page.wait_for_function("() => window.sidebarProbe.transitions().length === 0")
    return page.evaluate("() => window.sidebarProbe.drawn().highlighted_groups")


@pytest.mark.parametrize(
    ("stored_state", "layout", "toggle_title"),
    [
        pytest.param(None, _SIDEBAR_OPEN, "Collapse sidebar", id="open-by-default"),
        pytest.param("true", _SIDEBAR_OPEN, "Collapse sidebar", id="open"),
        pytest.param("false", _SIDEBAR_COLLAPSED, "Expand sidebar", id="collapsed"),
    ],
)
@pytest.mark.parametrize(
    ("path", "highlighted_groups"),
    [
        pytest.param("/", [], id="dashboard"),
        pytest.param("/simulate/home", ["Simulate"], id="single-home"),
        pytest.param("/scenarios/builder", ["Scenarios"], id="builder"),
        pytest.param("/history/runs", ["History"], id="runs"),
    ],
)
def test_a_page_load_draws_the_sidebar_in_its_stored_state_with_the_current_pages_group_highlighted_before_alpine_starts_and_transitions_nothing(
    page: Page,
    live_server: str,
    path: str,
    highlighted_groups: list[str],
    stored_state: str | None,
    layout: dict[str, int],
    toggle_title: str,
) -> None:
    """A page's sidebar and main column are drawn in the stored state, with the button of the group holding the page (if any) highlighted, before Alpine starts; nothing in them transitions as Alpine starts; and they are drawn the same once it has.

    The toggle's title shows that Alpine has started and agrees with the stored state. The dashboard
    holds no group, so its sidebar highlights none.
    """
    _open_with_the_sidebar_stored(page, live_server + path, stored_state)

    expect(_sidebar_toggle(page)).to_have_attribute("title", toggle_title)
    drawn = {"layout": layout, "highlighted_groups": highlighted_groups}
    assert _how_the_sidebar_loaded(page) == ({"before_alpine": drawn, "transitions_as_alpine_starts": []}, drawn)


@pytest.mark.parametrize(
    ("stored_state", "title_before", "title_after"),
    [
        pytest.param(None, "Collapse sidebar", "Expand sidebar", id="collapse"),
        pytest.param("false", "Expand sidebar", "Collapse sidebar", id="expand"),
    ],
)
def test_the_sidebar_toggle_slides_the_sidebar_and_the_main_column(
    page: Page, live_server: str, stored_state: str | None, title_before: str, title_after: str
) -> None:
    """The sidebar toggle slides the sidebar's width and the main column's margin.

    It clicks once per page load, in the page. A second click a few ms after the first reverses
    transitions that have not advanced a frame, which starts no new width transition. A Playwright
    click followed by a separate evaluate leaves two round trips in which a loaded host can let
    300 ms pass.
    """
    _open_with_the_sidebar_stored(page, live_server + "/", stored_state)
    expect(_sidebar_toggle(page)).to_have_attribute("title", title_before)

    transitions = _sidebar_toggle(page).evaluate(_CLICK_AND_READ_THE_TRANSITIONS)

    assert {"sidebar width", "main column margin-left"} <= set(transitions), f"The toggle started only these transitions: {transitions}"
    expect(_sidebar_toggle(page)).to_have_attribute("title", title_after)


def test_the_next_page_load_starts_in_the_state_the_sidebar_toggle_left(page: Page, live_server: str) -> None:
    """Once the toggle has collapsed the sidebar, and again once it has expanded it, a reload lays it out in that state before Alpine starts and transitions nothing."""
    _open_with_the_sidebar_stored(page, live_server + "/", None)
    expect(_sidebar_toggle(page)).to_have_attribute("title", "Collapse sidebar")

    for title_after, layout in (("Expand sidebar", _SIDEBAR_COLLAPSED), ("Collapse sidebar", _SIDEBAR_OPEN)):
        _sidebar_toggle(page).click()
        expect(_sidebar_toggle(page)).to_have_attribute("title", title_after)
        page.reload()
        expect(_sidebar_toggle(page)).to_have_attribute("title", title_after)
        drawn = {"layout": layout, "highlighted_groups": []}
        assert _how_the_sidebar_loaded(page) == ({"before_alpine": drawn, "transitions_as_alpine_starts": []}, drawn)


def test_a_group_opened_from_its_button_is_highlighted_until_closed_and_the_current_pages_group_stays_highlighted(
    page: Page, live_server: str
) -> None:
    """Opening the Scenarios group highlights its button and closing it removes the highlight, while the Simulate group holding the page stays highlighted.

    It presses Enter on the button instead of clicking it, because a mouse click leaves the pointer
    on the button, and its hover background would read as a highlight.
    """
    _open_with_the_sidebar_stored(page, live_server + "/simulate/home", None)
    expect(_sidebar_toggle(page)).to_have_attribute("title", "Collapse sidebar")
    scenarios = _desktop_sidebar(page).get_by_role("button", name="Scenarios")

    highlighted_groups = [_highlighted_groups_once_nothing_transitions(page)]
    for _ in range(2):
        scenarios.press("Enter")
        highlighted_groups.append(_highlighted_groups_once_nothing_transitions(page))

    assert highlighted_groups == [["Simulate"], ["Simulate", "Scenarios"], ["Simulate"]]
