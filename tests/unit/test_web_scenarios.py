"""Tests for the scenario builder and parameter sweep web features."""

import json
import math
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge import web
from solar_challenge.config import load_fleet_config
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    NormalDistribution,
    ShuffledPoolDistribution,
    UniformDistribution,
    WeightedDiscreteDistribution,
    parse_fleet_distribution_config,
)
from solar_challenge.location import LOCATION_PRESETS
from solar_challenge.scenario_blocks import (
    parse_location_block,
    parse_seg_rate,
)
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.charts import ChartPanel, SweepMetric, SweepPoint, sweep_panels, sweep_parameter_chart
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    MAX_DAYS,
    MAX_FLEET_HOMES,
    ComponentLimits,
    page_limits,
)
from solar_challenge.web.storage import RunStorage
from solar_challenge.web.sweep_request import SWEEP_MAX_STEPS
from tests._chart_absences import sweep_reason
from tests._error_records import error_records
from tests._finance_builders import make_fleet_results, make_home_config, make_sim_results
from tests._fleet_form import fleet_reader_refusal
from tests._html_labels import labelled_inputs
from tests._html_page import chart_figures, counts_of, element_attributes, element_count, headings, texts, texts_after
from tests._html_select_options import option_texts
from tests._plotly_figure import traces_by_name
from tests._run_summaries import home_summary
from tests._web_runs import store_fleet_run, store_home_run


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

    def test_the_builder_page_hands_its_script_only_the_section_it_opens_at(self, client: FlaskClient) -> None:
        """scenarioBuilder takes no components: static/js/scenario-builder.js reads each component's start from #page-limits, as the fleet page's script does."""
        page = client.get("/scenarios/builder").get_data(as_text=True)
        scopes = [attributes.get("x-data") or "" for attributes in element_attributes(page, "div")]
        (x_data,) = [scope for scope in scopes if scope.startswith("scenarioBuilder(")]
        try:
            arguments = json.loads("[" + x_data.removeprefix("scenarioBuilder(").removesuffix(")") + "]")
        except json.JSONDecodeError as exc:
            pytest.fail(f"x-data={x_data!r} does not pass scenarioBuilder JSON arguments: {exc}")
        assert [type(argument) for argument in arguments] == [str]

    def test_builder_offers_each_location_preset_labelled_with_its_name(
        self, client: FlaskClient
    ) -> None:
        """GET /scenarios/builder's location select offers each LOCATION_PRESETS key labelled with its Location's name, and a custom location."""
        page = client.get("/scenarios/builder").get_data(as_text=True)

        assert option_texts(page, {"x-model": "location_preset"}) == {
            **{key: preset.name for key, preset in LOCATION_PRESETS.items()},
            "custom": "Custom Location",
        }

    def test_the_builder_offers_a_seed_input_bounded_as_the_dashboard_bounds_a_fleets_seed(
        self, client: FlaskClient
    ) -> None:
        """GET /scenarios/builder labels one number input Seed, stepping by whole numbers between page_limits().seed's low and high."""
        page = client.get("/scenarios/builder").get_data(as_text=True)
        seed = page_limits().seed

        assert [
            {key: attributes.get(key) for key in ("type", "step", "min", "max")}
            for caption, attributes in labelled_inputs(page)
            if caption == "Seed"
        ] == [{"type": "number", "step": "1", "min": str(seed.low), "max": str(seed.high)}]

    def test_the_builder_loads_no_script_from_the_js_yaml_vendor_directory(self, client: FlaskClient) -> None:
        """The builder imports a scenario on the server, so GET /scenarios/builder loads no script under static/vendor/js-yaml."""
        page = client.get("/scenarios/builder").get_data(as_text=True)

        sources = [attributes.get("src") or "" for attributes in element_attributes(page, "script")]

        assert sources, "the builder page loads no script at all, so this check would pass vacuously"
        assert [src for src in sources if "/static/vendor/js-yaml/" in src] == []

    def test_the_web_package_vendors_no_js_yaml(self) -> None:
        """static/vendor/js-yaml is gone from the web package: no page parses YAML in the browser."""
        assert not (Path(web.__file__).parent / "static" / "vendor" / "js-yaml").exists()


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

    def test_sweep_page_offers_each_location_preset_labelled_with_its_name(
        self, client: FlaskClient
    ) -> None:
        """GET /scenarios/sweep's location select offers each LOCATION_PRESETS key, labelled with its Location's name."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)

        assert option_texts(page, {"x-model": "baseConfig.location"}) == {
            key: preset.name for key, preset in LOCATION_PRESETS.items()
        }

    def test_sweep_page_contains_mode_options(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep offers the Linear and Geometric modes, in that order, after the Sweep Mode label."""
        response = client.get("/scenarios/sweep")
        page = response.get_data(as_text=True)
        assert texts_after(page, "Sweep Mode", 2) == ["Linear", "Geometric"]

    def test_sweep_page_heads_each_panel_with_its_title(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep heads each of its panels, the configuration, the point preview and the results, with its title, once."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        titles = ("Sweep Configuration", "Sweep Point Preview", "Sweep Results")
        assert counts_of(headings(page), titles) == dict.fromkeys(titles, 1)

    def test_sweep_point_preview_counts_the_values_the_sweep_will_test(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep has exactly one paragraph bound to the count of values the sweep will test."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        assert element_count(page, "p", {"x-text": "previewValues.length + ' values will be tested'"}) == 1

    def test_sweep_page_shows_no_sweep_id(self, client: FlaskClient) -> None:
        """GET /scenarios/sweep mentions no Sweep ID: a sweep answers none, only its points' job ids."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        assert [text for text in texts(page) if "Sweep ID" in text] == []

    def test_sweep_page_days_input_allows_the_days_the_server_accepts(self, client: FlaskClient) -> None:
        """The base Days input, whose value the page sends as base_config.days, allows 1 to MAX_DAYS: the days parse_date_range accepts."""
        page = client.get("/scenarios/sweep").get_data(as_text=True)
        days_inputs = [
            attributes
            for attributes in element_attributes(page, "input")
            if attributes.get("x-model") == "baseConfig.days"
        ]
        assert [(attributes.get("min"), attributes.get("max")) for attributes in days_inputs] == [
            ("1", str(MAX_DAYS))
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


def _form_with_pv_pool(values: list[float], counts: list[int], **form_changes: Any) -> dict[str, Any]:
    """The default builder form with its PV a shuffled pool of *values*, each given to its count of *counts* homes, in place of its fixed capacity, and with *form_changes* over it."""
    pool = {"type": "shuffled_pool", "values": values, "counts": counts}
    return {**TestBuilderScenarioYaml._DEFAULT_FORM, "pv": {"capacity_kw": pool}, **form_changes}


def _validation_with_pv_pool(client: FlaskClient, values: list[float], counts: list[int], **form_changes: Any) -> Any:
    """POST /api/scenarios/validate's answer to _form_with_pv_pool's form."""
    response = client.post("/api/scenarios/validate", json=_form_with_pv_pool(values, counts, **form_changes))
    assert response.status_code == 200
    return response.get_json()


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
        ("changes", "error_text"),
        [
            pytest.param(
                {"pv": {"capacity_kw": {"type": "uniform", "min": 8, "max": 2}}},
                "min cannot be greater than max",
                id="PV uniform min above max",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "normal", "mean": 4}}},
                "pv.capacity_kw: requires 'std'",
                id="PV normal without its std",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "weighted_discrete", "values": [0, 5], "weights": [0, 0]}}},
                "weights cannot all be zero",
                id="battery weights all zero",
            ),
            pytest.param({"seg_rate_pence_per_kwh": -1}, "seg", id="negative SEG rate"),
            pytest.param({"import_rate": -0.1}, "rate_per_kwh must be at least 0", id="negative import rate"),
            pytest.param({"end_date": ""}, "end_date", id="cleared end date"),
            pytest.param(
                {"location_preset": "custom", "latitude": 95, "longitude": -2.2, "altitude": 38.0},
                "latitude must be between -90 and 90",
                id="custom latitude out of range",
            ),
            pytest.param({"export_rate": 0.15}, "export_rate", id="unread export_rate"),
        ],
    )
    def test_validate_reports_what_the_scenario_readers_reject(
        self,
        client: FlaskClient,
        changes: dict[str, Any],
        error_text: str,
    ) -> None:
        """The default builder form with *changes* is invalid for the reason a scenario reader gives."""
        form = {**TestBuilderScenarioYaml._DEFAULT_FORM, **changes}

        response = client.post("/api/scenarios/validate", json=form)

        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False
        assert any(error_text in error for error in data["errors"]), data["errors"]

    def test_validate_reports_a_drawn_value_outside_its_components_range(
        self, client: FlaskClient
    ) -> None:
        """P15: the default form with its PV a normal around 50 kW, which every home draws above the pv component's range, is invalid, naming pv.capacity_kw and the range."""
        form = {
            **TestBuilderScenarioYaml._DEFAULT_FORM,
            "pv": {"capacity_kw": {"type": "normal", "mean": 50, "std": 1}},
        }

        response = client.post("/api/scenarios/validate", json=form)

        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False
        assert any(
            error.startswith("pv.capacity_kw must be between 0.5 and 20 for every home, got ")
            for error in data["errors"]
        ), data["errors"]

    def test_validate_reports_a_shuffled_pool_too_small_for_the_fleet(
        self, client: FlaskClient
    ) -> None:
        """A PV pool of 90 values for 100 homes is the one fault in a form that validates with a pool of 100.

        The builder's default PV pool used to hold those 90 values.  The fault is reported in
        read_form_fleet's words, naming the pool at the form's path, n_homes and the pool's size.
        """
        values = [3.0, 4.0, 5.0]
        refusal = fleet_reader_refusal(_form_with_pv_pool(values, [20, 40, 30]))

        assert _validation_with_pv_pool(client, values, [20, 40, 40]) == {"valid": True, "errors": []}
        assert _validation_with_pv_pool(client, values, [20, 40, 30]) == {"valid": False, "errors": [refusal]}
        assert refusal.removeprefix("the top level: ").startswith("pv.capacity_kw: ")
        assert "n_homes (100), got 90" in refusal

    def test_validate_answers_the_readers_refusal_of_a_seg_block_without_a_temp_directory(
        self, client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The builder's document is judged in memory, so with the temp directory missing the answer is still parse_seg_rate's refusal of the negative rate."""
        with pytest.raises(ConfigurationError) as seg_refusal:
            parse_seg_rate({"rate_pence_per_kwh": -1.0})
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "absent"))

        response = client.post(
            "/api/scenarios/validate",
            json={**TestBuilderScenarioYaml._DEFAULT_FORM, "seg_rate_pence_per_kwh": -1},
        )

        assert response.status_code == 200
        assert response.get_json() == {"valid": False, "errors": [str(seg_refusal.value)]}

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
            json={"name": "Test", "pv": {"capacity_kw": 999}},
        )
        assert response.status_code == 200
        data = response.get_json()
        assert data["valid"] is False

    def test_validate_refuses_only_a_fleet_above_the_dashboard_fleet_limit(
        self, client: FlaskClient
    ) -> None:
        """The builder accepts a fleet of exactly the dashboard's fleet limit, and refuses one home more, naming the limit."""
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

    def test_validate_refuses_a_shuffled_pool_whose_counts_far_exceed_the_fleets_homes_naming_their_total_and_n_homes(
        self, client: FlaskClient
    ) -> None:
        """E7: a pool of 10**12 values for 10 homes is refused with read_form_fleet's one refusal, which holds the counts to n_homes before any value of the pool is built, naming pv.capacity_kw at the form's path, the counts' total and n_homes; a pool of 10 values for those homes validates."""
        form = _form_with_pv_pool([4.0], [10**12], n_homes=10)
        refusal = fleet_reader_refusal(form)

        assert _validation_with_pv_pool(client, [4.0], [10], n_homes=10) == {"valid": True, "errors": []}
        assert _validation_with_pv_pool(client, [4.0], [10**12], n_homes=10) == {"valid": False, "errors": [refusal]}
        assert refusal.removeprefix("the top level: ").startswith("pv.capacity_kw: ")
        assert f"n_homes (10), got {10**12}" in refusal

    def test_validate_accepts_each_fixed_value_the_builder_page_allows_and_refuses_one_beyond_it(
        self, client: FlaskClient
    ) -> None:
        """Each component's Fixed Value validates at either end of the min and max the builder page serves for it, and not one float step beyond either."""
        page = client.get("/scenarios/builder").get_data(as_text=True)
        bounds = [
            (attributes["min"], attributes["max"])
            for attributes in element_attributes(page, "input")
            if attributes.get("x-model.number") == "dist.fixed"
        ]

        def validation_with(component: ComponentLimits, value: float) -> Any:
            response = client.post(
                "/api/scenarios/validate",
                json={**TestBuilderScenarioYaml._DEFAULT_FORM, component.key: {component.grammar_key: value}},
            )
            assert response.status_code == 200
            return response.get_json()

        for component, (served_min, served_max) in zip(FLEET_COMPONENTS.values(), bounds, strict=True):
            low, high = float(served_min), float(served_max)
            field = f"{component.key}.{component.grammar_key}"
            for value in (low, high):
                answer = validation_with(component, value)
                assert answer == {"valid": True, "errors": []}, (
                    f"{field} {value!r}, which the page allows, was refused: {answer}"
                )
            for value in (math.nextafter(low, -math.inf), math.nextafter(high, math.inf)):
                answer = validation_with(component, value)
                assert answer["valid"] is False, (
                    f"{field} {value!r}, beyond what the page allows, was accepted: {answer}"
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
        "seed": 42,
        "import_rate": 0.245,
        "seg_rate_pence_per_kwh": "",
        "pv": {"capacity_kw": 4},
        "battery": {"capacity_kwh": 5},
        "load": {"annual_consumption_kwh": 3500},
    }
    """A form scenario-builder.js's getFormData() sends, given a name, with each component at its Fixed Value.

    tests/e2e/test_scenario_builder.py::test_default_form_previews_yaml_the_fleet_loader_loads
    pins the real payload's shape.
    """

    def test_default_form_yaml_loads_through_load_fleet_config(
        self, client: FlaskClient, tmp_path: Path
    ) -> None:
        """load_fleet_config builds every home of the form; the period is there for its own reader, and the seg: block is null, since the builder starts with no SEG rate."""
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
        assert document["seg"] is None

    @pytest.mark.parametrize(
        ("spec", "expected"),
        [
            pytest.param(
                {"type": "normal", "mean": 5, "std": 2, "min": 0, "max": 13.5},
                NormalDistribution(5.0, 2.0, min=0.0, max=13.5),
                id="normal",
            ),
            pytest.param(
                {"type": "uniform", "min": 2, "max": 8},
                UniformDistribution(2.0, 8.0),
                id="uniform",
            ),
            pytest.param(
                {"type": "weighted_discrete", "values": [3, 4], "weights": [20, 40]},
                WeightedDiscreteDistribution((3.0, 4.0), (20.0, 40.0)),
                id="weighted_discrete",
            ),
            pytest.param(
                {"type": "shuffled_pool", "values": [3, 4], "counts": [50, 50]},
                ShuffledPoolDistribution((3.0, 4.0), (50, 50)),
                id="shuffled_pool",
            ),
        ],
    )
    @pytest.mark.parametrize(
        "component", tuple(FLEET_COMPONENTS.values()), ids=lambda component: component.key
    )
    def test_each_distribution_the_form_offers_reaches_the_loader(
        self,
        client: FlaskClient,
        component: ComponentLimits,
        spec: dict[str, Any],
        expected: object,
    ) -> None:
        """A component sent as a distribution, in the grammar's spelling getFormData() sends it in, is read back as that distribution."""
        form = {**self._DEFAULT_FORM, component.key: {component.grammar_key: spec}}

        _, document = _preview_document(client, form)

        fleet_distribution = parse_fleet_distribution_config(document["fleet_distribution"])
        assert getattr(fleet_distribution, component.key).draws[component.grammar_key] == expected

    @pytest.mark.parametrize(
        "rate",
        [
            pytest.param("5.5", id="typed"),
            pytest.param(5.5, id="uploaded"),
        ],
    )
    def test_a_seg_rate_the_form_sets_is_the_rate_the_seg_reader_reads(
        self, client: FlaskClient, rate: str | float
    ) -> None:
        """A SEG rate the form sets is written in the seg: block as the rate the seg: reader reads.

        The builder sends a rate typed into its SEG input as text, and an uploaded scenario's rate as the number its YAML holds.
        """
        _, document = _preview_document(client, {**self._DEFAULT_FORM, "seg_rate_pence_per_kwh": rate})

        assert parse_seg_rate(document["seg"]) == 5.5

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
        """Clearing the import or SEG rate of a form that sets both means a scenario with no tariff or no SEG, which the readers accept.

        The block is written as null, the readers' spelling of none, not as an empty block they refuse.
        """
        form = {**self._DEFAULT_FORM, "seg_rate_pence_per_kwh": 5.5, rate_field: ""}

        _, document = _preview_document(client, form)
        validation = client.post("/api/scenarios/validate", json=form).get_json()

        assert document[block] is None
        assert validation == {"valid": True, "errors": []}

    @pytest.mark.parametrize(
        "omitted",
        [
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

    @pytest.mark.parametrize(
        "omitted",
        [
            pytest.param("latitude", id="without latitude"),
            pytest.param("longitude", id="without longitude"),
        ],
    )
    def test_a_custom_location_without_one_coordinate_is_written_as_given_and_reported(
        self, client: FlaskClient, omitted: str
    ) -> None:
        """A custom location the form sends without its latitude or its longitude is reported by the key it leaves out, not loaded as Bristol's.

        The form sends the *omitted* coordinate as ''.  The preview writes the coordinates
        given as the document's location: block, which the loader refuses naming the key it
        leaves out.
        """
        coordinates = {"latitude": 53.4, "longitude": -2.2, "altitude": 38.0}
        given = {key: value for key, value in coordinates.items() if key != omitted}
        form = {**self._DEFAULT_FORM, "location_preset": "custom", **given, omitted: ""}

        _, document = _preview_document(client, form)
        validation = client.post("/api/scenarios/validate", json=form).get_json()

        assert document["location"] == given
        assert validation["valid"] is False
        assert validation["errors"] == [f"location: requires {omitted!r}"], validation

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


_PV_CAPACITY = "PV Capacity (kW)"

# The three metrics' bests fall at three different values, and grid import's highest (2.0) is not
# its lowest (4.0). The ratios are exact in binary, so their percentages are exactly 50, 37.5 and 25.
_THREE_POINTS = (
    SweepPoint(
        2.0, home_summary(total_generation_kwh=72.0, self_consumption_ratio=0.5, total_grid_import_kwh=12.0)
    ),
    SweepPoint(
        4.0, home_summary(total_generation_kwh=108.0, self_consumption_ratio=0.375, total_grid_import_kwh=3.0)
    ),
    SweepPoint(
        6.0, home_summary(total_generation_kwh=144.0, self_consumption_ratio=0.25, total_grid_import_kwh=6.0)
    ),
)

# A battery sweep past what the home can fill: generation is the same at every capacity, and self-consumption
# and grid import stop changing from 5 kWh, so each metric's best reading is shared by more than one point.
_SATURATED_BATTERY_POINTS = (
    SweepPoint(
        0.0, home_summary(total_generation_kwh=108.0, self_consumption_ratio=0.375, total_grid_import_kwh=6.0)
    ),
    SweepPoint(
        5.0, home_summary(total_generation_kwh=108.0, self_consumption_ratio=0.5, total_grid_import_kwh=3.0)
    ),
    SweepPoint(
        10.0, home_summary(total_generation_kwh=108.0, self_consumption_ratio=0.5, total_grid_import_kwh=3.0)
    ),
)

_SWEEP_PANEL_HEADINGS = [
    ("chart-sweep-generation", "Generation (kWh) vs PV Capacity (kW)"),
    ("chart-sweep-self-consumption", "Self-Consumption (%) vs PV Capacity (kW)"),
    ("chart-sweep-grid-import", "Grid Import (kWh) vs PV Capacity (kW)"),
]


def _figure(panel: ChartPanel) -> str:
    """*panel*'s figure JSON, failing the test when the panel is an absence."""
    assert panel.figure_json is not None, f"{panel.dom_id} drew no figure: {panel.absence_reason}"
    return panel.figure_json


class TestSweepChart:
    """sweep_panels draws one panel per SweepMetric, each through sweep_parameter_chart, from a sweep's finished points."""

    def test_sweep_panels_draw_one_panel_per_metric_in_member_order(self) -> None:
        panels = sweep_panels(_PV_CAPACITY, _THREE_POINTS)

        assert [(panel.dom_id, panel.title) for panel in panels] == _SWEEP_PANEL_HEADINGS
        assert [panel.dom_id for panel in panels] == [metric.dom_id for metric in SweepMetric]

    def test_each_sweep_panel_draws_its_metric_at_each_swept_value_beside_the_optimal_point_and_the_trend(
        self,
    ) -> None:
        drawn = []
        for panel in sweep_panels(_PV_CAPACITY, _THREE_POINTS):
            by_name = traces_by_name(_figure(panel))
            names = list(by_name)
            drawn.append((names, by_name[names[0]]["x"], by_name[names[0]]["y"]))

        assert drawn == [
            (["Generation (kWh)", "Optimal", "Trend"], [2.0, 4.0, 6.0], [72.0, 108.0, 144.0]),
            (["Self-Consumption (%)", "Optimal", "Trend"], [2.0, 4.0, 6.0], [50.0, 37.5, 25.0]),
            (["Grid Import (kWh)", "Optimal", "Trend"], [2.0, 4.0, 6.0], [12.0, 3.0, 6.0]),
        ]

    @pytest.mark.parametrize(
        ("metric", "optimal_value", "optimal_metric"),
        [
            pytest.param(SweepMetric.GENERATION, 6.0, 144.0, id="generation-at-its-highest"),
            pytest.param(SweepMetric.SELF_CONSUMPTION, 2.0, 50.0, id="self-consumption-at-its-highest"),
            pytest.param(SweepMetric.GRID_IMPORT, 4.0, 3.0, id="grid-import-at-its-lowest"),
        ],
    )
    def test_sweep_parameter_chart_marks_the_optimal_point_by_its_metrics_direction(
        self, metric: SweepMetric, optimal_value: float, optimal_metric: float
    ) -> None:
        optimal = traces_by_name(_figure(sweep_parameter_chart(_PV_CAPACITY, _THREE_POINTS, metric)))["Optimal"]

        assert (optimal["x"], optimal["y"]) == ([optimal_value], [optimal_metric])

    @pytest.mark.parametrize(
        ("metric", "optimal_value", "optimal_metric"),
        [
            pytest.param(SweepMetric.GENERATION, 0.0, 108.0, id="generation-highest-at-every-point"),
            pytest.param(SweepMetric.SELF_CONSUMPTION, 5.0, 50.0, id="self-consumption-highest-from-5-kwh"),
            pytest.param(SweepMetric.GRID_IMPORT, 5.0, 3.0, id="grid-import-lowest-from-5-kwh"),
        ],
    )
    def test_sweep_parameter_chart_marks_the_earliest_swept_of_the_points_sharing_the_best_reading(
        self, metric: SweepMetric, optimal_value: float, optimal_metric: float
    ) -> None:
        panel = sweep_parameter_chart("Battery Capacity (kWh)", _SATURATED_BATTERY_POINTS, metric)

        optimal = traces_by_name(_figure(panel))["Optimal"]

        assert (optimal["x"], optimal["y"]) == ([optimal_value], [optimal_metric])

    @pytest.mark.parametrize(
        "points", [pytest.param((), id="no-points"), pytest.param(_THREE_POINTS[1:2], id="one-point")]
    )
    def test_sweep_panels_of_fewer_than_two_points_name_the_rule_and_the_sweeps_points_in_each_titled_panel(
        self, points: tuple[SweepPoint, ...]
    ) -> None:
        panels = sweep_panels(_PV_CAPACITY, points)

        assert [(panel.dom_id, panel.title, panel.absence_reason) for panel in panels] == [
            (dom_id, title, sweep_reason(len(points))) for dom_id, title in _SWEEP_PANEL_HEADINGS
        ]

    @pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf], ids=["nan", "inf", "minus-inf"])
    def test_a_sweep_point_refuses_a_value_that_is_not_finite(self, value: float) -> None:
        with pytest.raises(ValueError, match=r"SweepPoint\.value"):
            SweepPoint(value, home_summary())

    @pytest.mark.parametrize("label", ["", "   "], ids=["empty", "spaces"])
    def test_sweep_parameter_chart_refuses_a_blank_parameter_label(self, label: str) -> None:
        with pytest.raises(ValueError, match="parameter_label"):
            sweep_parameter_chart(label, _THREE_POINTS, SweepMetric.GENERATION)


_SWEEP_CHART_URL = "/scenarios/sweep/chart"


def _sweep_chart_body(*points: tuple[object, object]) -> dict[str, Any]:
    """A sweep chart request of the PV capacity sweep's *points*, each its value and its run's id."""
    return {"parameter_label": _PV_CAPACITY, "points": [{"value": value, "run_id": run_id} for value, run_id in points]}


def _store_a_finished_point(storage: RunStorage, run_id: str, self_kwh: float, export_kwh: float, import_kwh: float) -> None:
    """Save a day's home run under *run_id*, its totals the kWh given, as a sweep point's finished job saves it."""
    store_home_run(
        storage,
        run_id,
        make_home_config(),
        make_sim_results(self_kwh=self_kwh, export_kwh=export_kwh, import_kwh=import_kwh, days=1),
    )


def _no_run(storage: RunStorage, run_id: str) -> None:
    """Store nothing, so no run has *run_id*."""


def _a_finished_fleet_run(storage: RunStorage, run_id: str) -> None:
    store_fleet_run(storage, run_id, make_fleet_results(n_homes=2, days=1))


def _a_home_run_with_no_summary_yet(storage: RunStorage, run_id: str) -> None:
    storage.create_run(run_id, run_type="home", name="Sweep point", n_homes=1, created_at="2026-10-26T09:00:00+00:00")


_A_POINT = {"value": 2.0, "run_id": "run-2kw"}

_MALFORMED_SWEEP_CHART_BODIES = [
    pytest.param(["PV Capacity (kW)", [_A_POINT]], ["Request body"], id="body-not-an-object"),
    pytest.param(
        {"parameter_label": _PV_CAPACITY, "points": [_A_POINT], "metric": "generation"},
        ["'metric'"],
        id="unrecognised-key",
    ),
    pytest.param({"points": [_A_POINT]}, ["parameter_label"], id="parameter-label-missing"),
    pytest.param({"parameter_label": "  ", "points": [_A_POINT]}, ["parameter_label"], id="parameter-label-blank"),
    pytest.param({"parameter_label": 7, "points": [_A_POINT]}, ["parameter_label"], id="parameter-label-not-a-string"),
    pytest.param({"parameter_label": _PV_CAPACITY}, ["points"], id="points-missing"),
    pytest.param({"parameter_label": _PV_CAPACITY, "points": _A_POINT}, ["points"], id="points-not-an-array"),
    pytest.param(
        {"parameter_label": _PV_CAPACITY, "points": [_A_POINT] * (SWEEP_MAX_STEPS + 1)},
        ["points", str(SWEEP_MAX_STEPS)],
        id="more-points-than-a-sweep-has-steps",
    ),
    pytest.param({"parameter_label": _PV_CAPACITY, "points": [2.0]}, ["points[0]"], id="point-not-an-object"),
    pytest.param(
        {"parameter_label": _PV_CAPACITY, "points": [{**_A_POINT, "label": "2 kW"}]},
        ["points[0]", "'label'"],
        id="unrecognised-point-key",
    ),
    pytest.param(_sweep_chart_body((True, "run-2kw")), ["points[0].value"], id="value-a-bool"),
    pytest.param(_sweep_chart_body(("NaN", "run-2kw")), ["points[0].value"], id="value-the-text-nan"),
    pytest.param(
        {"parameter_label": _PV_CAPACITY, "points": [{"run_id": "run-2kw"}]}, ["points[0].value"], id="value-missing"
    ),
    pytest.param(_sweep_chart_body((2.0, 7)), ["points[0].run_id"], id="run-id-a-number"),
    pytest.param(_sweep_chart_body((2.0, "run-2kw"), (4.0, "\ud800")), ["points[1].run_id"], id="run-id-a-lone-surrogate"),
    pytest.param(
        {"parameter_label": _PV_CAPACITY, "points": [{"value": 2.0}]}, ["points[0].run_id"], id="run-id-missing"
    ),
    pytest.param(
        _sweep_chart_body((2.0, "run-2kw"), (False, "run-4kw")),
        ["points[1].value"],
        id="a-later-point-refused-before-an-earlier-points-unknown-run-is-read",
    ),
]


class TestSweepChartRoute:
    """POST /scenarios/sweep/chart answers the HTML of a sweep's panels, read from its finished points' stored runs."""

    def test_three_finished_points_draw_each_metrics_panel_marking_its_best_point_by_its_direction(
        self, client: FlaskClient, storage: RunStorage
    ) -> None:
        """Grid import is marked at its lowest, 4.0, while its highest is at 2.0 (B12)."""
        _store_a_finished_point(storage, "run-2kw", self_kwh=24.0, export_kwh=48.0, import_kwh=12.0)
        _store_a_finished_point(storage, "run-4kw", self_kwh=30.0, export_kwh=78.0, import_kwh=3.0)
        _store_a_finished_point(storage, "run-6kw", self_kwh=36.0, export_kwh=108.0, import_kwh=6.0)

        response = client.post(
            _SWEEP_CHART_URL, json=_sweep_chart_body((2.0, "run-2kw"), (4.0, "run-4kw"), (6.0, "run-6kw"))
        )

        assert (response.status_code, response.mimetype) == (200, "text/html"), response.get_data(as_text=True)
        figures = chart_figures(response.get_data(as_text=True))
        assert list(figures) == [metric.dom_id for metric in SweepMetric]
        assert {dom_id: traces_by_name(figure)["Optimal"]["x"] for dom_id, figure in figures.items()} == {
            "chart-sweep-generation": [6.0],
            "chart-sweep-self-consumption": [2.0],
            "chart-sweep-grid-import": [4.0],
        }

    def test_one_finished_point_gives_each_panel_the_reason_it_has_no_chart(
        self, client: FlaskClient, storage: RunStorage
    ) -> None:
        _store_a_finished_point(storage, "run-4kw", self_kwh=30.0, export_kwh=78.0, import_kwh=3.0)

        response = client.post(_SWEEP_CHART_URL, json=_sweep_chart_body((4.0, "run-4kw")))

        assert response.status_code == 200, response.get_data(as_text=True)
        page = response.get_data(as_text=True)
        assert chart_figures(page) == {}
        assert [texts_after(page, title, 1) for _, title in _SWEEP_PANEL_HEADINGS] == [
            [sweep_reason(1)] for _ in _SWEEP_PANEL_HEADINGS
        ]

    @pytest.mark.parametrize(
        ("store", "why"),
        [
            pytest.param(_no_run, "no run", id="no-run-has-the-id"),
            pytest.param(_a_finished_fleet_run, "fleet run", id="a-fleet-run"),
            pytest.param(_a_home_run_with_no_summary_yet, "no summary", id="a-home-run-with-no-summary-yet"),
        ],
    )
    def test_a_point_whose_run_is_not_a_finished_home_run_is_refused_naming_its_run_id(
        self,
        client: FlaskClient,
        storage: RunStorage,
        store: Callable[[RunStorage, str], None],
        why: str,
    ) -> None:
        _store_a_finished_point(storage, "run-2kw", self_kwh=24.0, export_kwh=48.0, import_kwh=12.0)
        store(storage, "run-4kw")

        response = client.post(_SWEEP_CHART_URL, json=_sweep_chart_body((2.0, "run-2kw"), (4.0, "run-4kw")))

        assert response.status_code == 400, response.get_data(as_text=True)
        body = response.get_json()
        assert body == {"error": body["error"]}
        assert [text for text in ("run-4kw", why) if text not in body["error"]] == [], body["error"]

    def test_a_runs_row_the_store_cannot_read_answers_500_not_a_refusal_of_the_request(
        self, app: Flask, client: FlaskClient, storage: RunStorage
    ) -> None:
        """A writer outside the store blanked the point's runs name, which contract C7 forbids, so RunRecord refuses the row with a ValueError: the store's fault, not the request's."""
        _store_a_finished_point(storage, "run-4kw", self_kwh=30.0, export_kwh=78.0, import_kwh=3.0)
        with storage.database.transaction() as conn:
            conn.execute("UPDATE runs SET name = '   ' WHERE id = ?", ("run-4kw",))
        app.config["PROPAGATE_EXCEPTIONS"] = False

        response = client.post(_SWEEP_CHART_URL, json=_sweep_chart_body((4.0, "run-4kw")))

        assert response.status_code == 500, response.get_data(as_text=True)

    def test_a_body_nested_past_the_recursion_limit_is_refused_not_a_500(self, app: Flask, client: FlaskClient) -> None:
        app.config["PROPAGATE_EXCEPTIONS"] = False

        response = client.post(_SWEEP_CHART_URL, data="[" * 100000, content_type="application/json")

        assert response.status_code == 400, response.get_data(as_text=True)
        assert "NoneType" in response.get_json()["error"]

    @pytest.mark.parametrize(("body", "named"), _MALFORMED_SWEEP_CHART_BODIES)
    def test_a_malformed_body_is_refused_naming_the_field(
        self, client: FlaskClient, caplog: pytest.LogCaptureFixture, body: object, named: list[str]
    ) -> None:
        response = client.post(_SWEEP_CHART_URL, json=body)

        assert response.status_code == 400, response.get_data(as_text=True)
        refusal = response.get_json()
        assert refusal == {"error": refusal["error"]}
        assert [text for text in named if text not in refusal["error"]] == [], refusal["error"]
        assert error_records(caplog) == []
