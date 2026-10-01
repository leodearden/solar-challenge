# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_orchestrator_config.py, the orchestrator contract tests' reader of dark-factory-orchestrator.yaml."""

from pathlib import Path

from tests._orchestrator_config import lane_job_directory


def test_a_lane_job_without_a_cwd_runs_in_the_project_root(tmp_path: Path) -> None:
    job = {"name": "probe", "command": "pytest"}

    assert lane_job_directory(tmp_path, job) == tmp_path


def test_a_lane_job_with_a_cwd_runs_in_that_directory_under_the_project_root(tmp_path: Path) -> None:
    job = {"name": "probe", "command": "pytest", "cwd": "tests/e2e"}

    assert lane_job_directory(tmp_path, job) == tmp_path / "tests" / "e2e"
