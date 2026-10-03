# SPDX-License-Identifier: AGPL-3.0-or-later
"""E2E lane contract tests.

The per-task verify never runs tests/e2e: its test_command ignores and
deselects it. The orchestrator offline lane's e2e job runs it after every
merge instead, so an e2e regression files a fix task rather than rotting
unseen.
"""

from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._lane_collection import collect_lane_job
from tests._orchestrator_config import lane_job_enabled, sole_offline_lane_job

_E2E_JOB = "e2e"


def test_offline_lane_runs_one_enabled_e2e_job(project_root: Path) -> None:
    """The offline lane runs exactly one e2e job, and it is enabled."""
    job = sole_offline_lane_job(project_root, _E2E_JOB)

    assert lane_job_enabled(job), (
        f"the {_E2E_JOB!r} lane job is disabled, so e2e regressions go unseen again"
    )


@requires_uv
@pytest.mark.usefixtures("callers_uv_lock_mode_is_frozen")
def test_e2e_job_collects_the_e2e_suite_and_nothing_else(
    project_root: Path, uv_probe_environment: dict[str, str]
) -> None:
    """Run as the lane runs it, the e2e job collects at least one test, every one under tests/e2e/.

    The repo's pytest addopts stay in force, as they do in the lane, so this also
    pins that the job's explicit tests/e2e path overrides their --ignore=tests/e2e.

    The job's uv environment is fresh, as the lane's is, so it holds only the
    extras the job names.
    """
    collection = collect_lane_job(project_root, _E2E_JOB, env=uv_probe_environment)

    assert collection.node_ids, (
        f"the {_E2E_JOB!r} lane job {collection.command!r} collected no tests, so the lane stays green "
        f"while the e2e suite goes unrun\n{collection.outcome}"
    )
    outside_e2e = collection.node_ids_outside("tests/e2e")
    assert not outside_e2e, (
        f"the {_E2E_JOB!r} lane job {collection.command!r} collected tests outside tests/e2e/, which the "
        f"per-task verify already runs: {outside_e2e}"
    )
