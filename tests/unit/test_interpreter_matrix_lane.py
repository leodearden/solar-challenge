# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interpreter-matrix lane contract tests.

Every Python minor requires-python admits is re-verified recurrently: the
.python-version pin by the per-task verify, every other minor by the
orchestrator offline lane's interpreter-matrix job (tests/interpreter_matrix).
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from tests._collect_only import collected_node_ids, describe_outcome, requires_uv, run_collect_only
from tests._interpreters import off_pin_minor_versions, python_version_pin
from tests._orchestrator_config import lane_job_directory, load_orchestrator_config, sole_offline_lane_job

_MATRIX_JOB = "interpreter-matrix"


def _git_config(project_root: Path) -> dict[str, Any]:
    """Return the `git` mapping of dark-factory-orchestrator.yaml, where the offline-lane keys live."""
    git: dict[str, Any] = load_orchestrator_config(project_root)["git"]
    return git


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
    matrix_job = sole_offline_lane_job(project_root, _MATRIX_JOB)
    assert matrix_job.get("enabled", True) is True, (
        f"the {_MATRIX_JOB!r} lane job is disabled, so the off-pin interpreters are never re-verified"
    )


@requires_uv
def test_interpreter_matrix_job_collects_one_case_per_off_pin_admitted_minor(project_root: Path) -> None:
    """Run as the lane runs it, the interpreter-matrix job collects one case per off-pin admitted minor.

    Each case's node-id must name its interpreter: that node-id is the only
    attribution a fix task filed by the lane carries.
    """
    job = sole_offline_lane_job(project_root, _MATRIX_JOB)
    command = job["command"]

    result = run_collect_only(command, lane_job_directory(project_root, job))

    assert result.returncode == pytest.ExitCode.OK, (
        f"the {_MATRIX_JOB!r} lane job {command!r} failed to collect\n{describe_outcome(result)}"
    )
    expected = sorted(f"{major}.{minor}" for major, minor in off_pin_minor_versions(project_root))
    node_ids = collected_node_ids(result.stdout)
    collected = sorted(node_id.rpartition("[")[2].removesuffix("]") for node_id in node_ids)
    assert collected == expected, (
        f"the {_MATRIX_JOB!r} lane job collected {node_ids}; expected exactly one case per minor "
        f"requires-python admits other than the .python-version pin {python_version_pin(project_root)}, "
        f"each node-id ending in its interpreter: {expected}"
    )


def test_default_collection_never_reaches_the_interpreter_matrix(project_root: Path) -> None:
    """Collecting tests/ never reaches tests/interpreter_matrix, even with addopts cleared.

    That covers plain `pytest`, the per-task verify, and dark-factory's serial
    and confirm reruns, which append `-o addopts=`. PYTEST_ADDOPTS is dropped so
    only the repo's own exclusion is measured; the sibling test directories are
    ignored only to keep the collection fast.
    """
    siblings = [
        path
        for path in (project_root / "tests").iterdir()
        if path.is_dir() and path.name != "interpreter_matrix"
    ]
    env = {name: value for name, value in os.environ.items() if name != "PYTEST_ADDOPTS"}

    result = subprocess.run(
        [
            sys.executable, "-m", "pytest", "--collect-only", "-q", "-o", "addopts=", "tests",
            *(f"--ignore={sibling}" for sibling in siblings),
        ],
        cwd=project_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )

    assert result.returncode in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED), (
        f"collecting tests/ failed (exit {result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    reached = [line for line in result.stdout.splitlines() if line.startswith("tests/interpreter_matrix/")]
    assert not reached, (
        f"a default collection with addopts cleared reached the interpreter matrix: {reached}; "
        "every verify, and every serial or confirm rerun of it, would then run the whole matrix "
        "of verify suites, one per admitted interpreter"
    )
