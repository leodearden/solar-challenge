# SPDX-License-Identifier: AGPL-3.0-or-later
"""The run kinds, and RunStorage.load_run, which reads a stored run as its record's kind reads it.

RUN_KINDS holds one RunKind for each RunType. A run's record names its kind, and load_run
reads the run's files back as a StoredHomeRun or a StoredFleetRun, the variant whose
export_frame the run's CSV export answers with. A record with no type names no kind, so its
run is refused as a StoredRunUnreadable naming runs.type. The kind also reads the
HomeConfigs the run's record holds, and builds from them the scenario the run's YAML export
answers with. A kind also names a run created without a name.
"""

import dataclasses
import re
from typing import get_args

import pandas as pd
import pytest

pytest.importorskip("flask")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, calculate_home_summaries
from solar_challenge.home import HomeConfig, SimulationResults, calculate_summary
from solar_challenge.scenario_writer import fleet_scenario, home_scenario
from solar_challenge.web.storage import RunRecord, RunStorage
from solar_challenge.web.stored_runs import (
    RUN_KINDS,
    RunType,
    StoredDocument,
    StoredFleetRun,
    StoredHomeRun,
    StoredRunUnreadable,
)
from tests._finance_builders import make_fleet_results_of, make_home_config, make_sim_results
from tests._web_runs import store_fleet_run, store_home_run

_HOME_RUN_ID = "home-1"
_FLEET_RUN_ID = "fleet-1"


def _a_home_named(name: str) -> HomeConfig:
    """make_home_config's home under *name*."""
    return dataclasses.replace(make_home_config(), name=name)


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


def _record(storage: RunStorage, run_id: str) -> RunRecord:
    """The record of run *run_id*, which the test has stored."""
    record = storage.run_record(run_id)
    assert record is not None, f"no run is recorded under {run_id!r}"
    return record


def _recorded_config(storage: RunStorage, run_id: str) -> StoredDocument:
    """The config document run *run_id*'s record holds, decoded from its config_json."""
    config_json = _record(storage, run_id).config_json
    assert config_json is not None, f"the record of run {run_id!r} holds no config"
    return StoredDocument.decoded(run_id, "runs.config_json", config_json)


def test_there_is_one_run_kind_for_each_run_type() -> None:
    assert set(RUN_KINDS) == set(get_args(RunType))


def test_a_stored_home_run_is_recorded_as_the_home_kind(storage: RunStorage) -> None:
    store_home_run(storage, _HOME_RUN_ID, *_a_home())

    assert _record(storage, _HOME_RUN_ID).kind is RUN_KINDS["home"]


def test_a_stored_home_run_loads_back_as_a_stored_home_run_of_its_config_results_and_summary(
    storage: RunStorage,
) -> None:
    config, results = _a_home()
    store_home_run(storage, _HOME_RUN_ID, config, results)

    stored = storage.load_run(_HOME_RUN_ID)

    assert isinstance(stored, StoredHomeRun)
    assert (stored.run_id, stored.config) == (_HOME_RUN_ID, config)
    assert stored.summary == calculate_summary(results)
    assert isinstance(stored.summary, RUN_KINDS["home"].summary_type)
    pd.testing.assert_frame_equal(stored.results.to_dataframe(), results.to_dataframe(), check_freq=False)


def test_a_stored_fleet_run_is_recorded_as_the_fleet_kind(storage: RunStorage) -> None:
    store_fleet_run(storage, _FLEET_RUN_ID, _two_unlike_homes())

    assert _record(storage, _FLEET_RUN_ID).kind is RUN_KINDS["fleet"]


def test_a_stored_fleet_run_loads_back_as_a_stored_fleet_run_of_its_homes_and_their_summaries(
    storage: RunStorage,
) -> None:
    fleet = _two_unlike_homes()
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)

    stored = storage.load_run(_FLEET_RUN_ID)

    assert isinstance(stored, StoredFleetRun)
    assert stored.run_id == _FLEET_RUN_ID
    assert stored.fleet_results.home_configs == fleet.home_configs
    assert stored.home_summaries == tuple(calculate_home_summaries(fleet))
    assert isinstance(stored.summary, RUN_KINDS["fleet"].summary_type)


def test_the_home_kind_reads_the_config_a_home_run_records_as_its_one_home(storage: RunStorage) -> None:
    config, results = _a_home()
    store_home_run(storage, _HOME_RUN_ID, config, results)

    assert RUN_KINDS["home"].home_configs(_recorded_config(storage, _HOME_RUN_ID)) == (config,)


def test_the_fleet_kind_reads_the_config_a_fleet_run_records_as_its_homes_in_order(storage: RunStorage) -> None:
    fleet = _two_unlike_homes()
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)

    assert RUN_KINDS["fleet"].home_configs(_recorded_config(storage, _FLEET_RUN_ID)) == tuple(fleet.home_configs)


def test_a_stored_home_run_exports_its_time_series(storage: RunStorage) -> None:
    config, results = _a_home()
    store_home_run(storage, _HOME_RUN_ID, config, results)

    stored = storage.load_run(_HOME_RUN_ID)

    pd.testing.assert_frame_equal(stored.export_frame(), results.to_dataframe(), check_freq=False)


