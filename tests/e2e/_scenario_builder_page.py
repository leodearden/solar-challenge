# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the Scenario Builder page at /scenarios/builder through its UI."""

from playwright.sync_api import Page, Response


def open_builder(page: Page, live_server: str) -> Response:
    """Open the scenario builder and return the preview of its default form, which its Alpine component requests as it initialises.

    Once that response has arrived, the component has bound its controls, Upload YAML's file
    input among them, and a later wait for a preview cannot catch this one.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as first_preview:
        page.goto(live_server + "/scenarios/builder")
    return first_preview.value
