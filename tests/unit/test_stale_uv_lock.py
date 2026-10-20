# SPDX-License-Identifier: AGPL-3.0-or-later
"""Stale uv.lock contract tests.

A commit that changes pyproject.toml's dependency declarations but not uv.lock
leaves the committed lock stale. A plain `uv run` silently re-locks it, so a
verify built on one passes and the stale lock merges. Every uv command the
orchestrator runs from dark-factory-orchestrator.yaml must instead refuse a
stale lock, failing with uv's error, which names the fix: run `uv lock`.

Each command runs verbatim, through run_collect_only, on a probe holding only
the project's uv metadata and orchestrator config, and no source. Each command
is read from the probe's copy of the config, so it runs in the probe. A command
that gets past the lock check, by re-locking or, like `uv run --frozen`, by
running on the stale pins, fails later, building the package, without naming
`uv lock`. So the tests look for that phrase, not merely a non-zero exit.

The tests run every uv command offline, reading the package index from uv's
cache (offline_uv_probe_environment says why).
"""

import hashlib
import shutil
import subprocess
from pathlib import Path

import pytest

from tests._collect_only import requires_uv, run_collect_only
from tests._command_runner import describe_outcome
from tests._orchestrator_config import VERIFY_SLOTS, OrchestratorCommand, lane_commands, verify_command
from tests._pyproject import load_project_table

pytestmark = requires_uv

_PROJECT_FILES = ("pyproject.toml", "uv.lock", ".python-version", "dark-factory-orchestrator.yaml")

_PROBE_EXTRA = "stale-lock-probe"

_THE_FIX = "uv lock"


def _run_uv(args: list[str], project: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["uv", *args], cwd=project, env=env, capture_output=True, text=True, timeout=120)


def _names_the_fix(result: subprocess.CompletedProcess[str]) -> bool:
    return _THE_FIX in result.stdout + result.stderr


def _fails_naming_the_fix(result: subprocess.CompletedProcess[str]) -> bool:
    return result.returncode != 0 and _names_the_fix(result)


def _lock_digest(project: Path) -> str:
    """Return the SHA-256 of *project*'s uv.lock, so a failed comparison shows two digests, not two whole locks."""
    return hashlib.sha256((project / "uv.lock").read_bytes()).hexdigest()


def _reset_to_copy_of(pristine: Path, project: Path) -> None:
    """Make *project* a fresh copy of *pristine*, so nothing a command wrote there earlier is left."""
    shutil.rmtree(project)
    shutil.copytree(pristine, project)


@pytest.fixture
def offline_uv_probe_environment(uv_probe_environment: dict[str, str]) -> dict[str, str]:
    """Return uv_probe_environment with uv's network access off, so every uv command here reads the package index from uv's cache alone.

    Telling a lock stale makes uv re-resolve the project. Online, uv revalidates
    each cached index page older than PyPI's ten-minute max-age, so the probes
    would need PyPI on most runs. Offline, the cache must already hold the index
    data that resolution reads: `uv sync` does not fetch it, but
    `uv lock --dry-run --refresh`, run once with network access, does.

    test_uv_in_the_probe_environment_reads_the_package_index_only_from_its_cache
    pins the offline switch: dropping UV_OFFLINE fails it.
    """
    return {**uv_probe_environment, "UV_OFFLINE": "1"}


@pytest.fixture
def stale_lock_project(project_root: Path, tmp_path: Path, offline_uv_probe_environment: dict[str, str]) -> Path:
    """Return a copy of the project's uv metadata and orchestrator config, and no source, whose pyproject.toml has outgrown its uv.lock.

    `uv add --frozen` writes a requirement without re-locking, as a commit that
    forgets `uv lock` does. The requirement is a core dependency put into a new
    extra, so uv tells the lock is stale from packages it already resolves, with
    no download; run offline, the check needs only index data already in uv's cache.
    """
    project = tmp_path / "project"
    project.mkdir()
    for name in _PROJECT_FILES:
        shutil.copy2(project_root / name, project / name)
    requirement = load_project_table(project_root)["dependencies"][0]

    added = _run_uv(
        ["add", "--frozen", "--optional", _PROBE_EXTRA, requirement], project, offline_uv_probe_environment
    )
    assert added.returncode == 0, (
        f"`uv add --frozen` could not add {requirement!r} to the probe project\n{describe_outcome(added)}"
    )
    checked = _run_uv(["lock", "--check"], project, offline_uv_probe_environment)
    assert checked.returncode == 1 and _names_the_fix(checked), (
        "offline, `uv lock --check` did not report the probe project's uv.lock stale, so no test here proves "
        "anything. uv tells it stale by re-resolving the project from the package index data in its cache; "
        "if it reports packages missing from that cache (`uv sync` does not fill it), run "
        f"`uv lock --dry-run --refresh` once with network access\n{describe_outcome(checked)}"
    )
    return project