def test_a_stored_fleet_run_exports_its_aggregate_time_series(storage: RunStorage) -> None:
    fleet = _two_unlike_homes()
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)

    stored = storage.load_run(_FLEET_RUN_ID)

    pd.testing.assert_frame_equal(stored.export_frame(), fleet.to_aggregate_dataframe(), check_freq=False)


def test_the_home_kinds_scenario_of_the_config_a_home_run_records_is_its_home_scenario(storage: RunStorage) -> None:
    config, results = _a_home()
    store_home_run(storage, _HOME_RUN_ID, config, results)
    home = RUN_KINDS["home"]

    scenario = home.scenario_document(home.home_configs(_recorded_config(storage, _HOME_RUN_ID)), "North Roof")

    assert scenario == home_scenario(config, name="North Roof")


def test_the_fleet_kinds_scenario_of_the_configs_a_fleet_run_records_is_its_fleet_scenario(storage: RunStorage) -> None:
    fleet = _two_unlike_homes()
    store_fleet_run(storage, _FLEET_RUN_ID, fleet)
    kind = RUN_KINDS["fleet"]

    scenario = kind.scenario_document(kind.home_configs(_recorded_config(storage, _FLEET_RUN_ID)), "Community Fleet")

    assert scenario == fleet_scenario(fleet.home_configs, name="Community Fleet")


def test_the_home_kinds_default_name_of_a_named_home_is_its_name() -> None:
    assert RUN_KINDS["home"].default_name((_a_home_named("North Roof"),)) == "North Roof"


@pytest.mark.parametrize("home_name", ["", "   ", "\t\n"], ids=["empty", "spaces", "tab-and-newline"])
def test_the_home_kinds_default_name_of_a_home_whose_name_cannot_name_a_run_is_web_simulation(home_name: str) -> None:
    assert RUN_KINDS["home"].default_name((_a_home_named(home_name),)) == "Web Simulation"


def test_the_home_kinds_default_name_of_no_home_is_web_simulation() -> None:
    """A run's record may hold no config, as one whose job failed before its save does, and its kind still names it."""
    assert RUN_KINDS["home"].default_name(()) == "Web Simulation"


@pytest.mark.parametrize(
    "homes",
    [(_a_home_named("Home 1"), _a_home_named("Home 2")), ()],
    ids=["two-named-homes", "no-home"],
)
def test_the_fleet_kinds_default_name_is_fleet_simulation_whatever_its_homes(homes: tuple[HomeConfig, ...]) -> None:
    assert RUN_KINDS["fleet"].default_name(homes) == "Fleet Simulation"


@pytest.mark.parametrize("run_id", ["no-such-run", "../escape"], ids=["no-run-has-it", "the-store-refuses-it"])
def test_loading_a_run_no_run_is_stored_under_raises_file_not_found_naming_its_id(
    storage: RunStorage, run_id: str
) -> None:
    with pytest.raises(FileNotFoundError, match=re.escape(run_id)):
        storage.load_run(run_id)


def test_loading_a_run_whose_job_saved_no_files_raises_file_not_found_naming_its_id(storage: RunStorage) -> None:
    storage.create_run("pending-1", run_type="home", name="Pending", n_homes=1, created_at="2024-06-01T09:00:00+00:00")

    with pytest.raises(FileNotFoundError, match="pending-1"):
        storage.load_run("pending-1")


def test_loading_a_run_whose_record_has_no_type_is_refused_as_the_kind_refuses_it_naming_its_id_and_runs_type(
    storage: RunStorage,
) -> None:
    """A run stored with no type cannot be read, so it is refused as unreadable, not as absent.

    The refusal is the one RunRecord.kind makes of the record, the one place a record with no
    type is refused a kind.
    """
    store_home_run(storage, _HOME_RUN_ID, *_a_home())
    with storage.database.transaction() as conn:
        conn.execute("UPDATE runs SET type = NULL WHERE id = ?", (_HOME_RUN_ID,))
    with pytest.raises(StoredRunUnreadable) as refused:
        _ = _record(storage, _HOME_RUN_ID).kind

    with pytest.raises(StoredRunUnreadable) as raised:
        storage.load_run(_HOME_RUN_ID)

    assert (raised.value.run_id, raised.value.document, raised.value.field) == (_HOME_RUN_ID, "runs.type", None)
    assert str(raised.value) == str(refused.value)


def test_the_kind_of_a_record_with_no_type_is_refused_as_unreadable_naming_its_run_and_runs_type() -> None:
    record = RunRecord(
        id="untyped-1",
        name="Untyped Run",
        type=None,
        config_json=None,
        summary_json=None,
        status=None,
        error_message=None,
        created_at=None,
        completed_at=None,
        duration_seconds=None,
        n_homes=None,
        notes=None,
    )

    with pytest.raises(StoredRunUnreadable, match="untyped-1") as refused:
        _ = record.kind

    assert (refused.value.run_id, refused.value.document, refused.value.field) == ("untyped-1", "runs.type", None)
