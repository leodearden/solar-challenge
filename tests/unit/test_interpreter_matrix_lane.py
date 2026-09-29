# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interpreter-matrix lane contract tests.

Every Python minor requires-python admits is re-verified recurrently: the
.python-version pin by the per-task verify, every other minor by the
orchestrator offline lane's interpreter-matrix job (tests/interpreter_matrix).
"""

from pathlib import Path
from typing import Any

from tests._orchestrator_config import load_orchestrator_config

_MATRIX_JOB = "interpreter-matrix"


def _git_config(project_root: Path) -> dict[str, Any]:
    """Return the `git` mapping of dark-factory-orchestrator.yaml, where the offline-lane keys live."""
    git: dict[str, Any] = load_orchestrator_config(project_root)["git"]
    return git


def _matrix_jobs(git: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the offline-lane command entries named interpreter-matrix."""
    return [job for job in git.get("offline_lane_commands") or [] if job.get("name") == _MATRIX_JOB]


def test_offline_lane_is_enabled_with_an_interpreter_matrix_job(project_root: Path) -> None:
    """The offline lane must start, skip the seams this repo lacks, and run one interpreter-matrix job."""
    git = _git_config(project_root)

    assert git.get("offline_lane_enabled") is True, (
        "git.offline_lane_enabled is not true, so the offline lane never starts and no "
        "interpreter other than the .python-version pin is re-verified"
    )
    assert git.get("persistent_offline_deep_worktree") is True, (
        "git.persistent_offline_deep_worktree is not true, so the lane has no _offline-deep "
        "worktree to run in and never starts"
    )
    assert git.get("offline_lane_legacy_numeric_enabled") is False, (
        "git.offline_lane_legacy_numeric_enabled is not false; that default-on seam runs "
        "scripts/run-offline-deep.sh, which this repo does not have, so every lane run goes red"
    )
    assert git.get("offline_lane_infra_enabled", False) is False, (
        "git.offline_lane_infra_enabled is on; that seam runs reify's tests/infra/run_all.sh, "
        "which this repo does not have, so every lane run goes red"
    )
    matrix_jobs = _matrix_jobs(git)
    assert len(matrix_jobs) == 1, (
        f"git.offline_lane_commands has {len(matrix_jobs)} entries named {_MATRIX_JOB!r}; with "
        "none the off-pin interpreters are never re-verified, with several every merge runs "
        "the matrix more than once"
    )
    assert matrix_jobs[0].get("enabled", True) is True, (
        f"the {_MATRIX_JOB!r} lane job is disabled, so the off-pin interpreters are never re-verified"
    )
