# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Usage::

    from tests._orchestrator_config import load_orchestrator_config, sole_offline_lane_job

    test_command = load_orchestrator_config(project_root)["test_command"]
    matrix_job = sole_offline_lane_job(project_root, "interpreter-matrix")
"""

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
