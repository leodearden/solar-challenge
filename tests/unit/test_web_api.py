"""Tests for the API blueprint endpoints with mocked JobManager.

Tests all endpoints in solar_challenge.web.api without running real
simulations.  The JobManager is mocked so that submit/status/event
calls return canned responses instantly.
"""

import dataclasses
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytest.importorskip("flask")
import pandas as pd
import yaml
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.config import DispatchStrategyConfig, load_fleet_config, parse_seg_rate
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.api import api_bp
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES
from tests._web_app import build_test_app
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES, VALID_HOME_PAYLOAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def mock_job_manager(app: Flask) -> MagicMock:
    """Replace the real JobManager on the app with a MagicMock.

    The mock is pre-configured with sensible return values so that
    tests can focus on request/response behaviour.
    """
    jm = MagicMock()
    jm.submit_home_job.return_value = ("job-home-001", "run-home-001")
    jm.submit_fleet_job.return_value = ("job-fleet-001", "run-fleet-001")
    jm.get_job_status.return_value = {
        "job_id": "job-home-001",
        "run_id": "run-home-001",
        "status": "running",
        "progress_pct": 42.0,
        "current_step": "Simulating",
        "message": "Running home simulation...",
    }
    jm.get_events.return_value = iter([
        {
            "event": "complete",
            "data": {"status": "completed", "run_id": "run-home-001"},
        }
    ])
    app.extensions["job_manager"] = jm
    return jm


@pytest.fixture
def client(app: Flask, mock_job_manager: MagicMock) -> FlaskClient:
    """Create a Flask test client with the mocked JobManager."""
    return app.test_client()


# ===================================================================
# POST /api/fleet/export-yaml
# ===================================================================


#: A fleet page form with every value away from the form converter's defaults and every overlay set.
_FLEET_FORM_BODY: dict = {
    "name": "Export Round Trip",
    "n_homes": 4,
    "seed": 7,
    "location": "london",
    "start": "2024-07-01",
    "end": "2024-07-03",
    "pv": {
        "capacity_kw": {
            "type": "weighted_discrete",
            "values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 2}],
        }
    },
    "battery": {
        "capacity_kwh": {
            "type": "shuffled_pool",
            "entries": [{"value": 0, "count": 2}, {"value": 5.0, "count": 2}],
        }
    },
    "load": {
        "annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800, "min": 2000, "max": 6000}
    },
    "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
    "seg": {"rate_pence_per_kwh": 5.5},
    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 21]]},
}


class TestExportFleetYAML:
    """POST /api/fleet/export-yaml writes the fleet scenario the fleet page's form describes."""

    def test_export_loads_back_through_load_fleet_config_as_the_fleet_simulate_runs(
        self, client: FlaskClient, mock_job_manager: MagicMock, tmp_path: Path
    ) -> None:
        """The exported file, read as `finance run` reads it, is the fleet POST /api/simulate/fleet-from-distribution runs for the same form: its homes, name and dates.

        load_fleet_config does not read seg: yet (task 185), so the SEG rate is threaded onto
        its homes as cli/finance.py threads it, as tests/unit/test_scenario_writer.py does.
        """
        export = client.post("/api/fleet/export-yaml", json=_FLEET_FORM_BODY)
        assert export.status_code == 200, export.get_data(as_text=True)
        assert "text/yaml" in export.content_type
        assert export.headers["Content-Disposition"] == "attachment; filename=fleet-config.yaml"
        text = export.get_data(as_text=True)
        path = tmp_path / "fleet.yaml"
        path.write_text(text, encoding="utf-8")

        fleet = load_fleet_config(path)
        document = yaml.safe_load(text)
        seg_tariff = SEGTariff(name="", rate_pence_per_kwh=parse_seg_rate(document["seg"]))
        loaded = [dataclasses.replace(home, seg_tariff=seg_tariff) for home in fleet.homes]

        simulate = client.post("/api/simulate/fleet-from-distribution", json=_FLEET_FORM_BODY)
        assert simulate.status_code == 201, simulate.get_data(as_text=True)
        submitted = mock_job_manager.submit_fleet_job.call_args.kwargs
        homes = submitted["configs"]
        batteries = [home.battery_config for home in homes if home.battery_config is not None]
        assert 0 < len(batteries) < len(homes)
        assert all(
            battery.dispatch_strategy == DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 21)])
            for battery in batteries
        )
        assert all(
            home.tariff_config == TariffConfig.economy_7(off_peak_rate=0.1, peak_rate=0.3)
            and home.seg_tariff == SEGTariff(name="", rate_pence_per_kwh=5.5)
            for home in homes
        )

        assert loaded == homes
        assert fleet.name == submitted["name"]
        timezone = homes[0].location.timezone
        period = document["period"]
        assert (
            pd.Timestamp(period["start_date"], tz=timezone),
            pd.Timestamp(period["end_date"], tz=timezone),
        ) == (submitted["start_date"], submitted["end_date"])

    def test_export_names_a_nameless_fleet_as_simulate_runs_it(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """A form without a name is exported under the name its simulation runs as."""
        body = {key: value for key, value in _FLEET_FORM_BODY.items() if key != "name"}

        export = client.post("/api/fleet/export-yaml", json=body)
        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)

        assert (export.status_code, simulate.status_code) == (200, 201)
        assert (
            yaml.safe_load(export.get_data(as_text=True))["name"]
            == mock_job_manager.submit_fleet_job.call_args.kwargs["name"]
        )

    @pytest.mark.parametrize(
        "patch",
        [
            pytest.param({"tariff": {"type": "flat_rate"}}, id="tariff-the-loaders-refuse"),
            pytest.param({"dispatch_strategy": ""}, id="empty-string-dispatch"),
            pytest.param({"days": float("inf")}, id="days-infinity"),
        ],
    )
    def test_export_refuses_what_simulate_refuses_with_the_same_answer(
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict
    ) -> None:
        """A form the simulate endpoint refuses gets the same 400 and error from the export, so no YAML is written for a fleet that cannot run; no job is queued.

        The empty-string dispatch is task 393's presence rule: only null reads as absent.
        """
        body = {**_FLEET_FORM_BODY, **patch}

        export = client.post("/api/fleet/export-yaml", json=body)
        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)

        assert export.status_code == 400
        assert (export.status_code, export.get_json()) == (simulate.status_code, simulate.get_json())
        mock_job_manager.submit_fleet_job.assert_not_called()


