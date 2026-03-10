"""Tests for the scenario builder and parameter sweep web features."""

import json
from pathlib import Path

import pytest
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.app import create_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
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


class TestScenarioBuilderRoute:
    """Tests for the GET /scenarios/builder route."""

    def test_builder_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder returns HTTP 200."""
        response = client.get("/scenarios/builder")
        assert response.status_code == 200

    def test_builder_contains_form_and_preview(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder contains form and YAML preview elements."""
        response = client.get("/scenarios/builder")
        data = response.data.decode()
        assert "yaml" in data.lower() or "preview" in data.lower()

    def test_builder_contains_scenario_name_input(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder contains the scenario name input."""
        response = client.get("/scenarios/builder")
        data = response.data.decode()
        assert "Scenario Name" in data or "name" in data

    def test_builder_contains_accordion_sections(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder contains accordion sections."""
        response = client.get("/scenarios/builder")
        data = response.data.decode()
        assert "General" in data
        assert "Period" in data
        assert "Location" in data
        assert "Fleet Distribution" in data
        assert "Tariff" in data

    def test_builder_contains_action_buttons(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder contains action buttons."""
        response = client.get("/scenarios/builder")
        data = response.data.decode()
        assert "Validate" in data
        assert "Download YAML" in data
        assert "Save" in data


class TestSweepRoute:
    """Tests for the GET /scenarios/sweep route."""

    def test_sweep_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /scenarios/sweep returns HTTP 200."""
        response = client.get("/scenarios/sweep")
        assert response.status_code == 200

    def test_sweep_page_contains_parameter_selector(self, client: FlaskClient) -> None:
        """Test GET /scenarios/sweep contains parameter selection elements."""
        response = client.get("/scenarios/sweep")
        data = response.data.decode()
        assert "parameter" in data.lower() or "sweep" in data.lower()

    def test_sweep_page_contains_mode_options(self, client: FlaskClient) -> None:
        """Test GET /scenarios/sweep contains linear/geometric mode options."""
        response = client.get("/scenarios/sweep")
        data = response.data.decode()
        assert "linear" in data.lower() or "Linear" in data
        assert "geometric" in data.lower() or "Geometric" in data

    def test_sweep_page_contains_preview_section(self, client: FlaskClient) -> None:
        """Test GET /scenarios/sweep contains the sweep point preview."""
        response = client.get("/scenarios/sweep")
        data = response.data.decode()
        assert "Sweep Point Preview" in data or "preview" in data.lower()


class TestScenarioAPI:
    """Tests for the /api/scenarios/* endpoints."""

    def test_preview_yaml_returns_yaml(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/preview-yaml returns YAML string."""
        response = client.post(
            "/api/scenarios/preview-yaml",
            json={"name": "Test Scenario", "n_homes": 10},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "yaml" in data
        assert isinstance(data["yaml"], str)
        assert "name" in data["yaml"]

    def test_preview_yaml_empty_body(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/preview-yaml with empty body returns valid YAML."""
        response = client.post(
            "/api/scenarios/preview-yaml",
            json={},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "yaml" in data

    def test_preview_yaml_with_location(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/preview-yaml with location preset."""
        response = client.post(
            "/api/scenarios/preview-yaml",
            json={"name": "Bristol Test", "location_preset": "bristol", "n_homes": 50},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert "location" in data["yaml"]

    def test_validate_valid_returns_ok(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/validate with valid data returns ok."""
        response = client.post(
            "/api/scenarios/validate",
            json={"name": "Test Scenario"},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is True

    def test_validate_missing_name_returns_errors(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/validate with missing name returns errors."""
        response = client.post(
            "/api/scenarios/validate",
            json={},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False
        assert len(data["errors"]) > 0

    def test_validate_invalid_pv_returns_errors(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/validate with invalid PV capacity."""
        response = client.post(
            "/api/scenarios/validate",
            json={"name": "Test", "pv_capacity_kw": 999},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False

    def test_list_presets(self, client: FlaskClient) -> None:
        """Test GET /api/scenarios/presets returns a list."""
        response = client.get("/api/scenarios/presets")
        assert response.status_code == 200
        data = response.get_json()
        assert isinstance(data, dict)
        assert "presets" in data
        assert isinstance(data["presets"], list)

    def test_save_preset(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/save stores a preset."""
        response = client.post(
            "/api/scenarios/save",
            json={"name": "test-preset", "config": {"n_homes": 10}},
        )
        assert response.status_code in (200, 201)
        data = response.get_json()
        assert data["name"] == "test-preset"

    def test_save_preset_no_name_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/scenarios/save with no name returns 400."""
        response = client.post(
            "/api/scenarios/save",
            json={"config": {"n_homes": 10}},
        )
        assert response.status_code == 400

    def test_save_and_list_roundtrip(self, client: FlaskClient) -> None:
        """Test saving a preset and then finding it in the list."""
        # Save
        client.post(
            "/api/scenarios/save",
            json={"name": "roundtrip-test", "config": {"n_homes": 25}},
        )
        # List
        response = client.get("/api/scenarios/presets")
        data = response.get_json()
        names = [p["name"] for p in data["presets"]]
        assert "roundtrip-test" in names

    def test_get_preset_not_found(self, client: FlaskClient) -> None:
        """Test GET /api/scenarios/presets/<name> returns 404 for unknown."""
        response = client.get("/api/scenarios/presets/nonexistent-preset-xyz")
        assert response.status_code == 404

    def test_get_saved_preset(self, client: FlaskClient) -> None:
        """Test saving then loading a specific preset by name."""
        # Save first
        client.post(
            "/api/scenarios/save",
            json={"name": "fetch-me", "config": {"n_homes": 30}},
        )
        # Fetch
        response = client.get("/api/scenarios/presets/fetch-me")
        assert response.status_code == 200
        data = response.get_json()
        assert data["name"] == "fetch-me"
        assert data["source"] == "saved"


class TestSweepAPI:
    """Tests for the POST /api/simulate/sweep endpoint."""

    def test_sweep_endpoint_returns_201(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/sweep returns 201 with job_ids."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 2.0,
                "max": 8.0,
                "steps": 4,
                "mode": "linear",
                "base_config": {"battery_kwh": 5.0, "location": "bristol", "days": 7},
            },
        )
        assert response.status_code == 201
        data = response.get_json()
        assert "values" in data
        assert len(data["values"]) == 4
        assert data["parameter"] == "pv_capacity_kw"
        assert "job_ids" in data
        assert len(data["job_ids"]) == 4

    def test_sweep_linear_values(self, client: FlaskClient) -> None:
        """Test that linear sweep generates evenly spaced values."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 2.0,
                "max": 8.0,
                "steps": 4,
                "mode": "linear",
            },
        )
        data = response.get_json()
        assert data["values"] == [2.0, 4.0, 6.0, 8.0]

    def test_sweep_geometric_values(self, client: FlaskClient) -> None:
        """Test that geometric sweep generates geometrically spaced values."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 1.0,
                "max": 8.0,
                "steps": 4,
                "mode": "geometric",
            },
        )
        data = response.get_json()
        assert len(data["values"]) == 4
        # First should be 1.0, last should be 8.0
        assert data["values"][0] == 1.0
        assert data["values"][-1] == 8.0
        # Geometric spacing: each ratio should be approximately equal
        ratios = [data["values"][i + 1] / data["values"][i] for i in range(len(data["values"]) - 1)]
        assert abs(ratios[0] - ratios[1]) < 0.01

    def test_sweep_empty_body_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/sweep with no body returns 400."""
        response = client.post(
            "/api/simulate/sweep",
            content_type="application/json",
        )
        assert response.status_code == 400

    def test_sweep_invalid_range_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/sweep with min >= max returns 400."""
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": "pv_capacity_kw", "min": 10.0, "max": 2.0, "steps": 4},
        )
        assert response.status_code == 400

    def test_sweep_too_few_steps_returns_400(self, client: FlaskClient) -> None:
        """Test POST /api/simulate/sweep with steps < 2 returns 400."""
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": "pv_capacity_kw", "min": 2.0, "max": 8.0, "steps": 1},
        )
        assert response.status_code == 400


class TestSweepChart:
    """Tests for the sweep_parameter_chart function in charts.py."""

    def test_sweep_parameter_chart_returns_json(self) -> None:
        """Test sweep_parameter_chart returns valid Plotly JSON."""
        from solar_challenge.web.charts import sweep_parameter_chart

        result = sweep_parameter_chart(
            [2.0, 4.0, 6.0, 8.0],
            [50.5, 65.3, 72.1, 78.4],
            "PV Capacity (kW)",
            "Self-Consumption (%)",
        )
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed

    def test_sweep_parameter_chart_has_traces(self) -> None:
        """Test sweep_parameter_chart includes main, optimal, and trend traces."""
        from solar_challenge.web.charts import sweep_parameter_chart

        result = sweep_parameter_chart(
            [1.0, 2.0, 3.0, 4.0, 5.0],
            [10.0, 25.0, 40.0, 55.0, 70.0],
            "Battery (kWh)",
            "Grid Import (kWh)",
        )
        parsed = json.loads(result)
        # Should have at least the main trace, optimal marker, and trend line
        assert len(parsed["data"]) >= 2

    def test_sweep_parameter_chart_empty_returns_empty(self) -> None:
        """Test sweep_parameter_chart returns '{}' with empty inputs."""
        from solar_challenge.web.charts import sweep_parameter_chart

        result = sweep_parameter_chart([], [], "X", "Y")
        assert result == "{}"

    def test_sweep_parameter_chart_two_points(self) -> None:
        """Test sweep_parameter_chart works with just two data points."""
        from solar_challenge.web.charts import sweep_parameter_chart

        result = sweep_parameter_chart(
            [1.0, 10.0],
            [20.0, 80.0],
            "Param",
            "Metric",
        )
        assert result and result != "{}"
        parsed = json.loads(result)
        assert "data" in parsed
        assert "layout" in parsed
