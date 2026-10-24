"""Tests for the run history browser and comparison features."""

import dataclasses
import io
import json
import logging
import uuid
from collections.abc import Callable
from pathlib import Path

import pandas as pd
import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.config import load_fleet_config
from solar_challenge.dispatch import (
    GridChargeConfig,
    PeakShavingStrategyConfig,
    SelfConsumptionStrategyConfig,
    TOUOptimizedStrategyConfig,
)
from solar_challenge.fleet import FleetResults, FleetSummary, calculate_fleet_summary
from solar_challenge.home import HomeConfig, SummaryStatistics
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.charts import (
    comparison_bar_chart,
    comparison_radar,
)
from solar_challenge.web.database import RUN_TYPES
from solar_challenge.web.request_boundary import LOCATION_PRESETS
from solar_challenge.web.storage import RunStorage

from tests._finance_builders import make_fleet_results, make_home_config
from tests._html_page import element_attributes, element_count, texts_after
from tests._run_storage_layout import stored_run_dir
from tests._run_summaries import fleet_summary, home_summary, summary_json
from tests._sinusoidal_sim_results import make_sinusoidal_sim_results
from tests._web_app import database_of, point_store_config_at_a_missing_directory
from tests._web_runs import store_fleet_run, store_home_run


def _field_tree(home: HomeConfig) -> dict:
    """*home*'s field tree in JSON's values, as a run's config_json holds each of its homes."""
    return json.loads(json.dumps(dataclasses.asdict(home)))


_A_HOME = HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())

_A_HOME_FIELD_TREE = _field_tree(_A_HOME)

_PRE_DISPATCH_UNION_HOME_CONFIGS = (
    Path(__file__).resolve().parents[1] / "fixtures" / "stored_runs" / "pre_dispatch_union_home_configs.json"
)
"""A home run's stored config per dispatch strategy, as runs stored it before the strategies were
variants of one union: all three strategy keys, the ones the strategy does not read null."""

_STRATEGIES = (
    SelfConsumptionStrategyConfig(),
    TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
    PeakShavingStrategyConfig(import_limit_kw=3.0),
)
"""One example of each dispatch strategy, those of the stored configs above."""


def _insert_test_run(
    app: Flask,
    run_id: str = "test-run-001",
    name: str = "Test Run",
    run_type: str = "home",
    status: str = "completed",
    summary: SummaryStatistics | FleetSummary | None = None,
    config: dict | None = None,
    created_at: str = "2025-06-01T12:00:00",
) -> None:
    """Insert a test run directly into *app*'s database, created at *created_at*.

    Its summary_json is the text a save writes for *summary*, home_summary() by default, and
    its config_json *config* in JSON, _A_HOME's field tree by default.

    This avoids needing to run a full simulation for route tests.
    """
    summary = home_summary() if summary is None else summary
    config = _A_HOME_FIELD_TREE if config is None else config

    with database_of(app).transaction() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO runs (
                id, name, type, config_json, summary_json,
                status, created_at, completed_at,
                duration_seconds, n_homes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                name,
                run_type,
                json.dumps(config),
                summary_json(summary),
                status,
                created_at,
                "2025-06-01T12:01:00",
                60.0,
                1,
            ),
        )


def _garble(app: Flask, run_id: str, column: str) -> None:
    """Overwrite run *run_id*'s *column*, summary_json or config_json, with text that is not JSON."""
    with database_of(app).transaction() as conn:
        conn.execute(f"UPDATE runs SET {column} = ? WHERE id = ?", ("{not json", run_id))


# ---------------------------------------------------------------------------
# Run Browser page tests
# ---------------------------------------------------------------------------


class TestRunBrowserRoute:
    """Tests for the runs browser page route."""

    def test_runs_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /history/runs returns HTTP 200."""
        response = client.get("/history/runs")
        assert response.status_code == 200

    def test_runs_page_contains_title(self, client: FlaskClient) -> None:
        """Test GET /history/runs page contains 'Run History' heading."""
        response = client.get("/history/runs")
        assert b"Run History" in response.data

    def test_runs_page_returns_html(self, client: FlaskClient) -> None:
        """Test GET /history/runs returns HTML content type."""
        response = client.get("/history/runs")
        assert "text/html" in response.content_type

    def test_runs_page_contains_filter_controls(self, client: FlaskClient) -> None:
        """Test GET /history/runs page has filter inputs."""
        response = client.get("/history/runs")
        html = response.data.decode("utf-8")
        assert "filter-type" in html
        assert "filter-search" in html

    def test_the_type_filter_offers_all_then_exactly_the_run_types(self, client: FlaskClient) -> None:
        """The type filter, the page's only select, offers All and then each run type, labelled Home and Fleet."""
        page = client.get("/history/runs").get_data(as_text=True)

        assert [option.get("value") for option in element_attributes(page, "option")] == ["", *RUN_TYPES]
        assert texts_after(page, "All", len(RUN_TYPES)) == ["Home", "Fleet"]


# ---------------------------------------------------------------------------
# Old /history/api/* path tests
# ---------------------------------------------------------------------------


