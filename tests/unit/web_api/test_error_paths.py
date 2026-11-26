# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the error handling every /api endpoint shares: malformed and non-object JSON bodies, a refusal answered 400 and a defect 500, and HTTP methods a route does not allow."""

from collections.abc import Callable
from functools import partial
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import Interval, as_whole_number
from solar_challenge.web import api
from solar_challenge.web.api import SWEEP_MAX_STEPS
from solar_challenge.web.builder_form import scenario_from_builder_form
from solar_challenge.web.fleet_config import sample_distribution
from solar_challenge.web.fleet_scenario import parse_fleet_form
from solar_challenge.web.simulation_params import parse_date_range, parse_home_config
from tests._api_routes import api_routes
from tests._error_records import error_records
from tests._raising import raising
from tests._fleet_form import valid_distribution_form


_API_ENDPOINTS_THAT_READ_NO_JSON_BODY = frozenset({"api.import_fleet_yaml"})


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
            for endpoint, method, path in api_routes({"POST", "PUT", "PATCH"})
            if endpoint not in _API_ENDPOINTS_THAT_READ_NO_JSON_BODY
        ],
    )
    def test_every_json_endpoint_answers_a_non_object_body_with_the_shared_400(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, method: str, path: str
    ) -> None:
        """The body is refused, naming its type, before any run lookup, save or job submission."""
        resp = client.open(path, method=method, json=[1])
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "Request body must be a JSON object, got list"}
        assert mock_job_manager.method_calls == []

    def test_no_stale_endpoint_is_listed_as_reading_no_json_body(self) -> None:
        """Every endpoint exempted from the shared 400 is still a POST, PUT or PATCH route of the api blueprint."""
        body_method_endpoints = {endpoint for endpoint, _, _ in api_routes({"POST", "PUT", "PATCH"})}
        assert _API_ENDPOINTS_THAT_READ_NO_JSON_BODY - body_method_endpoints == set()

    @pytest.mark.parametrize(
        ("data", "content_type"),
        [
            pytest.param(None, None, id="absent"),
            pytest.param("null", "application/json", id="json-null"),
        ],
    )
    def test_an_absent_or_null_body_is_refused_as_nonetype(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, data: str | None, content_type: str | None
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


_LONDN_HOME = {"pv_kw": 4.0, "location": "londn"}
_FLEET_FORM_WITH_A_BATTERY_DISPATCH = {
    **valid_distribution_form(),
    "battery": {"capacity_kwh": 5.0, "dispatch_strategy": {"type": "self_consumption"}},
}
_BUILDER_FORM_AT_ATLANTIS = {"name": "Atlantis", "n_homes": 2, "location_preset": "atlantis"}


@pytest.mark.parametrize(
    ("path", "body", "refuse"),
    [
        pytest.param(
            "/api/simulate/home", _LONDN_HOME, partial(parse_home_config, _LONDN_HOME), id="home-unknown-location"
        ),
        pytest.param(
            "/api/simulate/home",
            {"days": 7, "start": "2024-06-01"},
            partial(parse_date_range, {"days": 7, "start": "2024-06-01"}),
            id="home-days-with-start",
        ),
        pytest.param(
            "/api/fleet/preview-distribution",
            {"type": "bogus", "params": {}},
            partial(sample_distribution, "bogus", {}, 100),
            id="preview-unknown-type",
        ),
        pytest.param(
            "/api/simulate/sweep",
            {"steps": 1},
            partial(as_whole_number, 1, "steps", Interval(2, SWEEP_MAX_STEPS)),
            id="sweep-one-step",
        ),
        pytest.param(
            "/api/scenarios/preview-yaml",
            _BUILDER_FORM_AT_ATLANTIS,
            partial(scenario_from_builder_form, _BUILDER_FORM_AT_ATLANTIS),
            id="builder-unknown-location-preset",
        ),
        pytest.param(
            "/api/simulate/fleet-from-distribution",
            _FLEET_FORM_WITH_A_BATTERY_DISPATCH,
            partial(parse_fleet_form, _FLEET_FORM_WITH_A_BATTERY_DISPATCH),
            id="fleet-battery-dispatch-strategy",
        ),
    ],
)
def test_a_body_a_reader_refuses_is_answered_400_with_its_refusal_and_logs_nothing(
    client: FlaskClient,
    mock_job_manager: NonCallableMagicMock,
    caplog: pytest.LogCaptureFixture,
    path: str,
    body: dict[str, object],
    refuse: Callable[[], object],
) -> None:
    """Row R1: a reader's ConfigurationError is the blueprint's refusal, answered 400 with its text."""
    with pytest.raises(ConfigurationError) as refusal:
        refuse()

    resp = client.post(path, json=body)

    assert (resp.status_code, resp.get_json()) == (400, {"error": str(refusal.value)})
    assert error_records(caplog) == []
    assert mock_job_manager.method_calls == []


def test_a_value_error_that_is_not_a_configuration_error_is_answered_400_and_logged_as_a_probable_defect(
    client: FlaskClient,
    mock_job_manager: NonCallableMagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Row R2."""
    monkeypatch.setattr(api, "parse_home_config", raising(ValueError("probe")))

    resp = client.post("/api/simulate/home", json={"pv_kw": 4.0})

    assert (resp.status_code, resp.get_json()) == (400, {"error": "probe"})
    [record] = error_records(caplog)
    assert "ValueError" in record.getMessage()
    assert mock_job_manager.method_calls == []


@pytest.mark.parametrize(
    ("path", "body", "reader"),
    [
        pytest.param("/api/simulate/home", {"pv_kw": 4.0}, "parse_home_config", id="home"),
        pytest.param(
            "/api/simulate/fleet-from-distribution", valid_distribution_form(), "parse_fleet_form", id="fleet"
        ),
    ],
)
def test_a_type_error_is_no_refusal_and_is_answered_500_with_a_json_body(
    app: Flask,
    client: FlaskClient,
    mock_job_manager: NonCallableMagicMock,
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    body: dict[str, object],
    reader: str,
) -> None:
    """Row R3: anything but a ValueError is a defect, answered 500 with JSON, not the HTML error page."""
    app.config["PROPAGATE_EXCEPTIONS"] = False
    monkeypatch.setattr(api, reader, raising(TypeError("probe")))

    resp = client.post(path, json=body)

    assert resp.status_code == 500
    assert resp.mimetype == "application/json"
    assert resp.get_json() == {"error": "Internal server error"}
    assert mock_job_manager.method_calls == []
