# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Usage::

    from tests._orchestrator_config import load_orchestrator_config, offline_lane_jobs

    test_command = load_orchestrator_config(project_root)["test_command"]
    matrix_jobs = offline_lane_jobs(project_root, "interpreter-matrix")
"""

from pathlib import Path
from typing import Any

import yaml


def load_orchestrator_config(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s dark-factory-orchestrator.yaml, parsed as YAML."""
    config_path = project_root / "dark-factory-orchestrator.yaml"
    config: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config


def offline_lane_jobs(project_root: Path, name: str) -> list[dict[str, Any]]:
    """Return the offline-lane command entries (git.offline_lane_commands) named *name*."""
    git: dict[str, Any] = load_orchestrator_config(project_root)["git"]
    return [job for job in git.get("offline_lane_commands") or [] if job.get("name") == name]
