# SPDX-License-Identifier: AGPL-3.0-or-later
"""Interpreter-matrix lane contract tests.

Every Python minor requires-python admits is re-verified recurrently: the
.python-version pin by the per-task verify, every other minor by the
orchestrator offline lane's interpreter-matrix job (tests/interpreter_matrix).
The contracts the job shares with every lane job are checked in
tests/unit/test_offline_lane_contracts.py.
"""

from collections.abc import Iterable
from pathlib import Path

import pytest

from tests._collect_only import requires_uv
from tests._interpreters import off_pin_minor_versions, python_version_pin
from tests._lane_collection import collect_lane_job, suite_node_ids_matching

_MATRIX_JOB = "interpreter-matrix"
_MATRIX_SUITE = "tests/interpreter_matrix"


def _off_pin_interpreters(project_root: Path) -> list[str]:
    """Return the minors the interpreter matrix must cover, as its node ids name them (e.g. "3.13"), sorted."""
    return sorted(f"{major}.{minor}" for major, minor in off_pin_minor_versions(project_root))


def _interpreters_named_by(node_ids: Iterable[str]) -> list[str]:
    """Return the interpreter each interpreter-matrix node id ends in (e.g. "3.13" for "...[3.13]"), sorted."""
    return sorted(node_id.rpartition("[")[2].removesuffix("]") for node_id in node_ids)


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


def test_slow_selects_one_interpreter_matrix_case_per_off_pin_admitted_minor(project_root: Path) -> None:
    """`-m slow` selects one case per off-pin admitted minor.

    Each case's `uv run` provisions its interpreter's environment from PyPI
    whenever uv.lock changes, so it must run outside the offline guard.
    """
    slow_cases = _interpreters_named_by(suite_node_ids_matching(project_root, _MATRIX_SUITE, "slow"))

    expected = _off_pin_interpreters(project_root)
    assert slow_cases == expected, (
        f"`-m slow` collected the interpreter-matrix cases {slow_cases}, not one per off-pin admitted minor "
        f"{expected}; a case not marked slow runs under tests/conftest.py's offline guard, where its child uv "
        "cannot download what a uv.lock change needs, so the lane would go red after every dependency change"
    )
