# SPDX-License-Identifier: AGPL-3.0-or-later
"""Offline-lane contract tests.

After every merge, the orchestrator's offline lane runs each job in
dark-factory-orchestrator.yaml's git.offline_lane_commands, and each job runs a
suite the per-task verify never runs. These tests pin the git settings that
start the lane, and the contracts every job keeps, with one row per job in
LANE_JOBS, so a new lane job adds one row. A test only one job needs stays in
that job's module, as in test_pvgis_lane.py and test_interpreter_matrix_lane.py.
One test checks that every slow test runs in some LANE_JOBS job, unless
SLOW_TESTS_NO_LANE_JOB_RUNS lists it with the live service it needs.
"""

import functools
import os
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path, PurePosixPath

import pytest

from tests._collect_only import Collection, requires_uv
from tests._command_runner import describe_outcome, run_command
from tests._computed_once import ComputedOnce
from tests._lane_collection import (
    collect_lane_job,
    default_collection_node_ids_under,
    every_test_matching,
    suite_node_ids_matching,
)
from tests._network_guard import send_child_processes_to_a_dead_proxy
from tests._orchestrator_config import (
    git_config,
    lane_command,
    lane_jobs_declaring_an_outage_probe,
    lane_outage_probe,
    offline_lane_jobs,
)
from tests._uv_env import SharedUvEnvironments


class LaneContract(Enum):
    """A contract a LANE_JOBS row may list for its job.

    Every job also keeps a contract no row lists: the lane runs exactly one
    enabled job of its name. A job whose suite lies directly under tests/ keeps
    another, which its suite's path states: a default collection of tests/
    with addopts cleared never reaches the suite.
    """

    # Run as the lane runs it, the job collects at least one test, every one in its suite.
    COLLECTS_ONLY_ITS_SUITE = auto()
    # `-m 'not slow'` selects none of the suite's tests.
    EVERY_TEST_SLOW = auto()


@dataclass(frozen=True)
class LaneJob:
    """An offline-lane job, the suite its command runs, and the contracts this module checks for it.

    name is the job's git.offline_lane_commands name, and the id of each test
    run for it. suite is relative to the root, as node ids are. if_unrun is a
    clause stating what goes unseen while the lane does not run the suite.
    service is the live service the suite needs, as the job's outage probe names
    it at the start of an outage line, or None for a suite that needs none.
    """

    name: str
    suite: str
    if_unrun: str
    checked: frozenset[LaneContract]
    service: str | None


LANE_JOBS: tuple[LaneJob, ...] = (
    # test_interpreter_matrix_lane.py checks its COLLECTS_ONLY_ITS_SUITE more strictly: one case per off-pin minor.
    LaneJob(
        "interpreter-matrix",
        "tests/interpreter_matrix",
        if_unrun="the interpreters other than the .python-version pin are never re-verified",
        checked=frozenset({LaneContract.EVERY_TEST_SLOW}),
        service="PyPI",
    ),
    LaneJob(
        "e2e",
        "tests/e2e",
        if_unrun="e2e regressions go unseen",
        checked=frozenset({LaneContract.COLLECTS_ONLY_ITS_SUITE}),
        service=None,
    ),
    LaneJob(
        "pvgis",
        "tests/integration/test_pvgis.py",
        if_unrun="a change in PVGIS's or pvlib's response goes unseen",
        checked=frozenset({LaneContract.COLLECTS_ONLY_ITS_SUITE}),
        service="PVGIS",
    ),
    LaneJob(
        "css-build",
        "tests/css_build",
        if_unrun="a stylesheet its sources no longer build to, or a stale Tailwind license text, goes unseen",
        checked=frozenset(LaneContract),
        service="npm registry",
    ),
    LaneJob(
        "newest-releases",
        "tests/newest_releases",
        if_unrun="an upstream release that breaks this code goes unseen until a consumer re-locks",
        checked=frozenset(LaneContract),
        service="PyPI",
    ),
)


@dataclass(frozen=True)
class SlowTestsNoLaneJobRuns:
    """Slow tests no LANE_JOBS job runs, and the live service they need.

    node_ids are exact node ids, compared by equality, never by prefix: a new
    test in a listed class is listed only once its own id is.
    """

    service: str
    node_ids: frozenset[str]