class TestOldHistoryApiPaths:
    """The /history/api/* paths no longer resolve: the run history's JSON and export endpoints answer only under /api/history/."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            pytest.param("GET", "/history/api/runs", id="list-runs"),
            pytest.param("GET", "/history/api/runs/stored-run", id="get-run"),
            pytest.param("DELETE", "/history/api/runs/stored-run", id="delete-run"),
            pytest.param("PATCH", "/history/api/runs/stored-run", id="patch-run"),
            pytest.param("GET", "/history/api/runs/stored-run/export/csv", id="export-csv"),
            pytest.param("GET", "/history/api/runs/stored-run/export/yaml", id="export-yaml"),
        ],
    )
    def test_answers_404_instead_of_redirecting(
        self, storage: RunStorage, client: FlaskClient, method: str, path: str
    ) -> None:
        """Each old path, requested with the method its redirect took, answers 404 for a stored run, which its /api/history/ twin serves."""
        _store_home_run(storage, "stored-run", _A_HOME)

        assert client.open(path, method=method).status_code == 404


# ---------------------------------------------------------------------------
# Runs API tests
# ---------------------------------------------------------------------------


class TestRunsAPI:
    """Tests for the runs list API endpoint."""

    def test_api_runs_returns_json(self, client: FlaskClient) -> None:
        """Test GET /api/history/runs returns JSON with runs and pagination."""
        response = client.get("/api/history/runs")
        assert response.status_code == 200
        data = response.get_json()
        assert "runs" in data
        assert "pagination" in data

    def test_api_runs_pagination_metadata(self, client: FlaskClient) -> None:
        """Test pagination metadata has expected fields."""
        response = client.get("/api/history/runs?page=1&per_page=5")
        assert response.status_code == 200
        data = response.get_json()
        pag = data["pagination"]
        assert pag["page"] == 1
        assert pag["per_page"] == 5
        assert "total" in pag
        assert "total_pages" in pag
        assert "has_next" in pag
        assert "has_prev" in pag

    def test_api_runs_empty_database(self, client: FlaskClient) -> None:
        """Test API returns empty runs list for empty database."""
        response = client.get("/api/history/runs")
        data = response.get_json()
        assert data["runs"] == []
        assert data["pagination"]["total"] == 0

    def test_api_runs_with_data(self, app: Flask, client: FlaskClient) -> None:
        """Test API returns runs when data exists."""
        _insert_test_run(app, run_id="run-1", name="First Run")
        _insert_test_run(app, run_id="run-2", name="Second Run")

        response = client.get("/api/history/runs")
        data = response.get_json()
        assert len(data["runs"]) == 2
        assert data["pagination"]["total"] == 2

    def test_api_runs_type_filter(self, app: Flask, client: FlaskClient) -> None:
        """Test API filters by run type."""
        _insert_test_run(app, run_id="home-1", name="Home Run", run_type="home")
        _insert_test_run(app, run_id="fleet-1", name="Fleet Run", run_type="fleet", summary=fleet_summary())

        response = client.get("/api/history/runs?type=home")
        data = response.get_json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["type"] == "home"

    def test_api_runs_search_filter(self, app: Flask, client: FlaskClient) -> None:
        """Test API filters by search query."""
        _insert_test_run(app, run_id="run-a", name="Alpha Test")
        _insert_test_run(app, run_id="run-b", name="Beta Run")

        response = client.get("/api/history/runs?q=Alpha")
        data = response.get_json()
        assert len(data["runs"]) == 1
        assert data["runs"][0]["name"] == "Alpha Test"

    def test_api_runs_sort_order(self, app: Flask, client: FlaskClient) -> None:
        """Test API respects sort and order parameters."""
        _insert_test_run(app, run_id="run-a", name="AAA Run")
        _insert_test_run(app, run_id="run-b", name="ZZZ Run")

        response = client.get("/api/history/runs?sort=name&order=asc")
        data = response.get_json()
        assert data["runs"][0]["name"] == "AAA Run"

    def test_api_runs_includes_summary_metrics(self, app: Flask, client: FlaskClient) -> None:
        """Test API response includes extracted summary metrics."""
        _insert_test_run(app, run_id="run-1", name="Metrics Run")

        response = client.get("/api/history/runs")
        data = response.get_json()
        run = data["runs"][0]
        assert run["total_generation_kwh"] == 100.0
        assert run["self_consumption_ratio"] == 0.60

    def test_a_fleet_run_lists_the_generation_and_the_fleet_self_consumption_ratio_its_summary_holds(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """B7: a fleet run's row lists its FleetSummary's total generation and fleet_self_consumption_ratio, not null."""
        store_fleet_run(
            storage, "fleet-run", make_fleet_results(n_homes=2, self_kwh=18.0, export_kwh=54.0, import_kwh=27.0, days=1)
        )
        record = storage.run_record("fleet-run")
        assert record is not None
        summary = record.summary()
        assert isinstance(summary, FleetSummary)
        assert summary.fleet_self_consumption_ratio == pytest.approx(0.25)

        rows = client.get("/api/history/runs?type=fleet").get_json()["runs"]

        assert [
            (row["id"], row["total_generation_kwh"], row["self_consumption_ratio"], row["results_url"]) for row in rows
        ] == [("fleet-run", summary.total_generation_kwh, summary.fleet_self_consumption_ratio, "/results/fleet-run")]

    def test_a_type_that_is_no_run_type_is_refused_naming_it_and_each_run_type(self, client: FlaskClient) -> None:
        """?type=sweep answers 400 rather than a list of no runs."""
        response = client.get("/api/history/runs?type=sweep")

        assert response.status_code == 400
        error = response.get_json()["error"]
        assert [name for name in ("sweep", *RUN_TYPES) if repr(name) not in error] == [], error

    @pytest.mark.parametrize(
        ("parameter", "value"),
        [
            pytest.param("per_page", "0", id="per-page-0"),
            pytest.param("per_page", "101", id="per-page-101"),
            pytest.param("page", "0", id="page-0"),
            pytest.param("page", "abc", id="page-abc"),
            pytest.param("sort", "evil", id="sort-evil"),
            pytest.param("order", "sideways", id="order-sideways"),
            pytest.param("date_from", "not-a-date", id="date-from-not-a-date"),
            pytest.param("date_to", "not-a-date", id="date-to-not-a-date"),
        ],
    )
    def test_a_query_value_no_page_answers_is_refused_naming_its_parameter_and_the_value_sent(
        self, client: FlaskClient, parameter: str, value: str
    ) -> None:
        """The value is refused with 400, not clamped into range or replaced by the parameter's default."""
        response = client.get("/api/history/runs", query_string={parameter: value})

        assert response.status_code == 400
        error = response.get_json()["error"]
        assert parameter in error and value in error, error

    def test_a_run_whose_summary_does_not_decode_lists_no_figures_beside_the_others_and_a_warning_names_it(
        self, app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """One damaged run neither fails the list nor hides the other runs' figures (the G7 waiver in docs/prds/run-store-one-owner.md)."""
        _insert_test_run(
            app, run_id="readable-run", summary=home_summary(total_generation_kwh=987.65, self_consumption_ratio=0.37)
        )
        _insert_test_run(app, run_id="garbled-run")
        _garble(app, "garbled-run", "summary_json")
        caplog.set_level(logging.WARNING, logger="solar_challenge.web.storage")

        response = client.get("/api/history/runs")

        assert response.status_code == 200
        assert {
            row["id"]: (row["total_generation_kwh"], row["self_consumption_ratio"])
            for row in response.get_json()["runs"]
        } == {"readable-run": (987.65, 0.37), "garbled-run": (None, None)}
        assert [record.levelno for record in caplog.records if "garbled-run" in record.getMessage()] == [
            logging.WARNING
        ]

    def test_dates_keep_the_runs_created_from_the_first_date_to_the_end_of_the_last(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run created in the last fraction of a second of date_to is kept, as a run created at the next midnight is not."""
        _insert_test_run(app, run_id="day-before", created_at="2025-05-31T23:59:59.900000+00:00")
        _insert_test_run(app, run_id="first-day", created_at="2025-06-01T00:00:00+00:00")
        _insert_test_run(app, run_id="last-moment", created_at="2025-06-02T23:59:59.500000+00:00")
        _insert_test_run(app, run_id="next-midnight", created_at="2025-06-03T00:00:00+00:00")

        rows = client.get("/api/history/runs?date_from=2025-06-01&date_to=2025-06-02").get_json()["runs"]

        assert [row["id"] for row in rows] == ["last-moment", "first-day"]

    def test_each_listed_run_links_to_its_results_page(self, storage: RunStorage, client: FlaskClient) -> None:
        """Each row GET /api/history/runs lists, a home run's and a fleet run's alike, carries results_url, the path of its run's one results page, /results/<run_id>."""
        _store_home_run(storage, "home-run", _A_HOME)
        _store_fleet_run(storage, "fleet-run", [_A_HOME, _A_HOME])

        rows = client.get("/api/history/runs").get_json()["runs"]

        assert {row["id"]: row["results_url"] for row in rows} == {
            "home-run": "/results/home-run",
            "fleet-run": "/results/fleet-run",
        }

    def test_the_run_list_answers_from_the_apps_database_after_its_store_config_names_a_missing_directory(
        self, app: Flask, client: FlaskClient, tmp_path: Path
    ) -> None:
        """GET /api/history/runs reads the Database create_app built, whatever the app's store config names afterwards."""
        _insert_test_run(app, run_id="listed-run")
        point_store_config_at_a_missing_directory(app, tmp_path / "missing")

        response = client.get("/api/history/runs")

        assert response.status_code == 200
        assert [run["id"] for run in response.get_json()["runs"]] == ["listed-run"]


class TestRunDetailAPI:
    """Tests for the single run detail API endpoint."""

    def test_api_get_run_returns_data(self, app: Flask, client: FlaskClient) -> None:
        """Test GET /api/history/runs/<id> returns full run detail."""
        _insert_test_run(app, run_id="detail-run")

        response = client.get("/api/history/runs/detail-run")
        assert response.status_code == 200
        data = response.get_json()
        assert data["id"] == "detail-run"

    def test_api_get_run_nonexistent_returns_404(self, client: FlaskClient) -> None:
        """Test GET /api/history/runs/<id> returns 404 for missing run."""
        response = client.get("/api/history/runs/nonexistent-id")
        assert response.status_code == 404

    def test_api_get_run_answers_every_column_with_its_summary_and_homes_decoded(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run's detail is each column of its row, plus its summary's field tree and each of its homes' HomeConfig field tree."""
        summary = home_summary()
        _insert_test_run(app, run_id="detail-run", name="Detail Run", summary=summary)

        response = client.get("/api/history/runs/detail-run")

        assert response.get_json() == {
            "id": "detail-run",
            "name": "Detail Run",
            "type": "home",
            "config_json": json.dumps(_A_HOME_FIELD_TREE),
            "summary_json": summary_json(summary),
            "status": "completed",
            "error_message": None,
            "created_at": "2025-06-01T12:00:00",
            "completed_at": "2025-06-01T12:01:00",
            "duration_seconds": 60.0,
            "n_homes": 1,
            "notes": None,
            "summary": dataclasses.asdict(summary),
            "home_configs": [_A_HOME_FIELD_TREE],
        }

    def test_api_get_run_of_a_fleet_run_answers_its_fleet_summary_and_each_home_in_the_fleet_s_order(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """A fleet run's summary is its FleetSummary's field tree, fleet_self_consumption_ratio among them."""
        homes = [make_home_config(), make_home_config(battery_config=BatteryConfig(capacity_kwh=5.0))]
        fleet = make_fleet_results(homes=homes, days=1)
        store_fleet_run(storage, "fleet-run", fleet)

        data = client.get("/api/history/runs/fleet-run").get_json()

        assert "fleet_self_consumption_ratio" in data["summary"]
        assert data["summary"] == dataclasses.asdict(calculate_fleet_summary(fleet))
        assert data["home_configs"] == [_field_tree(home) for home in homes]

    def test_api_get_run_of_a_running_run_answers_its_row_without_a_summary_or_homes(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A running run's detail is its row alone: with no config or summary stored yet, neither is decoded.

        The row is the placeholder JobManager.submit_fleet_job writes when it queues a fleet run.
        """
        with database_of(app).transaction() as conn:
            conn.execute(
                "INSERT INTO runs (id, name, type, status, created_at, n_homes)"
                " VALUES ('running-run', 'Still Running', 'fleet', 'running', '2025-06-02T09:00:00', 3)"
            )

        response = client.get("/api/history/runs/running-run")

        assert response.get_json() == {
            "id": "running-run",
            "name": "Still Running",
            "type": "fleet",
            "config_json": None,
            "summary_json": None,
            "status": "running",
            "error_message": None,
            "created_at": "2025-06-02T09:00:00",
            "completed_at": None,
            "duration_seconds": None,
            "n_homes": 3,
            "notes": None,
        }

    @pytest.mark.parametrize("column", ["summary_json", "config_json"])
    def test_api_get_run_of_a_run_whose_document_does_not_decode_answers_409_naming_the_run_and_its_column(
        self, app: Flask, client: FlaskClient, column: str
    ) -> None:
        """A stored summary or config that is not JSON is refused, not decoded as {}."""
        _insert_test_run(app, run_id="garbled-run")
        _garble(app, "garbled-run", column)

        response = client.get("/api/history/runs/garbled-run")

        assert response.status_code == 409
        body = response.get_json()
        assert body == {"error": body["error"], "run_id": "garbled-run"}
        assert "'garbled-run'" in body["error"] and f"runs.{column}" in body["error"], body["error"]


class TestDeleteAPI:
    """Tests for the run delete API endpoint."""

    def test_api_delete_nonexistent_run(self, client: FlaskClient) -> None:
        """Test DELETE /api/history/runs/<id> returns 404 for missing run."""
        response = client.delete("/api/history/runs/nonexistent-id")
        assert response.status_code == 404

    def test_api_delete_of_an_id_that_is_no_valid_run_id_is_404(self, client: FlaskClient) -> None:
        """An id the store refuses answers 404, as an id no run has does, not a server error."""
        response = client.delete("/api/history/runs/no.such.run")

        assert response.status_code == 404
        assert response.get_json() == {"error": "Run not found"}

    def test_api_delete_existing_run(self, app: Flask, client: FlaskClient) -> None:
        """Test DELETE /api/history/runs/<id> deletes an existing run."""
        _insert_test_run(app, run_id="delete-me")

        response = client.delete("/api/history/runs/delete-me")
        assert response.status_code == 200
        data = response.get_json()
        assert data["success"] is True

        # Verify it is gone
        verify = client.get("/api/history/runs/delete-me")
        assert verify.status_code == 404


class TestPatchAPI:
    """Tests for the run update (PATCH) API endpoint."""

    def test_api_patch_nonexistent_run(self, client: FlaskClient) -> None:
        """Test PATCH /api/history/runs/<id> returns 404 for missing run."""
        response = client.patch(
            "/api/history/runs/nonexistent-id",
            json={"name": "test"},
        )
        assert response.status_code == 404

    def test_api_patch_rename_run(self, app: Flask, client: FlaskClient) -> None:
        """Test PATCH /api/history/runs/<id> updates run name."""
        _insert_test_run(app, run_id="rename-me", name="Old Name")

        response = client.patch(
            "/api/history/runs/rename-me",
            json={"name": "New Name"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "New Name"

    def test_api_patch_update_notes(self, app: Flask, client: FlaskClient) -> None:
        """Test PATCH /api/history/runs/<id> updates run notes."""
        _insert_test_run(app, run_id="note-me")

        response = client.patch(
            "/api/history/runs/note-me",
            json={"notes": "Some notes here"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["notes"] == "Some notes here"

    def test_api_patch_no_fields_returns_400(self, app: Flask, client: FlaskClient) -> None:
        """Test PATCH with no updatable fields returns 400."""
        _insert_test_run(app, run_id="empty-patch")

        response = client.patch(
            "/api/history/runs/empty-patch",
            json={},
        )
        assert response.status_code == 400

    def test_api_patch_of_name_and_notes_answers_the_updated_row(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A PATCH of name and notes answers the run's row as updated, its config and summary not decoded."""
        config = {"pv_config": {"capacity_kw": 4.0}}
        summary = home_summary()
        _insert_test_run(app, run_id="relabel-me", name="Old Name", summary=summary, config=config)

        response = client.patch(
            "/api/history/runs/relabel-me",
            json={"name": "New Name", "notes": "Checked"},
        )

        assert response.status_code == 200
        assert response.get_json() == {
            "id": "relabel-me",
            "name": "New Name",
            "type": "home",
            "config_json": json.dumps(config),
            "summary_json": summary_json(summary),
            "status": "completed",
            "error_message": None,
            "created_at": "2025-06-01T12:00:00",
            "completed_at": "2025-06-01T12:01:00",
            "duration_seconds": 60.0,
            "n_homes": 1,
            "notes": "Checked",
        }

    def test_api_patch_with_no_fields_of_an_unknown_run_is_404(self, client: FlaskClient) -> None:
        """An unknown run answers 404 even when the body has no fields to update, which would answer 400."""
        response = client.patch("/api/history/runs/nonexistent-id", json={})

        assert response.status_code == 404
        assert response.get_json() == {"error": "Run not found"}

    @pytest.mark.parametrize(
        "body",
        [{"name": ""}, {"name": None}, {"name": "   "}, {"name": "", "notes": "Checked"}],
        ids=["empty", "null", "spaces", "empty-beside-notes"],
    )
    def test_api_patch_of_a_null_or_blank_name_is_400_naming_name_and_writes_no_label(
        self, app: Flask, client: FlaskClient, body: dict[str, str | None]
    ) -> None:
        """A run's name is never NULL or blank, so the run keeps its name, and the notes given beside it are not written."""
        _insert_test_run(app, run_id="keep-my-name", name="Old Name")

        response = client.patch("/api/history/runs/keep-my-name", json=body)

        assert response.status_code == 400
        assert response.get_json()["error"].startswith("name is ")
        run = client.get("/api/history/runs/keep-my-name").get_json()
        assert (run["name"], run["notes"]) == ("Old Name", None)


class TestExportAPI:
    """Tests for the CSV and YAML export API endpoints."""

    def test_api_export_csv_nonexistent_returns_404(self, client: FlaskClient) -> None:
        """Test CSV export for missing run returns 404."""
        response = client.get("/api/history/runs/nonexistent/export/csv")
        assert response.status_code == 404

    def test_api_export_yaml_nonexistent_returns_404(self, client: FlaskClient) -> None:
        """Test YAML export for missing run returns 404."""
        response = client.get("/api/history/runs/nonexistent/export/yaml")
        assert response.status_code == 404

    def test_api_export_yaml_of_a_run_whose_job_has_saved_nothing_yet_returns_404(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """A running run's record holds no config yet, so it has no scenario to export."""
        storage.create_run("pending-1", run_type="home", name="Pending", n_homes=1, created_at="2024-06-01T09:00:00+00:00")

        response = client.get("/api/history/runs/pending-1/export/yaml")

        assert (response.status_code, response.get_json()) == (404, {"error": "No config data available"})

    def test_api_export_yaml_with_config(self, storage: RunStorage, client: FlaskClient) -> None:
        """Test YAML export returns config data."""
        _store_home_run(
            storage,
            "yaml-export",
            _A_HOME,
            name="YAML Run",
        )

        response = client.get("/api/history/runs/yaml-export/export/yaml")
        assert response.status_code == 200
        assert "attachment" in response.headers.get("Content-Disposition", "")

    @pytest.mark.parametrize("export", ["csv", "yaml"])
    def test_export_is_named_after_its_run(
        self, storage: RunStorage, client: FlaskClient, export: str
    ) -> None:
        """An export's file is named after its run's name and the first 8 characters of its id."""
        run_id = "0123456789-named-export"
        _store_home_run(
            storage,
            run_id,
            _A_HOME,
            name="North Roof",
        )

        response = client.get(f"/api/history/runs/{run_id}/export/{export}")

        assert response.status_code == 200
        assert response.headers["Content-Disposition"] == f'attachment; filename="North Roof_01234567.{export}"'

    def test_export_of_a_home_run_loads_back_through_home_run(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path
    ) -> None:
        """The task's repro: this run's export loaded back with PV 4.0, no battery and no SEG.

        The SEG tariff comes back unnamed, as a seg: block names no tariff.
        """
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=9.0),
            load_config=LoadConfig(annual_consumption_kwh=3500.0),
            battery_config=BatteryConfig(capacity_kwh=10.0),
            location=LOCATION_PRESETS["edinburgh"],
            name="Nine",
            tariff_config=TariffConfig.economy_7(),
            seg_tariff=SEGTariff(name="Custom", rate_pence_per_kwh=5.5),
        )
        _store_home_run(storage, "nine-kw-home", config)

        response = client.get("/api/history/runs/nine-kw-home/export/yaml")

        assert response.status_code == 200
        assert "attachment" in response.headers.get("Content-Disposition", "")
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        assert home_config_for_run(path) == dataclasses.replace(
            config, seg_tariff=SEGTariff(name="", rate_pence_per_kwh=5.5)
        )

    def test_export_of_a_fleet_run_loads_back_through_load_fleet_config(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path
    ) -> None:
        edinburgh = LOCATION_PRESETS["edinburgh"]
        home_configs = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=3.0),
                load_config=LoadConfig(annual_consumption_kwh=2900.0),
                location=edinburgh,
                name="Home 1",
            ),
            HomeConfig(
                pv_config=PVConfig(capacity_kw=6.0),
                load_config=LoadConfig(annual_consumption_kwh=4100.0),
                battery_config=BatteryConfig(capacity_kwh=5.0),
                location=edinburgh,
                name="Home 2",
            ),
        ]
        _store_fleet_run(storage, "two-home-fleet", home_configs)

        response = client.get("/api/history/runs/two-home-fleet/export/yaml")

        assert response.status_code == 200
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        assert load_fleet_config(path).homes == home_configs

    def test_export_of_a_fleet_run_reads_its_homes_from_its_record_and_none_of_its_time_series(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path
    ) -> None:
        """The scenario is built from the config the run's record holds, so the export still answers once every time series file is gone."""
        home_configs = [
            HomeConfig(pv_config=PVConfig(capacity_kw=3.0), load_config=LoadConfig(annual_consumption_kwh=2900.0), name="Home 1"),
            HomeConfig(pv_config=PVConfig(capacity_kw=6.0), load_config=LoadConfig(annual_consumption_kwh=4100.0), name="Home 2"),
        ]
        _store_fleet_run(storage, "fleet-without-time-series", home_configs)
        time_series = list(stored_run_dir(storage, "fleet-without-time-series").rglob("*.parquet"))
        assert len(time_series) == len(home_configs)
        for time_series_file in time_series:
            time_series_file.unlink()

        response = client.get("/api/history/runs/fleet-without-time-series/export/yaml")

        assert response.status_code == 200
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        assert load_fleet_config(path).homes == home_configs

    @pytest.mark.parametrize("strategy", _STRATEGIES, ids=lambda strategy: strategy.strategy_type)
    def test_export_of_a_home_run_with_battery_dispatch_and_grid_charging_loads_back(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path, strategy: object
    ) -> None:
        """A battery's dispatch strategy, whichever it is, and its grid charging survive the export."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500.0),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                dispatch_strategy=strategy,
                grid_charging=GridChargeConfig(target_soc_fraction=0.8),
            ),
            tariff_config=TariffConfig.economy_7(),
            dispatch_strategy="tou_optimized",
        )
        _store_home_run(storage, "tou-battery-home", config)

        response = client.get("/api/history/runs/tou-battery-home/export/yaml")

        assert response.status_code == 200
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        assert home_config_for_run(path) == config

    def test_export_of_a_fleet_run_with_battery_dispatch_loads_back_through_load_fleet_config(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path
    ) -> None:
        """Each home keeps its battery's dispatch strategy, TOU with grid charging or peak shaving."""
        home_configs = [
            HomeConfig(
                pv_config=PVConfig(capacity_kw=3.0),
                load_config=LoadConfig(annual_consumption_kwh=2900.0),
                battery_config=BatteryConfig(
                    capacity_kwh=5.0,
                    dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19),)),
                    grid_charging=GridChargeConfig(target_soc_fraction=0.8),
                ),
                tariff_config=TariffConfig.economy_7(),
                name="Home 1",
            ),
            HomeConfig(
                pv_config=PVConfig(capacity_kw=6.0),
                load_config=LoadConfig(annual_consumption_kwh=4100.0),
                battery_config=BatteryConfig(
                    capacity_kwh=10.0,
                    dispatch_strategy=PeakShavingStrategyConfig(import_limit_kw=3.0),
                ),
                name="Home 2",
            ),
        ]
        _store_fleet_run(storage, "dispatch-fleet", home_configs)

        response = client.get("/api/history/runs/dispatch-fleet/export/yaml")

        assert response.status_code == 200
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        assert load_fleet_config(path).homes == home_configs

    @pytest.mark.parametrize("strategy", _STRATEGIES, ids=lambda strategy: strategy.strategy_type)
    def test_export_of_a_run_stored_before_the_dispatch_union_loads_back_with_its_variant(
        self, app: Flask, client: FlaskClient, tmp_path: Path, strategy: object
    ) -> None:
        """Such a run stores all three strategy keys, the ones its strategy does not read null."""
        stored = json.loads(_PRE_DISPATCH_UNION_HOME_CONFIGS.read_text())[strategy.strategy_type]
        _insert_test_run(app, run_id="pre-union", config=stored)

        response = client.get("/api/history/runs/pre-union/export/yaml")

        assert response.status_code == 200
        path = tmp_path / "export.yaml"
        path.write_bytes(response.data)
        battery_config = home_config_for_run(path).battery_config
        assert battery_config is not None
        assert battery_config.dispatch_strategy == strategy
        assert battery_config.grid_charging == GridChargeConfig(target_soc_fraction=0.8)

    def test_export_refuses_a_run_config_the_scenario_grammar_cannot_express(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0, custom_module_params={"pdc0": 250.0}),
            load_config=LoadConfig(),
        )
        _store_home_run(storage, "custom-pvlib", config)

        response = client.get("/api/history/runs/custom-pvlib/export/yaml")

        assert response.status_code == 422
        assert "custom_module_params" in response.get_json()["error"]

    @pytest.mark.parametrize(
        ("config", "named"),
        [
            pytest.param({"pv_config": {"capacity_kw": 4.0}}, (), id="no load_config"),
            pytest.param(
                {
                    "pv_config": {"capacity_kw": 4.0},
                    "load_config": {},
                    "battery_config": {
                        "capacity_kwh": 5.0,
                        "dispatch_strategy": {"strategy_type": "tou_optimized"},
                    },
                },
                (),
                id="TOU dispatch strategy without peak hours",
            ),
            pytest.param(
                {
                    "pv_config": {"capacity_kw": 4.0},
                    "load_config": {},
                    "battery_config": {
                        "capacity_kwh": 5.0,
                        "dispatch_strategy": {"strategy_type": "turbo"},
                    },
                },
                ("strategy_type", "'turbo'"),
                id="dispatch strategy no strategy is tagged with",
            ),
        ],
    )
    def test_export_of_an_undecodable_stored_config_is_a_server_error(
        self, app: Flask, client: FlaskClient, config: dict, named: tuple[str, ...]
    ) -> None:
        """A stored config that a HomeConfig-tree constructor refuses, or whose strategy no variant is tagged with, is a JSON server error."""
        _insert_test_run(app, run_id="undecodable", config=config)

        response = client.get("/api/history/runs/undecodable/export/yaml")

        assert response.status_code == 500
        error = response.get_json()["error"]
        assert error.startswith("Invalid run data")
        for text in named:
            assert text in error


