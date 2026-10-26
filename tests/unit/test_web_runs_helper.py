# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_runs.py, which seeds runs in a RunStorage as simulation jobs leave them."""

from pathlib import Path

import pandas as pd
import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, FleetSummary
from solar_challenge.home import HomeConfig, SimulationResults, SummaryStatistics
from solar_challenge.web.jobs import JobManager
from solar_challenge.web.storage import RUN_STATUSES, RunStatus, RunStorage
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._run_stores import empty_run_storage
from tests._web_runs import record_run_status, store_fleet_run, store_home_run


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """The store of no app that the tests seed runs in with the helpers, beside the runs a finished job saves there."""
    return empty_run_storage(tmp_path)


def _two_unlike_homes() -> FleetResults:
    """A fleet of two homes whose totals and batteries differ, so a mix-up of their order shows."""
    return make_fleet_results_of(
        [
            make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
            make_sim_results(self_kwh=10.0, export_kwh=20.0, import_kwh=30.0, days=1),
        ],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )


_JUNE_1 = pd.Timestamp("2024-06-01", tz="UTC")
_JUNE_2 = pd.Timestamp("2024-06-02", tz="UTC")


def _job_manager_simulating(
    storage: RunStorage, homes: list[HomeConfig], results: list[SimulationResults]
) -> JobManager:
    """A JobManager recording its jobs' runs in *storage*, whose simulation of each of *homes* returns the results at the same place in *results*."""

    def simulate(config: HomeConfig, start_date: pd.Timestamp, end_date: pd.Timestamp) -> SimulationResults:
        return results[homes.index(config)]

    return JobManager(storage, max_workers=1, simulate_home=simulate)


def _wait_until_completed(manager: JobManager, job_id: str) -> None:
    """Wait for *manager* to finish its jobs, and check that job *job_id* completed."""
    assert manager.wait_until_idle(timeout=30), f"job {job_id} did not finish within 30 s"
    state = manager.job_state(job_id)
    assert state is not None and state.status == "completed", state


def _summaries_a_finished_fleet_job_saves(
    storage: RunStorage, fleet: FleetResults
) -> tuple[FleetSummary, tuple[SummaryStatistics, ...]]:
    """The fleet and per-home summaries a fleet job saves to *storage* when simulating *fleet*'s homes gives its results."""
    manager = _job_manager_simulating(storage, fleet.home_configs, fleet.per_home_results)
    job_id, run_id = manager.submit_fleet_job(configs=fleet.home_configs, start_date=_JUNE_1, end_date=_JUNE_2)
    _wait_until_completed(manager, job_id)
    loaded = storage.load_run(run_id)
    return loaded.summary, loaded.home_summaries


def _summary_a_finished_home_job_saves(
    storage: RunStorage, config: HomeConfig, results: SimulationResults
) -> SummaryStatistics:
    """The summary a home job saves to *storage* when simulating *config* gives *results*."""
    manager = _job_manager_simulating(storage, [config], [results])
    job_id, run_id = manager.submit_home_job(config=config, start_date=_JUNE_1, end_date=_JUNE_2)
    _wait_until_completed(manager, job_id)
    return storage.load_run(run_id).summary


def test_a_stored_fleet_run_loads_back_with_the_summaries_a_finished_fleet_job_saves(
    storage: RunStorage,
) -> None:
    fleet = _two_unlike_homes()
    job_fleet_summary, job_per_home_summaries = _summaries_a_finished_fleet_job_saves(storage, fleet)

    store_fleet_run(storage, "fleet-1", fleet)

    loaded = storage.load_run("fleet-1")
    assert loaded.fleet_results.home_configs == fleet.home_configs
    assert loaded.summary == job_fleet_summary
    assert loaded.home_summaries == job_per_home_summaries


def test_a_stored_fleet_run_is_recorded_as_a_completed_fleet_run_with_the_given_name_and_creation_time(
    storage: RunStorage,
) -> None:
    store_fleet_run(
        storage,
        "fleet-1",
        _two_unlike_homes(),
        name="Community Fleet",
        created_at="2024-06-02T09:00:00+00:00",
    )

    record = storage.run_record("fleet-1")
    assert record is not None
    assert (record.name, record.type, record.status, record.created_at, record.n_homes) == (
        "Community Fleet",
        "fleet",
        "completed",
        "2024-06-02T09:00:00+00:00",
        2,
    )


def test_a_stored_home_run_loads_back_with_the_summary_a_finished_home_job_saves(
    storage: RunStorage,
) -> None:
    config = make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))
    results = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
    job_summary = _summary_a_finished_home_job_saves(storage, config, results)

    store_home_run(storage, "home-1", config, results)

    loaded = storage.load_run("home-1")
    assert loaded.config == config
    assert loaded.summary == job_summary


def test_a_stored_home_run_is_recorded_as_a_completed_home_run_with_the_given_name_and_creation_time(
    storage: RunStorage,
) -> None:
    store_home_run(
        storage,
        "home-1",
        make_home_config(),
        make_sim_results(days=1),
        name="North Roof",
        created_at="2024-06-01T09:00:00+00:00",
    )

    record = storage.run_record("home-1")
    assert record is not None
    assert (record.name, record.type, record.status, record.created_at) == (
        "North Roof",
        "home",
        "completed",
        "2024-06-01T09:00:00+00:00",
    )


def _lifecycle_of(storage: RunStorage, run_id: str) -> tuple[RunStatus | None, bool, str | None]:
    """The lifecycle columns of run *run_id*: its status, whether it has a completion time, and its error message."""
    record = storage.run_record(run_id)
    assert record is not None, f"no run has id {run_id!r}"
    return record.status, record.completed_at is not None, record.error_message


def _lifecycle_a_job_leaves(status: RunStatus) -> tuple[RunStatus, bool, str | None]:
    """The lifecycle columns, as _lifecycle_of reads them, of a run its job's lifecycle left *status*.

    A run that ended has a completion time, and a failed one the error its job failed with.
    """
    return status, status != "running", "the simulation failed" if status == "failed" else None


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_a_stored_home_run_is_recorded_with_the_status_it_is_given_as_its_jobs_lifecycle_records_it(
    storage: RunStorage, status: RunStatus
) -> None:
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1), status=status)

    assert _lifecycle_of(storage, "home-1") == _lifecycle_a_job_leaves(status)


@pytest.mark.parametrize("status", RUN_STATUSES)
def test_a_run_created_as_a_jobs_submit_creates_it_is_moved_to_the_status_it_is_given_as_its_jobs_lifecycle_moves_it(
    storage: RunStorage, status: RunStatus
) -> None:
    storage.create_run("run-1", run_type="home", name="North Roof", n_homes=1, created_at="2024-06-01T09:00:00+00:00")

    record_run_status(storage, "run-1", status)

    assert _lifecycle_of(storage, "run-1") == _lifecycle_a_job_leaves(status)