SLOW_TESTS_NO_LANE_JOB_RUNS: tuple[SlowTestsNoLaneJobRuns, ...] = (
    SlowTestsNoLaneJobRuns(
        service="the Anthropic API",
        node_ids=frozenset(
            {
                "tests/unit/web_assistant/test_chat.py::TestChatLiveSmoke::test_single_turn_returns_nonempty_reply",
                "tests/unit/web_assistant/test_chat.py::TestChatLiveSmoke::test_second_turn_shows_cache_hit",
            }
        ),
    ),
    # docs/prds/assistant-facts-from-engine.md §6 decision 3 keeps this guard out of the pvgis lane job.
    SlowTestsNoLaneJobRuns(
        service="PVGIS",
        node_ids=frozenset(
            {
                "tests/integration/test_pv_performance_ratio.py::TestBristolPerformanceRatio::test_the_default_system_performs_at_mcs_ratio",
                "tests/integration/test_pv_performance_ratio.py::TestBristolPerformanceRatio::test_the_default_systems_yield_is_validations_bristol_constant",
            }
        ),
    ),
)

# tests/e2e's modules import the e2e extra, so only every extra imports every test module.
_EVERY_EXTRA_PYTEST = ("uv", "run", "--locked", "--all-extras", "pytest")


def _checked_for(contract: LaneContract) -> tuple[LaneJob, ...]:
    """Return the LANE_JOBS rows that list *contract*, in table order."""
    return tuple(job for job in LANE_JOBS if contract in job.checked)


def _needing_a_live_service() -> tuple[LaneJob, ...]:
    """Return the LANE_JOBS rows that name a service, in table order."""
    return tuple(job for job in LANE_JOBS if job.service is not None)


def _whose_suite_lies_directly_under_tests() -> tuple[LaneJob, ...]:
    """Return the LANE_JOBS rows whose suite lies directly under tests/, in table order."""
    return tuple(job for job in LANE_JOBS if PurePosixPath(job.suite).parent == PurePosixPath("tests"))


