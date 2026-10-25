# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the runs-row writes a simulation job's lifecycle makes through RunStorage.

A job's submit creates its run, running; a job that fails marks its run failed; and the next
server start fails every run a job left running.
"""

import dataclasses
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.web.schema import open_database
from solar_challenge.web.storage import RunQuery, RunRecord, RunStorage
from solar_challenge.web.stored_runs import RunType
from tests._finance_builders import make_home_config, make_sim_results
from tests._run_storage_layout import stored_run_dir
from tests._web_runs import store_home_run

_CREATED_AT = "2026-10-20T09:00:00+00:00"


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """An empty RunStorage of no app under tmp_path, its database a new store open_database created."""
    return RunStorage(open_database(tmp_path / "runs.db"), tmp_path / "data")


def _create_north_roof_run(
    storage: RunStorage, run_id: str = "run-1", *, run_type: RunType = "home", n_homes: int = 1
) -> RunRecord:
    """Create run *run_id*, named North Roof and created at _CREATED_AT, as a job's submit creates its run."""
    return storage.create_run(run_id, run_type=run_type, name="North Roof", n_homes=n_homes, created_at=_CREATED_AT)


def _record(storage: RunStorage, run_id: str) -> RunRecord:
    """The record of run *run_id*, which the test has written."""
    record = storage.run_record(run_id)
    assert record is not None, f"no run has id {run_id!r}"
    return record


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _completion_time(record: RunRecord) -> datetime:
    """The time *record*'s run completed, read from its ISO 8601 completed_at."""
    assert record.completed_at is not None, f"run {record.id!r} has no completed_at"
    return datetime.fromisoformat(record.completed_at)


class TestCreateRun:
    """Tests for RunStorage.create_run, the running run a job's submit records before its simulation is queued."""

    @pytest.mark.parametrize(("run_type", "n_homes"), [("home", 1), ("fleet", 3)])
    def test_a_created_run_is_running_with_the_name_type_homes_and_creation_time_it_is_given_and_nothing_else(
        self, storage: RunStorage, run_type: RunType, n_homes: int
    ) -> None:
        created = storage.create_run(
            "run-1", run_type=run_type, name="North Roof", n_homes=n_homes, created_at=_CREATED_AT
        )

        expected = RunRecord(
            id="run-1",
            name="North Roof",
            type=run_type,
            config_json=None,
            summary_json=None,
            status="running",
            error_message=None,
            created_at=_CREATED_AT,
            completed_at=None,
            duration_seconds=None,
            n_homes=n_homes,
            notes=None,
        )
        assert created == expected
        assert storage.run_record("run-1") == expected

    def test_create_run_writes_no_file(self, storage: RunStorage) -> None:
        _create_north_roof_run(storage)

        assert not stored_run_dir(storage, "run-1").exists()

    @pytest.mark.parametrize("run_id", ["../escape", "has space"])
    def test_create_run_of_an_id_the_store_refuses_raises_value_error_naming_it_and_writes_nothing(
        self, storage: RunStorage, run_id: str
    ) -> None:
        with pytest.raises(ValueError, match=re.escape(repr(run_id))):
            _create_north_roof_run(storage, run_id)

        assert storage.page_runs(RunQuery()).total == 0

    def test_create_run_of_a_type_that_is_not_a_run_type_raises_value_error_naming_it_and_writes_nothing(
        self, storage: RunStorage
    ) -> None:
        with pytest.raises(ValueError, match=re.escape("type is 'sweeep'")):
            storage.create_run("run-1", run_type="sweeep", name="North Roof", n_homes=1, created_at=_CREATED_AT)

        assert storage.page_runs(RunQuery()).total == 0

    @pytest.mark.parametrize("name", ["", "   ", None], ids=["empty", "spaces", "none"])
    def test_create_run_of_a_name_that_cannot_name_a_run_raises_value_error_naming_it_and_writes_nothing(
        self, storage: RunStorage, name: str | None
    ) -> None:
        """A run's name is never NULL or blank: it holds a character other than whitespace."""
        with pytest.raises(ValueError, match=re.escape(f"name is {name!r}")):
            storage.create_run("run-1", run_type="home", name=name, n_homes=1, created_at=_CREATED_AT)

        assert storage.page_runs(RunQuery()).total == 0

    def test_create_run_of_the_id_of_a_stored_run_raises_integrity_error_and_leaves_that_run_as_it_was(
        self, storage: RunStorage
    ) -> None:
        store_home_run(storage, "run-1", make_home_config(), make_sim_results(days=1), name="Stored")
        stored = _record(storage, "run-1")

        with pytest.raises(sqlite3.IntegrityError, match=re.escape("UNIQUE constraint failed: runs.id")):
            _create_north_roof_run(storage)

        assert storage.run_record("run-1") == stored

    def test_a_created_run_saved_as_a_finished_job_saves_it_is_completed_and_keeps_its_name_and_creation_time(
        self, storage: RunStorage
    ) -> None:
        _create_north_roof_run(storage)

        storage.save_home_run_from_results(
            "run-1",
            make_home_config(),
            make_sim_results(days=1),
            name="Another Name",
            created_at="2027-01-01T00:00:00+00:00",
            duration_seconds=2.0,
        )

        record = _record(storage, "run-1")
        assert (record.status, record.name, record.created_at, record.duration_seconds) == (
            "completed",
            "North Roof",
            _CREATED_AT,
            2.0,
        )
        assert record.completed_at is not None
        assert record.summary_json is not None


