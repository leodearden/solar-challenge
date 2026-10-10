"""Tests for the scenario builder and parameter sweep web features."""

import json
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
from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS
from tests._html_page import element_attributes, element_count, texts, texts_after
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application."""
    return build_test_app(tmp_path)


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

    def test_sweep_page_days_input_allows_the_days_the_server_accepts(self, client: FlaskClient) -> None:
        """The base Days input, whose value the page sends as base_config.days, allows 1 to MAX_WINDOW_DAYS: the days parse_date_range accepts."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        days_inputs = [
            attributes
            for attributes in element_attributes(page, "input")
            if attributes.get("x-model") == "baseConfig.days"
        ]
        assert [(attributes.get("min"), attributes.get("max")) for attributes in days_inputs] == [
            ("1", str(MAX_WINDOW_DAYS))
        ]


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

    def test_save_under_a_name_a_saved_home_preset_holds_returns_409_and_changes_nothing(
        self, client: FlaskClient
    ) -> None:
        """Saved presets share one namespace: a scenario save under a home preset's name is a 409 naming that preset, which keeps its config."""
        assert client.post("/api/presets", json={"name": "Taken", "pv_kw": 3.0}).status_code == 201

        response = client.post("/api/scenarios/save", json={"name": "Taken", "config": {"n_homes": 9}})

        assert response.status_code == 409
        assert response.get_json() == {"error": "A saved home preset is already named 'Taken'"}
        home_preset = client.get("/api/presets/Taken").get_json()
        assert (home_preset["source"], home_preset["pv_kw"]) == ("saved", 3.0)
        assert "Taken" not in [p["name"] for p in client.get("/api/scenarios/presets").get_json()["presets"]]

    def test_saving_a_scenario_again_replaces_its_config_and_keeps_its_id(self, client: FlaskClient) -> None:
        """A second save under a saved scenario's name updates that preset in place."""
        first = client.post("/api/scenarios/save", json={"name": "again", "config": {"n_homes": 9}})
        second = client.post("/api/scenarios/save", json={"name": "again", "config": {"n_homes": 12}})
        assert (first.status_code, second.status_code) == (201, 201)
        assert second.get_json()["id"] == first.get_json()["id"]
        assert client.get("/api/scenarios/presets/again").get_json()["config"] == {"n_homes": 12}

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

    def test_a_builtin_scenario_file_is_listed_and_served_by_its_name(self, client: FlaskClient) -> None:
        """GET /api/scenarios/presets lists scenarios/bristol-phase1.yaml as the builtin preset bristol-phase1, and GET /api/scenarios/presets/bristol-phase1 answers that file's scenario."""
        listed = client.get("/api/scenarios/presets").get_json()["presets"]
        preset = client.get("/api/scenarios/presets/bristol-phase1")

        assert {"name": "bristol-phase1", "source": "builtin", "filename": "bristol-phase1.yaml"} in listed
        assert preset.status_code == 200
        answer = preset.get_json()
        assert (answer["name"], answer["source"], answer["config"]["name"]) == (
            "bristol-phase1",
            "builtin",
            "Bristol Phase 1",
        )


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