# ===================================================================
# POST /api/fleet/import-yaml
# ===================================================================


class TestImportFleetYAML:
    """POST /api/fleet/import-yaml answers the fleet form a fleet scenario's YAML describes, and the settings of it the form does not load."""

    def test_an_exported_fleet_imports_back_as_its_form(self, client: FlaskClient) -> None:
        """The page's export imports in full, and the form the import answers exports the same scenario."""
        body = {key: value for key, value in _FLEET_FORM_BODY.items() if key != "location"}
        exported = client.post("/api/fleet/export-yaml", json=body)
        assert exported.status_code == 200, exported.get_data(as_text=True)
        text = exported.get_data(as_text=True)

        imported = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert imported.status_code == 200, imported.get_data(as_text=True)
        answer = imported.get_json()
        assert answer["not_loaded"] == []
        re_exported = client.post("/api/fleet/export-yaml", json=answer["form"])
        assert re_exported.status_code == 200, re_exported.get_data(as_text=True)
        assert yaml.safe_load(re_exported.get_data(as_text=True)) == yaml.safe_load(text)

    def test_a_scenario_file_imports_naming_what_was_not_loaded(self, client: FlaskClient) -> None:
        """A scenario file loads what the form holds and names the settings the form has no control for."""
        text = (
            "fleet_distribution:\n"
            "  n_homes: 25\n"
            "  random_order: bristol_legacy\n"
            "  pv:\n"
            "    capacity_kw: {type: uniform, min: 3.0, max: 6.0}\n"
            "  load:\n"
            "    annual_consumption_kwh: {type: uniform, min: 2500, max: 4500}\n"
        )

        resp = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        answer = resp.get_json()
        assert answer["form"]["n_homes"] == 25
        assert answer["not_loaded"] == ["fleet_distribution.random_order"]

    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            pytest.param("", "Empty request body", id="empty-body"),
            pytest.param("[[[not valid yaml", "Invalid YAML", id="malformed-yaml"),
            pytest.param(
                "home:\n  pv:\n    capacity_kw: 4.0\n", "fleet_distribution", id="home-scenario"
            ),
            pytest.param(
                "n_homes: 25\nseed: 7\n", "fleet_distribution", id="bare-fleet-distribution"
            ),
        ],
    )
    def test_a_body_that_is_no_fleet_scenario_is_refused(
        self, client: FlaskClient, text: str, reason: str
    ) -> None:
        """An empty body, malformed YAML, and a scenario without a fleet_distribution block get a 400 saying why.

        The loaders read a fleet only from a fleet_distribution: or homes: file, so a bare
        fleet_distribution block is not one.
        """
        resp = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert resp.status_code == 400
        assert reason in resp.get_json()["error"]


