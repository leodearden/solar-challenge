"""End-to-end tests for mobile responsive layout.

Verifies that the app renders correctly at a mobile viewport (375x812),
the hamburger menu is visible, the desktop sidebar is hidden, the mobile
menu opens, and key pages remain usable on small screens.
"""

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

MOBILE_WIDTH = 375
MOBILE_HEIGHT = 812


# -- Mobile dashboard rendering --------------------------------------------


def test_mobile_dashboard_renders(page: Page, live_server: str) -> None:
    """At 375x812 viewport, the dashboard renders without errors."""
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})

    response = page.goto(live_server + "/")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    # On mobile, the desktop sidebar is hidden.  The "Solar Challenge"
    # title is in the mobile top bar header (the one with class lg:hidden).
    mobile_header = page.locator("header.lg\\:hidden")
    expect(mobile_header).to_be_visible()

    # The brand name inside the mobile header
    brand = mobile_header.locator("text=Solar Challenge")
    expect(brand).to_be_visible()


# -- Hamburger menu button visible -----------------------------------------


def test_mobile_hamburger_visible(page: Page, live_server: str) -> None:
    """At 375px width, the hamburger menu button (in the lg:hidden mobile
    header) should be visible.
    """
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    # The hamburger button has aria-label="Open menu" and is inside
    # the mobile top bar header (which has the class lg:hidden)
    hamburger = page.locator('button[aria-label="Open menu"]')
    expect(hamburger).to_be_visible()


# -- Desktop sidebar hidden on mobile -------------------------------------


def test_mobile_sidebar_hidden(page: Page, live_server: str) -> None:
    """At 375px width, the desktop sidebar (aside with class 'hidden lg:flex')
    should not be visible.
    """
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    # The desktop sidebar is the first <aside> which has class "hidden lg:flex"
    desktop_sidebar = page.locator("aside").first
    expect(desktop_sidebar).not_to_be_visible()


# -- Mobile menu opens on hamburger click ----------------------------------


def test_mobile_menu_opens(page: Page, live_server: str) -> None:
    """At 375px width, clicking the hamburger button opens the mobile menu
    overlay and sidebar.
    """
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page.goto(live_server + "/")
    page.wait_for_load_state("domcontentloaded")

    # Click the hamburger button
    hamburger = page.locator('button[aria-label="Open menu"]')
    hamburger.click()

    # Wait for the slide-in transition
    page.wait_for_timeout(400)

    # The mobile sidebar (the <aside> with class "lg:hidden" that has
    # x-show="mobileMenuOpen") should now be visible
    mobile_sidebar = page.locator("aside.lg\\:hidden")
    expect(mobile_sidebar).to_be_visible()

    # The close button inside the mobile sidebar should be visible
    close_btn = page.locator('button[aria-label="Close menu"]')
    expect(close_btn).to_be_visible()

    # Navigation links should be present in the mobile sidebar
    mobile_nav = mobile_sidebar.locator("nav")
    expect(mobile_nav).to_be_visible()

    # Verify at least the Dashboard link is present
    dashboard_link = mobile_sidebar.locator("a", has_text="Dashboard")
    expect(dashboard_link).to_be_visible()


# -- Simulate home page usable on mobile -----------------------------------


def test_mobile_simulate_home_usable(page: Page, live_server: str) -> None:
    """At 375px width, the /simulate/home form is visible and the submit
    button is accessible (visible and not clipped off-screen).
    """
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})

    response = page.goto(live_server + "/simulate/home")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("networkidle")

    # The page heading should be visible
    heading = page.locator("text=Single Home Simulation").first
    expect(heading).to_be_visible()

    # The tab navigation should be visible (it has overflow-x-auto for
    # horizontal scrolling on mobile)
    tab_nav = page.locator('nav[aria-label="Configuration tabs"]')
    expect(tab_nav).to_be_visible()

    # The submit button should be in the DOM and reachable by scrolling
    submit_btn = page.locator("button[type='submit']")
    expect(submit_btn).to_be_attached()

    # Scroll the submit button into view and verify it is visible
    submit_btn.scroll_into_view_if_needed()
    expect(submit_btn).to_be_visible()


# -- History lists runs as cards on mobile ---------------------------------


def test_mobile_history_lists_runs_as_cards(
    page: Page,
    live_server: str,
    seeded_home_run: tuple[str, str],
) -> None:
    """Below the md breakpoint, runs are listed as cards linking to their results; the table is hidden."""
    run_id, run_name = seeded_home_run
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})

    response = page.goto(live_server + "/history/runs")
    assert response is not None
    assert response.status == 200

    # Narrow the list to the seeded run, whatever other runs the shared session DB holds
    page.get_by_label("Search", exact=True).fill(run_name)

    view_links = page.get_by_role("link", name="View", exact=True)
    expect(view_links).to_have_count(1)
    expect(view_links).to_have_attribute("href", f"/results/home/{run_id}")
    expect(page.locator("table")).to_be_hidden()


# -- History shows its empty and loading states on mobile ------------------


@pytest.mark.usefixtures("runs_api_returns_no_runs")
def test_mobile_history_shows_empty_state(page: Page, live_server: str) -> None:
    """Below the md breakpoint, 'No simulation runs found' shows when the runs API returns no runs."""
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page.goto(live_server + "/history/runs")

    expect(page.get_by_text("No simulation runs found")).to_be_visible()


@pytest.mark.usefixtures("runs_api_never_answers")
def test_mobile_history_shows_loading_state(page: Page, live_server: str) -> None:
    """Below the md breakpoint, 'Loading runs...' shows while the runs API has not answered."""
    page.set_viewport_size({"width": MOBILE_WIDTH, "height": MOBILE_HEIGHT})
    page.goto(live_server + "/history/runs")

    expect(page.get_by_text("Loading runs...")).to_be_visible()
