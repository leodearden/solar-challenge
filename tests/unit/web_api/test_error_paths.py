# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the error handling every /api endpoint shares: malformed and non-object JSON bodies, and HTTP methods a route does not allow."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.web.api import api_bp


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
