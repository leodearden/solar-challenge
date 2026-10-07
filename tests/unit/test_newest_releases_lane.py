# SPDX-License-Identifier: AGPL-3.0-or-later
"""newest-releases lane contract tests.

tests/newest_releases re-runs the verify suite on the newest releases
pyproject.toml's dependency ranges admit. It needs PyPI, so the per-task verify
never runs it. The orchestrator offline lane's newest-releases job runs it
after every merge instead, so an upstream release that breaks this code files a
fix task before a consumer that re-locks meets it.
"""

from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._lane_collection import collect_lane_job, default_collection_node_ids_under, suite_node_ids_matching
from tests._orchestrator_config import lane_job_enabled, sole_offline_lane_job

_NEWEST_RELEASES_JOB = "newest-releases"
_NEWEST_RELEASES_SUITE = "tests/newest_releases"


def test_offline_lane_runs_one_enabled_newest_releases_job(project_root: Path) -> None:
    """The offline lane runs exactly one newest-releases job, and it is enabled."""
    job = sole_offline_lane_job(project_root, _NEWEST_RELEASES_JOB)

    assert lane_job_enabled(job), (
        f"the {_NEWEST_RELEASES_JOB!r} lane job is disabled, so an upstream release that breaks this code goes "
        "unseen until a consumer re-locks"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_newest_releases_job_collects_the_newest_releases_suite_and_nothing_else(
    project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the newest-releases job collects at least one test, every one in tests/newest_releases.

    The job's uv environment is fresh, as the lane's is, so it holds only the
    extras the job names.
    """
    collection = collect_lane_job(project_root, _NEWEST_RELEASES_JOB, env=uv_probe_environment)

    assert collection.node_ids, (
        f"the {_NEWEST_RELEASES_JOB!r} lane job {collection.command!r} collected no tests, so the lane stays "
        f"green while the newest releases go untested\n{collection.outcome}"
    )
    outside_suite = collection.node_ids_outside(_NEWEST_RELEASES_SUITE)
    assert not outside_suite, (
        f"the {_NEWEST_RELEASES_JOB!r} lane job {collection.command!r} collected tests outside "
        f"{_NEWEST_RELEASES_SUITE}, which the per-task verify already runs: {outside_suite}"
    )


def test_default_collection_never_reaches_the_newest_releases_suite(project_root: Path) -> None:
    """Collecting tests/ never reaches tests/newest_releases, even with addopts cleared."""
    reached = default_collection_node_ids_under(project_root, _NEWEST_RELEASES_SUITE)

    assert not reached, (
        f"a default collection with addopts cleared reached the newest_releases suite: {reached}; plain `pytest` "
        "would then re-run the whole verify suite inside itself, on releases fetched from PyPI, and only the "
        "suite's slow mark would keep it out of the per-task verify"
    )


def test_newest_releases_tests_are_slow_so_uv_reaches_pypi_outside_the_offline_guard(project_root: Path) -> None:
    """Every newest_releases test is marked slow, since uv resolves and downloads the newest releases from PyPI.

    test_newest_releases_job_collects_the_newest_releases_suite_and_nothing_else
    pins that the suite has tests.
    """
    fast_tests = suite_node_ids_matching(project_root, _NEWEST_RELEASES_SUITE, "not slow")

    assert not fast_tests, (
        f"`-m 'not slow'` collected the newest_releases tests {fast_tests}; a newest_releases test not marked "
        "slow runs under tests/conftest.py's offline guard, whose proxy refuses uv's requests to PyPI, so the "
        "lane would go red after every merge"
    )
