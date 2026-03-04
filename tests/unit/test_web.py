"""Tests for the Flask web dashboard module."""

import pytest
import pandas as pd
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


@pytest.fixture
def app() -> Flask:
    """Create a test Flask application."""
    test_app = create_app(
        test_config={
            "TESTING": True,
            "SECRET_KEY": "test-secret-key",
            "WTF_CSRF_ENABLED": False,
        }
    )
    return test_app


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


class TestIndexRoute:
    """Tests for the GET / route."""

    def test_get_index_returns_200(self, client: FlaskClient) -> None:
        """Test GET / returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_get_index_returns_html(self, client: FlaskClient) -> None:
        """Test GET / returns HTML content."""
        response = client.get("/")
        assert b"html" in response.data.lower() or b"<" in response.data

    def test_get_index_content_type_html(self, client: FlaskClient) -> None:
        """Test GET / returns text/html content type."""
        response = client.get("/")
        assert "text/html" in response.content_type


class TestDashboardRoute:
    """Tests for the dashboard page rendered at GET /."""

    def test_dashboard_returns_200(self, client: FlaskClient) -> None:
        """Test GET / returns HTTP 200."""
        response = client.get("/")
        assert response.status_code == 200

    def test_dashboard_contains_dashboard_text(self, client: FlaskClient) -> None:
        """Test GET / response contains 'Dashboard' text."""
        response = client.get("/")
        assert b"Dashboard" in response.data

    def test_dashboard_contains_sidebar_navigation(self, client: FlaskClient) -> None:
        """Test GET / response contains sidebar navigation elements."""
        response = client.get("/")
        html_data = response.data.decode("utf-8")
        # Sidebar should contain navigation group labels
        assert "Simulate" in html_data
        assert "Scenarios" in html_data
        assert "History" in html_data

    def test_dashboard_contains_quick_start_cards(self, client: FlaskClient) -> None:
        """Test GET / response contains quick-start action cards."""
        response = client.get("/")
        html_data = response.data.decode("utf-8")
        assert "Run Single Home" in html_data
        assert "Run Fleet Simulation" in html_data
        assert "Build Scenario" in html_data

    def test_dashboard_contains_stats_section(self, client: FlaskClient) -> None:
        """Test GET / response contains aggregate stats section."""
        response = client.get("/")
        html_data = response.data.decode("utf-8")
        assert "Total Runs" in html_data
        assert "Homes Simulated" in html_data
        assert "Energy Modelled" in html_data

    def test_dashboard_contains_recent_runs_section(self, client: FlaskClient) -> None:
        """Test GET / response contains recent runs section."""
        response = client.get("/")
        html_data = response.data.decode("utf-8")
        assert "Recent Runs" in html_data
        # Should show either existing runs in a table or the empty state message
        has_runs_table = "recent-runs-table" in html_data
        has_empty_state = "No simulation runs yet" in html_data
        assert has_runs_table or has_empty_state


class TestSimulateHomeRoute:
    """Tests for the GET /simulate/home route."""

    def test_simulate_home_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/home returns HTTP 200."""
        response = client.get("/simulate/home")
        assert response.status_code == 200

    def test_simulate_home_page_contains_form(self, client: FlaskClient) -> None:
        """Test GET /simulate/home response contains form elements for PV, Battery, etc."""
        response = client.get("/simulate/home")
        html_data = response.data.decode("utf-8")
        assert "pv_kw" in html_data
        assert "battery_kwh" in html_data
        assert "consumption_kwh" in html_data
        assert "Run Simulation" in html_data

    def test_simulate_home_page_contains_tabs(self, client: FlaskClient) -> None:
        """Test GET /simulate/home response contains tab navigation."""
        response = client.get("/simulate/home")
        html_data = response.data.decode("utf-8")
        assert "activeTab" in html_data
        assert "'pv'" in html_data or '"pv"' in html_data
        assert "'battery'" in html_data or '"battery"' in html_data
        assert "'load'" in html_data or '"load"' in html_data
        assert "'location'" in html_data or '"location"' in html_data
        assert "'period'" in html_data or '"period"' in html_data


# ---------------------------------------------------------------------------
# Helpers for chart / results tests
# ---------------------------------------------------------------------------

