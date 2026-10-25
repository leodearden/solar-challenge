# SPDX-License-Identifier: AGPL-3.0-or-later
"""base.html, the layout every page extends, links static/dist/favicon.svg as the page's icon.

`npm run build:favicon` (build-favicon.js) draws that file in the theme's primary-500, so
the browser tab's icon follows the accent. The css-build lane,
tests/css_build/test_dist_style_css.py, checks that the committed file is that build's output.
"""

import pytest

pytest.importorskip("flask")
from flask import Flask, url_for

from tests._html_page import element_attributes


def test_the_layout_links_only_the_built_favicon_which_the_app_serves_as_svg(app: Flask) -> None:
    client = app.test_client()
    page = client.get("/").get_data(as_text=True)
    icons = [link.get("href") for link in element_attributes(page, "link") if link.get("rel") == "icon"]
    with app.test_request_context():
        built = url_for("static", filename="dist/favicon.svg")

    assert icons == [built], (
        f"the layout links the icons {icons}, where it must link only {built}: link the favicon "
        "build-favicon.js writes, never a hand-written copy, whose colour would not follow the accent"
    )
    with client.get(built) as response:
        assert (response.status_code, response.mimetype) == (200, "image/svg+xml")
