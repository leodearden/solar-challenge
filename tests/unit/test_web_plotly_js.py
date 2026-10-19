# SPDX-License-Identifier: AGPL-3.0-or-later
"""charts.py builds every figure with plotly's Python API, which writes figure JSON for the
plotly.js release the same plotly package bundles, so the dashboard serves that release."""

import hashlib
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask, url_for
from plotly.offline import get_plotlyjs

from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    return build_test_app(tmp_path)


def _plotly_js_url(app: Flask) -> str:
    with app.test_request_context():
        return url_for("plotly_js.script")


def test_the_app_serves_the_plotly_js_its_plotly_package_bundles(app: Flask) -> None:
    url = _plotly_js_url(app)

    with app.test_client().get(url) as response:
        assert response.status_code == 200
        assert response.content_type == "text/javascript; charset=utf-8"
        served = response.get_data()

    bundled = get_plotlyjs().encode("utf-8")
    assert hashlib.sha256(served).hexdigest() == hashlib.sha256(bundled).hexdigest(), (
        f"{url} serves {len(served):,} bytes that are not the {len(bundled):,} bytes"
        " of the plotly.js the installed plotly package bundles"
    )


def test_a_browser_revalidating_its_copy_of_plotly_js_is_answered_not_modified(
    app: Flask,
) -> None:
    url = _plotly_js_url(app)
    client = app.test_client()

    with client.get(url) as first_load:
        etag = first_load.headers.get("ETag")
    assert etag, f"{url} names no ETag, so a browser cannot revalidate its copy"

    with client.get(url, headers={"If-None-Match": etag}) as revalidation:
        assert revalidation.status_code == 304, (
            f"{url} answers {revalidation.status_code} to a browser revalidating its copy"
            f" under ETag {etag}, so every chart page load downloads the script again"
        )
