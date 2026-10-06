# SPDX-License-Identifier: AGPL-3.0-or-later
"""css-build lane contract tests.

tests/css_build checks that static/dist/style.css is what its committed sources
build to, and that the Tailwind license texts beside it are the locked
tailwindcss package's. It needs npm and registry.npmjs.org, so the per-task
verify never runs it. The orchestrator offline lane's css-build job runs it
after every merge instead, so a stylesheet committed without a rebuild files a
fix task rather than going unseen.
"""

from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._lane_collection import collect_lane_job, default_collection_node_ids_under, suite_node_ids_matching
from tests._orchestrator_config import lane_job_enabled, sole_offline_lane_job

_CSS_BUILD_JOB = "css-build"
_CSS_BUILD_SUITE = "tests/css_build"


def test_offline_lane_runs_one_enabled_css_build_job(project_root: Path) -> None:
    """The offline lane runs exactly one css-build job, and it is enabled."""
    job = sole_offline_lane_job(project_root, _CSS_BUILD_JOB)

    assert lane_job_enabled(job), (
        f"the {_CSS_BUILD_JOB!r} lane job is disabled, so a stylesheet its sources no longer build to goes "
        "unseen again"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_css_build_job_collects_the_css_build_suite_and_nothing_else(
    project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the css-build job collects at least one test, every one in tests/css_build.

    The job's uv environment is fresh, as the lane's is, so it holds only the
    extras the job names.
    """
    collection = collect_lane_job(project_root, _CSS_BUILD_JOB, env=uv_probe_environment)

    assert collection.node_ids, (
        f"the {_CSS_BUILD_JOB!r} lane job {collection.command!r} collected no tests, so the lane stays green "
        f"while the committed stylesheet goes unchecked\n{collection.outcome}"
    )
    outside_suite = collection.node_ids_outside(_CSS_BUILD_SUITE)
    assert not outside_suite, (
        f"the {_CSS_BUILD_JOB!r} lane job {collection.command!r} collected tests outside {_CSS_BUILD_SUITE}, "
        f"which the per-task verify already runs: {outside_suite}"
    )


def test_default_collection_never_reaches_the_css_build_suite(project_root: Path) -> None:
    """Collecting tests/ never reaches tests/css_build, even with addopts cleared."""
    reached = default_collection_node_ids_under(project_root, _CSS_BUILD_SUITE)

    assert not reached, (
        f"a default collection with addopts cleared reached the css_build suite: {reached}; plain `pytest` "
        "would then rebuild the stylesheet, which needs npm and registry.npmjs.org, and only the suite's slow "
        "mark would keep it out of the per-task verify"
    )


def test_css_build_tests_are_slow_so_npm_reaches_the_registry_outside_the_offline_guard(project_root: Path) -> None:
    """Every css_build test is marked slow, since its npm ci installs Tailwind from registry.npmjs.org.

    test_css_build_job_collects_the_css_build_suite_and_nothing_else pins that
    the suite has tests.
    """
    fast_tests = suite_node_ids_matching(project_root, _CSS_BUILD_SUITE, "not slow")

    assert not fast_tests, (
        f"`-m 'not slow'` collected the css_build tests {fast_tests}; a css_build test not marked slow runs "
        "under tests/conftest.py's offline guard, whose proxy refuses npm's requests to registry.npmjs.org, "
        "so the lane would go red after every merge"
    )
