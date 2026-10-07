# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline-lane contract tests.

After every merge, the orchestrator's offline lane runs each job in
dark-factory-orchestrator.yaml's git.offline_lane_commands, and each job runs a
suite the per-task verify never runs. These tests pin the contracts every job
keeps, with one row per job in LANE_JOBS, so a new lane job adds one row. A
test only one job needs stays in that job's module, as in test_pvgis_lane.py
and test_interpreter_matrix_lane.py.
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._lane_collection import collect_lane_job, default_collection_node_ids_under, suite_node_ids_matching
from tests._orchestrator_config import lane_job_enabled, sole_offline_lane_job


class LaneContract(Enum):
    """A contract a LANE_JOBS row may list for its job.

    Every job also keeps the one contract no row lists: the lane runs exactly
    one enabled job of its name.
    """

    # Run as the lane runs it, the job collects at least one test, every one in its suite.
    COLLECTS_ONLY_ITS_SUITE = auto()
    # A default collection of tests/ with addopts cleared never reaches the suite.
    NEVER_IN_A_DEFAULT_COLLECTION = auto()
    # `-m 'not slow'` selects none of the suite's tests.
    EVERY_TEST_SLOW = auto()


@dataclass(frozen=True)
class LaneJob:
    """An offline-lane job, the suite its command runs, and the contracts this module checks for it.

    name is the job's git.offline_lane_commands name, and the id of each test
    run for it. suite is relative to the root, as node ids are. if_unrun is a
    clause stating what goes unseen while the lane does not run the suite.
    """

    name: str
    suite: str
    if_unrun: str
    checked: frozenset[LaneContract]


LANE_JOBS: tuple[LaneJob, ...] = (
    LaneJob(
        "e2e",
        "tests/e2e",
        if_unrun="e2e regressions go unseen",
        checked=frozenset({LaneContract.COLLECTS_ONLY_ITS_SUITE}),
    ),
    LaneJob(
        "css-build",
        "tests/css_build",
        if_unrun="a stylesheet its sources no longer build to, or a stale Tailwind license text, goes unseen",
        checked=frozenset(LaneContract),
    ),
    LaneJob(
        "newest-releases",
        "tests/newest_releases",
        if_unrun="an upstream release that breaks this code goes unseen until a consumer re-locks",
        checked=frozenset(LaneContract),
    ),
)


def _checked_for(contract: LaneContract) -> tuple[LaneJob, ...]:
    """Return the LANE_JOBS rows that list *contract*, in table order."""
    return tuple(job for job in LANE_JOBS if contract in job.checked)


def _job_name(job: LaneJob) -> str:
    """Return *job*'s name, the test id that makes each failing node id name its job."""
    return job.name


@pytest.mark.parametrize("job", LANE_JOBS, ids=_job_name)
def test_the_lane_runs_one_enabled_job_of_its_name(job: LaneJob, project_root: Path) -> None:
    """The offline lane runs exactly one job of the row's name, and it is enabled."""
    lane_job = sole_offline_lane_job(project_root, job.name)

    assert lane_job_enabled(lane_job), f"the {job.name!r} lane job is disabled, so {job.if_unrun}"


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
@pytest.mark.parametrize("job", _checked_for(LaneContract.COLLECTS_ONLY_ITS_SUITE), ids=_job_name)
def test_the_job_collects_its_suite_and_nothing_else(
    job: LaneJob, project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the job collects at least one test, every one in its suite.

    The repo's pytest addopts stay in force, as they do in the lane, so a job
    whose suite they --ignore, as they do tests/e2e, collects it only by naming
    it explicitly. The job's uv environment is fresh, as the lane's is, so it
    holds only the extras the job names.
    """
    collection = collect_lane_job(project_root, job.name, env=uv_probe_environment)

    assert collection.node_ids, (
        f"the {job.name!r} lane job {collection.command!r} collected no tests, so the lane stays green while "
        f"{job.if_unrun}\n{collection.outcome}"
    )
    outside = collection.node_ids_outside(job.suite)
    assert not outside, (
        f"the {job.name!r} lane job {collection.command!r} collected tests outside {job.suite}, the one suite it "
        f"exists to run, so after every merge it runs them beside that suite: {outside}"
    )


@pytest.mark.parametrize("job", _checked_for(LaneContract.NEVER_IN_A_DEFAULT_COLLECTION), ids=_job_name)
def test_a_default_collection_never_reaches_the_suite(job: LaneJob, project_root: Path) -> None:
    """Collecting tests/ never reaches the job's suite, even with addopts cleared."""
    reached = default_collection_node_ids_under(project_root, job.suite)

    assert not reached, (
        f"a default collection with addopts cleared reached {job.suite}: {reached}; plain `pytest` would then run "
        f"that suite, which only the {job.name!r} lane job is meant to run, and only its tests' marks would keep it "
        "out of the per-task verify; name its directory in tests/conftest.py's collect_ignore"
    )


@pytest.mark.parametrize("job", _checked_for(LaneContract.EVERY_TEST_SLOW), ids=_job_name)
def test_every_test_in_the_suite_is_slow(job: LaneJob, project_root: Path) -> None:
    """Every test in the job's suite is marked slow, so it reaches the live service it needs outside the offline guard.

    An empty suite passes vacuously; the job's collection check pins that it has
    tests.
    """
    fast_tests = suite_node_ids_matching(project_root, job.suite, "not slow")

    assert not fast_tests, (
        f"`-m 'not slow'` collected the {job.suite} tests {fast_tests}; a test there not marked slow runs under "
        "tests/conftest.py's offline guard, which refuses the live service the suite needs, so the "
        f"{job.name!r} lane job goes red whenever such a test needs that service; mark it slow"
    )
