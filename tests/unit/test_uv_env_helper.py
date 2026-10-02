# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_uv_env.py, the process environment in which a test runs a uv command."""

import os
from pathlib import Path

import pytest

from tests._uv_env import isolated_uv_env

_CALLERS_VIRTUALENV_AND_LOCK_MODE = ["VIRTUAL_ENV", "UV_FROZEN", "UV_LOCKED", "UV_NO_SYNC"]


@pytest.mark.parametrize("name", _CALLERS_VIRTUALENV_AND_LOCK_MODE)
def test_the_callers_virtualenv_and_lock_mode_are_left_out(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(name, "1")

    assert name not in isolated_uv_env(tmp_path / "venv")


def test_the_project_environment_is_the_one_given_not_the_callers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(tmp_path / "callers-venv"))

    assert isolated_uv_env(tmp_path / "venv")["UV_PROJECT_ENVIRONMENT"] == str(tmp_path / "venv")


def test_every_other_variable_of_this_process_is_kept(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """UV_PYTHON_INSTALL_DIR, for one, which a sandboxed caller sets so uv can install an interpreter."""
    monkeypatch.setenv("UV_PYTHON_INSTALL_DIR", str(tmp_path / "pythons"))
    kept = {name: value for name, value in os.environ.items() if name not in _CALLERS_VIRTUALENV_AND_LOCK_MODE}

    assert isolated_uv_env(tmp_path / "venv") == {**kept, "UV_PROJECT_ENVIRONMENT": str(tmp_path / "venv")}