# ===================================================================
# GET /api/fleet/presets/<name>
# ===================================================================

#: The built-in scenarios the fleet page's Load Preset offers: the scenarios/ directory's files.
_BUILTIN_SCENARIO_STEMS = sorted(
    path.stem
    for path in (Path(__file__).resolve().parents[2] / "scenarios").iterdir()
    if path.suffix in (".yaml", ".yml") and path.is_file()
)


class TestFleetPresetEndpoint:
    """GET /api/fleet/presets/<name> answers for a built-in scenario file what the import answers for its YAML."""

    def test_a_fleet_preset_answers_its_form_and_what_was_not_loaded(
        self, client: FlaskClient
    ) -> None:
        """bristol-phase1 loads its PV pool and SEG rate, and names its random order, which the form has no control for."""
        resp = client.get("/api/fleet/presets/bristol-phase1")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        answer = resp.get_json()
        assert answer["form"]["pv"]["capacity_kw"] == {
            "type": "shuffled_pool",
            "entries": [
                {"value": 3.0, "count": 20},
                {"value": 4.0, "count": 40},
                {"value": 5.0, "count": 30},
                {"value": 6.0, "count": 10},
            ],
        }
        assert answer["form"]["seg"] == {"rate_pence_per_kwh": 4.1}
        assert "fleet_distribution.random_order" in answer["not_loaded"]

    def test_an_unknown_preset_is_not_found(self, client: FlaskClient) -> None:
        """A name no built-in scenario file has is a 404 naming it."""
        resp = client.get("/api/fleet/presets/no-such-preset")

        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Preset 'no-such-preset' not found"}

    def test_a_home_scenario_preset_is_refused_naming_fleet_distribution(
        self, client: FlaskClient
    ) -> None:
        """bristol-arbitrage is a home: scenario, which the fleet page cannot load."""
        resp = client.get("/api/fleet/presets/bristol-arbitrage")

        assert resp.status_code == 400
        assert "fleet_distribution" in resp.get_json()["error"]

    @pytest.mark.parametrize("name", _BUILTIN_SCENARIO_STEMS)
    def test_every_builtin_scenario_loads_or_is_refused_with_a_reason(
        self, client: FlaskClient, name: str
    ) -> None:
        """Every preset the fleet page offers loads as a form, or is refused with an error the page shows; none fails the server."""
        answer_keys = {200: {"form", "not_loaded"}, 400: {"error"}}

        resp = client.get(f"/api/fleet/presets/{name}")

        assert resp.status_code in answer_keys, resp.get_data(as_text=True)
        assert set(resp.get_json()) == answer_keys[resp.status_code]


# ===================================================================
# Error path tests (miscellaneous)
# ===================================================================

_API_ENDPOINTS_THAT_READ_NO_JSON_BODY = frozenset({"api.import_fleet_yaml"})


def _api_body_method_routes() -> list[tuple[str, str, str]]:
    """Return the endpoint, method and path of every POST, PUT and PATCH route of the api blueprint.

    A path argument is filled with a value that names no record, e.g. no-such-run_id.
    """
    api_only = Flask(__name__, static_folder=None)
    api_only.register_blueprint(api_bp)
    urls = api_only.url_map.bind("localhost")
    return [
        (
            rule.endpoint,
            method,
            urls.build(rule.endpoint, {name: f"no-such-{name}" for name in rule.arguments}, method=method),
        )
        for rule in api_only.url_map.iter_rules()
        for method in sorted({"POST", "PUT", "PATCH"}.intersection(rule.methods or ()))
    ]


