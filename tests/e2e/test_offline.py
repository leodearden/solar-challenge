"""End-to-end tests: the dashboard's pages work when the app's own origin is the only one
reachable.
"""

from pathlib import Path
from urllib.parse import urlsplit

import pytest
import yaml
from playwright.sync_api import Page, Route, expect

from tests.e2e._scenario_builder_page import open_builder, upload_scenario

pytestmark = pytest.mark.e2e


@pytest.fixture
def refused_offsite_requests(page: Page, live_server: str) -> list[str]:
    """The URL of each request the test's page makes to another origin than the app's,
    in the order made; each is refused as if the network were down."""
    app_host = urlsplit(live_server).netloc
    refused: list[str] = []

    def refuse(route: Route) -> None:
        refused.append(route.request.url)
        route.abort("internetdisconnected")

    page.route(lambda url: urlsplit(url).netloc != app_host, refuse)
    return refused


def test_the_home_form_renders_with_every_other_origin_unreachable(
    page: Page, live_server: str, refused_offsite_requests: list[str]
) -> None:
    page.goto(live_server + "/simulate/home")

    expect(
        page.get_by_role("tab", name="Battery", exact=True),
        "Alpine never rendered the home form's tabs;"
        f" requests refused to other origins: {refused_offsite_requests}",
    ).to_be_visible()
    assert refused_offsite_requests == [], (
        f"/simulate/home requested these from other origins: {refused_offsite_requests}"
    )


def test_the_builder_reads_an_uploaded_yaml_with_every_other_origin_unreachable(
    page: Page, live_server: str, refused_offsite_requests: list[str], tmp_path: Path
) -> None:
    open_builder(page, live_server)

    upload_scenario(
        page,
        tmp_path / "scenario.yaml",
        yaml.safe_dump({"name": "Uploaded offline", "fleet_distribution": {"n_homes": 3}}),
    )

    expect(
        page.get_by_role("textbox", name="Scenario Name", exact=True),
        "the builder never read the uploaded scenario into its form;"
        f" requests refused to other origins: {refused_offsite_requests}",
    ).to_have_value("Uploaded offline")
    assert refused_offsite_requests == [], (
        f"/scenarios/builder requested these from other origins: {refused_offsite_requests}"
    )
