"""Tests for the run history browser and comparison features."""

import dataclasses
import io
import json
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.battery import BatteryConfig
from solar_challenge.cli.home import home_config_for_run
from solar_challenge.config import DispatchStrategyConfig, GridChargeConfig, load_fleet_config
from solar_challenge.fleet import FleetResults, calculate_fleet_summary
from solar_challenge.home import HomeConfig, calculate_summary
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.database import get_db, init_db
from solar_challenge.web.shared import LOCATION_PRESETS
from solar_challenge.web.storage import RunStorage

from tests._html_page import texts_after
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


@pytest.fixture
def storage(app: Flask) -> RunStorage:
    """Create a RunStorage instance using the test app config."""
    return RunStorage(
        db_path=app.config["DATABASE"],
        data_dir=app.config["DATA_DIR"],
    )


def _insert_test_run(
    app: Flask,
    run_id: str = "test-run-001",
    name: str = "Test Run",
    run_type: str = "home",
    status: str = "completed",
    summary: dict | None = None,
    config: dict | None = None,
) -> None:
    """Insert a test run directly into the database.

    This avoids needing to run a full simulation for route tests.
    """
    db_path = app.config["DATABASE"]
    summary = summary or {
        "total_generation_kwh": 100.0,
        "total_demand_kwh": 80.0,
        "total_self_consumption_kwh": 60.0,
        "total_grid_import_kwh": 20.0,
        "total_grid_export_kwh": 40.0,
        "total_battery_charge_kwh": 10.0,
        "total_battery_discharge_kwh": 8.0,
        "self_consumption_ratio": 0.60,
        "grid_dependency_ratio": 0.25,
        "export_ratio": 0.40,
    }
    config = config or {"pv_config": {"capacity_kw": 4.0}}

    with get_db(db_path) as conn:
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
                json.dumps(summary),
                status,
                "2025-06-01T12:00:00",
                "2025-06-01T12:01:00",
                60.0,
                1,
            ),
        )


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
        _insert_test_run(app, run_id="fleet-1", name="Fleet Run", run_type="fleet")

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

    def test_api_get_run_answers_every_column_with_config_and_summary_decoded(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A run's detail is each column of its row, plus its config and summary decoded."""
        config = {"pv_config": {"capacity_kw": 4.0}}
        summary = {"total_generation_kwh": 100.0, "self_consumption_ratio": 0.6}
        _insert_test_run(app, run_id="detail-run", name="Detail Run", summary=summary, config=config)

        response = client.get("/api/history/runs/detail-run")

        assert response.get_json() == {
            "id": "detail-run",
            "name": "Detail Run",
            "type": "home",
            "config_json": json.dumps(config),
            "summary_json": json.dumps(summary),
            "status": "completed",
            "error_message": None,
            "created_at": "2025-06-01T12:00:00",
            "completed_at": "2025-06-01T12:01:00",
            "duration_seconds": 60.0,
            "n_homes": 1,
            "notes": None,
            "config": config,
            "summary": summary,
        }

    def test_api_get_run_of_a_running_run_answers_its_row_without_decoded_config_or_summary(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A running run's detail is its row alone: with no config or summary stored yet, neither is decoded.

        The row is the placeholder JobManager.submit_fleet_job writes when it queues a fleet run.
        """
        with get_db(app.config["DATABASE"]) as conn:
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
        summary = {"total_generation_kwh": 100.0, "self_consumption_ratio": 0.6}
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
            "summary_json": json.dumps(summary),
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

    def test_api_export_yaml_with_config(self, storage: RunStorage, client: FlaskClient) -> None:
        """Test YAML export returns config data."""
        _store_home_run(
            storage,
            "yaml-export",
            HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
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
            HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
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

    def test_export_of_a_home_run_with_battery_dispatch_and_grid_charging_loads_back(
        self, storage: RunStorage, client: FlaskClient, tmp_path: Path
    ) -> None:
        """A battery's TOU dispatch strategy and grid charging survive the export."""
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500.0),
            battery_config=BatteryConfig(
                capacity_kwh=5.0,
                dispatch_strategy=DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 19)]),
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
                    dispatch_strategy=DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 19)]),
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
                    dispatch_strategy=DispatchStrategyConfig("peak_shaving", import_limit_kw=3.0),
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
        "config",
        [
            pytest.param({"pv_config": {"capacity_kw": 4.0}}, id="no load_config"),
            pytest.param(
                {
                    "pv_config": {"capacity_kw": 4.0},
                    "load_config": {},
                    "battery_config": {
                        "capacity_kwh": 5.0,
                        "dispatch_strategy": {"strategy_type": "tou_optimized"},
                    },
                },
                id="TOU dispatch strategy without peak hours",
            ),
        ],
    )
    def test_export_of_an_undecodable_stored_config_is_a_server_error(
        self, app: Flask, client: FlaskClient, config: dict
    ) -> None:
        """A stored config that a HomeConfig-tree constructor refuses is a JSON server error."""
        _insert_test_run(app, run_id="undecodable", config=config)

        response = client.get("/api/history/runs/undecodable/export/yaml")

        assert response.status_code == 500
        assert response.get_json()["error"].startswith("Invalid config data")


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
        from solar_challenge.web.charts import comparison_bar_chart

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
        from solar_challenge.web.charts import comparison_radar

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
        from solar_challenge.web.charts import comparison_bar_chart

        summaries = [{"total_generation_kwh": 50}, {}]
        result = comparison_bar_chart(summaries, ["A", "B"])
        assert result and result != "{}"

    def test_comparison_radar_handles_zero_generation(self) -> None:
        """Test comparison_radar handles zero generation gracefully."""
        from solar_challenge.web.charts import comparison_radar

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

    def test_overlaid_power_flows_returns_json(self) -> None:
        """Test overlaid_power_flows returns a non-empty JSON string."""
        import numpy as np

        from solar_challenge.home import SimulationResults
        from solar_challenge.web.charts import overlaid_power_flows

        index = pd.date_range("2024-06-01", periods=60, freq="min")
        gen = pd.Series(np.sin(np.arange(60) * 0.1) * 2, index=index)
        dem = pd.Series(np.ones(60) * 0.5, index=index)
        zeros = pd.Series(np.zeros(60), index=index)

        results = SimulationResults(
            generation=gen,
            demand=dem,
            self_consumption=dem,
            battery_charge=zeros,
            battery_discharge=zeros,
            battery_soc=zeros,
            grid_import=zeros,
            grid_export=zeros,
            import_cost=zeros,
            export_revenue=zeros,
            tariff_rate=zeros,
            strategy_name="greedy",
        )

        output = overlaid_power_flows([results, results], ["Run A", "Run B"])
        assert output and output != "{}"
        parsed = json.loads(output)
        assert "data" in parsed


