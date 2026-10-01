# SPDX-License-Identifier: AGPL-3.0-or-later
"""Build the web dashboard's Flask app for tests, with its database and run files under one directory.

The application factory is imported when build_test_app is called, not when this
module loads. So importing this module needs no web extra, and a call made after a
test drops solar_challenge.web.app from sys.modules imports the factory anew.

Usage::

    from tests._web_app import build_test_app

    app = build_test_app(tmp_path)
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from flask import Flask


def build_test_app(
    data_dir: Path, *, secret_key: str | None = "test-secret-key"
) -> Flask:
    """Return the dashboard app in testing mode, keeping its database and run files under *data_dir*.

    The test_config supplies *secret_key* as the app's SECRET_KEY. With
    secret_key=None it holds no SECRET_KEY, and create_app looks a key up itself.
    """
    from solar_challenge.web.app import create_app

    secret_key_config = {} if secret_key is None else {"SECRET_KEY": secret_key}
    return create_app(
        test_config={
            "TESTING": True,
            "DATABASE": str(data_dir / "test.db"),
            "DATA_DIR": str(data_dir),
            **secret_key_config,
        }
    )
