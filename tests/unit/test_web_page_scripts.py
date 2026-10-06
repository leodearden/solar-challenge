# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that the app itself serves every script a guarded page loads, and
serves each vendored one with the bytes its integrity attribute names.

A script from another origin is a fetch the page depends on every time it loads, and a
failed fetch breaks the page. base.html, the layout every page extends, loads Alpine,
without which no page renders its UI. The scenario builder loads js-yaml, without which
its Upload YAML reports 'jsyaml is not defined'.

So each third-party script is vendored under static/vendor/<package>/: its upstream
release, verbatim, loaded with an integrity attribute naming the SHA-384 of the bytes
jsdelivr serves for that release. Browsers enforce integrity on same-origin scripts too,
so the app must serve exactly those bytes. The app's own scripts, under static/js/, need
no integrity attribute.

To vendor a package, or move a vendored one to a new release:
1. From the repository root, download the release file verbatim, under a name that
   carries the version, and delete any older release's file:
   `curl -fsS --create-dirs -o src/solar_challenge/web/static/vendor/<package>/<name> https://cdn.jsdelivr.net/npm/<package>@<version>/<path>`.
2. Beside it, keep the release's upstream LICENSE, downloaded the same way, and an
   upstream.toml recording license = "<SPDX id>". tests/integration/test_external_install.py
   checks that the wheel ships the one and declares the other.
3. In the template, load the file with url_for('static', filename=...) and set its
   integrity to "sha384-" followed by the output of
   `curl -fsS <that URL> | openssl dgst -sha384 -binary | openssl base64 -A`.
   That hashes the bytes jsdelivr serves, never a local file: a hash of the local file
   would have this test compare the file with itself, and pass an edited copy.
"""

import base64
import hashlib
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

import pytest

pytest.importorskip("flask")
from flask import Flask, render_template, url_for
from flask.testing import FlaskClient

from tests._html_page import element_attributes
from tests._web_app import build_test_app

_GUARDED_TEMPLATES = ("base.html", "scenarios/builder.html")
"""The layout every page extends, and the scenario builder, whose Upload YAML parses the file with js-yaml."""


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _page_scripts(app: Flask, template: str) -> list[tuple[str, str | None]]:
    """The src of each script the rendered *template* loads, in document order, paired
    with its integrity attribute, or with None when it names none."""
    with app.test_request_context():
        page = render_template(template)
    scripts = [
        (src, attributes.get("integrity"))
        for attributes in element_attributes(page, "script")
        if (src := attributes.get("src"))
    ]
    assert scripts, (
        f"read no <script src> from the rendered {template},"
        " so the checks on its scripts would pass vacuously"
    )
    return scripts


def _vendored_scripts(app: Flask, template: str) -> list[tuple[str, str | None]]:
    """The scripts of _page_scripts(app, template) that the app serves from static/vendor/."""
    with app.test_request_context():
        vendor = PurePosixPath(url_for("static", filename="vendor"))
    vendored = [
        (src, integrity)
        for src, integrity in _page_scripts(app, template)
        if PurePosixPath(urlsplit(src).path).is_relative_to(vendor)
    ]
    assert vendored, (
        f"read no script under {vendor} from the rendered {template},"
        " so the check on its vendored scripts would pass vacuously"
    )
    return vendored


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


@pytest.mark.parametrize("template", _GUARDED_TEMPLATES)
def test_a_guarded_page_loads_no_script_from_another_origin(
    app: Flask, template: str
) -> None:
    offsite = sorted(
        src for src, _ in _page_scripts(app, template) if urlsplit(src).netloc
    )

    assert offsite == [], (
        f"{template} loads these scripts from another origin, so a failed fetch leaves"
        f" the page without them: {offsite}. Vendor each one as this module's"
        " docstring describes."
    )


@pytest.mark.parametrize("template", _GUARDED_TEMPLATES)
def test_the_app_serves_each_vendored_script_of_a_guarded_page_with_the_bytes_its_integrity_names(
    app: Flask, template: str
) -> None:
    client = app.test_client()

    problems = [
        (src, problem)
        for src, integrity in _vendored_scripts(app, template)
        if (problem := _serving_problem(client, src, integrity))
    ]

    assert problems == [], (
        f"a browser would not run these vendored scripts of {template} as the app"
        f" serves them: {problems}. A vendored file must be its upstream release,"
        " verbatim: re-download it with curl -o, never edit it. Its integrity must hash"
        " the bytes jsdelivr serves for that release, never a local file, which would"
        " let an edited copy pass; this module's docstring gives the command."
    )
