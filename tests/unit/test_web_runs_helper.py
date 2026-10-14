# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_web_runs.py, which saves runs to a RunStorage as a finished simulation job saves them."""

from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import calculate_summary
from solar_challenge.web.database import init_db
from solar_challenge.web.storage import RunStorage
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._web_runs import store_fleet_run, store_home_run


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """An empty RunStorage under tmp_path, with the schema init_db creates."""
    storage = RunStorage(db_path=tmp_path / "runs.db", data_dir=tmp_path)
    init_db(storage.db_path)
    return storage


def _two_unlike_homes() -> FleetResults:
    """A fleet of two homes whose totals and batteries differ, so a mix-up of their order shows."""
    return make_fleet_results_of(
        [
            make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
            make_sim_results(self_kwh=10.0, export_kwh=20.0, import_kwh=30.0, days=1),
        ],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )


def test_a_stored_fleet_run_loads_back_with_the_summaries_a_finished_fleet_job_saves(
    storage: RunStorage,
) -> None:
    fleet = _two_unlike_homes()

    store_fleet_run(storage, "fleet-1", fleet)

    loaded_fleet, fleet_summary, per_home_summaries = storage.load_fleet_run("fleet-1")
    assert loaded_fleet.home_configs == fleet.home_configs
    assert fleet_summary == calculate_fleet_summary(fleet)
    assert per_home_summaries == [calculate_summary(results) for results in fleet.per_home_results]


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

    store_home_run(storage, "home-1", config, results)

    loaded_config, _, summary = storage.load_home_run("home-1")
    assert loaded_config == config
    assert summary == calculate_summary(results)


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


def test_a_stored_home_run_is_recorded_with_the_status_it_is_given(storage: RunStorage) -> None:
    store_home_run(storage, "home-1", make_home_config(), make_sim_results(days=1), status="failed")

    record = storage.run_record("home-1")
    assert record is not None
    assert record.status == "failed"
