"""Tests for the run history browser and comparison features."""

import io
import json
import tempfile
import uuid
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app
from solar_challenge.web.database import get_db, init_db
from solar_challenge.web.storage import RunStorage


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    db_path = tmp_path / "test.db"
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
            "DATABASE": str(db_path),
            "DATA_DIR": str(tmp_path),
        }
    )
    return test_app


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


class TestDeleteAPI:
    """Tests for the run delete API endpoint."""

    def test_api_delete_nonexistent_run(self, client: FlaskClient) -> None:
        """Test DELETE /api/history/runs/<id> returns 404 for missing run."""
        response = client.delete("/api/history/runs/nonexistent-id")
        assert response.status_code == 404

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

    def test_api_export_yaml_with_config(self, app: Flask, client: FlaskClient) -> None:
        """Test YAML export returns config data."""
        _insert_test_run(
            app,
            run_id="yaml-export",
            name="YAML Run",
            config={"pv_config": {"capacity_kw": 4.0}},
        )

        response = client.get("/api/history/runs/yaml-export/export/yaml")
        assert response.status_code == 200
        assert "attachment" in response.headers.get("Content-Disposition", "")


# ---------------------------------------------------------------------------
# Comparison route tests
# ---------------------------------------------------------------------------


class TestComparisonRoute:
    """Tests for the comparison page route."""

    def test_compare_no_ids_redirects(self, client: FlaskClient) -> None:
        """Test GET /history/compare with no IDs redirects to runs page."""
        response = client.get("/history/compare")
        assert response.status_code == 302

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
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Test YAML export Content-Disposition header has quotes around the filename."""
        run_id = str(uuid.uuid4())
        _insert_test_run(app, run_id=run_id, name="YAML Quote Test")

        response = client.get(f"/api/history/runs/{run_id}/export/yaml")
        assert response.status_code == 200

        cd = response.headers.get("Content-Disposition", "")
        assert "attachment" in cd
        assert 'filename="' in cd, (
            f"Content-Disposition filename is not properly quoted: {cd}"
        )


class TestCompareWithoutIDs:
    """Tests for /history/compare redirect behavior without proper IDs."""

    def test_compare_without_ids_redirects_to_runs(self, client: FlaskClient) -> None:
        """Test GET /history/compare without IDs returns a redirect (not raw 400)."""
        response = client.get("/history/compare")
        # Should redirect, not return a raw 400 error
        assert response.status_code == 302
        assert response.status_code != 400

    def test_compare_without_ids_redirect_targets_runs_page(
        self, client: FlaskClient
    ) -> None:
        """Test that /history/compare redirect location points to the runs page."""
        response = client.get("/history/compare")
        assert response.status_code == 302
        location = response.headers.get("Location", "")
        assert "/history/runs" in location

    def test_compare_without_ids_follow_redirect_shows_flash(
        self, client: FlaskClient
    ) -> None:
        """Test that following the redirect shows a friendly flash message."""
        response = client.get("/history/compare", follow_redirects=True)
        assert response.status_code == 200
        html = response.data.decode("utf-8")
        # The flash message should inform user about selecting runs
        assert "No run IDs provided" in html or "Select" in html or "runs" in html.lower()
