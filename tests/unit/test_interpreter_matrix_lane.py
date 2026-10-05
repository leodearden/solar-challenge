# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interpreter-matrix lane contract tests.

Every Python minor requires-python admits is re-verified recurrently: the
.python-version pin by the per-task verify, every other minor by the
orchestrator offline lane's interpreter-matrix job (tests/interpreter_matrix).
"""

from collections.abc import Iterable
from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._interpreters import off_pin_minor_versions, python_version_pin
from tests._lane_collection import collect_lane_job, default_collection_node_ids_under, suite_node_ids_matching
from tests._orchestrator_config import git_config, lane_job_enabled, sole_offline_lane_job

_MATRIX_JOB = "interpreter-matrix"
_MATRIX_SUITE = "tests/interpreter_matrix"


def _off_pin_interpreters(project_root: Path) -> list[str]:
    """Return the minors the interpreter matrix must cover, as its node ids name them (e.g. "3.13"), sorted."""
    return sorted(f"{major}.{minor}" for major, minor in off_pin_minor_versions(project_root))


def _interpreters_named_by(node_ids: Iterable[str]) -> list[str]:
    """Return the interpreter each interpreter-matrix node id ends in (e.g. "3.13" for "...[3.13]"), sorted."""
    return sorted(node_id.rpartition("[")[2].removesuffix("]") for node_id in node_ids)


def test_offline_lane_is_enabled_with_an_interpreter_matrix_job(project_root: Path) -> None:
    """The offline lane must start, skip the seams this repo lacks, and run one interpreter-matrix job."""
    git = git_config(project_root)

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
    assert git.get("offline_lane_infra_enabled") is False, (
        "git.offline_lane_infra_enabled is not false; when on, that seam runs reify's "
        "tests/infra/run_all.sh, which this repo does not have, so every lane run goes red, and "
        "when unset it is on if dark-factory's default ever is"
    )
    matrix_job = sole_offline_lane_job(project_root, _MATRIX_JOB)
    assert lane_job_enabled(matrix_job), (
        f"the {_MATRIX_JOB!r} lane job is disabled, so the off-pin interpreters are never re-verified"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_interpreter_matrix_job_collects_one_case_per_off_pin_admitted_minor(
    project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the interpreter-matrix job collects one case per off-pin admitted minor.

    Each case's node-id must name its interpreter: that node-id is the only
    attribution a fix task filed by the lane carries.
    """
    collection = collect_lane_job(project_root, _MATRIX_JOB, env=uv_probe_environment)

    expected = _off_pin_interpreters(project_root)
    collected = _interpreters_named_by(collection.node_ids)
    assert collected == expected, (
        f"the {_MATRIX_JOB!r} lane job collected {collection.node_ids}; expected exactly one case per minor "
        f"requires-python admits other than the .python-version pin {python_version_pin(project_root)}, "
        f"each node-id ending in its interpreter: {expected}"
    )


def test_default_collection_never_reaches_the_interpreter_matrix(project_root: Path) -> None:
    """Collecting tests/ never reaches tests/interpreter_matrix, even with addopts cleared."""
    reached = default_collection_node_ids_under(project_root, _MATRIX_SUITE)

    assert not reached, (
        f"a default collection with addopts cleared reached the interpreter matrix: {reached}; "
        "every verify, and every serial or confirm rerun of it, would then run the whole matrix "
        "of verify suites, one per admitted interpreter"
    )


def test_interpreter_matrix_cases_are_slow_so_they_provision_outside_the_offline_guard(project_root: Path) -> None:
    """Each case's `uv run` provisions its interpreter's environment from PyPI whenever uv.lock changes."""
    slow_cases = _interpreters_named_by(suite_node_ids_matching(project_root, _MATRIX_SUITE, "slow"))
    fast_cases = suite_node_ids_matching(project_root, _MATRIX_SUITE, "not slow")

    expected = _off_pin_interpreters(project_root)
    why = (
        "a case not marked slow runs under tests/conftest.py's offline guard, where its child uv cannot "
        "download what a uv.lock change needs, so the lane would go red after every dependency change"
    )
    assert slow_cases == expected, (
        f"`-m slow` collected the interpreter-matrix cases {slow_cases}, not one per off-pin admitted minor "
        f"{expected}; {why}"
    )
    assert not fast_cases, f"`-m 'not slow'` collected the interpreter-matrix cases {fast_cases}; {why}"
