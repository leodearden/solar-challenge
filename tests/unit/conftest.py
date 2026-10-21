# SPDX-License-Identifier: AGPL-3.0-or-later
"""The dashboard's Flask test app, a client of it, and its template macros, for the unit tests that drive the app.

The client's requests reach the JobManager that create_app built. A test module or
package conftest whose tests need another job manager defines its own client, which
pytest uses instead of this one.

Nothing here imports the web extra when it loads:
tests/unit/test_conftests_need_no_web_extra.py says why.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from tests._server_drawn_badges import dashboard_macros_of
from tests._web_app import build_test_app

if TYPE_CHECKING:
    from flask import Flask
    from flask.testing import FlaskClient


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """The dashboard app in testing mode, its database and run files under the test's tmp_path."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client of the app fixture's app."""
    return app.test_client()


@pytest.fixture
def macros(app: Flask) -> Any:
    """The public macros of components/macros.html, as callables that return their markup."""
    return dashboard_macros_of(app)
