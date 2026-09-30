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
