# SPDX-License-Identifier: AGPL-3.0-or-later
r"""Collect-only probes for the lane contract tests.

They collect an offline-lane job as the lane runs it, a default collection of
tests/, and a suite by its explicit path under a mark expression.

Usage::

    from tests._lane_collection import collect_lane_job, default_collection_node_ids_under, suite_node_ids_matching

    collection = collect_lane_job(project_root, "e2e", env=uv_probe_environment)
    assert collection.node_ids, f"{collection.command!r} collected no tests\n{collection.outcome}"
    assert not collection.node_ids_outside("tests/e2e"), f"{collection.command!r} collected tests outside tests/e2e"

    reached = default_collection_node_ids_under(project_root, "tests/interpreter_matrix")
    assert not reached, f"a default collection reached the interpreter matrix: {reached}"

    fast = suite_node_ids_matching(project_root, "tests/css_build", "not slow")
    assert not fast, f"css_build tests not marked slow: {fast}"
"""

import shlex
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import pytest

from tests._collect_only import collected_node_ids, describe_outcome, run_collect_only
from tests._orchestrator_config import lane_job_directory, sole_offline_lane_job


def _lies_under(node_id: str, path: str) -> bool:
    """Return whether *node_id*'s test file is *path* or under it; *path* is relative to the rootdir, as node ids are."""
    return PurePosixPath(node_id.partition("::")[0]).is_relative_to(path)


@dataclass(frozen=True)
class LaneJobCollection:
    """What an offline-lane job's command collected: its node ids in order, and how its run ended, described for an assertion message."""

    command: str
    node_ids: tuple[str, ...]
    outcome: str

    def node_ids_outside(self, path: str) -> tuple[str, ...]:
        """Return the node ids whose test file is neither *path* nor under it; *path* is relative to the rootdir, as node ids are."""
        return tuple(node_id for node_id in self.node_ids if not _lies_under(node_id, path))


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


def default_collection_node_ids_under(project_root: Path, suite: str) -> tuple[str, ...]:
    """Return the node ids under *suite* that collecting *project_root*'s tests/ with addopts cleared reaches, in order.

    *suite* is a directory directly under tests/, relative to the rootdir as node
    ids are, e.g. "tests/css_build". Clearing addopts covers plain `pytest`, the
    per-task verify, and dark-factory's serial and confirm reruns, which append
    `-o addopts=`. Only the repo's own exclusion is measured; the other
    directories under tests/ are ignored only to keep the collection fast. It
    asserts that *suite* is such a directory and that the collection ran.
    """
    suite_directory = project_root / suite
    assert PurePosixPath(suite).parent == PurePosixPath("tests") and suite_directory.is_dir(), (
        f"{suite!r} is not a directory directly under tests/; probed, it would read as never reached"
    )
    siblings = [path for path in (project_root / "tests").iterdir() if path.is_dir() and path != suite_directory]
    command = shlex.join(
        [sys.executable, "-m", "pytest", "-o", "addopts=", "tests", *(f"--ignore={sibling}" for sibling in siblings)]
    )
    result = run_collect_only(command, project_root)
    assert result.returncode in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED), (
        f"collecting tests/ failed\n{describe_outcome(result)}"
    )
    return tuple(node_id for node_id in collected_node_ids(result.stdout) if _lies_under(node_id, suite))


def suite_node_ids_matching(project_root: Path, suite: str, mark_expression: str) -> tuple[str, ...]:
    """Return the node ids `-m` *mark_expression* selects when *suite* is collected by its explicit path, in order.

    *suite* is relative to *project_root*, e.g. "tests/css_build". Its explicit
    path overrides tests/conftest.py's collect_ignore, as an offline-lane job's
    command does. It asserts that the collection ran; an expression that selects
    none of the suite's tests is no failure.
    """
    command = shlex.join([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", suite])
    result = run_collect_only(command, project_root, "-m", mark_expression)
    assert result.returncode in (pytest.ExitCode.OK, pytest.ExitCode.NO_TESTS_COLLECTED), (
        f"collecting {suite} under `-m {mark_expression!r}` failed\n{describe_outcome(result)}"
    )
    return tuple(collected_node_ids(result.stdout))
