# SPDX-License-Identifier: AGPL-3.0-or-later
"""E2E lane contract tests.

The per-task verify never runs tests/e2e: its test_command ignores and
deselects it. The orchestrator offline lane's e2e job runs it after every
merge instead, so an e2e regression files a fix task rather than rotting
unseen.
"""

import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests._orchestrator_config import offline_lane_jobs

_E2E_JOB = "e2e"


def _sole_e2e_job(project_root: Path) -> dict[str, Any]:
    """Return the offline lane's e2e job, asserting there is exactly one."""
    e2e_jobs = offline_lane_jobs(project_root, _E2E_JOB)
    assert len(e2e_jobs) == 1, (
        f"git.offline_lane_commands has {len(e2e_jobs)} entries named {_E2E_JOB!r}; with none "
        "e2e regressions go unseen again, with several every merge runs the browser suite "
        "more than once"
    )
    return e2e_jobs[0]


def test_offline_lane_runs_one_enabled_e2e_job(project_root: Path) -> None:
    """The offline lane runs exactly one e2e job, and it is enabled."""
    job = _sole_e2e_job(project_root)

    assert job.get("enabled", True) is True, (
        f"the {_E2E_JOB!r} lane job is disabled, so e2e regressions go unseen again"
    )


def test_e2e_job_collects_the_e2e_suite_and_nothing_else(project_root: Path) -> None:
    """Run as the lane runs it, the e2e job collects at least one test, every one under tests/e2e/."""
    if shutil.which("uv") is None:
        pytest.skip("uv is not installed; the e2e job runs through it")
    job = _sole_e2e_job(project_root)
    command = job["command"]

    result = subprocess.run(
        command,
        shell=True,
        cwd=project_root / job.get("cwd", "."),
        env={**os.environ, "PYTEST_ADDOPTS": "--collect-only -q -o addopts="},
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert result.returncode == 0, (
        f"the {_E2E_JOB!r} lane job {command!r} failed to collect (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    node_ids = [line for line in result.stdout.splitlines() if "::" in line]
    assert node_ids, (
        f"the {_E2E_JOB!r} lane job {command!r} collected no tests, so the lane stays green "
        f"while the e2e suite goes unrun\nstdout:\n{result.stdout}"
    )
    outside_e2e = [node_id for node_id in node_ids if not node_id.startswith("tests/e2e/")]
    assert not outside_e2e, (
        f"the {_E2E_JOB!r} lane job {command!r} collected tests outside tests/e2e/, which the "
        f"per-task verify already runs: {outside_e2e}"
    )
