# SPDX-License-Identifier: AGPL-3.0-or-later
"""Newest-releases lane contract tests.

The orchestrator offline lane's newest-releases job (tests/newest_releases) runs
the verify suite in a copy of the tree whose uv.lock is upgraded. It deselects,
by node id, each test tests/_newest_releases_deselections.py names.
tests/conftest.py keeps that suite out of every default collection, so a
deselection that stops naming its test would turn the lane red only after a
merge. The contracts the job shares with every lane job are checked in
tests/unit/test_offline_lane_contracts.py.
"""

from pathlib import Path

import pytest

from tests._collect_only import CollectedTest
from tests._lane_collection import suite_tests_matching
from tests._newest_releases_deselections import NEWEST_RELEASES_DESELECTIONS, DeselectedTest


def _is_a_case_of(test: CollectedTest, deselected: DeselectedTest) -> bool:
    """Return whether *test* is a case of *deselected*'s function: its node id is *deselected*'s, followed by its
    parametrize id in brackets if it has one."""
    if test.parametrize_id is None:
        return test.node_id == deselected.node_id
    return test.node_id == f"{deselected.node_id}[{test.parametrize_id}]"


@pytest.mark.parametrize(
    "deselected", NEWEST_RELEASES_DESELECTIONS, ids=[deselected.function for deselected in NEWEST_RELEASES_DESELECTIONS]
)
def test_each_node_id_the_lane_deselects_matches_exactly_the_cases_of_a_collected_test(
    project_root: Path, deselected: DeselectedTest
) -> None:
    """The newest-releases lane's --deselect of the entry's node id matches exactly the cases of one collected test.

    The module is collected as the verify suite selects its tests (`-m 'not slow'`). The lane's --deselect matches by
    node-id prefix, as pytest's pytest_collection_modifyitems applies it. A rename of the test or of its module
    therefore fails here, in the per-task verify, rather than in the lane after the merge. A test whose name begins
    with the deselected one's would be deselected with it and never run on the newest releases.
    """
    assert (project_root / deselected.module).is_file(), (
        f"the newest-releases lane deselects {deselected.node_id}, but {deselected.module} is no file: a renamed or "
        "deleted module must take its entry in tests/_newest_releases_deselections.py with it"
    )

    tests = suite_tests_matching(project_root, deselected.module.as_posix(), "not slow")

    deselected_by_the_lane = [test.node_id for test in tests if test.node_id.startswith(deselected.node_id)]
    cases = [test.node_id for test in tests if _is_a_case_of(test, deselected)]
    assert cases, (
        f"the newest-releases lane deselects {deselected.node_id}, but {deselected.module} collects no case of it; "
        f"the node-id prefix matched {deselected_by_the_lane or 'nothing'} instead. A renamed test would run in the "
        "lane's upgraded copy, where it fails or may fail, only after a merge, so its entry in "
        "tests/_newest_releases_deselections.py must be renamed with it"
    )
    assert deselected_by_the_lane == cases, (
        f"the newest-releases lane's --deselect={deselected.node_id} matches by node-id prefix, so it also deselects "
        f"{[node_id for node_id in deselected_by_the_lane if node_id not in cases]}, which the lane would then never "
        f"run on the newest releases; rename each so its name does not begin with {deselected.function}"
    )