# ---------------------------------------------------------------------------
# Fleet CSV export tests
# ---------------------------------------------------------------------------


def _make_sim_results(days: int = 1, gen_scale: float = 3.0, demand_val: float = 0.5) -> "SimulationResults":
    """Create a minimal SimulationResults object for testing.

    Args:
        days: Number of simulation days.
        gen_scale: Peak generation scale (kW).
        demand_val: Flat demand value (kW).

    Returns:
        SimulationResults with simple but valid data.
    """
    from solar_challenge.home import SimulationResults

    freq = "min"
    index = pd.date_range("2024-06-01", periods=days * 1440, freq=freq, tz="Europe/London")

    hours = np.arange(len(index)) / 60.0
    generation = np.maximum(0, np.sin(hours * np.pi / 12) * gen_scale)
    demand = np.full(len(index), demand_val)
    self_consumption = np.minimum(generation, demand)
    grid_import = np.maximum(0, demand - generation)
    grid_export = np.maximum(0, generation - demand)
    battery_charge = np.zeros(len(index))
    battery_discharge = np.zeros(len(index))
    battery_soc = np.zeros(len(index))

    def _series(values: np.ndarray, name: str) -> pd.Series:
        return pd.Series(values, index=index, name=name)

    return SimulationResults(
        generation=_series(generation, "generation_kw"),
        demand=_series(demand, "demand_kw"),
        self_consumption=_series(self_consumption, "self_consumption_kw"),
        battery_charge=_series(battery_charge, "battery_charge_kw"),
        battery_discharge=_series(battery_discharge, "battery_discharge_kw"),
        battery_soc=_series(battery_soc, "battery_soc_kwh"),
        grid_import=_series(grid_import, "grid_import_kw"),
        grid_export=_series(grid_export, "grid_export_kw"),
        import_cost=_series(np.zeros(len(index)), "import_cost_gbp"),
        export_revenue=_series(np.zeros(len(index)), "export_revenue_gbp"),
        tariff_rate=_series(np.zeros(len(index)), "tariff_rate_per_kwh"),
        strategy_name="self_consumption",
    )