def test_the_verify_refuses_a_stale_lock_naming_uv_lock(
    stale_lock_project: Path, offline_uv_probe_environment: dict[str, str]
) -> None:
    """Run as the orchestrator runs it on a stale uv.lock, the verify fails naming `uv lock`, and no verify command rewrites the lock.

    One that re-locked it would let every verify command after it pass.
    """
    stale_lock = _lock_digest(stale_lock_project)
    outcomes: list[tuple[OrchestratorCommand, subprocess.CompletedProcess[str]]] = []

    for slot in VERIFY_SLOTS:
        command = verify_command(stale_lock_project, slot)
        result = run_collect_only(command, env=offline_uv_probe_environment)
        assert _lock_digest(stale_lock_project) == stale_lock, (
            f"{command.label} {command.command!r} rewrote a stale uv.lock instead of refusing it, so a commit that "
            f"forgot `uv lock` passes the verify and its stale lock merges; the fix is `uv run --locked`\n"
            f"{describe_outcome(result)}"
        )
        outcomes.append((command, result))

    report = "\n".join(
        f"{command.label} {command.command!r}: {describe_outcome(result)}" for command, result in outcomes
    )
    assert any(_fails_naming_the_fix(result) for _, result in outcomes), (
        f"no verify command failed naming `{_THE_FIX}` on a stale uv.lock, so a commit that forgot it passes "
        f"the verify\n{report}"
    )


def test_each_lane_job_refuses_a_stale_lock_naming_uv_lock(
    stale_lock_project: Path, tmp_path: Path, offline_uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it on a stale uv.lock, each offline-lane job fails naming `uv lock` without rewriting the lock.

    The lane runs on main's committed tree, so a stale lock on main turns it red
    instead of being re-locked and tested. Each job runs on a fresh copy of the
    stale probe, and every job's failure is reported, so a job that rewrites the
    lock neither stops the probe of the jobs after it nor hands them a lock that is
    no longer stale.
    """
    lane_jobs = lane_commands(stale_lock_project)
    assert lane_jobs, "git.offline_lane_commands holds no job, so this probe checks nothing"
    pristine = shutil.copytree(stale_lock_project, tmp_path / "pristine-project")
    stale_lock = _lock_digest(pristine)
    failures: list[str] = []

    for lane_job in lane_jobs:
        _reset_to_copy_of(pristine, stale_lock_project)
        result = run_collect_only(lane_job, env=offline_uv_probe_environment)
        if _lock_digest(stale_lock_project) != stale_lock:
            failures.append(
                f"the {lane_job.label} {lane_job.command!r} rewrote a stale uv.lock instead of refusing it, so the "
                f"lane tests main against a lock nobody committed; the fix is `uv run --locked`\n"
                f"{describe_outcome(result)}"
            )
        elif not _fails_naming_the_fix(result):
            failures.append(
                f"the {lane_job.label} {lane_job.command!r} did not fail naming `{_THE_FIX}` on a stale uv.lock, so a "
                f"stale lock on main does not turn the lane red with the fix named\n{describe_outcome(result)}"
            )

    assert not failures, "\n\n".join(failures)


def test_uv_in_the_probe_environment_reads_the_package_index_only_from_its_cache(
    stale_lock_project: Path, tmp_path: Path, offline_uv_probe_environment: dict[str, str]
) -> None:
    """With its cache empty, uv in the probe environment cannot re-resolve the stale probe, so it gives no verdict on the lock.

    Online it would fetch the index from PyPI and report the lock stale or, with PyPI out of
    reach, fail the request (exit 2). The same outcome is what lets stale_lock_project's
    precondition tell a cold cache from a stale lock.
    """
    empty_cache_environment = {**offline_uv_probe_environment, "UV_CACHE_DIR": str(tmp_path / "empty-uv-cache")}

    checked = _run_uv(["lock", "--check"], stale_lock_project, empty_cache_environment)

    assert checked.returncode == 1 and not _names_the_fix(checked), (
        "with its cache empty, uv in the probe environment did not fail for want of the package index "
        f"(exit 1, not naming `{_THE_FIX}`): it fetched the index from PyPI, or tried to (exit 2), so every "
        f"probe here needs PyPI whenever uv's cached index pages are stale\n{describe_outcome(checked)}"
    )
