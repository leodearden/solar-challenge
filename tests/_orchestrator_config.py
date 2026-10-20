# SPDX-License-Identifier: AGPL-3.0-or-later
"""Structured read access to dark-factory-orchestrator.yaml for the orchestrator contract tests.

Each command the yaml names is read as an OrchestratorCommand value: what it
runs, where, and in which DF_VERIFY_ROLE.

Usage::

    from tests._orchestrator_config import (
        VERIFY_SLOTS,
        git_config,
        lane_command,
        lane_commands,
        offline_lane_jobs,
        verify_command,
    )

    test_command = verify_command(project_root, "test_command")
    verify_commands = [verify_command(project_root, slot) for slot in VERIFY_SLOTS]
    e2e_job = lane_command(project_root, "e2e")
    every_lane_job = lane_commands(project_root)
    offline_lane_enabled = git_config(project_root).get("offline_lane_enabled")
    lane_job_names = [job["name"] for job in offline_lane_jobs(project_root)]
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, get_args

import yaml

VerifySlot = Literal["lint_command", "type_check_command", "test_command"]

VERIFY_SLOTS: tuple[VerifySlot, ...] = get_args(VerifySlot)

VerifyRole = Literal["task", "offline"]


@dataclass(frozen=True)
class OrchestratorCommand:
    """A command dark-factory-orchestrator.yaml names, as the orchestrator runs it.

    label is what failure messages call it, e.g. "test_command" or "lane job 'e2e'";
    command is the yaml string, verbatim; directory is where the orchestrator runs
    it, the project root standing in for the worktree's root; and role is the
    DF_VERIFY_ROLE dark-factory sets for it.
    """

    label: str
    command: str
    directory: Path
    role: VerifyRole

    def __post_init__(self) -> None:
        assert self.directory.is_dir(), (
            f"the {self.label} runs in {self.directory}, which is not a directory, so its command cannot start there"
        )


def verify_command(project_root: Path, slot: VerifySlot) -> OrchestratorCommand:
    """Return the verify slot *slot* of *project_root*'s yaml, run in *project_root* as a task verify runs it."""
    assert slot in VERIFY_SLOTS, f"{slot!r} is not a dark-factory verify slot; those are {VERIFY_SLOTS}"
    command = _load_orchestrator_config(project_root).get(slot)
    assert isinstance(command, str), (
        f"dark-factory-orchestrator.yaml's verify slot {slot!r} is {command!r} (None if the yaml lacks it), "
        "not a command string"
    )
    return OrchestratorCommand(label=slot, command=command, directory=project_root, role="task")


def lane_command(project_root: Path, name: str) -> OrchestratorCommand:
    """Return the offline-lane job *name* of *project_root*'s yaml as the lane runs it, *project_root* standing in for the lane worktree's root.

    The rules are dark-factory's LaneCommand (orchestrator/src/orchestrator/config.py):
    the lane runs the command with `sh -c` in <worktree>/<cwd>, cwd defaulting to
    '.', and skips the job unless it is enabled, which it is by default. It asserts
    the job is the only one of its name, its cwd a path string and its enabled flag
    a YAML boolean that is true, so a job the lane would not run as named fails
    here, naming the job.
    """
    job = _sole_offline_lane_job(project_root, name)
    label = f"lane job {name!r}"
    enabled = job.get("enabled", True)
    assert isinstance(enabled, bool), (
        f"the enabled flag of the {label} is {enabled!r}, not a YAML boolean; dark-factory rejects some such "
        "values and coerces others, so write true or false"
    )
    assert enabled, f"the {label} is disabled, so the lane never runs it"
    cwd = job.get("cwd", ".")
    assert isinstance(cwd, str), f"the cwd of the {label} is {cwd!r}, not a path string, so dark-factory rejects it"
    return OrchestratorCommand(label=label, command=job["command"], directory=project_root / cwd, role="offline")


def lane_commands(project_root: Path) -> tuple[OrchestratorCommand, ...]:
    """Return every offline-lane job of *project_root*'s yaml as lane_command builds it, in config order."""
    return tuple(lane_command(project_root, job["name"]) for job in offline_lane_jobs(project_root))


def _load_orchestrator_config(project_root: Path) -> dict[str, Any]:
    """Return *project_root*'s dark-factory-orchestrator.yaml, parsed as YAML."""
    config_path = project_root / "dark-factory-orchestrator.yaml"
    config: dict[str, Any] = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return config


def git_config(project_root: Path) -> dict[str, Any]:
    """Return the `git` mapping (dark-factory's GitConfig) of *project_root*'s dark-factory-orchestrator.yaml, where the offline-lane settings live."""
    git: dict[str, Any] = _load_orchestrator_config(project_root)["git"]
    return git


def offline_lane_jobs(project_root: Path) -> list[dict[str, Any]]:
    """Return *project_root*'s offline-lane jobs (git.offline_lane_commands entries) in config order; none when that key is absent or empty."""
    jobs: list[dict[str, Any]] = git_config(project_root).get("offline_lane_commands") or []
    return jobs


def _sole_offline_lane_job(project_root: Path, name: str) -> dict[str, Any]:
    """Return the offline-lane job (git.offline_lane_commands entry) named *name*, asserting it is the only one."""
    jobs = [job for job in offline_lane_jobs(project_root) if job.get("name") == name]
    assert len(jobs) == 1, (
        f"git.offline_lane_commands has {len(jobs)} entries named {name!r}; with none the lane "
        "never runs that job, with several every merge runs it more than once"
    )
    return jobs[0]
