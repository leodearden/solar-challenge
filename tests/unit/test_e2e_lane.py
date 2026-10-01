# SPDX-License-Identifier: AGPL-3.0-or-later
"""E2E lane contract tests.

The per-task verify never runs tests/e2e: its test_command ignores and
deselects it. The orchestrator offline lane's e2e job runs it after every
merge instead, so an e2e regression files a fix task rather than rotting
unseen.
"""

from pathlib import Path

import pytest

from tests._collect_only import collected_node_ids, describe_outcome, requires_uv, run_collect_only
from tests._orchestrator_config import lane_job_directory, sole_offline_lane_job

_E2E_JOB = "e2e"


def test_offline_lane_runs_one_enabled_e2e_job(project_root: Path) -> None:
    """The offline lane runs exactly one e2e job, and it is enabled."""
    job = sole_offline_lane_job(project_root, _E2E_JOB)

    assert job.get("enabled", True) is True, (
        f"the {_E2E_JOB!r} lane job is disabled, so e2e regressions go unseen again"
    )


@requires_uv
def test_e2e_job_collects_the_e2e_suite_and_nothing_else(project_root: Path) -> None:
    """Run as the lane runs it, the e2e job collects at least one test, every one under tests/e2e/.

    The repo's pytest addopts stay in force, as they do in the lane, so this also
    pins that the job's explicit tests/e2e path overrides their --ignore=tests/e2e.
    """
    job = sole_offline_lane_job(project_root, _E2E_JOB)
    command = job["command"]

    result = run_collect_only(command, lane_job_directory(project_root, job))

    assert result.returncode == pytest.ExitCode.OK, (
        f"the {_E2E_JOB!r} lane job {command!r} failed to collect\n{describe_outcome(result)}"
    )
    node_ids = collected_node_ids(result.stdout)
    assert node_ids, (
        f"the {_E2E_JOB!r} lane job {command!r} collected no tests, so the lane stays green "
        f"while the e2e suite goes unrun\n{describe_outcome(result)}"
    )
    outside_e2e = [node_id for node_id in node_ids if not node_id.startswith("tests/e2e/")]
    assert not outside_e2e, (
        f"the {_E2E_JOB!r} lane job {command!r} collected tests outside tests/e2e/, which the "
        f"per-task verify already runs: {outside_e2e}"
    )
