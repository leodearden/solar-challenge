# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Usage::

    from tests._orchestrator_config import lane_job_directory, load_orchestrator_config, sole_offline_lane_job

    test_command = load_orchestrator_config(project_root)["test_command"]
    matrix_job = sole_offline_lane_job(project_root, "interpreter-matrix")
    matrix_directory = lane_job_directory(project_root, matrix_job)
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml


def load_orchestrator_config(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s dark-factory-orchestrator.yaml, parsed as YAML."""
    config_path = project_root / "dark-factory-orchestrator.yaml"
    config: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config


def sole_offline_lane_job(project_root: Path, name: str) -> dict[str, Any]:
    """Return the offline-lane job (git.offline_lane_commands entry) named *name*, asserting it is the only one."""
    git: dict[str, Any] = load_orchestrator_config(project_root)["git"]
    jobs: list[dict[str, Any]] = [
        job for job in git.get("offline_lane_commands") or [] if job.get("name") == name
    ]
    assert len(jobs) == 1, (
        f"git.offline_lane_commands has {len(jobs)} entries named {name!r}; with none the lane "
        "never runs that job, with several every merge runs it more than once"
    )
    return jobs[0]


def lane_job_directory(project_root: Path, job: Mapping[str, Any]) -> Path:
    """Return the directory the offline lane runs *job*'s command in, *project_root* standing in for the lane worktree's root.

    That is the job's cwd under the root, or the root itself when the job sets none.
    The rule is dark-factory's LaneCommand.cwd (orchestrator/src/orchestrator/config.py), which defaults to '.'.
    """
    cwd: str = job.get("cwd", ".")
    return project_root / cwd
