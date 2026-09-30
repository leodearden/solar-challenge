# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_app.py, the shared builder of the web tests' Flask app."""

import subprocess
import sys
from pathlib import Path

import pytest

pytest.importorskip("flask")

from tests._web_app import build_test_app


def test_importing_the_helper_needs_no_web_extra(project_root: Path) -> None:
    """The web_assistant conftest imports the helper when it loads, and a run without the web extra must skip those tests, not abort."""
    result = subprocess.run(
        [sys.executable, "-c", "import sys; sys.modules['flask'] = None; import tests._web_app"],
        cwd=project_root,
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr


def test_the_app_runs_in_testing_mode_with_its_data_under_the_given_directory(
    tmp_path: Path,
) -> None:
    app = build_test_app(tmp_path)

    assert app.testing
    assert Path(app.config["DATABASE"]).is_relative_to(tmp_path)
    assert Path(app.config["DATA_DIR"]) == tmp_path


@pytest.fixture
def exported_secret_key(monkeypatch: pytest.MonkeyPatch) -> str:
    """A SECRET_KEY exported in the environment: create_app's own key lookup takes it before any key persisted under the home directory."""
    key = "a-key-from-the-environment"
    monkeypatch.setenv("SECRET_KEY", key)
    return key


def test_by_default_the_builder_supplies_the_apps_secret_key(
    exported_secret_key: str, tmp_path: Path
) -> None:
    """A key in test_config keeps create_app from looking one up, and that lookup reads, and can write, a key persisted under the home directory."""
    assert build_test_app(tmp_path).secret_key != exported_secret_key


@pytest.mark.usefixtures("exported_secret_key")
def test_a_given_secret_key_becomes_the_apps_key(tmp_path: Path) -> None:
    assert build_test_app(tmp_path, secret_key="a-given-key").secret_key == "a-given-key"


def test_secret_key_none_leaves_the_apps_key_to_create_apps_own_lookup(
    exported_secret_key: str, tmp_path: Path
) -> None:
    assert build_test_app(tmp_path, secret_key=None).secret_key == exported_secret_key