def _store_home_run(
    storage: RunStorage, run_id: str, config: HomeConfig, name: str | None = None
) -> None:
    """Save a one-day home run of *config* through RunStorage, as a finished job does."""
    results = _make_sim_results(days=1)
    storage.save_home_run(
        run_id=run_id,
        config=config,
        results=results,
        summary=calculate_summary(results),
        name=name,
    )


def _store_fleet_run(storage: RunStorage, run_id: str, home_configs: list[HomeConfig]) -> None:
    """Save a one-day fleet run of *home_configs* through RunStorage, as a finished job does."""
    fleet_results = FleetResults(
        per_home_results=[_make_sim_results(days=1) for _ in home_configs],
        home_configs=home_configs,
    )
    storage.save_fleet_run(
        run_id=run_id,
        fleet_results=fleet_results,
        fleet_summary=calculate_fleet_summary(fleet_results),
        per_home_summaries=[calculate_summary(r) for r in fleet_results.per_home_results],
    )


class TestFleetCSVExport:
    """Tests for fleet CSV export containing aggregate data."""

    def _save_fleet_run(self, app: Flask, run_id: str, n_homes: int = 3) -> None:
        """Save a fleet run with multiple homes to storage for testing.

        Each home gets different generation/demand to verify aggregation.
        """
        from solar_challenge.fleet import FleetResults, calculate_fleet_summary
        from solar_challenge.home import HomeConfig, calculate_summary, SummaryStatistics
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig

        per_home_results = []
        home_configs = []
        per_home_summaries = []

        for i in range(n_homes):
            # Each home has different generation scale to make aggregation testable
            gen_scale = 2.0 + i * 1.0  # 2.0, 3.0, 4.0
            demand_val = 0.3 + i * 0.2  # 0.3, 0.5, 0.7

            results = _make_sim_results(days=1, gen_scale=gen_scale, demand_val=demand_val)
            per_home_results.append(results)

            config = HomeConfig(
                pv_config=PVConfig(capacity_kw=gen_scale),
                load_config=LoadConfig(annual_consumption_kwh=3000 + i * 500),
                name=f"Home {i + 1}",
            )
            home_configs.append(config)
            per_home_summaries.append(calculate_summary(results))

        fleet_results = FleetResults(
            per_home_results=per_home_results,
            home_configs=home_configs,
        )
        fleet_summary = calculate_fleet_summary(fleet_results)

        with app.app_context():
            storage = RunStorage(
                db_path=app.config["DATABASE"],
                data_dir=app.config["DATA_DIR"],
            )
            storage.save_fleet_run(
                run_id=run_id,
                fleet_results=fleet_results,
                fleet_summary=fleet_summary,
                per_home_summaries=per_home_summaries,
                name="Test Fleet",
            )

    def test_fleet_csv_contains_aggregate_data(self, app: Flask, client: FlaskClient) -> None:
        """Test that fleet CSV export contains aggregated data from all homes, not just the first."""
        run_id = str(uuid.uuid4())
        self._save_fleet_run(app, run_id, n_homes=3)

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
        # Each home has different gen_scale (2.0, 3.0, 4.0), so the aggregate
        # maximum should be higher than any single home's max.
        # A single home with gen_scale=4.0 would have max ~4.0 kW.
        # The aggregate of 3 homes should have max ~(2+3+4) = ~9 kW.
        max_gen = df["generation_kw"].max()
        assert max_gen > 5.0, (
            f"Aggregate generation max {max_gen} is too low; "
            "CSV may contain only first home, not the aggregate"
        )

    def test_fleet_csv_has_expected_columns(self, app: Flask, client: FlaskClient) -> None:
        """Test fleet CSV export has the expected aggregate columns."""
        run_id = str(uuid.uuid4())
        self._save_fleet_run(app, run_id, n_homes=2)

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
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Test CSV export Content-Disposition header has quotes around the filename."""
        run_id = str(uuid.uuid4())

        # Save a simple home run for export
        from solar_challenge.home import HomeConfig, calculate_summary
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig

        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500),
            name="Quote Test",
        )
        results = _make_sim_results(days=1)
        summary = calculate_summary(results)

        with app.app_context():
            storage = RunStorage(
                db_path=app.config["DATABASE"],
                data_dir=app.config["DATA_DIR"],
            )
            storage.save_home_run(
                run_id=run_id,
                config=config,
                results=results,
                summary=summary,
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
            HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig()),
            name="YAML Quote Test",
        )

        response = client.get(f"/api/history/runs/{run_id}/export/yaml")
        assert response.status_code == 200

        cd = response.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert 'filename="' in cd, (
            f"Content-Disposition filename is not properly quoted: {cd}"
        )


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