class TestErrorPaths:
    """Catch-all tests for error handling across the API."""

    def test_bad_json_simulate_home(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for home simulation."""
        resp = client.post(
            "/api/simulate/home",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_simulate_fleet(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for fleet simulation."""
        resp = client.post(
            "/api/simulate/fleet",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_save_preset(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for preset save."""
        resp = client.post(
            "/api/presets",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    def test_bad_json_sweep(self, client: FlaskClient) -> None:
        """Malformed JSON body returns 400 for sweep."""
        resp = client.post(
            "/api/simulate/sweep",
            data="{bad json",
            content_type="application/json",
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("method", "path"),
        [
            pytest.param(method, path, id=endpoint)
            for endpoint, method, path in _api_body_method_routes()
            if endpoint not in _API_ENDPOINTS_THAT_READ_NO_JSON_BODY
        ],
    )
    def test_every_json_endpoint_answers_a_non_object_body_with_the_shared_400(
        self, client: FlaskClient, mock_job_manager: MagicMock, method: str, path: str
    ) -> None:
        """The body is refused, naming its type, before any run lookup, save or job submission."""
        resp = client.open(path, method=method, json=[1])
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Request body must be a JSON object, got list"}
        assert mock_job_manager.method_calls == []

    def test_no_stale_endpoint_is_listed_as_reading_no_json_body(self) -> None:
        """Every endpoint exempted from the shared 400 is still a POST, PUT or PATCH route of the api blueprint."""
        body_method_endpoints = {endpoint for endpoint, _, _ in _api_body_method_routes()}
        assert _API_ENDPOINTS_THAT_READ_NO_JSON_BODY - body_method_endpoints == set()

    @pytest.mark.parametrize(
        ("data", "content_type"),
        [
            pytest.param(None, None, id="absent"),
            pytest.param("null", "application/json", id="json-null"),
        ],
    )
    def test_an_absent_or_null_body_is_refused_as_nonetype(
        self, client: FlaskClient, mock_job_manager: MagicMock, data: str | None, content_type: str | None
    ) -> None:
        """No body at all, and a JSON null, are both refused naming NoneType."""
        resp = client.post("/api/simulate/home", data=data, content_type=content_type)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Request body must be a JSON object, got NoneType"}
        assert mock_job_manager.method_calls == []

    def test_get_method_not_allowed_simulate_home(self, client: FlaskClient) -> None:
        """GET on POST-only endpoint returns 405."""
        resp = client.get("/api/simulate/home")
        assert resp.status_code == 405

    def test_get_method_not_allowed_simulate_fleet(self, client: FlaskClient) -> None:
        """GET on POST-only endpoint returns 405."""
        resp = client.get("/api/simulate/fleet")
        assert resp.status_code == 405

    def test_delete_method_not_allowed_on_jobs(self, client: FlaskClient) -> None:
        """DELETE on job status endpoint returns 405."""
        resp = client.delete("/api/jobs/some-id")
        assert resp.status_code == 405


# ===================================================================
# UI render smoke test
# ===================================================================


class TestHomeFormRender:
    """Smoke test: GET /simulate/home renders the new tabs and controls."""

    def test_home_form_shows_heat_pump_tariff_and_dispatch(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/home returns 200 with Heat Pump, Tariff tabs and dispatch control."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Heat Pump" in html
        assert "Tariff" in html
        assert "Dispatch Strategy" in html

    def test_home_form_shows_pv_age_inputs(self, client: FlaskClient) -> None:
        """GET /simulate/home returns HTML containing the two PV-age number inputs."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'name="system_age_years"' in html
        assert 'name="degradation_rate_per_year"' in html

    def test_home_form_shows_seg_section(self, client: FlaskClient) -> None:
        """GET /simulate/home renders the SEG sub-section with all six preset options."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Preset dropdown field must be present
        assert 'name="seg_preset"' in html
        # Explicit-rate input field must be present
        assert 'name="seg_rate_pence_per_kwh"' in html
        # All six UK supplier preset keys must appear as selectable option values
        for preset_key in ("Octopus", "British Gas", "EDF", "E.ON", "Scottish Power", "OVO"):
            assert preset_key in html, f"SEG preset '{preset_key}' missing from form HTML"


# ===================================================================
# apply_fleet_overlay pure helper unit tests
# ===================================================================


def _make_test_homes() -> tuple:
    """Build two HomeConfig instances for overlay tests.

    Returns:
        (home_a, home_b) where home_a has a BatteryConfig and home_b does not.
    """
    from solar_challenge.battery import BatteryConfig
    from solar_challenge.home import HomeConfig
    from solar_challenge.load import LoadConfig
    from solar_challenge.pv import PVConfig

    pv_a = PVConfig(capacity_kw=4.0)
    pv_b = PVConfig(capacity_kw=3.0)
    load_a = LoadConfig(annual_consumption_kwh=3500.0)
    load_b = LoadConfig(annual_consumption_kwh=2800.0)
    battery_a = BatteryConfig(capacity_kwh=5.0)

    home_a = HomeConfig(pv_config=pv_a, load_config=load_a, battery_config=battery_a)
    home_b = HomeConfig(pv_config=pv_b, load_config=load_b, battery_config=None)
    return home_a, home_b


class TestApplyFleetOverlay:
    """Unit tests for the pure helper apply_fleet_overlay in web/fleet_config.py."""

    def test_tariff_applied_to_all_homes(self) -> None:
        """Passing tariff_config sets tariff_config on every home in the fleet."""
        from solar_challenge.tariff import TariffConfig
        from solar_challenge.web.fleet_config import apply_fleet_overlay

        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)

        result = apply_fleet_overlay([home_a, home_b], tariff_config=tariff)

        assert len(result) == 2
        assert result[0].tariff_config is tariff
        assert result[1].tariff_config is tariff

    def test_dispatch_applied_only_to_homes_with_battery(self) -> None:
        """dispatch_strategy is set on BatteryConfig only when battery_config is not None."""
        from solar_challenge.config import DispatchStrategyConfig
        from solar_challenge.web.fleet_config import apply_fleet_overlay

        home_a, home_b = _make_test_homes()
        dispatch = DispatchStrategyConfig(
            strategy_type="tou_optimized", peak_hours=[(16, 21)]
        )

        result = apply_fleet_overlay([home_a, home_b], dispatch_strategy=dispatch)

        # Home A (has battery) — dispatch_strategy applied
        assert result[0].battery_config is not None
        assert result[0].battery_config.dispatch_strategy is dispatch
        # Home B (no battery) — battery_config stays None, no fabricated battery
        assert result[1].battery_config is None

    def test_seg_tariff_applied_to_all_homes(self) -> None:
        """Passing seg_tariff sets seg_tariff on every home in the fleet."""
        from solar_challenge.seg import SEGTariff
        from solar_challenge.web.fleet_config import apply_fleet_overlay

        home_a, home_b = _make_test_homes()
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        result = apply_fleet_overlay([home_a, home_b], seg_tariff=seg)

        assert result[0].seg_tariff is seg
        assert result[1].seg_tariff is seg

    def test_original_homes_are_immutable(self) -> None:
        """After the call the original HomeConfig objects are unchanged (frozen dataclass)."""
        from solar_challenge.seg import SEGTariff
        from solar_challenge.tariff import TariffConfig
        from solar_challenge.web.fleet_config import apply_fleet_overlay

        home_a, home_b = _make_test_homes()
        tariff = TariffConfig.flat_rate(rate_per_kwh=0.30)
        seg = SEGTariff(name="Custom", rate_pence_per_kwh=5.5)

        apply_fleet_overlay([home_a, home_b], tariff_config=tariff, seg_tariff=seg)

        # Originals must be unchanged
        assert home_a.tariff_config is None
        assert home_a.seg_tariff is None
        assert home_b.tariff_config is None
        assert home_b.seg_tariff is None

    def test_all_none_overlay_is_noop(self) -> None:
        """Calling with all None args returns homes that match the inputs field-for-field."""
        from solar_challenge.web.fleet_config import apply_fleet_overlay

        home_a, home_b = _make_test_homes()

        result = apply_fleet_overlay([home_a, home_b])

        # Should return the same objects (or equal ones) — no mutations
        assert result[0] is home_a
        assert result[1] is home_b


# ===================================================================
# GET /simulate/fleet — render smoke test
# ===================================================================


class TestFleetFormRender:
    """Smoke test: GET /simulate/fleet renders the tariff/dispatch/SEG overlay section."""

    def test_fleet_form_shows_tariff_dispatch_seg_section(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/fleet returns 200 with the fleet-wide overlay section rendered.

        Checks stable form-wiring markers:
        - The tariff type selector is present (name="tariff_type").
        - The dispatch strategy selector is present (name="dispatch_strategy_type").
        - The SEG preset dropdown and custom rate input are present.
        - All six UK supplier SEG preset keys appear as option text (parity with
          test_home_form_shows_seg_section).

        Heading-prose strings are intentionally NOT asserted — form-field name
        attributes and preset-key option text are the meaningful contract checks
        without pinning cosmetic copy.
        """
        resp = client.get("/simulate/fleet")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Tariff section — wiring contract
        assert 'name="tariff_type"' in html, "tariff_type select missing"

        # Dispatch strategy section — wiring contract
        assert 'name="dispatch_strategy_type"' in html, "dispatch_strategy_type select missing"

        # SEG section — wiring contract
        assert 'name="seg_preset"' in html, "seg_preset select missing"
        assert 'name="seg_rate_pence_per_kwh"' in html, "seg_rate_pence_per_kwh input missing"

        # All six UK supplier preset keys (parity with test_home_form_shows_seg_section)
        for preset_key in ("Octopus", "British Gas", "EDF", "E.ON", "Scottish Power", "OVO"):
            assert preset_key in html, f"SEG preset '{preset_key}' missing from fleet form HTML"
