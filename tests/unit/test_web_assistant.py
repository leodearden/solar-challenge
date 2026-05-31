# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the AI assistant web blueprint (slice ①: foundation wiring)."""

import logging
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


def test_assistant_blueprint_registers_without_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Blueprint imports and registers cleanly — no 'Assistant blueprint not available' log."""
    db_path = tmp_path / "test.db"
    with caplog.at_level(logging.WARNING, logger="solar_challenge.web.app"):
        fresh_app = create_app(
            test_config={
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": str(db_path),
                "DATA_DIR": str(tmp_path),
            }
        )

    assert "Assistant blueprint not available" not in caplog.text, (
        f"Expected no assistant import warning, got: {caplog.text!r}"
    )
    assert "assistant" in fresh_app.blueprints, (
        f"Expected 'assistant' blueprint to be registered; got: {list(fresh_app.blueprints.keys())}"
    )
