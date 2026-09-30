# SPDX-License-Identifier: AGPL-3.0-or-later
"""Fixtures for the Flask test app the web-assistant test modules drive.

Nothing here imports Flask, the optional web extra, when the module loads: without
it, each test module's ``pytest.importorskip("flask")`` skips that module, whereas
an import error in this conftest would abort the run.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from tests._web_app import build_test_app

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()
