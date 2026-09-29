# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the web dashboard's application factory."""

import importlib
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")


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
    # A fresh import re-runs the factory's own imports, wherever they live.
    monkeypatch.delitem(sys.modules, "solar_challenge.web.app", raising=False)
    with pytest.raises(ImportError, match=re.escape(module)):
        importlib.import_module("solar_challenge.web.app").create_app(
            test_config={
                "TESTING": True,
                "SECRET_KEY": "test-secret-key",
                "DATABASE": str(tmp_path / "test.db"),
                "DATA_DIR": str(tmp_path),
            }
        )
