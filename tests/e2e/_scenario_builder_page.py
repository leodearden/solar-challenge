# SPDX-License-Identifier: AGPL-3.0-or-later
"""Drive the Scenario Builder page at /scenarios/builder through its UI."""

from pathlib import Path

from playwright.sync_api import Page, Response


def open_builder(page: Page, live_server: str) -> Response:
    """Open the scenario builder and return the preview of its default form, which its Alpine component requests as it initialises.

    Once that response has arrived, the component has bound its controls, Upload YAML's file
    input among them, and a later wait for a preview cannot catch this one.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as first_preview:
        page.goto(live_server + "/scenarios/builder")
    return first_preview.value


def upload_scenario(page: Page, path: Path, yaml_text: str) -> None:
    """Write *yaml_text* to *path* and upload that file through Upload YAML's file input, on a builder open_builder opened.

    It does not wait for the preview the builder requests for an upload it accepts: it requests none for one it refuses.
    """
    path.write_text(yaml_text, encoding="utf-8")
    page.set_input_files('input[type="file"]', path)
