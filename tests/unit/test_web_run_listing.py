# SPDX-License-Identifier: AGPL-3.0-or-later
"""The typed reads of a run's record, RunRecord.summary() and RunRecord.home_configs().

A record decodes its summary_json and config_json through its kind: a home run's summary
is a SummaryStatistics and a fleet run's a FleetSummary, and each run's config is its
homes' HomeConfigs, in order. A run with no document yet answers None, and a document that
does not decode is refused with a ValueError naming the run and the column.
"""

import dataclasses
from collections.abc import Callable
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.battery import BatteryConfig
from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import calculate_summary
from solar_challenge.web.database import init_db
from solar_challenge.web.storage import RunRecord, RunStorage
from tests._finance_builders import make_fleet_results, make_fleet_results_of, make_home_config, make_sim_results
from tests._web_runs import store_fleet_run, store_home_run


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """An empty RunStorage of no app under tmp_path, its database holding the schema init_db creates."""
    return RunStorage(init_db(tmp_path / "runs.db"), tmp_path / "data")


def _record(storage: RunStorage, run_id: str) -> RunRecord:
    """The record of run *run_id*, which the test has written."""
    record = storage.run_record(run_id)
    assert record is not None, f"no run has id {run_id!r}"
    return record


def _two_unlike_homes() -> FleetResults:
    """A fleet of two homes whose totals and batteries differ, so a mix-up of their order shows."""
    return make_fleet_results_of(
        [
            make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1),
            make_sim_results(self_kwh=10.0, export_kwh=20.0, import_kwh=30.0, days=1),
        ],
        homes=[make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))],
    )


def _store_a_home_run(storage: RunStorage, run_id: str) -> RunRecord:
    """Save a day of a default home's results as home run *run_id*, and answer its record."""
    store_home_run(storage, run_id, make_home_config(), make_sim_results(days=1))
    return _record(storage, run_id)


def _store_a_fleet_run(storage: RunStorage, run_id: str) -> RunRecord:
    """Save a day of two default homes' results as fleet run *run_id*, and answer its record."""
    store_fleet_run(storage, run_id, make_fleet_results(n_homes=2, days=1))
    return _record(storage, run_id)


_STORE_A_RUN_OF_EACH_KIND = [
    pytest.param(_store_a_home_run, id="home-run"),
    pytest.param(_store_a_fleet_run, id="fleet-run"),
]


def _summary_of(record: RunRecord) -> object:
    return record.summary()


def _home_configs_of(record: RunRecord) -> object:
    return record.home_configs()


_READ_OF_COLUMN: dict[str, Callable[[RunRecord], object]] = {
    "summary_json": _summary_of,
    "config_json": _home_configs_of,
}


class TestRunRecordTypedDocuments:
    """RunRecord.summary() and RunRecord.home_configs(): the run's documents, decoded through its kind."""

    def test_a_saved_home_run_has_the_summary_of_its_results_and_its_one_home_s_config(
        self, storage: RunStorage
    ) -> None:
        config = make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))
        results = make_sim_results(self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
        store_home_run(storage, "home-1", config, results)

        record = _record(storage, "home-1")

        assert record.summary() == calculate_summary(results)
        assert record.home_configs() == (config,)

    def test_a_saved_fleet_run_has_the_fleet_summary_of_its_results_and_each_home_s_config_in_order(
        self, storage: RunStorage
    ) -> None:
        fleet = _two_unlike_homes()
        store_fleet_run(storage, "fleet-1", fleet)

        record = _record(storage, "fleet-1")

        assert record.summary() == calculate_fleet_summary(fleet)
        assert record.home_configs() == tuple(fleet.home_configs)

    def test_a_run_whose_job_is_still_running_has_no_summary_and_no_homes_yet(self, storage: RunStorage) -> None:
        storage.create_run("running-1", run_type="fleet", name="North Roof", n_homes=3, created_at="2026-10-20T09:00:00+00:00")

        record = _record(storage, "running-1")

        assert (record.summary(), record.home_configs()) == (None, None)

    @pytest.mark.parametrize("store_a_run", _STORE_A_RUN_OF_EACH_KIND)
    @pytest.mark.parametrize(
        ("column", "text"),
        [
            pytest.param("summary_json", "{not json", id="summary-not-json"),
            pytest.param("summary_json", "[]", id="summary-not-an-object"),
            pytest.param("summary_json", '{"total_generation_kwh": 100.0}', id="summary-missing-required-fields"),
            pytest.param("config_json", "{not json", id="config-not-json"),
            pytest.param("config_json", "[]", id="config-not-an-object"),
            pytest.param("config_json", '{"pv_config": {"capacity_kw": 4.0}}', id="config-missing-load-config"),
        ],
    )
    def test_a_document_that_does_not_decode_is_refused_with_a_value_error_naming_the_run_and_its_column(
        self,
        storage: RunStorage,
        store_a_run: Callable[[RunStorage, str], RunRecord],
        column: str,
        text: str,
    ) -> None:
        garbled = dataclasses.replace(store_a_run(storage, "garbled-run"), **{column: text})

        with pytest.raises(ValueError) as refusal:
            _READ_OF_COLUMN[column](garbled)

        assert "'garbled-run'" in str(refusal.value)
        assert f"runs.{column}" in str(refusal.value)

    @pytest.mark.parametrize("column", list(_READ_OF_COLUMN))
    def test_a_record_with_no_type_is_refused_its_documents_by_the_kind_s_refusal_naming_its_run(
        self, storage: RunStorage, column: str
    ) -> None:
        untyped = dataclasses.replace(_store_a_home_run(storage, "untyped-run"), type=None)
        with pytest.raises(ValueError) as kind_refusal:
            _ = untyped.kind

        with pytest.raises(ValueError, match="untyped-run") as refusal:
            _READ_OF_COLUMN[column](untyped)

        assert str(refusal.value) == str(kind_refusal.value)
