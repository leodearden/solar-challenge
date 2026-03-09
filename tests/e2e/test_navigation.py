"""Navigation tests: sidebar links, breadcrumbs, dark mode, and collapse.

These tests exercise the interactive UI chrome that wraps every page:
sidebar navigation, theme toggle, and sidebar collapse/expand.  They run
against the live Flask server provided by the ``live_server`` fixture.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

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