class TestMarkRunFailed:
    """Tests for RunStorage.mark_run_failed, which records that a job's run failed with the job's message."""

    def test_a_run_marked_failed_has_the_message_and_a_completion_time_of_now_and_is_otherwise_as_created(
        self, storage: RunStorage
    ) -> None:
        created = _create_north_roof_run(storage)

        before = _utc_now()
        storage.mark_run_failed("run-1", "the simulation failed")
        after = _utc_now()

        record = _record(storage, "run-1")
        assert before <= _completion_time(record) <= after
        assert record == dataclasses.replace(
            created, status="failed", error_message="the simulation failed", completed_at=record.completed_at
        )

    def test_marking_failed_an_id_no_run_has_raises_nothing_and_writes_nothing(self, storage: RunStorage) -> None:
        storage.mark_run_failed("run-1", "the simulation failed")

        assert storage.page_runs(RunQuery()).total == 0


class TestFailInterruptedRuns:
    """Tests for RunStorage.fail_interrupted_runs, which a server start calls for the runs its jobs left running."""

    def test_each_running_run_is_failed_as_interrupted_by_a_server_restart_with_a_completion_time_of_now(
        self, storage: RunStorage
    ) -> None:
        _create_north_roof_run(storage, "run-1")
        _create_north_roof_run(storage, "run-2", run_type="fleet", n_homes=3)

        before = _utc_now()
        failed_run_count = storage.fail_interrupted_runs()
        after = _utc_now()

        assert failed_run_count == 2
        for run_id in ("run-1", "run-2"):
            record = _record(storage, run_id)
            assert (record.status, record.error_message) == ("failed", "Interrupted by server restart")
            assert before <= _completion_time(record) <= after

    def test_a_completed_run_and_a_failed_run_are_left_as_they_were(self, storage: RunStorage) -> None:
        store_home_run(storage, "completed-run", make_home_config(), make_sim_results(days=1))
        _create_north_roof_run(storage, "failed-run")
        storage.mark_run_failed("failed-run", "the simulation failed")
        records_before = [_record(storage, run_id) for run_id in ("completed-run", "failed-run")]

        assert storage.fail_interrupted_runs() == 0

        assert [_record(storage, run_id) for run_id in ("completed-run", "failed-run")] == records_before
