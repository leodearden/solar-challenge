# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-task verify contract tests.

The orchestrator runs dark-factory-orchestrator.yaml's test_command in each
task's fresh worktree before merging it, so these tests run it the same way.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._orchestrator_config import load_orchestrator_config

_WEB_TEST_MODULE = "tests/unit/test_web_app.py"


def test_verify_collects_the_web_tests_instead_of_skipping_them(project_root: Path, tmp_path: Path) -> None:
    """Run as the orchestrator runs it, test_command collects a web test module instead of skipping it.

    The command runs verbatim, in a fresh uv environment holding exactly the
    extras it names. The shared environment would prove nothing: `uv run` never
    uninstalls, so it keeps any extra an earlier `uv run` installed, and
    tests/unit/test_e2e_lane.py's nested run installs the web extra into it.
    """
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed; test_command runs through it")
    command = load_orchestrator_config(project_root)["test_command"]
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "venv")
    env["PYTEST_ADDOPTS"] = f"--collect-only --verbosity=-1 {_WEB_TEST_MODULE}"

    result = subprocess.run(
        command,
        shell=True,
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == pytest.ExitCode.OK, (
        f"test_command {command!r} did not collect {_WEB_TEST_MODULE} (exit {result.returncode}); without "
        "the web extra that module, like every test module that needs the extra, skips through "
        "pytest.importorskip, so the verify passes while silently dropping their coverage\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