def test_offline_lane_starts_and_skips_the_seams_this_repo_lacks(project_root: Path) -> None:
    """The offline lane must start, and skip the seams this repo lacks."""
    git = git_config(project_root)

    assert git.get("offline_lane_enabled") is True, (
        "git.offline_lane_enabled is not true, so the offline lane never starts and none of its jobs runs"
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


@pytest.mark.parametrize("job", LANE_JOBS, ids=lambda job: job.name)
def test_the_lane_runs_one_enabled_job_of_its_name(job: LaneJob, project_root: Path) -> None:
    """The offline lane runs exactly one job of the row's name, and it is enabled, as lane_command asserts."""
    try:
        lane_command(project_root, job.name)
    except AssertionError as failure:
        pytest.fail(f"{failure}; while the lane does not run the {job.name!r} job, {job.if_unrun}")


def test_every_offline_lane_job_has_a_row_in_lane_jobs(project_root: Path) -> None:
    """Every job the offline lane runs has a LANE_JOBS row, so no lane job goes without its contracts."""
    row_names = {job.name for job in LANE_JOBS}
    rowless = [
        lane_job.get("name") for lane_job in offline_lane_jobs(project_root) if lane_job.get("name") not in row_names
    ]

    assert not rowless, (
        f"git.offline_lane_commands runs {rowless}, with no row in LANE_JOBS, so none of the lane contracts is "
        "checked for them; add a row naming each job's suite and the contracts it keeps"
    )


@pytest.fixture(scope="module")
def lane_job_collection(shared_uv_probe_environments: SharedUvEnvironments) -> ComputedOnce[Collection]:
    """Each lane job collected as the lane runs it, by the first test that asks, and shared by the rest."""
    return ComputedOnce(functools.partial(collect_lane_job, env_for=shared_uv_probe_environments.for_command))


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
@pytest.mark.parametrize("job", _checked_for(LaneContract.COLLECTS_ONLY_ITS_SUITE), ids=lambda job: job.name)
def test_the_job_collects_its_suite_and_nothing_else(
    job: LaneJob, project_root: Path, lane_job_collection: ComputedOnce[Collection]
) -> None:
    """Run as the lane runs it, the job collects at least one test, every one in its suite.

    The repo's pytest addopts stay in force, as they do in the lane. A suite
    that tests/conftest.py's collect_ignore names, as it names tests/e2e, is
    collected only because the job names it explicitly. The job's uv
    environment is fresh, as the lane's is, and shared only with probes whose
    uv run options are the same, so it holds only the extras the job names.
    """
    collection = lane_job_collection(project_root, job.name)

    node_ids = collection.node_ids()
    assert node_ids, (
        f"the {job.name!r} lane job {collection.command!r} collected no tests, so the lane stays green while "
        f"{job.if_unrun}\n{collection.describe()}"
    )
    outside = collection.node_ids_outside(job.suite)
    assert not outside, (
        f"the {job.name!r} lane job {collection.command!r} collected tests outside {job.suite}, the one suite it "
        f"exists to run, so after every merge it runs them beside that suite: {outside}"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_every_slow_test_runs_in_a_lane_job_or_is_listed_as_one_no_lane_job_runs(
    project_root: Path,
    shared_uv_probe_environments: SharedUvEnvironments,
    lane_job_collection: ComputedOnce[Collection],
) -> None:
    """Every slow test runs in some LANE_JOBS job, as the lane runs it, unless SLOW_TESTS_NO_LANE_JOB_RUNS lists it.

    The slow tests are collected across all of tests/ with every extra, the
    lane-only suites included. Each listed id must still be a slow test no lane
    job runs.
    """
    slow = every_test_matching(
        project_root, "slow", pytest_invocation=_EVERY_EXTRA_PYTEST, env_for=shared_uv_probe_environments.for_command
    )
    laned = {node_id for job in LANE_JOBS for node_id in lane_job_collection(project_root, job.name).node_ids()}
    unlaned = [test.node_id for test in slow if test.node_id not in laned]
    listed = {node_id: entry.service for entry in SLOW_TESTS_NO_LANE_JOB_RUNS for node_id in entry.node_ids}

    unlisted = [node_id for node_id in unlaned if node_id not in listed]
    assert not unlisted, (
        f"no lane job runs the slow tests {unlisted}, and the per-task verify deselects every slow test, so nothing "
        "runs them; seed what such a test fetches and drop its slow mark if it needs no live service (CLAUDE.md, "
        "\"Offline fast tests\"), bring it into a lane job's suite, or list it in SLOW_TESTS_NO_LANE_JOB_RUNS, naming "
        "the live service no lane job runs it against"
    )
    stale = {node_id: listed[node_id] for node_id in sorted(listed.keys() - set(unlaned))}
    assert not stale, (
        f"SLOW_TESTS_NO_LANE_JOB_RUNS lists {stale}, each id with its entry's service, though none is a slow test no "
        "lane job runs: `-m slow` no longer selects it, or a lane job now runs it; remove each from its entry"
    )


@pytest.mark.parametrize("job", _whose_suite_lies_directly_under_tests(), ids=lambda job: job.name)
def test_a_default_collection_never_reaches_the_suite(job: LaneJob, project_root: Path) -> None:
    """Collecting tests/ never reaches the job's suite, even with addopts cleared.

    Every job whose suite lies directly under tests/ keeps this contract, since
    tests/conftest.py's collect_ignore is what keeps such a suite lane-only.
    pvgis's suite is a file under tests/integration and stays out of the
    per-task verify through its tests' slow mark.
    """
    reached = default_collection_node_ids_under(project_root, job.suite)

    assert not reached, (
        f"a default collection with addopts cleared reached {job.suite}: {reached}; plain `pytest` would then run "
        f"that suite, which only the {job.name!r} lane job is meant to run, and only its tests' marks would keep it "
        "out of the per-task verify; name its directory in tests/conftest.py's collect_ignore"
    )


@pytest.mark.parametrize("job", _checked_for(LaneContract.EVERY_TEST_SLOW), ids=lambda job: job.name)
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


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
@pytest.mark.parametrize("job", _needing_a_live_service(), ids=lambda job: job.name)
def test_with_its_service_out_of_reach_the_jobs_outage_probe_reports_its_outage(
    job: LaneJob,
    monkeypatch: pytest.MonkeyPatch,
    project_root: Path,
    shared_uv_probe_environments: SharedUvEnvironments,
) -> None:
    """Run as the lane runs it after a red run, with everything off this machine out of reach, the job's outage probe reports an outage of the row's service.

    It runs in the uv environment of the job's command, as the lane runs it. Here that environment may not be synced
    yet, so the run is given longer than the job's outage_probe_timeout_secs.
    """
    send_child_processes_to_a_dead_proxy(monkeypatch)
    probe = lane_outage_probe(project_root, job.name)
    environment = shared_uv_probe_environments.for_command(lane_command(project_root, job.name).command)

    result = run_command(probe, environment, timeout_secs=300)

    assert result.returncode == os.EX_TEMPFAIL and result.stdout.startswith(f"{job.service}: "), (
        f"with everything off this machine behind a dead proxy, the {probe.label}, {probe.command!r}, reported no "
        f"{job.service} outage, so every {job.service} outage that outlasts a run and its confirm re-run files a fix "
        f"task instead of one escalation the lane closes itself\n{describe_outcome(result)}"
    )


def test_every_lane_job_declaring_an_outage_probe_has_a_row_naming_its_service(project_root: Path) -> None:
    """Every job that declares an outage probe has a LANE_JOBS row naming its service, so no declared probe goes unrun here."""
    services = {job.name: job.service for job in LANE_JOBS}
    unchecked = [name for name in lane_jobs_declaring_an_outage_probe(project_root) if services.get(name) is None]

    assert not unchecked, (
        f"git.offline_lane_commands declares an outage_probe for {unchecked}, whose LANE_JOBS rows are missing or "
        "name no service, so nothing checks that each probe reports its service out of reach as an outage; name in "
        "each job's row the service its probe names at the start of an outage line"
    )
