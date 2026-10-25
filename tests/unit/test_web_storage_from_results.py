# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for saving a run to RunStorage from its simulation results alone, with the summaries derived from them."""

from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary
from solar_challenge.web.storage import RunRecord, RunStorage
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._run_stores import empty_run_storage


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """The store of no app that the tests save runs to from their simulation results alone, then load back."""
    return empty_run_storage(tmp_path)


def _a_home() -> tuple[HomeConfig, SimulationResults]:
    """A home with a 5 kWh battery, and a day of its results."""
    return (
        make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0)),
        make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
    )


def _two_unlike_homes() -> FleetResults:
    """A fleet of two homes whose totals and batteries differ, so a mix-up of their order shows."""
    return make_fleet_results_of(
        [
            make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
            make_sim_results(self_kwh=10.0, export_kwh=20.0, import_kwh=30.0, days=1),
        ],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )


def _records_of_the_home_and_fleet_runs(storage: RunStorage) -> tuple[RunRecord, RunRecord]:
    """The records of home run "home-1" and fleet run "fleet-1", which the test has saved."""
    home_record, fleet_record = storage.run_record("home-1"), storage.run_record("fleet-1")
    assert home_record is not None and fleet_record is not None, (home_record, fleet_record)
    return home_record, fleet_record


def test_a_home_run_saved_from_its_results_loads_back_with_the_summary_calculate_summary_derives_from_them(
    storage: RunStorage,
) -> None:
    config, results = _a_home()

    storage.save_home_run_from_results("home-1", config, results, name="Saved Run")

    loaded = storage.load_run("home-1")
    assert loaded.config == config
    assert loaded.summary == calculate_summary(results)


def test_a_fleet_run_saved_from_its_results_loads_back_with_each_homes_summary_and_the_fleet_summary(
    storage: RunStorage,
) -> None:
    fleet = _two_unlike_homes()

    storage.save_fleet_run_from_results("fleet-1", fleet, name="Saved Run")

    loaded = storage.load_run("fleet-1")
    assert loaded.fleet_results.home_configs == fleet.home_configs
    assert loaded.home_summaries == tuple(calculate_summary(results) for results in fleet.per_home_results)
    assert loaded.summary == calculate_fleet_summary(fleet)


def test_a_run_saved_from_its_results_is_recorded_with_the_name_duration_and_creation_time_it_is_given(
    storage: RunStorage,
) -> None:
    config, results = _a_home()

    storage.save_home_run_from_results(
        "home-1",
        config,
        results,
        name="North Roof",
        duration_seconds=2.5,
        created_at="2024-06-01T09:00:00+00:00",
    )
    storage.save_fleet_run_from_results(
        "fleet-1",
        _two_unlike_homes(),
        name="Community Fleet",
        duration_seconds=1.5,
        created_at="2024-06-02T09:00:00+00:00",
    )

    assert [
        (record.name, record.type, record.duration_seconds, record.created_at, record.n_homes)
        for record in _records_of_the_home_and_fleet_runs(storage)
    ] == [
        ("North Roof", "home", 2.5, "2024-06-01T09:00:00+00:00", 1),
        ("Community Fleet", "fleet", 1.5, "2024-06-02T09:00:00+00:00", 2),
    ]


def test_a_run_saved_from_its_results_without_a_status_is_recorded_as_completed(storage: RunStorage) -> None:
    config, results = _a_home()

    storage.save_home_run_from_results("home-1", config, results, name="Saved Run")
    storage.save_fleet_run_from_results("fleet-1", _two_unlike_homes(), name="Saved Run")

    assert [
        (record.status, record.completed_at is not None) for record in _records_of_the_home_and_fleet_runs(storage)
    ] == [("completed", True), ("completed", True)]


def test_a_run_saved_from_its_results_with_a_status_is_recorded_with_it(storage: RunStorage) -> None:
    config, results = _a_home()

    storage.save_home_run_from_results("home-1", config, results, name="Saved Run", status="failed")
    storage.save_fleet_run_from_results("fleet-1", _two_unlike_homes(), name="Saved Run", status="running")

    assert [(record.status, record.completed_at) for record in _records_of_the_home_and_fleet_runs(storage)] == [
        ("failed", None),
        ("running", None),
    ]


def test_a_fleet_unpaired_after_construction_is_refused_and_nothing_is_saved(storage: RunStorage) -> None:
    fleet = _two_unlike_homes()
    fleet.home_configs.pop()

    with pytest.raises(ValueError, match="got 2 per_home_results and 1 home_configs"):
        storage.save_fleet_run_from_results("fleet-1", fleet, name="Saved Run")

    assert storage.run_record("fleet-1") is None
    with pytest.raises(FileNotFoundError):
        storage.load_run("fleet-1")
