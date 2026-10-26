# SPDX-License-Identifier: AGPL-3.0-or-later
"""Upgrade an old dashboard and keep every run: B16 of docs/prds/run-store-one-owner.md §10, end to end through the CLI and HTTP.

The legacy store sits where default_store_location() puts it for `solar-challenge web start`
and `solar-challenge web migrate`: under ~/.solar-challenge, with HOME at the test's tmp_path.
It is:

- ι's pre-548 database (tests/fixtures/databases/pre_548_store.sql): no schema version, the
  retired jobs table, runs with no name;
- holding κ's three runs, stored before runs carried a format version
  (tests/fixtures/stored_runs), each with its run directory.

The pre-548 database's own runs have no run directory, so the tests list and delete every
run, but render and export only the stored ones.

`web start` refuses the store until `web migrate` has migrated it, and then serves it.
Flask.run is replaced by a recorder, so `web start` hands its dashboard over without serving
it, and each test drives that dashboard through its test client. cli/web.py's _serve shuts
every job manager down once its server stops (shutdown_all_managers), so no test submits a
job.
"""

import io
import json
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeGuard

import pandas as pd
import pytest
import yaml
from flask import Flask
from flask.testing import FlaskClient
from typer.testing import CliRunner, Result

from solar_challenge.cli.main import app
from solar_challenge.web.app import default_store_location
from solar_challenge.web.database import Database
from solar_challenge.web.schema import SCHEMA_VERSION
from solar_challenge.web.stored_runs import RunType
from tests._dashboard_databases import write_pre_548_database
from tests._html_page import headings
from tests._run_storage_layout import stored_run_dir
from tests._stored_run_fixtures import (
    STORED_RUN_FIXTURES,
    fixture_run_type,
    install_stored_run_fixture,
    stored_run_fixture_dir,
)
from tests._web_app import release_store_lock, run_storage_of

_MINUTES_OF_THE_FIXTURES_DAY = 24 * 60
"""The rows of each stored run's time series: one day at 1-minute resolution (tests/_stored_run_fixtures.py)."""

_HEADLINE_RATIO: Mapping[RunType, str] = {"home": "self_consumption_ratio", "fleet": "fleet_self_consumption_ratio"}
"""The field of a run's summary that History lists as its self_consumption_ratio, by run type (B7)."""

_NO_HEADLINE = (None, None)
"""The figures History lists for a run with no summary: its generation and its self-consumption ratio."""


@dataclass(frozen=True)
class _LegacyStore:
    """The legacy store's database file; by run id, each run's name as the database holds it (None for NULL); and by run id, the fixture name of each run that has files."""

    database: Path
    run_names: Mapping[str, str | None]
    stored_runs: Mapping[str, str]

    @property
    def run_ids(self) -> frozenset[str]:
        """Every run id the legacy database holds."""
        return frozenset(self.run_names)


def _web(*args: str) -> Result:
    """Run `solar-challenge web <args>` in this process, on a console wide enough that Rich prints each message on one line."""
    return CliRunner().invoke(app, ["web", *args], env={"COLUMNS": "1000"})


def _run_names_in(database: Path) -> dict[str, str | None]:
    """By run id, the name (None for NULL) of every run the runs table of the database file *database* holds, read with sqlite3 before anything migrates it."""
    with closing(sqlite3.connect(database)) as conn:
        return {run_id: name for run_id, name in conn.execute("SELECT id, name FROM runs")}


def _names_a_run(name: object) -> TypeGuard[str]:
    """Whether *name* can name a run, as contract C7 requires of every run's name: a str holding a character other than whitespace."""
    return isinstance(name, str) and name.strip() != ""


@pytest.fixture
def legacy_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _LegacyStore:
    """The pre-548 store, holding the three stored-run fixtures, under ~/.solar-challenge with HOME at *tmp_path*."""
    monkeypatch.setenv("HOME", str(tmp_path))
    location = default_store_location()
    database = write_pre_548_database(location.database)
    stored = {
        install_stored_run_fixture(name, Database(database), location.data_dir): name for name in STORED_RUN_FIXTURES
    }
    return _LegacyStore(database, _run_names_in(database), stored)


@pytest.fixture
def served_dashboards(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Flask]]:
    """Each dashboard `web start` hands to Flask.run, which records it rather than serving it; each one's store lock is released at teardown."""
    served: list[Flask] = []

    def record(self: Flask, *args: Any, **kwargs: Any) -> None:
        served.append(self)

    monkeypatch.setattr(Flask, "run", record)
    yield served
    for dashboard in served:
        release_store_lock(dashboard)


@pytest.fixture
def dashboard(legacy_store: _LegacyStore, served_dashboards: list[Flask]) -> Flask:
    """The dashboard `web start` serves on the legacy store once `web migrate` has migrated it."""
    migrated = _web("migrate")
    assert migrated.exit_code == 0, migrated.output
    started = _web("start")
    assert started.exit_code == 0, started.output
    (served,) = served_dashboards
    return served


def _history_rows(client: FlaskClient) -> list[dict[str, Any]]:
    """The rows History lists, every run on its first page."""
    response = client.get("/api/history/runs")
    assert response.status_code == 200, response.get_data(as_text=True)
    listing = response.get_json()
    runs: list[dict[str, Any]] = listing["runs"]
    assert listing["pagination"]["total"] == len(runs), listing["pagination"]
    return runs


def _fixture_headline(name: str) -> tuple[float, float]:
    """The generation and self-consumption ratio of fixture *name*'s run, as its summary.json holds them."""
    summary = json.loads((stored_run_fixture_dir(name) / "summary.json").read_text())
    return summary["total_generation_kwh"], summary[_HEADLINE_RATIO[fixture_run_type(name)]]


