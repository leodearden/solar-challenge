# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the error handling every /api endpoint shares: malformed and non-object JSON bodies, refusals besides the one per route the request boundary's gate sends, and HTTP methods a route does not allow.

The gate, tests/integration/test_request_boundary.py, holds every POST route's answer to a refusal, to a ValueError that is no refusal and to a defect.
"""

from collections.abc import Callable
from functools import partial
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.errors import ConfigurationError
from solar_challenge.web.fleet_scenario import parse_fleet_form
from solar_challenge.web.simulation_params import parse_date_range
from solar_challenge.web.sweep_request import read_sweep_request
from tests._api_routes import api_routes
from tests._error_records import error_records
from tests._fleet_form import valid_distribution_form


_API_ENDPOINTS_THAT_READ_NO_JSON_BODY = frozenset({"api.import_fleet_yaml", "api.scenarios_import_yaml"})


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


_FLEET_FORM_WITH_A_BATTERY_DISPATCH = {
    **valid_distribution_form(),
    "battery": {"capacity_kwh": 5.0, "dispatch_strategy": {"type": "self_consumption"}},
}


@pytest.mark.parametrize(
    ("path", "body", "refuse"),
    [
        pytest.param(
            "/api/simulate/home",
            {"days": 7, "start": "2024-06-01"},
            partial(parse_date_range, {"days": 7, "start": "2024-06-01"}),
            id="home-days-with-start",
        ),
        pytest.param(
            "/api/simulate/sweep",
            {"steps": 1},
            partial(read_sweep_request, {"steps": 1}),
            id="sweep-one-step",
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
    """A route answers each of its readers' refusals 400 with its text, not only the one the gate's row R1 sends it."""
    with pytest.raises(ConfigurationError) as refusal:
        refuse()

    resp = client.post(path, json=body)

    assert (resp.status_code, resp.get_json()) == (400, {"error": str(refusal.value)})
    assert error_records(caplog) == []
    assert mock_job_manager.method_calls == []
