# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that the app itself serves every script base.html loads, with the
bytes its integrity attribute names.

base.html is the layout every page template extends, so its scripts load on every page.
Each must come from the app itself. A script from another origin is a fetch every page
load depends on, and when it fails the page renders without Alpine.

The vendored scripts keep their upstream release's integrity attribute. Browsers enforce
it on same-origin scripts too, so the app must serve exactly those bytes.

To upgrade one, download https://cdn.jsdelivr.net/npm/<package>@<version>/dist/cdn.min.js
verbatim into static/vendor/alpinejs/, under a name that carries the version. In
base.html, point the src at the new file and set integrity to the SRI hash jsdelivr
publishes for it. This test then confirms the bytes match.
"""

import base64
import hashlib
from pathlib import Path
from urllib.parse import urlsplit

import pytest

pytest.importorskip("flask")
from flask import Flask, render_template
from flask.testing import FlaskClient

from tests._html_page import element_attributes
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _layout_scripts(app: Flask) -> dict[str, str | None]:
    """The src of each script the rendered base.html loads, mapped to its integrity
    attribute, or to None when it names none."""
    with app.test_request_context():
        layout = render_template("base.html")
    scripts = {
        src: attributes.get("integrity")
        for attributes in element_attributes(layout, "script")
        if (src := attributes.get("src"))
    }
    assert scripts, (
        "read no <script src> from the rendered base.html,"
        " so the checks below would pass vacuously"
    )
    return scripts


def _sri_sha384(body: bytes) -> str:
    return "sha384-" + base64.b64encode(hashlib.sha384(body).digest()).decode("ascii")


def _serving_problem(
    client: FlaskClient, src: str, integrity: str | None
) -> str | None:
    """Why a browser would not run the script the app serves at *src* under
    *integrity*, or None when it would."""
    with client.get(src) as response:
        if response.status_code != 200:
            return f"the app answers {response.status_code}"
        if integrity is None:
            return "names no integrity attribute"
        served = _sri_sha384(response.get_data())
        if served != integrity:
            return (
                f"its integrity attribute names {integrity}, but the bytes the app"
                f" serves hash to {served}, so a browser refuses to run the script"
            )
        return None


def test_the_layout_loads_no_script_from_another_origin(app: Flask) -> None:
    offsite = sorted(src for src in _layout_scripts(app) if urlsplit(src).netloc)

    assert offsite == [], (
        f"base.html loads these scripts on every page from another origin, so a failed"
        f" fetch leaves pages without them: {offsite}. Vendor each one verbatim under"
        " static/vendor/ and load it with url_for('static', filename=...)."
    )


def test_the_app_serves_every_layout_script_with_the_bytes_its_integrity_names(
    app: Flask,
) -> None:
    client = app.test_client()

    problems = {
        src: problem
        for src, integrity in _layout_scripts(app).items()
        if (problem := _serving_problem(client, src, integrity))
    }

    assert problems == {}, (
        f"a browser would not run these layout scripts as the app serves them: {problems}."
        " A vendored file must be its upstream release, verbatim: re-download the file,"
        " or set integrity to the SRI hash the release publishes."
    )
