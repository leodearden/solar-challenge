# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Collect-only probes of offline-lane jobs, run as the lane runs them, for the lane contract tests.

Usage::

    from tests._lane_collection import collect_lane_job

    collection = collect_lane_job(project_root, "e2e", env=uv_probe_environment)
    assert collection.node_ids, f"{collection.command!r} collected no tests\n{collection.outcome}"
"""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from tests._collect_only import collected_node_ids, describe_outcome, run_collect_only
from tests._orchestrator_config import lane_job_directory, sole_offline_lane_job


@dataclass(frozen=True)
class LaneJobCollection:
    """What an offline-lane job's command collected: its node ids in order, and how its run ended, described for an assertion message."""

    command: str
    node_ids: tuple[str, ...]
    outcome: str


def collect_lane_job(project_root: Path, name: str, *, env: Mapping[str, str]) -> LaneJobCollection:
    """Run the offline-lane job *name*'s command verbatim in the job's directory under *project_root*, in *env*, collecting only.

    It asserts the command collected, naming the job, its command and how the run
    ended. Whether what it collected is right is the calling lane test's own assertion.
    """
    job = sole_offline_lane_job(project_root, name)
    command = job["command"]
    result = run_collect_only(command, lane_job_directory(project_root, job), env=env)
    outcome = describe_outcome(result)
    assert result.returncode == pytest.ExitCode.OK, f"the {name!r} lane job {command!r} failed to collect\n{outcome}"
    return LaneJobCollection(command=command, node_ids=tuple(collected_node_ids(result.stdout)), outcome=outcome)