def _first_heading(client: FlaskClient, path: str) -> tuple[int, list[str]]:
    """The status of the page at *path*, and its first heading, if it has one."""
    response = client.get(path)
    return response.status_code, headings(response.get_data(as_text=True))[:1]


def _csv_export_rows(client: FlaskClient, run_id: str) -> int:
    """The rows of run *run_id*'s CSV export."""
    response = client.get(f"/api/history/runs/{run_id}/export/csv")
    assert (response.status_code, response.mimetype) == (200, "text/csv"), response.get_data(as_text=True)
    return len(pd.read_csv(io.StringIO(response.get_data(as_text=True)), index_col=0))


def _yaml_export_name(client: FlaskClient, run_id: str) -> str:
    """The name of the scenario run *run_id*'s YAML export holds."""
    response = client.get(f"/api/history/runs/{run_id}/export/yaml")
    assert (response.status_code, response.mimetype) == (200, "text/yaml"), response.get_data(as_text=True)
    name: str = yaml.safe_load(response.get_data(as_text=True))["name"]
    return name


def test_web_start_refuses_the_legacy_store_until_web_migrate_has_migrated_it(
    legacy_store: _LegacyStore, served_dashboards: list[Flask]
) -> None:
    """The refusal names the database, its version, this solar-challenge's and the migrate command, and changes nothing."""
    bytes_before = legacy_store.database.read_bytes()

    refused = _web("start")

    assert refused.exit_code == 1, refused.output
    for named in [str(legacy_store.database), "schema version 0", str(SCHEMA_VERSION), "solar-challenge web migrate"]:
        assert named in refused.stderr, (named, refused.stderr)
    assert legacy_store.database.read_bytes() == bytes_before
    assert served_dashboards == []

    migrated = _web("migrate")
    assert migrated.exit_code == 0, migrated.output
    started = _web("start")
    assert started.exit_code == 0, started.output
    assert len(served_dashboards) == 1, served_dashboards
    assert served_dashboards[0].test_client().get("/").status_code == 200


def test_history_lists_every_run_each_stored_one_with_its_summary_s_headline(
    dashboard: Flask, legacy_store: _LegacyStore
) -> None:
    """The runs of the pre-548 database have no summary, so no headline; none is unreadable."""
    rows = _history_rows(dashboard.test_client())

    headlines = {row["id"]: (row["total_generation_kwh"], row["self_consumption_ratio"]) for row in rows}
    assert headlines == dict.fromkeys(legacy_store.run_ids, _NO_HEADLINE) | {
        run_id: _fixture_headline(name) for run_id, name in legacy_store.stored_runs.items()
    }
    assert {row["id"]: row["unreadable"] for row in rows if row["unreadable"] is not None} == {}


def test_history_lists_every_run_under_a_name_each_named_one_under_the_name_it_had(
    dashboard: Flask, legacy_store: _LegacyStore
) -> None:
    """`web migrate` names each run the pre-548 database left NULL or blank (contract C7), and keeps every other run's name."""
    listed = {row["id"]: row["name"] for row in _history_rows(dashboard.test_client())}
    named = {run_id: name for run_id, name in legacy_store.run_names.items() if _names_a_run(name)}
    assert named.keys() < legacy_store.run_names.keys(), (
        f"the legacy store names every run, so this test sees no name back-filled: {legacy_store.run_names}"
    )

    assert {run_id: name for run_id, name in listed.items() if not _names_a_run(name)} == {}
    assert {run_id: listed.get(run_id) for run_id in named} == named


def test_each_stored_run_s_results_url_renders_its_results_page_under_its_name(
    dashboard: Flask, legacy_store: _LegacyStore
) -> None:
    """A home run's page and a fleet run's alike."""
    client = dashboard.test_client()
    rows = {row["id"]: row for row in _history_rows(client)}

    pages = {run_id: _first_heading(client, rows[run_id]["results_url"]) for run_id in legacy_store.stored_runs}

    assert pages == {run_id: (200, [rows[run_id]["name"]]) for run_id in legacy_store.stored_runs}


def test_each_stored_run_exports_its_day_of_time_series_as_csv_and_its_scenario_as_yaml(
    dashboard: Flask, legacy_store: _LegacyStore
) -> None:
    """The YAML scenario is named as History lists the run."""
    client = dashboard.test_client()
    names = {row["id"]: row["name"] for row in _history_rows(client)}

    exports = {
        run_id: (_csv_export_rows(client, run_id), _yaml_export_name(client, run_id))
        for run_id in legacy_store.stored_runs
    }

    assert exports == {run_id: (_MINUTES_OF_THE_FIXTURES_DAY, names[run_id]) for run_id in legacy_store.stored_runs}


def test_deleting_every_run_leaves_history_empty_and_no_stored_run_s_files(
    dashboard: Flask, legacy_store: _LegacyStore
) -> None:
    """Each run's detail answers 404 once it is deleted, and no stored run's directory is left."""
    client = dashboard.test_client()
    run_dirs = {run_id: stored_run_dir(run_storage_of(dashboard), run_id) for run_id in legacy_store.stored_runs}
    assert {run_id: run_dir.is_dir() for run_id, run_dir in run_dirs.items()} == dict.fromkeys(run_dirs, True)

    deleted = {run_id: client.delete(f"/api/history/runs/{run_id}").status_code for run_id in legacy_store.run_ids}

    assert deleted == dict.fromkeys(legacy_store.run_ids, 200)
    assert _history_rows(client) == []
    details = {run_id: client.get(f"/api/history/runs/{run_id}").status_code for run_id in legacy_store.run_ids}
    assert details == dict.fromkeys(legacy_store.run_ids, 404)
    assert [run_dir for run_dir in run_dirs.values() if run_dir.exists()] == []
