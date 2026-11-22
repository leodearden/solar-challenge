# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for solar_challenge.web.dashboard: the Dashboard an app holds, attached with attach_dashboard and read back with dashboard_of, and its close()."""

import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("flask")
from flask import Flask

from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.web.dashboard import Dashboard, attach_dashboard, dashboard_of
from solar_challenge.web.database import Database
from solar_challenge.web.jobs import JobManager, JobState
from solar_challenge.web.storage import RunQuery, RunStorage
from solar_challenge.web.store_lock import acquire_store_lock
from tests._run_stores import empty_run_storage
from tests._web_app import store_lock_is_free
from tests._web_job_runner import jobs_running
from tests.unit.web_jobs._fakes import BlockingSimulation, RecordingSimulation

_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig(annual_consumption_kwh=3500))
_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")
_DROPPED = "Dropped: the server shut down before the job ran"


def _dashboard_over(
    directory: Path, jobs: Callable[[RunStorage], JobManager], closes_at_teardown: ExitStack
) -> Dashboard:
    """A Dashboard over a new, empty store in *directory*, holding the store's lock and a JobManager *jobs* builds over its storage; the test's teardown shuts the manager down, then releases the lock."""
    storage = empty_run_storage(directory)
    lock = acquire_store_lock(directory)
    closes_at_teardown.callback(lock.release)
    manager = jobs(storage)
    closes_at_teardown.callback(manager.shutdown, wait=True)
    return Dashboard(storage=storage, jobs=manager, database=storage.database, lock=lock)


def _wait_for_state(manager: JobManager, job_id: str, reached: Callable[[JobState], bool]) -> JobState:
    """Job *job_id*'s state as soon as *reached* holds for it, polling *manager*; the test fails after 30 s without it."""
    deadline = time.monotonic() + 30
    while (state := manager.job_state(job_id)) is None or not reached(state):
        if time.monotonic() > deadline:
            pytest.fail(f"job {job_id} did not reach the state awaited within 30 s; its last state was {state}")
        time.sleep(0.01)
    return state


class TestDashboardOf:
    """dashboard_of reads back the one Dashboard attach_dashboard attached to an app, and refuses an app that holds none."""

    def test_an_app_holding_no_dashboard_is_refused_by_name(self) -> None:
        with pytest.raises(LookupError, match="'not-a-dashboard'") as refused:
            dashboard_of(Flask("not-a-dashboard"))

        assert "create_app" in str(refused.value)

    def test_an_app_holding_something_else_under_the_dashboards_key_is_refused_by_name(
        self, tmp_path: Path, closes_at_teardown: ExitStack
    ) -> None:
        attached_to = Flask("attached-to")
        keys_before = set(attached_to.extensions)
        attach_dashboard(attached_to, _dashboard_over(tmp_path, jobs_running(RecordingSimulation()), closes_at_teardown))
        [dashboard_key] = set(attached_to.extensions) - keys_before
        holding_something_else = Flask("holds-something-else")
        holding_something_else.extensions[dashboard_key] = "not a Dashboard"

        with pytest.raises(LookupError, match="'holds-something-else'"):
            dashboard_of(holding_something_else)

    def test_the_dashboard_attached_to_an_app_is_the_one_read_back(
        self, tmp_path: Path, closes_at_teardown: ExitStack
    ) -> None:
        app = Flask("dashboard")
        dashboard = _dashboard_over(tmp_path, jobs_running(RecordingSimulation()), closes_at_teardown)

        attach_dashboard(app, dashboard)

        assert dashboard_of(app) is dashboard


class TestDashboardConstruction:
    """A Dashboard's storage keeps its runs in the Dashboard's database: they are one store."""

    def test_a_storage_keeping_its_runs_in_another_database_is_refused_naming_both(
        self, tmp_path: Path, closes_at_teardown: ExitStack
    ) -> None:
        held = _dashboard_over(tmp_path, jobs_running(RecordingSimulation()), closes_at_teardown)
        another = Database(tmp_path / "another.db")

        with pytest.raises(ValueError) as refused:
            Dashboard(storage=held.storage, jobs=held.jobs, database=another, lock=held.lock)

        assert str(held.storage.database.path) in str(refused.value)
        assert str(another.path) in str(refused.value)


class TestDashboardClose:
    """close() drops the queued jobs, waits for the running ones, and only then releases the store's lock."""

    def test_a_closed_dashboards_jobs_refuse_a_job_and_its_store_is_free(
        self, tmp_path: Path, closes_at_teardown: ExitStack
    ) -> None:
        dashboard = _dashboard_over(tmp_path, jobs_running(RecordingSimulation()), closes_at_teardown)

        dashboard.close()

        with pytest.raises(RuntimeError, match="shutdown"):
            dashboard.jobs.submit_home_job(_A_HOME, _JUNE_1, _JUNE_2)
        assert dashboard.storage.page_runs(RunQuery()).total == 0
        assert store_lock_is_free(tmp_path)

    def test_closing_a_closed_dashboard_is_harmless(self, tmp_path: Path, closes_at_teardown: ExitStack) -> None:
        dashboard = _dashboard_over(tmp_path, jobs_running(RecordingSimulation()), closes_at_teardown)
        dashboard.close()

        dashboard.close()

        assert store_lock_is_free(tmp_path)

    def test_close_releases_the_store_only_once_the_running_job_has_finished(
        self, tmp_path: Path, closes_at_teardown: ExitStack
    ) -> None:
        blocking_simulation = BlockingSimulation()
        dashboard = _dashboard_over(tmp_path, jobs_running(blocking_simulation, max_workers=1), closes_at_teardown)
        closes_at_teardown.callback(blocking_simulation.release)
        running, running_run = dashboard.jobs.submit_home_job(_A_HOME, _JUNE_1, _JUNE_2)
        blocking_simulation.wait_until_started()
        queued, _ = dashboard.jobs.submit_home_job(_A_HOME, _JUNE_1, _JUNE_2)
        closing = threading.Thread(target=dashboard.close, daemon=True)
        closing.start()

        _wait_for_state(dashboard.jobs, queued, lambda state: (state.status, state.message) == ("failed", _DROPPED))
        still_running = dashboard.storage.run_record(running_run)

        assert closing.is_alive()
        assert not store_lock_is_free(tmp_path)
        assert still_running is not None and still_running.status == "running"
        blocking_simulation.release()
        closing.join(timeout=30)
        assert not closing.is_alive()
        finished = dashboard.jobs.job_state(running)
        assert finished is not None and finished.status == "completed"
        assert store_lock_is_free(tmp_path)
