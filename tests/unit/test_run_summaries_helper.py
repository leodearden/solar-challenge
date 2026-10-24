# SPDX-License-Identifier: AGPL-3.0-or-later
"""Unit tests for tests/_run_summaries.py, a run's summary with chosen figures and the summary_json text a save writes for it."""

import dataclasses
import json
from pathlib import Path

import pytest

pytest.importorskip("pyarrow")

from solar_challenge.fleet import FleetSummary
from solar_challenge.home import SummaryStatistics
from solar_challenge.web.schema import open_database
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.stored_runs import RunType
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._run_summaries import fleet_summary, home_summary, summary_json


@pytest.fixture
def storage(tmp_path: Path) -> RunStorage:
    """An empty RunStorage of no app under tmp_path, its database a new store open_database created."""
    return RunStorage(open_database(tmp_path / "runs.db"), tmp_path / "data")


def _stored_summary_json(storage: RunStorage, run_id: str) -> str:
    """The summary_json text of run *run_id*'s row, which the test has written with one."""
    record = storage.run_record(run_id)
    assert record is not None and record.summary_json is not None, f"run {run_id!r} has no summary_json"
    return record.summary_json


@pytest.mark.parametrize(
    ("run_type", "summary"),
    [
        pytest.param("home", home_summary(total_generation_kwh=987.65), id="home"),
        pytest.param("fleet", fleet_summary(fleet_self_consumption_ratio=0.25), id="fleet"),
    ],
)
def test_a_runs_row_written_with_a_summary_s_json_reads_back_as_the_summary_s_field_tree(
    storage: RunStorage, run_type: RunType, summary: SummaryStatistics | FleetSummary
) -> None:
    with storage.database.transaction() as conn:
        conn.execute(
            "INSERT INTO runs (id, type, status, summary_json) VALUES ('run-1', ?, 'completed', ?)",
            (run_type, summary_json(summary)),
        )

    assert json.loads(_stored_summary_json(storage, "run-1")) == dataclasses.asdict(summary)


def test_a_home_summary_s_json_is_the_text_a_home_run_s_save_writes(storage: RunStorage) -> None:
    summary = home_summary(total_generation_kwh=987.65)

    storage.save_home_run("home-1", make_home_config(), make_sim_results(days=1), summary)

    assert _stored_summary_json(storage, "home-1") == summary_json(summary)


def test_a_fleet_summary_s_json_is_the_text_a_fleet_run_s_save_writes(storage: RunStorage) -> None:
    summary = fleet_summary(fleet_self_consumption_ratio=0.25)

    storage.save_fleet_run("fleet-1", make_fleet_results(n_homes=2, days=1), summary, [home_summary(), home_summary()])

    assert _stored_summary_json(storage, "fleet-1") == summary_json(summary)


@pytest.mark.parametrize(
    ("given", "fixed", "figures"),
    [
        pytest.param(
            home_summary(total_generation_kwh=987.65, simulation_days=3),
            home_summary(),
            {"total_generation_kwh": 987.65, "simulation_days": 3},
            id="home",
        ),
        pytest.param(
            fleet_summary(fleet_self_consumption_ratio=0.25, n_homes=5),
            fleet_summary(),
            {"fleet_self_consumption_ratio": 0.25, "n_homes": 5},
            id="fleet",
        ),
    ],
)
def test_a_summary_holds_the_figures_given_in_place_of_those_fields_fixed_figures(
    given: SummaryStatistics | FleetSummary, fixed: SummaryStatistics | FleetSummary, figures: dict[str, object]
) -> None:
    assert dataclasses.asdict(given) == {**dataclasses.asdict(fixed), **figures}


def test_a_home_summary_is_100_kwh_generated_60_of_it_self_consumed_over_7_days_unless_given_other_figures() -> None:
    summary = home_summary()

    assert (
        summary.total_generation_kwh,
        summary.total_self_consumption_kwh,
        summary.self_consumption_ratio,
        summary.simulation_days,
    ) == (100.0, 60.0, 0.6, 7)


def test_a_fleet_summary_is_2_homes_200_kwh_generated_120_of_it_self_consumed_over_7_days_unless_given_other_figures() -> None:
    summary = fleet_summary()

    assert (
        summary.n_homes,
        summary.total_generation_kwh,
        summary.total_self_consumption_kwh,
        summary.fleet_self_consumption_ratio,
        summary.simulation_days,
    ) == (2, 200.0, 120.0, 0.6, 7)
