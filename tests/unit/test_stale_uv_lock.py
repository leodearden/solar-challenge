# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stale uv.lock contract tests.

A commit that changes pyproject.toml's dependency declarations but not uv.lock
leaves the committed lock stale. A plain `uv run` silently re-locks it, so a
verify built on one passes and the stale lock merges. Every uv command the
orchestrator runs from dark-factory-orchestrator.yaml must instead refuse a
stale lock, failing with uv's error, which names the fix: run `uv lock`.

Each command runs verbatim through run_collect_only, so one that got past the
lock check would only collect its tests.
"""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._collect_only import describe_outcome, requires_uv, run_collect_only
from tests._orchestrator_config import (
    lane_job_directory,
    load_orchestrator_config,
    offline_lane_jobs,
    sole_offline_lane_job,
)
from tests._pyproject import load_project_table

pytestmark = requires_uv

# Parametrization happens at collection time, before any fixture exists.
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# dark-factory's three verify slots, in the order it starts them.
_VERIFY_COMMAND_KEYS = ("lint_command", "type_check_command", "test_command")

_PROJECT_FILES = ("pyproject.toml", "uv.lock", ".python-version")

_PROBE_EXTRA = "stale-lock-probe"

_THE_FIX = "uv lock"


def _run_uv(args: list[str], project: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", *args], cwd=project, env=env, capture_output=True, text=True, timeout=120)


def _fails_naming_the_fix(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and _THE_FIX in result.stdout + result.stderr


def _lock_digest(project: Path) -> str:
    """Return the SHA-256 of *project*'s uv.lock, so a failed comparison shows two digests, not two whole locks."""
    return hashlib.sha256((project / "uv.lock").read_bytes()).hexdigest()


@pytest.fixture
def uv_probe_environment(tmp_path: Path) -> dict[str, str]:
    """Return this process's environment, minus VIRTUAL_ENV, with a uv project environment of its own under *tmp_path*.

    No probe may touch an environment another run uses: inside the interpreter
    matrix, UV_PROJECT_ENVIRONMENT names that case's own venv.
    """
    env = {name: value for name, value in os.environ.items() if name != "VIRTUAL_ENV"}
    env["UV_PROJECT_ENVIRONMENT"] = str(tmp_path / "venv")
    return env


@pytest.fixture
def stale_lock_project(project_root: Path, tmp_path: Path, uv_probe_environment: dict[str, str]) -> Path:
    """Return a copy of the project's uv metadata whose pyproject.toml has outgrown its uv.lock.

    `uv add --frozen` writes a requirement without re-locking, as a commit that
    forgets `uv lock` does. The requirement is a core dependency put into a new
    extra, so uv tells the lock is stale from packages it already resolves, with
    no download; that holds under UV_OFFLINE=1 too.
    """
    project = tmp_path / "project"
    project.mkdir()
    for name in _PROJECT_FILES:
        shutil.copy2(project_root / name, project / name)
    requirement = load_project_table(project_root)["dependencies"][0]

    added = _run_uv(["add", "--frozen", "--optional", _PROBE_EXTRA, requirement], project, uv_probe_environment)
    assert added.returncode == 0, (
        f"`uv add --frozen` could not add {requirement!r} to the probe project\n{describe_outcome(added)}"
    )
    checked = _run_uv(["lock", "--check"], project, uv_probe_environment)
    assert checked.returncode == 1, (
        "`uv lock --check` did not report the probe project's uv.lock stale, so no test here proves "
        f"anything\n{describe_outcome(checked)}"
    )
    return project


def test_the_verify_refuses_a_stale_lock_naming_uv_lock(
    project_root: Path, stale_lock_project: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the orchestrator runs it on a stale uv.lock, the verify fails naming `uv lock`, and no verify command rewrites the lock.

    One that re-locked it would let every verify command after it pass.
    """
    config = load_orchestrator_config(project_root)
    stale_lock = _lock_digest(stale_lock_project)
    outcomes: dict[str, subprocess.CompletedProcess[str]] = {}

    for key in _VERIFY_COMMAND_KEYS:
        result = run_collect_only(config[key], stale_lock_project, env=uv_probe_environment)
        assert _lock_digest(stale_lock_project) == stale_lock, (
            f"{key} {config[key]!r} rewrote a stale uv.lock instead of refusing it, so a commit that forgot "
            f"`uv lock` passes the verify and its stale lock merges; the fix is `uv run --locked`\n"
            f"{describe_outcome(result)}"
        )
        outcomes[key] = result

    report = "\n".join(f"{key} {config[key]!r}: {describe_outcome(result)}" for key, result in outcomes.items())
    assert any(_fails_naming_the_fix(result) for result in outcomes.values()), (
        f"no verify command failed naming `{_THE_FIX}` on a stale uv.lock, so a commit that forgot it passes "
        f"the verify\n{report}"
    )


@pytest.mark.parametrize("job_name", [job["name"] for job in offline_lane_jobs(PROJECT_ROOT)])
def test_each_lane_job_refuses_a_stale_lock_naming_uv_lock(
    job_name: str, project_root: Path, stale_lock_project: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it on a stale uv.lock, each offline-lane job fails naming `uv lock` without rewriting the lock.

    The lane runs on main's committed tree, so a stale lock on main turns it red
    instead of being re-locked and tested.
    """
    job = sole_offline_lane_job(project_root, job_name)
    command = job["command"]
    stale_lock = _lock_digest(stale_lock_project)

    result = run_collect_only(command, lane_job_directory(stale_lock_project, job), env=uv_probe_environment)

    assert _lock_digest(stale_lock_project) == stale_lock, (
        f"the {job_name!r} lane job {command!r} rewrote a stale uv.lock instead of refusing it, so the lane "
        f"tests main against a lock nobody committed; the fix is `uv run --locked`\n{describe_outcome(result)}"
    )
    assert _fails_naming_the_fix(result), (
        f"the {job_name!r} lane job {command!r} did not fail naming `{_THE_FIX}` on a stale uv.lock, so a "
        f"stale lock on main does not turn the lane red with the fix named\n{describe_outcome(result)}"
    )