def _make_sim_results(days: int = 3) -> "SimulationResults":
    """Create a minimal SimulationResults object for testing.

    Builds synthetic 1-minute resolution time series spanning the
    requested number of days, suitable for exercising chart functions.

    Args:
        days: Number of simulation days.

    Returns:
        SimulationResults with simple but valid data.
    """
    import numpy as np
    from solar_challenge.home import SimulationResults as SR

    freq = "min"
    index = pd.date_range("2024-06-01", periods=days * 1440, freq=freq, tz="Europe/London")

    # Simple synthetic profiles (sinusoidal generation, flat demand)
    hours = np.arange(len(index)) / 60.0
    generation = np.maximum(0, np.sin(hours * np.pi / 12) * 3.0)
    demand = np.full(len(index), 0.5)
    self_consumption = np.minimum(generation, demand)
    grid_import = np.maximum(0, demand - generation)
    grid_export = np.maximum(0, generation - demand)
    battery_charge = np.zeros(len(index))
    battery_discharge = np.zeros(len(index))
    battery_soc = np.zeros(len(index))

    def _series(values: np.ndarray, name: str) -> pd.Series:
        return pd.Series(values, index=index, name=name)

    return SR(
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


def _make_summary_dict() -> dict:
    """Return a minimal summary dictionary for testing sankey_diagram."""
    return {
        "total_generation_kwh": 100.0,
        "total_demand_kwh": 80.0,
        "total_self_consumption_kwh": 50.0,
        "total_grid_import_kwh": 30.0,
        "total_grid_export_kwh": 40.0,
        "total_battery_charge_kwh": 10.0,
        "total_battery_discharge_kwh": 8.0,
        "peak_generation_kw": 4.0,
        "peak_demand_kw": 2.5,
        "self_consumption_ratio": 0.5,
        "grid_dependency_ratio": 0.375,
        "export_ratio": 0.4,
        "simulation_days": 3,
    }


class TestChartFunctions:
    """Tests for the centralized chart functions in charts.py."""

    def test_daily_energy_balance_returns_json(self) -> None:
        """Test daily_energy_balance returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import daily_energy_balance

        results = _make_sim_results(days=3)
        output = daily_energy_balance(results)
        assert isinstance(output, str)
        assert len(output) > 2  # more than just "{}"
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_sankey_returns_json(self) -> None:
        """Test sankey_diagram returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import sankey_diagram

        summary = _make_summary_dict()
        output = sankey_diagram(summary)
        assert isinstance(output, str)
        assert len(output) > 2
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_power_flow_timeline_returns_json(self) -> None:
        """Test power_flow_timeline returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import power_flow_timeline

        results = _make_sim_results(days=2)
        output = power_flow_timeline(results)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_battery_soc_chart_returns_json(self) -> None:
        """Test battery_soc_chart returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import battery_soc_chart

        results = _make_sim_results(days=2)
        output = battery_soc_chart(results, battery_capacity_kwh=10.0)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_financial_breakdown_returns_json(self) -> None:
        """Test financial_breakdown returns a non-empty JSON string."""
        import json as _json
        from solar_challenge.web.charts import financial_breakdown

        results = _make_sim_results(days=3)
        output = financial_breakdown(results)
        assert isinstance(output, str)
        parsed = _json.loads(output)
        assert "data" in parsed

    def test_monthly_summary_returns_none_for_short_sim(self) -> None:
        """Test monthly_summary returns None when simulation < 90 days."""
        from solar_challenge.web.charts import monthly_summary

        results = _make_sim_results(days=30)
        output = monthly_summary(results)
        assert output is None

    def test_seasonal_comparison_returns_none_for_short_sim(self) -> None:
        """Test seasonal_comparison returns None when simulation < 180 days."""
        from solar_challenge.web.charts import seasonal_comparison

        results = _make_sim_results(days=60)
        output = seasonal_comparison(results)
        assert output is None

    def test_heat_pump_analysis_returns_none_without_hp(self) -> None:
        """Test heat_pump_analysis returns None when no heat pump data."""
        from solar_challenge.web.charts import heat_pump_analysis

        results = _make_sim_results(days=2)
        output = heat_pump_analysis(results)
        assert output is None

    def test_adaptive_downsample_preserves_small_data(self) -> None:
        """Test _adaptive_downsample returns data unchanged when small."""
        from solar_challenge.web.charts import _adaptive_downsample

        index = pd.date_range("2024-01-01", periods=100, freq="min")
        df = pd.DataFrame({"a": range(100)}, index=index)
        result = _adaptive_downsample(df, max_points=200)
        assert len(result) == 100

    def test_adaptive_downsample_reduces_large_data(self) -> None:
        """Test _adaptive_downsample reduces rows for large data."""
        from solar_challenge.web.charts import _adaptive_downsample

        index = pd.date_range("2024-01-01", periods=10000, freq="min")
        df = pd.DataFrame({"a": range(10000)}, index=index)
        result = _adaptive_downsample(df, max_points=500)
        assert len(result) < 10000


class TestHomeResultsRoute:
    """Tests for the GET /results/home/<run_id> route."""

    def test_home_results_unknown_run_redirects(self, client: FlaskClient) -> None:
        """Test accessing results for a non-existent run redirects."""
        response = client.get("/results/home/nonexistent-id")
        assert response.status_code in (302, 404)

    def test_home_results_after_simulation(self, app: Flask, client: FlaskClient) -> None:
        """Test accessing results after saving a run directly returns 200."""
        import uuid
        from solar_challenge.home import HomeConfig, calculate_summary
        from solar_challenge.pv import PVConfig
        from solar_challenge.load import LoadConfig
        from solar_challenge.web.storage import RunStorage

        # Create a test run directly via storage
        run_id = str(uuid.uuid4())
        config = HomeConfig(
            pv_config=PVConfig(capacity_kw=4.0),
            load_config=LoadConfig(annual_consumption_kwh=3500),
            name="Test Run",
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
                name="Test Run",
            )

        # Access the results page
        response = client.get(f"/results/home/{run_id}")
        assert response.status_code == 200
        html_data = response.data.decode("utf-8")
        assert "Total Generation" in html_data or "Generation" in html_data
        assert "chart-sankey" in html_data or "chart-daily-balance" in html_data


class TestFleetConfigRoute:
    """Tests for the GET /simulate/fleet route."""

    def test_fleet_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet returns HTTP 200."""
        response = client.get("/simulate/fleet")
        assert response.status_code == 200

    def test_fleet_page_contains_distribution_editors(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet response contains distribution editors."""
        response = client.get("/simulate/fleet")
        html_data = response.data.decode("utf-8").lower()
        assert "distribution" in html_data
        assert "n_homes" in html_data or "homes" in html_data

    def test_fleet_page_contains_pv_battery_load_sections(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet contains PV, Battery, and Load sections."""
        response = client.get("/simulate/fleet")
        html_data = response.data.decode("utf-8")
        assert "PV Capacity" in html_data
        assert "Battery Capacity" in html_data
        assert "Annual Consumption" in html_data

    def test_fleet_page_contains_action_buttons(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet contains import/export/run buttons."""
        response = client.get("/simulate/fleet")
        html_data = response.data.decode("utf-8")
        assert "Import YAML" in html_data
        assert "Export YAML" in html_data
        assert "Run Fleet Simulation" in html_data

    def test_fleet_page_has_correct_page_identifier(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet passes simulate-fleet page identifier."""
        response = client.get("/simulate/fleet")
        html_data = response.data.decode("utf-8")
        assert "simulate-fleet" in html_data


class TestFleetConfigHelpers:
    """Tests for fleet_config.py helper functions."""

    def test_sample_distribution_normal(self) -> None:
        """Test normal distribution sampling produces correct count and bounds."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}
        )
        assert len(samples) == 100
        assert all(1.0 <= s <= 8.0 for s in samples)

    def test_sample_distribution_normal_custom_count(self) -> None:
        """Test normal distribution with custom n_samples."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "normal", {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0}, n_samples=50
        )
        assert len(samples) == 50

    def test_sample_distribution_uniform(self) -> None:
        """Test uniform distribution sampling produces correct count and bounds."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution("uniform", {"min": 2.0, "max": 6.0})
        assert len(samples) == 100
        assert all(2.0 <= s <= 6.0 for s in samples)

    def test_sample_distribution_weighted_discrete(self) -> None:
        """Test weighted discrete distribution sampling."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "weighted_discrete",
            {"values": [{"value": 3.0, "weight": 50}, {"value": 5.0, "weight": 50}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_shuffled_pool(self) -> None:
        """Test shuffled pool distribution sampling."""
        from solar_challenge.web.fleet_config import sample_distribution

        samples = sample_distribution(
            "shuffled_pool",
            {"entries": [{"value": 3.0, "count": 30}, {"value": 5.0, "count": 70}]},
        )
        assert len(samples) == 100
        assert all(s in (3.0, 5.0) for s in samples)

    def test_sample_distribution_unknown_type_raises(self) -> None:
        """Test that unknown distribution type raises ValueError."""
        from solar_challenge.web.fleet_config import sample_distribution

        with pytest.raises(ValueError, match="Unknown distribution type"):
            sample_distribution("bogus", {})

    def test_form_to_fleet_distribution_config(self) -> None:
        """Test converting form data to fleet distribution config."""
        from solar_challenge.web.fleet_config import form_to_fleet_distribution_config

        form_data = {
            "n_homes": 50,
            "pv": {
                "capacity_kw": {
                    "type": "normal",
                    "mean": 4.0,
                    "std": 1.0,
                    "min": 2.0,
                    "max": 8.0,
                }
            },
            "load": {
                "annual_consumption_kwh": {
                    "type": "uniform",
                    "min": 2000,
                    "max": 5000,
                }
            },
        }
        config = form_to_fleet_distribution_config(form_data)
        assert config["n_homes"] == 50
        assert "pv" in config
        assert "load" in config

    def test_fleet_distribution_to_yaml(self) -> None:
        """Test converting fleet config to YAML string."""
        from solar_challenge.web.fleet_config import fleet_distribution_to_yaml

        config = {
            "n_homes": 100,
            "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
            "load": {"annual_consumption_kwh": {"type": "uniform", "min": 2000, "max": 5000}},
        }
        yaml_str = fleet_distribution_to_yaml(config)
        assert "n_homes: 100" in yaml_str
        assert isinstance(yaml_str, str)

    def test_yaml_to_fleet_distribution(self) -> None:
        """Test parsing YAML string to fleet distribution config."""
        from solar_challenge.web.fleet_config import yaml_to_fleet_distribution

        yaml_str = """
fleet_distribution:
  n_homes: 100
  pv:
    capacity_kw:
      type: normal
      mean: 4.0
      std: 1.0
  load:
    annual_consumption_kwh:
      type: uniform
      min: 2000
      max: 5000
"""
        config = yaml_to_fleet_distribution(yaml_str)
        assert config["n_homes"] == 100
        assert "pv" in config
        assert "load" in config

    def test_yaml_to_fleet_distribution_invalid_raises(self) -> None:
        """Test that invalid YAML raises ValueError."""
        from solar_challenge.web.fleet_config import yaml_to_fleet_distribution

        with pytest.raises(ValueError):
            yaml_to_fleet_distribution("not: a: valid: fleet: config")

    def test_yaml_roundtrip(self) -> None:
        """Test that export/import YAML round-trips correctly."""
        from solar_challenge.web.fleet_config import (
            fleet_distribution_to_yaml,
            yaml_to_fleet_distribution,
        )

        original = {
            "n_homes": 50,
            "seed": 42,
            "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
            "load": {"annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800}},
        }
        yaml_str = fleet_distribution_to_yaml(original)
        restored = yaml_to_fleet_distribution(yaml_str)
        assert restored["n_homes"] == 50
        assert restored["pv"]["capacity_kw"]["type"] == "uniform"
        assert restored["load"]["annual_consumption_kwh"]["type"] == "normal"


class TestFleetApiEndpoints:
    """Tests for fleet-related API endpoints."""

    def test_preview_distribution_normal(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/preview-distribution with normal distribution."""
        response = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "normal",
                "params": {"mean": 4.0, "std": 1.0, "min": 1.0, "max": 8.0},
                "n_samples": 50,
            },
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "samples" in data
        assert len(data["samples"]) == 50

    def test_preview_distribution_invalid_type(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/preview-distribution with invalid type returns 400."""
        response = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "invalid_type", "params": {}},
        )
        assert response.status_code == 400

    def test_simulate_fleet_from_distribution(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/fleet-from-distribution accepts valid config."""
        response = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                "n_homes": 10,
                "pv": {
                    "capacity_kw": {
                        "type": "normal",
                        "mean": 4.0,
                        "std": 1.0,
                        "min": 2.0,
                        "max": 8.0,
                    }
                },
                "load": {
                    "annual_consumption_kwh": {
                        "type": "uniform",
                        "min": 2000,
                        "max": 5000,
                    }
                },
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert data["n_homes"] == 10

    def test_simulate_fleet_from_distribution_empty_body(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/fleet-from-distribution with empty body returns 400."""
        response = client.post(
            "/api/simulate/fleet-from-distribution",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_export_fleet_yaml(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/export-yaml returns YAML content."""
        response = client.post(
            "/api/fleet/export-yaml",
            json={
                "n_homes": 100,
                "pv": {"capacity_kw": {"type": "uniform", "min": 3, "max": 6}},
            },
        )
        assert response.status_code == 200
        assert "text/yaml" in response.content_type
        assert b"n_homes" in response.data

    def test_import_fleet_yaml(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/import-yaml parses YAML correctly."""
        yaml_content = """
fleet_distribution:
  n_homes: 50
  pv:
    capacity_kw:
      type: normal
      mean: 4.0
      std: 1.0
"""
        response = client.post(
            "/api/fleet/import-yaml",
            data=yaml_content,
            content_type="text/yaml",
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["n_homes"] == 50

    def test_import_fleet_yaml_invalid(self, client: FlaskClient) -> None:
        """Test POST /api/fleet/import-yaml with invalid YAML returns 400."""
        response = client.post(
            "/api/fleet/import-yaml",
            data="just: some: random: yaml",
            content_type="text/yaml",
        )
        assert response.status_code == 400
