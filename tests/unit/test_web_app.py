# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the web dashboard's application factory."""

import importlib
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask


def _uncache_module(monkeypatch: pytest.MonkeyPatch, module: str) -> None:
    """Make the next import of *module* run it afresh; the cached module comes back after the test.

    A fresh import that succeeds also rebinds the module's attribute on its parent package,
    so that attribute is restored along with the sys.modules entry.
    """
    package, _, name = module.rpartition(".")
    monkeypatch.delitem(sys.modules, module, raising=False)
    monkeypatch.delattr(importlib.import_module(package), name, raising=False)


def _build_app(tmp_path: Path) -> Flask:
    """Import the application factory and build an app that keeps its data under *tmp_path*."""
    app: Flask = importlib.import_module("solar_challenge.web.app").create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "DATABASE": str(tmp_path / "test.db"),
            "DATA_DIR": str(tmp_path),
        }
    )
    return app


@pytest.mark.parametrize(
    "module",
    [
        "solar_challenge.web.jobs",
        "solar_challenge.web.routes",
        "solar_challenge.web.history",
        "solar_challenge.web.scenarios",
        "solar_challenge.web.api",
        "solar_challenge.web.assistant",
    ],
    ids=lambda module: module.rpartition(".")[2],
)
def test_building_the_app_fails_when_a_module_it_wires_in_cannot_import(
    module: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A job-manager or blueprint module that cannot import fails the app build instead of vanishing from the app."""
    # A None entry makes any import of the module raise ModuleNotFoundError naming it.
    monkeypatch.setitem(sys.modules, module, None)
    _uncache_module(monkeypatch, "solar_challenge.web.app")
    with pytest.raises(ImportError, match=re.escape(module)):
        _build_app(tmp_path)


def test_building_the_app_does_not_import_the_anthropic_sdk(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Building the app and serving the assistant page never import the anthropic SDK: the assistant imports it only to answer a chat."""
    monkeypatch.setitem(sys.modules, "anthropic", None)
    _uncache_module(monkeypatch, "solar_challenge.web.assistant")
    _uncache_module(monkeypatch, "solar_challenge.web.app")

    app = _build_app(tmp_path)

    assert app.test_client().get("/assistant").status_code == 200
