"""Tests for the scenario builder and parameter sweep web features."""

import json
from collections.abc import Callable
from inspect import signature
from pathlib import Path
from typing import Any

import pytest
import yaml
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.config import (
    NormalDistribution,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    load_fleet_config,
    parse_fleet_distribution_config,
    parse_location_block,
    parse_seg_rate,
)
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.shared import LOCATION_PRESETS
from tests._html_page import element_count, texts, texts_after
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
    return build_test_app(tmp_path)


class _RecordingJobManager:
    """Stands in for the app's JobManager: records each home config a request submits and simulates nothing."""

    def __init__(self) -> None:
        self.submitted_homes: list[object] = []

    def submit_home_job(
        self,
        config: object,
        start_date: object,
        end_date: object,
        db_path: str,
        data_dir: str,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Record the home config and return a fresh (job_id, run_id) pair."""
        self.submitted_homes.append(config)
        n = len(self.submitted_homes)
        return f"job-{n}", f"run-{n}"


@pytest.fixture
def recording_job_manager(app: Flask) -> _RecordingJobManager:
    """Install a recording double as the app's job manager and return it."""
    job_manager = _RecordingJobManager()
    app.extensions["job_manager"] = job_manager
    return job_manager


@pytest.fixture
def client(app: Flask, recording_job_manager: _RecordingJobManager) -> FlaskClient:
    """Create a Flask test client whose requests submit jobs to the recording double, so none starts a real simulation."""
    return app.test_client()


def _call_shape(method: Callable[..., object]) -> list[tuple[str, object, object]]:
    """The parameter names, kinds and defaults that decide which calls a method accepts."""
    return [(p.name, p.kind, p.default) for p in signature(method).parameters.values()]


class TestRecordingJobManager:
    """The recording double stays in step with the real JobManager it stands in for."""

    def test_submit_home_job_takes_the_parameters_the_real_one_takes(self, app: Flask) -> None:
        """A change to the real submit_home_job's parameters fails here, instead of passing silently behind the double."""
        real_job_manager = app.extensions["job_manager"]
        double = _RecordingJobManager()

        assert _call_shape(double.submit_home_job) == _call_shape(real_job_manager.submit_home_job)


class TestScenarioBuilderRoute:
    """Tests for the GET /scenarios/builder route."""

    def test_builder_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /scenarios/builder returns HTTP 200."""
        response = client.get("/scenarios/builder")
        assert response.status_code == 200

    def test_builder_contains_form_and_preview(self, client: FlaskClient) -> None:
        """GET /scenarios/builder has its YAML Preview pane: the heading, once, and one element bound to yamlPreview."""
        response = client.get("/scenarios/builder")
        page = response.get_data(as_text=True)
        assert texts(page).count("YAML Preview") == 1
        assert element_count(page, "pre", {"x-text": "yamlPreview"}) == 1

    def test_builder_contains_scenario_name_input(self, client: FlaskClient) -> None:
        """GET /scenarios/builder has exactly one input bound to the scenario's name."""
        response = client.get("/scenarios/builder")
        page = response.get_data(as_text=True)
        assert element_count(page, "input", {"x-model": "name"}) == 1

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
        """GET /scenarios/sweep has exactly one select bound to the swept parameter."""
        response = client.get("/scenarios/sweep")
        page = response.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "parameter"}) == 1

    def test_sweep_page_contains_mode_options(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep offers the Linear and Geometric modes, in that order, after the Sweep Mode label."""
        response = client.get("/scenarios/sweep")
        page = response.get_data(as_text=True)
        assert texts_after(page, "Sweep Mode", 2) == ["Linear", "Geometric"]

    def test_sweep_page_contains_preview_section(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep has the Sweep Point Preview heading, once."""
        response = client.get("/scenarios/sweep")
        page = response.get_data(as_text=True)
        assert texts(page).count("Sweep Point Preview") == 1


class TestOldScenarioApiPaths:
    """The /scenarios/api/* paths no longer resolve: the scenario builder's JSON endpoints answer only under /api/scenarios/."""

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            pytest.param("POST", "/scenarios/api/preview-yaml", id="preview-yaml"),
            pytest.param("POST", "/scenarios/api/validate", id="validate"),
            pytest.param("POST", "/scenarios/api/save", id="save"),
            pytest.param("GET", "/scenarios/api/presets", id="presets"),
            pytest.param("GET", "/scenarios/api/presets/bristol-phase1", id="preset by name"),
        ],
    )
    def test_answers_404_instead_of_redirecting(self, client: FlaskClient, method: str, path: str) -> None:
        """Each old path, requested with the method its redirect took, answers 404 rather than redirecting to /api/scenarios/*."""
        assert client.open(path, method=method).status_code == 404


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
        """A named, complete builder form validates with no errors."""
        response = client.post(
            "/api/scenarios/validate",
            json=TestBuilderScenarioYaml._DEFAULT_FORM,
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is True
        assert data["errors"] == []

    @pytest.mark.parametrize(
        ("without", "changes", "error_text"),
        [
            pytest.param(
                ("pv_capacity_kw",),
                {"pv_distribution_type": "uniform", "pv_min": 8, "pv_max": 2},
                "min cannot be greater than max",
                id="PV uniform min above max",
            ),
            pytest.param(
                ("battery_capacity_kwh",),
                {
                    "battery_distribution_type": "weighted_discrete",
                    "battery_wd_values": [{"value": 0, "weight": 0}, {"value": 5, "weight": 0}],
                },
                "weights cannot all be zero",
                id="battery weights all zero",
            ),
            pytest.param((), {"seg_rate_pence_per_kwh": -1}, "seg", id="negative SEG rate"),
            pytest.param((), {"import_rate": -0.1}, "negative", id="negative import rate"),
            pytest.param((), {"end_date": ""}, "end_date", id="cleared end date"),
            pytest.param(
                (),
                {"location_preset": "custom", "latitude": 95, "longitude": -2.2, "altitude": 38.0},
                "Latitude must be between -90 and 90",
                id="custom latitude out of range",
            ),
            pytest.param((), {"export_rate": 0.15}, "export_rate", id="unread export_rate"),
        ],
    )
    def test_validate_reports_what_the_scenario_readers_reject(
        self,
        client: FlaskClient,
        without: tuple[str, ...],
        changes: dict[str, Any],
        error_text: str,
    ) -> None:
        """The default builder form, *without* those fields and with *changes*, is invalid for the reason a scenario reader gives."""
        form = {
            key: value
            for key, value in TestBuilderScenarioYaml._DEFAULT_FORM.items()
            if key not in without
        }
        form.update(changes)

        response = client.post("/api/scenarios/validate", json=form)

        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False
        assert any(error_text in error for error in data["errors"]), data["errors"]

    def test_validate_reports_a_shuffled_pool_too_small_for_the_fleet(
        self, client: FlaskClient
    ) -> None:
        """A PV pool of 90 values for 100 homes is the one fault in a form that validates with a pool of 100.

        The builder's default PV pool used to hold those 90 values.  The fault's message is
        not asserted: load_fleet_config raises a bare IndexError for it today.
        """

        def validation_with_pv_pool(counts: tuple[int, int, int]) -> Any:
            form = {
                key: value
                for key, value in TestBuilderScenarioYaml._DEFAULT_FORM.items()
                if key != "pv_capacity_kw"
            }
            form["pv_distribution_type"] = "shuffled_pool"
            form["pv_sp_entries"] = [
                {"value": value, "count": count}
                for value, count in zip((3.0, 4.0, 5.0), counts)
            ]
            response = client.post("/api/scenarios/validate", json=form)
            assert response.status_code == 200
            return response.get_json()

        assert validation_with_pv_pool((20, 40, 40)) == {"valid": True, "errors": []}
        short_pool = validation_with_pv_pool((20, 40, 30))
        assert short_pool["valid"] is False
        assert len(short_pool["errors"]) == 1, short_pool["errors"]

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

    def test_validate_refuses_only_a_fleet_above_the_dashboard_fleet_limit(
        self, client: FlaskClient
    ) -> None:
        """The builder accepts a fleet of exactly the dashboard's fleet limit, and refuses one home more, naming the limit."""
        from solar_challenge.web.fleet_config import MAX_FLEET_HOMES

        at_limit = client.post(
            "/api/scenarios/validate",
            json={**TestBuilderScenarioYaml._DEFAULT_FORM, "n_homes": MAX_FLEET_HOMES},
        )
        above_limit = client.post(
            "/api/scenarios/validate",
            json={**TestBuilderScenarioYaml._DEFAULT_FORM, "n_homes": MAX_FLEET_HOMES + 1},
        )

        assert at_limit.get_json() == {"valid": True, "errors": []}
        assert above_limit.get_json() == {
            "valid": False,
            "errors": [f"Number of homes must be between 1 and {MAX_FLEET_HOMES:,}."],
        }

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


def _preview_document(client: FlaskClient, form: dict[str, Any]) -> tuple[str, Any]:
    """The YAML text /api/scenarios/preview-yaml answers for the builder *form*, and the document it holds."""
    response = client.post("/api/scenarios/preview-yaml", json=form)
    assert response.status_code == 200, response.get_json()
    yaml_text: str = response.get_json()["yaml"]
    return yaml_text, yaml.safe_load(yaml_text)


class TestBuilderScenarioYaml:
    """The YAML /api/scenarios/preview-yaml writes for a builder form is a fleet scenario its loaders read."""

    _DEFAULT_FORM: dict[str, Any] = {
        "name": "Builder defaults",
        "description": "",
        "start_date": "2024-01-01",
        "end_date": "2024-12-31",
        "location_preset": "bristol",
        "n_homes": 100,
        "import_rate": 0.245,
        "seg_rate_pence_per_kwh": 15.0,
        "pv_capacity_kw": 4,
        "battery_capacity_kwh": 5,
        "annual_consumption_kwh": 3500,
    }
    """The form scenario-builder.js's getFormData() sends on page load, given a name.

    tests/e2e/test_scenario_builder.py::test_default_form_previews_yaml_the_fleet_loader_loads
    pins the real payload this mirrors.
    """

    def test_default_form_yaml_loads_through_load_fleet_config(
        self, client: FlaskClient, tmp_path: Path
    ) -> None:
        """load_fleet_config builds every home of the form; the period and SEG rate are there for their own readers."""
        yaml_text, document = _preview_document(client, self._DEFAULT_FORM)
        path = tmp_path / "builder.yaml"
        path.write_text(yaml_text, encoding="utf-8")

        fleet = load_fleet_config(path)

        assert len(fleet.homes) == 100
        assert {
            (
                home.pv_config.capacity_kw,
                home.battery_config.capacity_kwh if home.battery_config is not None else None,
                home.load_config.annual_consumption_kwh,
                home.tariff_config,
                home.location,
            )
            for home in fleet.homes
        } == {(4.0, 5.0, 3500.0, TariffConfig.flat_rate(0.245), LOCATION_PRESETS["bristol"])}
        assert document["period"] == {"start_date": "2024-01-01", "end_date": "2024-12-31"}
        assert parse_seg_rate(document["seg"]) == 15.0

    @pytest.mark.parametrize(
        ("distribution_fields", "expected"),
        [
            pytest.param(
                {"distribution_type": "normal", "mean": 5, "std": 2, "min": 0, "max": 13.5},
                NormalDistribution(5.0, 2.0, min=0.0, max=13.5),
                id="normal",
            ),
            pytest.param(
                {"distribution_type": "uniform", "mean": 5, "std": 2, "min": 2, "max": 8},
                UniformDistribution(2.0, 8.0),
                id="uniform",
            ),
            pytest.param(
                {
                    "distribution_type": "weighted_discrete",
                    "wd_values": [{"value": 3, "weight": 20}, {"value": 4, "weight": 40}],
                },
                WeightedDiscreteDistribution((3.0, 4.0), (20.0, 40.0)),
                id="weighted_discrete",
            ),
            pytest.param(
                {
                    "distribution_type": "shuffled_pool",
                    "sp_entries": [{"value": 3, "count": 50}, {"value": 4, "count": 50}],
                },
                ShuffledPoolDistribution((3.0, 4.0), (50, 50)),
                id="shuffled_pool",
            ),
        ],
    )
    @pytest.mark.parametrize(
        ("component", "fixed_field", "grammar_key"),
        [
            pytest.param("pv", "pv_capacity_kw", "capacity_kw", id="pv"),
            pytest.param("battery", "battery_capacity_kwh", "capacity_kwh", id="battery"),
            pytest.param(
                "load", "annual_consumption_kwh", "annual_consumption_kwh", id="load"
            ),
        ],
    )
    def test_each_distribution_the_form_offers_reaches_the_loader(
        self,
        client: FlaskClient,
        component: str,
        fixed_field: str,
        grammar_key: str,
        distribution_fields: dict[str, Any],
        expected: object,
    ) -> None:
        """A component sent as a distribution, in the keys getFormData() sends, is read back as that distribution.

        The form keys are the component's prefix on each of *distribution_fields*,
        and the component's fixed field is not sent.
        """
        form = {key: value for key, value in self._DEFAULT_FORM.items() if key != fixed_field}
        form.update(
            {f"{component}_{suffix}": value for suffix, value in distribution_fields.items()}
        )

        _, document = _preview_document(client, form)

        fleet_distribution = parse_fleet_distribution_config(document["fleet_distribution"])
        assert getattr(getattr(fleet_distribution, component), grammar_key) == expected

    @pytest.mark.parametrize(
        ("rate_field", "block"),
        [
            pytest.param("import_rate", "tariff", id="import rate"),
            pytest.param("seg_rate_pence_per_kwh", "seg", id="SEG rate"),
        ],
    )
    def test_a_cleared_rate_writes_its_block_as_null_and_the_form_validates(
        self, client: FlaskClient, rate_field: str, block: str
    ) -> None:
        """Clearing the import or SEG rate means a scenario with no tariff or no SEG, which the readers accept.

        The block is written as null, the readers' spelling of none, not as an empty block they refuse.
        """
        form = {**self._DEFAULT_FORM, rate_field: ""}

        _, document = _preview_document(client, form)
        validation = client.post("/api/scenarios/validate", json=form).get_json()

        assert document[block] is None
        assert validation == {"valid": True, "errors": []}

    @pytest.mark.parametrize(
        "omitted",
        [
            pytest.param(("latitude",), id="without latitude"),
            pytest.param(("longitude",), id="without longitude"),
            pytest.param(("altitude",), id="without altitude"),
            pytest.param(("latitude", "longitude", "altitude"), id="without any coordinate"),
        ],
    )
    def test_each_custom_coordinate_the_form_omits_is_left_to_the_loader(
        self, client: FlaskClient, tmp_path: Path, omitted: tuple[str, ...]
    ) -> None:
        """A custom coordinate the form omits is left to the loader, the one home of its default.

        The form sends each *omitted* coordinate as '', the cleared input scenarioFormFields
        leaves for an uploaded location: block without that key.  The block holds the
        coordinates given, the homes are where load_fleet_config puts a hand-written block
        with the same keys, and the form validates.
        """
        coordinates = {"latitude": 53.4, "longitude": -2.2, "altitude": 38.0}
        given = {key: value for key, value in coordinates.items() if key not in omitted}
        cleared = dict.fromkeys(omitted, "")
        form = {**self._DEFAULT_FORM, "location_preset": "custom", **given, **cleared}

        yaml_text, document = _preview_document(client, form)
        path = tmp_path / "builder.yaml"
        path.write_text(yaml_text, encoding="utf-8")
        validation = client.post("/api/scenarios/validate", json=form).get_json()

        assert document["location"] == given
        assert {home.location for home in load_fleet_config(path).homes} == {
            parse_location_block(given)
        }
        assert validation == {"valid": True, "errors": []}

    def test_a_form_key_the_builder_does_not_read_is_refused(self, client: FlaskClient) -> None:
        """A key the builder does not read gets 400 naming it, instead of being dropped from the YAML."""
        response = client.post(
            "/api/scenarios/preview-yaml", json={**self._DEFAULT_FORM, "export_rate": 0.15}
        )

        assert response.status_code == 400
        assert "export_rate" in response.get_json()["error"]

    def test_a_custom_coordinate_that_is_not_a_number_is_refused(
        self, client: FlaskClient
    ) -> None:
        """A custom coordinate that does not read as a number gets 400 naming it."""
        response = client.post(
            "/api/scenarios/preview-yaml",
            json={
                **self._DEFAULT_FORM,
                "location_preset": "custom",
                "latitude": "north",
                "longitude": -2.2,
                "altitude": 38.0,
            },
        )

        assert response.status_code == 400
        assert "latitude" in response.get_json()["error"]


class TestSweepAPI:
    """Tests for the POST /api/simulate/sweep endpoint."""

    def test_sweep_endpoint_returns_201(self, client: FlaskClient) -> None:
        """POST /api/simulate/sweep returns 201 with the values, the parameter and each point's job id, in point order."""
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
        assert data["job_ids"] == ["job-1", "job-2", "job-3", "job-4"]

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


class TestSweepParameters:
    """What POST /api/simulate/sweep submits for a swept parameter: one home per point, carrying that point's value, or nothing at all when the parameter is unsupported or any of its points is invalid."""

    @pytest.mark.parametrize(
        ("parameter", "values", "swept_value_of"),
        [
            pytest.param(
                "pv_capacity_kw",
                [2.0, 5.0, 8.0],
                lambda home: home.pv_config.capacity_kw,
                id="pv",
            ),
            pytest.param(
                "battery_capacity_kwh",
                [5.0, 10.0, 15.0],
                lambda home: home.battery_config.capacity_kwh,
                id="battery",
            ),
            pytest.param(
                "annual_consumption_kwh",
                [2000.0, 3500.0, 5000.0],
                lambda home: home.load_config.annual_consumption_kwh,
                id="consumption",
            ),
        ],
    )
    def test_each_point_simulates_a_home_carrying_that_points_value(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        parameter: str,
        values: list[float],
        swept_value_of: Callable[[object], float],
    ) -> None:
        """Each sweep point submits one home whose swept field holds that point's value."""
        response = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": parameter,
                "min": values[0],
                "max": values[-1],
                "steps": len(values),
                "mode": "linear",
            },
        )

        assert response.status_code == 201
        assert response.get_json()["values"] == values
        assert [swept_value_of(home) for home in recording_job_manager.submitted_homes] == values

    @pytest.mark.parametrize("parameter", ["n_homes", "tilt", "no_such_parameter"])
    def test_unsupported_parameter_is_refused_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        parameter: str,
    ) -> None:
        """A parameter outside the supported set, even a real home-config key, gets 400 and submits nothing.

        The error names the refused parameter and every supported one.
        """
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": parameter, "min": 10.0, "max": 40.0, "steps": 3},
        )

        assert response.status_code == 400
        error = response.get_json()["error"]
        assert parameter in error
        for supported in ("pv_capacity_kw", "battery_capacity_kwh", "annual_consumption_kwh"):
            assert supported in error
        assert recording_job_manager.submitted_homes == []

    def test_a_later_invalid_point_refuses_the_sweep_before_any_point_is_submitted(
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
    ) -> None:
        """A sweep whose last point exceeds the PV capacity a home accepts gets 400 naming that point, and submits none of its points.

        Its earlier points are valid, so a sweep that submitted each point as it validated it would already have started their jobs.
        """
        response = client.post(
            "/api/simulate/sweep",
            json={"parameter": "pv_capacity_kw", "min": 5.0, "max": 25.0, "steps": 3},
        )

        assert response.status_code == 400
        assert "pv_capacity_kw=25.0" in response.get_json()["error"]
        assert recording_job_manager.submitted_homes == []


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