# ---------------------------------------------------------------------------
# Comparison route tests
# ---------------------------------------------------------------------------


class TestComparisonRoute:
    """Tests for the comparison page route."""

    def test_compare_no_ids_shows_empty_state(self, client: FlaskClient) -> None:
        """Test GET /history/compare with no IDs shows empty state page."""
        response = client.get("/history/compare")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "No Runs Selected" in html

    def test_compare_single_id_redirects(self, client: FlaskClient) -> None:
        """Test GET /history/compare with only 1 ID redirects to runs page."""
        response = client.get("/history/compare?ids=run-1")
        assert response.status_code == 302

    def test_compare_two_valid_runs(self, app: Flask, client: FlaskClient) -> None:
        """Test GET /history/compare with 2 valid run IDs returns 200."""
        _insert_test_run(app, run_id="cmp-1", name="Compare A")
        _insert_test_run(app, run_id="cmp-2", name="Compare B")

        response = client.get("/history/compare?ids=cmp-1,cmp-2")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "Compare Runs" in html
        assert "Compare A" in html
        assert "Compare B" in html

    def test_compare_shows_each_run_s_name_type_creation_time_and_summary_metrics(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Each run's header card shows its name, type and creation time; each metric row its values, Delta and % Change.

        The cards are read after the page's subtitle, the one text before them, since each run
        name appears twice on the page.
        """
        _insert_test_run(
            app, run_id="cmp-a", name="Compare A", run_type="home", summary=home_summary(total_generation_kwh=100.0)
        )
        _insert_test_run(
            app, run_id="cmp-b", name="Compare B", run_type="fleet", summary=fleet_summary(total_generation_kwh=120.0)
        )

        page = client.get("/history/compare?ids=cmp-a,cmp-b").get_data(as_text=True)

        assert texts_after(page, "Side-by-side comparison of selected simulation runs", 6) == [
            "Compare A",
            "home",
            "2025-06-01T12:00:00",
            "Compare B",
            "fleet",
            "2025-06-01T12:00:00",
        ]
        assert texts_after(page, "Total Generation", 4) == ["100.0 kWh", "120.0 kWh", "+20.0 kWh", "+20.0%"]

    def test_compare_answers_a_server_error_when_a_chart_cannot_be_drawn(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A comparison chart that cannot be drawn fails the request with the app's 500 page, as a results page's chart does, instead of the page being served without it."""
        _insert_test_run(app, run_id="cmp-1", name="Compare A")
        null_ratio = home_summary(grid_dependency_ratio=None)
        _insert_test_run(app, run_id="cmp-2", name="Compare B", summary=null_ratio)
        app.config["PROPAGATE_EXCEPTIONS"] = False

        response = client.get("/history/compare?ids=cmp-1,cmp-2")

        assert response.status_code == 500
        page = response.get_data(as_text=True)
        assert texts_after(page, "500", 1) == ["Internal Server Error"]

    def test_compare_answers_a_server_error_when_a_run_s_summary_does_not_decode(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run whose stored summary is not JSON fails the request with the app's 500 page, instead of being compared as a run of zeros."""
        _insert_test_run(app, run_id="cmp-1", name="Compare A")
        _insert_test_run(app, run_id="cmp-2", name="Compare B")
        _garble(app, "cmp-2", "summary_json")
        app.config["PROPAGATE_EXCEPTIONS"] = False

        response = client.get("/history/compare?ids=cmp-1,cmp-2")

        assert response.status_code == 500
        page = response.get_data(as_text=True)
        assert texts_after(page, "500", 1) == ["Internal Server Error"]

    def test_compare_nonexistent_ids_redirects(self, client: FlaskClient) -> None:
        """Test GET /history/compare with all invalid IDs redirects to runs page."""
        response = client.get("/history/compare?ids=fake-1,fake-2")
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# Comparison chart function tests
# ---------------------------------------------------------------------------


class TestComparisonCharts:
    """Tests for the comparison chart functions in charts.py."""

    def test_comparison_bar_chart_returns_json(self) -> None:
        """Test comparison_bar_chart returns a non-empty JSON string."""
        summaries = [
            {
                "total_generation_kwh": 100,
                "total_demand_kwh": 80,
                "total_self_consumption_kwh": 60,
                "total_grid_import_kwh": 20,
                "total_grid_export_kwh": 40,
            },
            {
                "total_generation_kwh": 120,
                "total_demand_kwh": 90,
                "total_self_consumption_kwh": 70,
                "total_grid_import_kwh": 20,
                "total_grid_export_kwh": 50,
            },
        ]
        result = comparison_bar_chart(summaries, ["Run A", "Run B"])
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed

    def test_comparison_radar_returns_json(self) -> None:
        """Test comparison_radar returns a non-empty JSON string."""
        summaries = [
            {
                "self_consumption_ratio": 0.6,
                "grid_dependency_ratio": 0.25,
                "export_ratio": 0.4,
                "total_battery_charge_kwh": 10,
                "total_generation_kwh": 100,
            },
            {
                "self_consumption_ratio": 0.7,
                "grid_dependency_ratio": 0.2,
                "export_ratio": 0.3,
                "total_battery_charge_kwh": 15,
                "total_generation_kwh": 120,
            },
        ]
        result = comparison_radar(summaries, ["Run A", "Run B"])
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed

    def test_comparison_bar_chart_handles_missing_keys(self) -> None:
        """Test comparison_bar_chart handles summaries with missing keys."""
        summaries = [{"total_generation_kwh": 50}, {}]
        result = comparison_bar_chart(summaries, ["A", "B"])
        assert result and result != "{}"

    def test_comparison_radar_handles_zero_generation(self) -> None:
        """Test comparison_radar handles zero generation gracefully."""
        summaries = [
            {
                "self_consumption_ratio": 0,
                "grid_dependency_ratio": 1.0,
                "export_ratio": 0,
                "total_battery_charge_kwh": 0,
                "total_generation_kwh": 0,
            },
        ]
        result = comparison_radar(summaries, ["Empty Run"])
        assert result and result != "{}"


# ---------------------------------------------------------------------------
# Fleet CSV export tests
# ---------------------------------------------------------------------------


def _store_home_run(
    storage: RunStorage, run_id: str, config: HomeConfig, name: str | None = None
) -> None:
    """Save a one-day home run of *config* through RunStorage, as a finished job does."""
    store_home_run(storage, run_id, config, make_sinusoidal_sim_results(days=1), name=name)


def _store_fleet_run(storage: RunStorage, run_id: str, home_configs: list[HomeConfig]) -> None:
    """Save a one-day fleet run of *home_configs* through RunStorage, as a finished job does."""
    store_fleet_run(
        storage,
        run_id,
        FleetResults(
            per_home_results=[make_sinusoidal_sim_results(days=1) for _ in home_configs],
            home_configs=home_configs,
        ),
    )


class TestFleetCSVExport:
    """Tests for fleet CSV export containing aggregate data."""

    def _save_fleet_run(self, storage: RunStorage, run_id: str, n_homes: int = 3) -> None:
        """Save a fleet run with multiple homes to storage for testing.

        Each home gets different generation/demand to verify aggregation.
        """
        per_home_results = []
        home_configs = []

        for i in range(n_homes):
            # Each home has a different peak generation to make aggregation testable
            peak_generation_kw = 2.0 + i * 1.0  # 2.0, 3.0, 4.0
            demand_kw = 0.3 + i * 0.2  # 0.3, 0.5, 0.7

            results = make_sinusoidal_sim_results(
                days=1, peak_generation_kw=peak_generation_kw, demand_kw=demand_kw
            )
            per_home_results.append(results)

            config = HomeConfig(
                pv_config=PVConfig(capacity_kw=peak_generation_kw),
                load_config=LoadConfig(annual_consumption_kwh=3000 + i * 500),
                name=f"Home {i + 1}",
            )
            home_configs.append(config)

        store_fleet_run(
            storage,
            run_id,
            FleetResults(per_home_results=per_home_results, home_configs=home_configs),
            name="Test Fleet",
        )

    def test_fleet_csv_contains_aggregate_data(self, storage: RunStorage, client: FlaskClient) -> None:
        """Test that fleet CSV export contains aggregated data from all homes, not just the first."""
        run_id = str(uuid.uuid4())
        self._save_fleet_run(storage, run_id, n_homes=3)

        response = client.get(f"/api/history/runs/{run_id}/export/csv")
        assert response.status_code == 200
        assert "text/csv" in response.content_type

        csv_text = response.data.decode("utf-8")

        # Parse the CSV
        df = pd.read_csv(io.StringIO(csv_text))

        # The aggregate should have generation_kw column
        assert "generation_kw" in df.columns
        assert "demand_kw" in df.columns

        # Aggregate generation should be the SUM of all homes.
        # Each home has a different peak_generation_kw (2.0, 3.0, 4.0), so the aggregate
        # maximum should be higher than any single home's max.
        # A single home with peak_generation_kw=4.0 would have max ~4.0 kW.
        # The aggregate of 3 homes should have max ~(2+3+4) = ~9 kW.
        max_gen = df["generation_kw"].max()
        assert max_gen > 5.0, (
            f"Aggregate generation max {max_gen} is too low; "
            "CSV may contain only first home, not the aggregate"
        )

    def test_fleet_csv_has_expected_columns(self, storage: RunStorage, client: FlaskClient) -> None:
        """Test fleet CSV export has the expected aggregate columns."""
        run_id = str(uuid.uuid4())
        self._save_fleet_run(storage, run_id, n_homes=2)

        response = client.get(f"/api/history/runs/{run_id}/export/csv")
        assert response.status_code == 200

        csv_text = response.data.decode("utf-8")
        df = pd.read_csv(io.StringIO(csv_text))

        expected_cols = {"generation_kw", "demand_kw", "self_consumption_kw",
                         "grid_import_kw", "grid_export_kw"}
        assert expected_cols.issubset(set(df.columns))


class TestContentDispositionHeader:
    """Tests for Content-Disposition header quoting in export endpoints."""

    def test_csv_content_disposition_has_quoted_filename(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Test CSV export Content-Disposition header has quotes around the filename."""
        run_id = str(uuid.uuid4())
        _store_home_run(
            storage,
            run_id,
            HomeConfig(
                pv_config=PVConfig(capacity_kw=4.0),
                load_config=LoadConfig(annual_consumption_kwh=3500),
                name="Quote Test",
            ),
            name="Quote Test",
        )

        response = client.get(f"/api/history/runs/{run_id}/export/csv")
        assert response.status_code == 200

        cd = response.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        # The filename should be quoted: filename="something.csv"
        assert 'filename="' in cd, (
            f"Content-Disposition filename is not properly quoted: {cd}"
        )

    def test_yaml_content_disposition_has_quoted_filename(
        self, storage: RunStorage, client: FlaskClient
    ) -> None:
        """Test YAML export Content-Disposition header has quotes around the filename."""
        run_id = str(uuid.uuid4())
        _store_home_run(
            storage,
            run_id,
            _A_HOME,
            name="YAML Quote Test",
        )

        response = client.get(f"/api/history/runs/{run_id}/export/yaml")
        assert response.status_code == 200

        cd = response.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert 'filename="' in cd, (
            f"Content-Disposition filename is not properly quoted: {cd}"
        )


def _store_home_run_and_return_its_results_page(storage: RunStorage, run_id: str) -> str:
    """Save a home run of _A_HOME as *run_id*, and return the path of its results page."""
    _store_home_run(storage, run_id, _A_HOME)
    return f"/results/{run_id}"


def _store_fleet_run_and_return_its_results_page(storage: RunStorage, run_id: str) -> str:
    """Save a fleet run of two _A_HOMEs as *run_id*, and return the path of its results page."""
    _store_fleet_run(storage, run_id, [_A_HOME, _A_HOME])
    return f"/results/{run_id}"


class TestResultsPageExportLinks:
    """Each results page links to its run's CSV and YAML exports at /api/history/runs/<run_id>/export/*, the URLs that serve them."""

    @pytest.mark.parametrize("export", ["csv", "yaml"])
    @pytest.mark.parametrize(
        "store_run_and_return_its_results_page",
        [
            pytest.param(_store_home_run_and_return_its_results_page, id="home"),
            pytest.param(_store_fleet_run_and_return_its_results_page, id="fleet"),
        ],
    )
    def test_the_results_page_links_to_each_export_of_its_run(
        self,
        storage: RunStorage,
        client: FlaskClient,
        store_run_and_return_its_results_page: Callable[[RunStorage, str], str],
        export: str,
    ) -> None:
        """A stored run's results page, home or fleet, has exactly one link to that run's export at /api/history/runs/<run_id>/export/<export>."""
        run_id = "stored-run"
        results_page = store_run_and_return_its_results_page(storage, run_id)

        response = client.get(results_page)

        assert response.status_code == 200
        assert element_count(
            response.get_data(as_text=True),
            "a",
            {"href": f"/api/history/runs/{run_id}/export/{export}"},
        ) == 1


class TestCompareWithoutIDs:
    """Tests for /history/compare redirect behavior without proper IDs."""

    def test_compare_without_ids_shows_empty_state(self, client: FlaskClient) -> None:
        """Test GET /history/compare without IDs returns empty state (not raw 400)."""
        response = client.get("/history/compare")
        # Should render empty state page, not return a raw 400 error
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "No Runs Selected" in html

    def test_compare_without_ids_contains_link_to_runs_page(
        self, client: FlaskClient
    ) -> None:
        """Test that /history/compare empty state contains link to runs page."""
        response = client.get("/history/compare")
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        assert "/history/runs" in html

    def test_compare_without_ids_shows_helpful_message(
        self, client: FlaskClient
    ) -> None:
        """The empty state's No Runs Selected heading is followed by the message saying how to select runs."""
        response = client.get("/history/compare")
        assert response.status_code == 200
        page = response.get_data(as_text=True)
        assert texts_after(page, "No Runs Selected", 1) == [
            "Select 2-4 simulation runs from the history page to compare their results side by side."
        ]
