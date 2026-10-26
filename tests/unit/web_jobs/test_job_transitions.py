# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the job state table: LEGAL_JOB_TRANSITIONS, TERMINAL_JOB_STATUSES and check_job_transition.

_THE_PRDS_TABLE spells out the table of docs/prds/job-events-and-sse-framing.md §3.4, along
which a job's status moves: check_job_transition refuses every other move with
IllegalJobTransition, naming the job, its run and both statuses, and a terminal status has no
exits.
"""

import itertools
from typing import get_args

import pytest

pytest.importorskip("flask")

from solar_challenge.web.jobs import (
    LEGAL_JOB_TRANSITIONS,
    TERMINAL_JOB_STATUSES,
    IllegalJobTransition,
    JobStatus,
    check_job_transition,
)

_THE_PRDS_TABLE: dict[JobStatus, set[JobStatus]] = {
    "queued": {"running", "failed", "cancelled"},
    "running": {"running", "completed", "failed", "cancelled"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}

_LEGAL_MOVES = [(status, exit) for status, exits in _THE_PRDS_TABLE.items() for exit in sorted(exits)]
_ILLEGAL_MOVES = [move for move in itertools.product(get_args(JobStatus), repeat=2) if move not in _LEGAL_MOVES]


def _move_ids(moves: list[tuple[JobStatus, JobStatus]]) -> list[str]:
    return [f"{from_status}-to-{to_status}" for from_status, to_status in moves]


def test_the_table_is_the_prds() -> None:
    assert {status: set(exits) for status, exits in LEGAL_JOB_TRANSITIONS.items()} == _THE_PRDS_TABLE


def test_the_table_has_one_entry_per_job_status() -> None:
    assert sorted(LEGAL_JOB_TRANSITIONS) == sorted(get_args(JobStatus))


def test_the_terminal_statuses_are_completed_failed_and_cancelled_and_none_has_an_exit() -> None:
    assert TERMINAL_JOB_STATUSES == {"completed", "failed", "cancelled"}
    assert {status: LEGAL_JOB_TRANSITIONS[status] for status in TERMINAL_JOB_STATUSES} == dict.fromkeys(
        TERMINAL_JOB_STATUSES, frozenset()
    )


@pytest.mark.parametrize(("from_status", "to_status"), _LEGAL_MOVES, ids=_move_ids(_LEGAL_MOVES))
def test_check_job_transition_allows_each_move_the_table_lists(from_status: JobStatus, to_status: JobStatus) -> None:
    assert check_job_transition("job-1", "run-1", from_status, to_status) is None


@pytest.mark.parametrize(("from_status", "to_status"), _ILLEGAL_MOVES, ids=_move_ids(_ILLEGAL_MOVES))
def test_check_job_transition_refuses_every_other_move_naming_the_job_its_run_and_both_statuses(
    from_status: JobStatus, to_status: JobStatus
) -> None:
    with pytest.raises(IllegalJobTransition) as raised:
        check_job_transition("job-1", "run-1", from_status, to_status)

    refusal = raised.value
    assert isinstance(refusal, RuntimeError)
    assert (refusal.job_id, refusal.run_id, refusal.from_status, refusal.to_status) == (
        "job-1",
        "run-1",
        from_status,
        to_status,
    )
    for named in ("job-1", "run-1", from_status, to_status):
        assert named in str(refusal)


def test_a_job_that_completed_cannot_then_fail() -> None:
    with pytest.raises(IllegalJobTransition) as raised:
        check_job_transition("job-1", "run-1", "completed", "failed")

    refusal = raised.value
    assert (refusal.job_id, refusal.run_id, refusal.from_status, refusal.to_status) == (
        "job-1",
        "run-1",
        "completed",
        "failed",
    )
    for named in ("job-1", "run-1", "completed", "failed"):
        assert named in str(refusal)
