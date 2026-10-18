# SPDX-License-Identifier: AGPL-3.0-or-later
"""Guards the invariant that the app itself serves every script the dashboard's templates
load, and serves each vendored one with the bytes its integrity attribute names.

A script from another origin is a fetch the page depends on every time it loads, and a
failed fetch breaks the page. base.html, the layout every page extends, loads Alpine,
without which no page renders its UI. The scenario builder loads js-yaml, without which
its Upload YAML reports 'jsyaml is not defined'. The results and compare pages load
plotly.js, without which they draw no chart.

So the app serves each script from one of three sources:
- its own scripts, under static/js/, which need no integrity attribute;
- plotly.js, from the installed plotly package: plotly writes figure JSON for the
  plotly.js release it bundles, so web/plotly_js.py serves that release at
  url_for('plotly_js.script'). uv.lock's hash of the plotly wheel pins those bytes, so
  its tags carry no integrity attribute;
- every other third-party script, vendored under static/vendor/<package>/: its upstream
  release, verbatim, loaded with an integrity attribute naming the SHA-384 of the bytes
  jsdelivr serves for that release. Browsers enforce integrity on same-origin scripts
  too, so the app must serve exactly those bytes.

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
from flask import Flask, render_template_string, url_for
from flask.testing import FlaskClient
from jinja2 import Environment

from tests._html_page import element_attributes
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _scripts_by_template(app: Flask) -> dict[str, list[tuple[str, str | None]]]:
    """The scripts each template of *app* loads, in source order: the src of each, rendered
    as its page renders it, paired with its integrity attribute, or with None when it names
    none.

    Each template is read as written, every branch included. So a script is read once, from
    the template that loads it, and a template that renders only with its view's context is
    read too."""
    scripts = {
        template: _scripts_in(app, template)
        for template in sorted(app.jinja_env.list_templates(extensions=["html"]))
    }
    assert any(scripts.values()), (
        "read no <script src> from any template,"
        " so the checks on their scripts would pass vacuously"
    )
    return scripts


def _scripts_in(app: Flask, template: str) -> list[tuple[str, str | None]]:
    """The scripts *template* loads, as _scripts_by_template reads them."""
    env = app.jinja_env
    source, _, _ = env.loader.get_source(env, template)
    markup = _markup_keeping_expressions(env, source)
    with app.test_request_context():
        return [
            (render_template_string(src), attributes.get("integrity"))
            for attributes in element_attributes(markup, "script")
            if (src := attributes.get("src"))
        ]


def _markup_keeping_expressions(env: Environment, source: str) -> str:
    """The template *source* as HTML: each Jinja statement and comment blanked, so none can
    open or close a tag, and its literal markup and {{ expressions }} kept as written."""
    kept: list[str] = []
    in_expression = False
    for _, token, value in env.lex(source):
        if token == "variable_begin":
            in_expression = True
        kept.append(value if in_expression or token == "data" else " ")
        if token == "variable_end":
            in_expression = False
    return "".join(kept)


def _vendored_scripts(app: Flask) -> list[tuple[str, str, str | None]]:
    """(template, src, integrity) of each script a template loads from static/vendor/."""
    with app.test_request_context():
        vendor = PurePosixPath(url_for("static", filename="vendor"))
    vendored = [
        (template, src, integrity)
        for template, scripts in _scripts_by_template(app).items()
        for src, integrity in scripts
        if PurePosixPath(urlsplit(src).path).is_relative_to(vendor)
    ]
    assert vendored, (
        f"read no script under {vendor} from any template,"
        " so the check on vendored scripts would pass vacuously"
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


def _status_of(client: FlaskClient, src: str) -> int:
    with client.get(src) as response:
        return response.status_code


def test_no_template_loads_a_script_from_another_origin(app: Flask) -> None:
    offsite_by_template = {
        template: srcs
        for template, scripts in _scripts_by_template(app).items()
        if (srcs := [src for src, _ in scripts if urlsplit(src).netloc])
    }

    assert offsite_by_template == {}, (
        f"templates load these scripts from other origins: {offsite_by_template}. A failed"
        " fetch leaves a page without its script, so serve each one from the app, as this"
        " module's docstring describes."
    )


def test_the_app_serves_every_script_a_template_loads(app: Flask) -> None:
    client = app.test_client()

    unserved = [
        (template, src, status)
        for template, scripts in _scripts_by_template(app).items()
        for src, _ in scripts
        if (status := _status_of(client, src)) != 200
    ]

    assert unserved == [], (
        "the app does not answer 200 to these scripts its templates load, as"
        f" (template, src, status): {unserved}. A page runs without each one: correct a"
        " mistyped src, or serve the script from the app, as this module's docstring"
        " describes."
    )


def test_the_app_serves_each_vendored_script_with_the_bytes_its_integrity_names(
    app: Flask,
) -> None:
    client = app.test_client()

    problems = [
        (template, src, problem)
        for template, src, integrity in _vendored_scripts(app)
        if (problem := _serving_problem(client, src, integrity))
    ]

    assert problems == [], (
        f"a browser would not run these vendored scripts as the app serves them: {problems}."
        " A vendored file must be its upstream release, verbatim: re-download it with"
        " curl -o, never edit it. Its integrity must hash the bytes jsdelivr serves for"
        " that release, never a local file, which would let an edited copy pass; this"
        " module's docstring gives the command."
    )
