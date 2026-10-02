"""End-to-end test: the dashboard renders its Alpine UI when the app's own origin is the
only one reachable.
"""

from urllib.parse import urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


def test_the_home_form_renders_with_every_other_origin_unreachable(
    page: Page, live_server: str
) -> None:
    app_host = urlsplit(live_server).netloc
    refused: list[str] = []

    def refuse(route: Route) -> None:
        refused.append(route.request.url)
        route.abort("internetdisconnected")

    page.route(lambda url: urlsplit(url).netloc != app_host, refuse)
    page.goto(live_server + "/simulate/home")

    expect(
        page.get_by_role("tab", name="Battery", exact=True),
        "Alpine never rendered the home form's tabs;"
        f" requests refused to other origins: {refused}",
    ).to_be_visible()
    assert refused == [], (
        f"/simulate/home requested these from other origins: {refused}"
    )
