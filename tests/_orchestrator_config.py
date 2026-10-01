# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Usage::

    from tests._orchestrator_config import (
        lane_job_directory,
        lane_job_enabled,
        load_orchestrator_config,
        sole_offline_lane_job,
    )

    test_command = load_orchestrator_config(project_root)["test_command"]
    matrix_job = sole_offline_lane_job(project_root, "interpreter-matrix")
    matrix_directory = lane_job_directory(project_root, matrix_job)
    matrix_enabled = lane_job_enabled(matrix_job)
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
    It asserts the cwd is a path string that resolves to a directory, so a cwd the lane cannot use fails here, naming the job.
    """
    cwd = job.get("cwd", ".")
    assert isinstance(cwd, str), (
        f"the {job.get('name')!r} lane job's cwd is {cwd!r}, not a path string; dark-factory's "
        "LaneCommand.cwd must be a string, so the orchestrator rejects the config"
    )
    directory = project_root / cwd
    assert directory.is_dir(), (
        f"the {job.get('name')!r} lane job's cwd {cwd!r} resolves to {directory}, which is not a "
        "directory, so the lane cannot start the job's command"
    )
    return directory


def lane_job_enabled(job: Mapping[str, Any]) -> bool:
    """Return whether the offline lane runs *job*: its enabled flag, or True when the job sets none.

    The rule is dark-factory's LaneCommand.enabled (orchestrator/src/orchestrator/config.py), which defaults to True;
    the lane skips a job whose flag is false.
    It asserts the flag is a YAML boolean, so a flag this rule cannot read as the lane does fails here, naming the job.
    """
    enabled = job.get("enabled", True)
    assert isinstance(enabled, bool), (
        f"the {job.get('name')!r} lane job's enabled is {enabled!r}, not a YAML boolean; dark-factory's "
        "LaneCommand.enabled rejects some such values and coerces others, so write true or false"
    )
    return enabled
