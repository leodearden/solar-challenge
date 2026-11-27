# SPDX-License-Identifier: AGPL-3.0-or-later
"""The request boundary's integration gate: docs/prds/web-request-boundary.md §6 rows L5, R1, R2 and R3, and the presence rule, across the CLI and every /api POST route.

Row L5 holds the CLI and the web to one location grammar and one message. Rows R1, R2 and
R3 run over every POST route of the api blueprint's url_map, so a route added later fails
until it is tabled. Every expected refusal text is the reader's own, computed by calling the
reader, never a literal copy.
"""

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient
from typer.testing import CliRunner

from solar_challenge.cli.main import app as cli_app
from solar_challenge.errors import ConfigurationError
from solar_challenge.web import api
from solar_challenge.web.builder_form import builder_form_from_yaml, scenario_from_builder_form
from solar_challenge.web.fleet_scenario import fleet_form_from_yaml, parse_fleet_form, scenario_from_fleet_form
from solar_challenge.web.request_boundary import read_string, require_json_object
from solar_challenge.web.simulation_params import parse_home_config
from solar_challenge.web.sweep_request import read_sweep_request
from tests._api_routes import ApiRoute, api_routes
from tests._cli_stderr_text import stderr_text
from tests._config_preset_rows import saved_preset_names
from tests._error_records import error_records
from tests._fleet_form import valid_distribution_form
from tests._job_manager_double import autospecced_job_manager
from tests._raising import raising
from tests._web_app import app_builder, database_of


@pytest.fixture
def job_manager() -> NonCallableMagicMock:
    """The dashboard's JobManager, autospecced, whose submissions answer a job and run id each."""
    job_manager = autospecced_job_manager()
    job_manager.submit_home_job.return_value = ("job-home", "run-home")
    job_manager.submit_fleet_job.return_value = ("job-fleet", "run-fleet")
    return job_manager


@pytest.fixture
def client(tmp_path: Path, closes_at_teardown: ExitStack, job_manager: NonCallableMagicMock) -> FlaskClient:
    """A client of the real dashboard app over *job_manager*, which answers a defect as a production app does rather than raising it into the client."""
    app = app_builder(closes_at_teardown)(tmp_path / "dashboard", jobs=lambda storage: job_manager)
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app.test_client()


@pytest.mark.parametrize(
    "text",
    [
        pytest.param("londn", id="misspelt-preset"),
        pytest.param("51.5;-0.1", id="semicolon"),
        pytest.param("51.5,-0.1,x", id="altitude-not-a-number"),
        pytest.param("95,0", id="latitude-out-of-range"),
    ],
)
def test_the_cli_and_the_web_refuse_a_location_string_with_one_message(
    client: FlaskClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, text: str
) -> None:
    """Row L5: `home run --location` and POST /api/simulate/home read a location string with one grammar, and refuse it with one message."""
    monkeypatch.chdir(tmp_path)

    web = client.post("/api/simulate/home", json={"location": text})
    result = CliRunner().invoke(cli_app, ["home", "run", "--location", text], catch_exceptions=False)

    assert web.status_code == 400
    assert (result.exit_code, stderr_text(result)) == (1, f"Configuration error: {web.get_json()['error']}")


@dataclass(frozen=True)
class _RouteProbe:
    """How the gate reaches one POST route of the api blueprint.

    *refused* and *reaching* are the test client's keyword arguments of a request the route's
    reader refuses and of one that reaches that reader. *refusal* is the reader's call that
    raises the ConfigurationError the route answers *refused* with. *reader* is the name in
    solar_challenge.web.api of a reader the route calls, which the defect probes replace.
    """

    refused: Mapping[str, Any]
    refusal: Callable[[], object]
    reader: str
    reaching: Mapping[str, Any]


_HOME_AT_LONDN = {"location": "londn"}
_NAME_NOT_A_STRING = 5
_FLEET_FORM_AT_LONDN = {**valid_distribution_form(), "location": "londn"}
_UNREADABLE_YAML = "a: ["
_NOT_AN_OBJECT = [1]
_BUILDER_FORM_AT_ATLANTIS = {"location_preset": "atlantis"}
_SCENARIO_CONFIG_NOT_AN_OBJECT = [1, 2]
_A_MODE_NO_SWEEP_HAS = {"mode": "log"}

_ROUTE_PROBES: Mapping[str, _RouteProbe] = {
    "api.simulate_home_api": _RouteProbe(
        refused={"json": _HOME_AT_LONDN},
        refusal=partial(parse_home_config, _HOME_AT_LONDN),
        reader="parse_home_config",
        reaching={"json": {}},
    ),
    "api.simulate_fleet_api": _RouteProbe(
        refused={"json": {"homes": [_HOME_AT_LONDN]}},
        refusal=partial(parse_home_config, _HOME_AT_LONDN),
        reader="parse_home_config",
        reaching={"json": {"homes": [{}]}},
    ),
    "api.save_preset": _RouteProbe(
        refused={"json": {"name": _NAME_NOT_A_STRING}},
        refusal=partial(read_string, _NAME_NOT_A_STRING, "name"),
        reader="read_string",
        reaching={"json": {"name": "x"}},
    ),
    "api.preview_distribution": _RouteProbe(
        refused={"json": _FLEET_FORM_AT_LONDN},
        refusal=partial(parse_fleet_form, _FLEET_FORM_AT_LONDN),
        reader="parse_fleet_form",
        reaching={"json": {}},
    ),
    "api.simulate_fleet_from_distribution": _RouteProbe(
        refused={"json": _FLEET_FORM_AT_LONDN},
        refusal=partial(parse_fleet_form, _FLEET_FORM_AT_LONDN),
        reader="parse_fleet_form",
        reaching={"json": {}},
    ),
    "api.export_fleet_yaml": _RouteProbe(
        refused={"json": _FLEET_FORM_AT_LONDN},
        refusal=partial(scenario_from_fleet_form, _FLEET_FORM_AT_LONDN),
        reader="scenario_from_fleet_form",
        reaching={"json": {}},
    ),
    "api.import_fleet_yaml": _RouteProbe(
        refused={"data": _UNREADABLE_YAML, "content_type": "text/yaml"},
        refusal=partial(fleet_form_from_yaml, _UNREADABLE_YAML),
        reader="fleet_form_from_yaml",
        reaching={"data": "a: 1", "content_type": "text/yaml"},
    ),
    "api.scenarios_import_yaml": _RouteProbe(
        refused={"data": _UNREADABLE_YAML, "content_type": "text/yaml"},
        refusal=partial(builder_form_from_yaml, _UNREADABLE_YAML),
        reader="builder_form_from_yaml",
        reaching={"data": "a: 1", "content_type": "text/yaml"},
    ),
    "api.simulate_sweep": _RouteProbe(
        refused={"json": {"base_config": _NOT_AN_OBJECT}},
        refusal=partial(require_json_object, _NOT_AN_OBJECT, "base_config"),
        reader="parse_home_config",
        reaching={"json": {}},
    ),
    "api.simulate_sweep_points": _RouteProbe(
        refused={"json": _A_MODE_NO_SWEEP_HAS},
        refusal=partial(read_sweep_request, _A_MODE_NO_SWEEP_HAS),
        reader="read_sweep_request",
        reaching={"json": {}},
    ),
    "api.scenarios_preview_yaml": _RouteProbe(
        refused={"json": _BUILDER_FORM_AT_ATLANTIS},
        refusal=partial(scenario_from_builder_form, _BUILDER_FORM_AT_ATLANTIS),
        reader="scenario_from_builder_form",
        reaching={"json": {}},
    ),
    "api.scenarios_validate_scenario": _RouteProbe(
        refused={"json": _NOT_AN_OBJECT},
        refusal=partial(require_json_object, _NOT_AN_OBJECT, "Request body"),
        reader="builder_form_errors",
        reaching={"json": {}},
    ),
    "api.scenarios_save_scenario": _RouteProbe(
        refused={"json": {"name": "x", "config": _SCENARIO_CONFIG_NOT_AN_OBJECT}},
        refusal=partial(require_json_object, _SCENARIO_CONFIG_NOT_AN_OBJECT, "config"),
        reader="read_string",
        reaching={"json": {"name": "x"}},
    ),
}

_POST_ROUTES = api_routes({"POST"})


def _probe_of(route: ApiRoute) -> _RouteProbe:
    """The row of _ROUTE_PROBES for *route*; the test fails, naming the route, when it has none."""
    probe = _ROUTE_PROBES.get(route.endpoint)
    if probe is None:
        pytest.fail(
            f"{route.endpoint}, at POST {route.path}, has no row in _ROUTE_PROBES: every POST route of api_bp "
            "needs one naming a request its reader refuses and a reader it calls",
            pytrace=False,
        )
    return probe


def _saved_presets(client: FlaskClient) -> object:
    """The home presets the dashboard lists and the name of each preset its database holds, so a test can show that a request saved none.

    The saved presets are read from the database, not from the scenario preset menu, which
    lists the built-ins the builder's reader loads: a probe that replaces that reader would
    change the menu, not what is saved.
    """
    return client.get("/api/presets").get_json(), saved_preset_names(database_of(client.application))


def test_no_probe_names_a_route_api_bp_lacks() -> None:
    """Every row of _ROUTE_PROBES is still a POST route of the api blueprint."""
    assert set(_ROUTE_PROBES) - {route.endpoint for route in _POST_ROUTES} == set()


@pytest.mark.parametrize("route", _POST_ROUTES, ids=lambda route: route.endpoint)
def test_every_api_post_route_answers_its_readers_refusal_400_and_logs_nothing(
    client: FlaskClient, job_manager: NonCallableMagicMock, caplog: pytest.LogCaptureFixture, route: ApiRoute
) -> None:
    """Row R1: a request the route's reader refuses is answered 400 with the reader's ConfigurationError text, logs no ERROR, submits no job and saves no preset."""
    probe = _probe_of(route)
    with pytest.raises(ConfigurationError) as refusal:
        probe.refusal()
    saved = _saved_presets(client)

    resp = client.post(route.path, **probe.refused)

    assert (resp.status_code, resp.get_json()) == (400, {"error": str(refusal.value)})
    assert error_records(caplog) == []
    assert job_manager.method_calls == []
    assert _saved_presets(client) == saved


@pytest.mark.parametrize("route", _POST_ROUTES, ids=lambda route: route.endpoint)
def test_every_api_post_route_answers_a_value_error_that_is_no_refusal_400_and_logs_it_as_a_probable_defect(
    client: FlaskClient,
    job_manager: NonCallableMagicMock,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    route: ApiRoute,
) -> None:
    """Row R2: a reader's ValueError that is not a ConfigurationError is answered 400 with its text and logged once at ERROR naming its type, so no route answers a ValueError itself; no job is submitted and no preset saved."""
    probe = _probe_of(route)
    saved = _saved_presets(client)
    monkeypatch.setattr(api, probe.reader, raising(ValueError("probe")))

    resp = client.post(route.path, **probe.reaching)

    assert (resp.status_code, resp.get_json()) == (400, {"error": "probe"})
    [record] = error_records(caplog)
    assert "ValueError" in record.getMessage()
    assert job_manager.method_calls == []
    assert _saved_presets(client) == saved


@pytest.mark.parametrize("route", _POST_ROUTES, ids=lambda route: route.endpoint)
def test_every_api_post_route_answers_a_defect_500_with_a_json_body(
    client: FlaskClient, job_manager: NonCallableMagicMock, monkeypatch: pytest.MonkeyPatch, route: ApiRoute
) -> None:
    """Row R3: a reader's TypeError is a defect, answered 500 with JSON, so no route catches it as a refusal; no job is submitted and no preset saved."""
    probe = _probe_of(route)
    saved = _saved_presets(client)
    monkeypatch.setattr(api, probe.reader, raising(TypeError("probe")))

    resp = client.post(route.path, **probe.reaching)

    assert resp.status_code == 500
    assert resp.mimetype == "application/json"
    assert resp.get_json() == {"error": "Internal server error"}
    assert job_manager.method_calls == []
    assert _saved_presets(client) == saved


_FLEET_FORM_WITHOUT_A_SEED = {key: value for key, value in valid_distribution_form().items() if key != "seed"}


@pytest.mark.parametrize(
    ("path", "without", "field", "status"),
    [
        pytest.param("/api/simulate/home", {"pv_kw": 4.0, "days": 1}, "location", 201, id="home"),
        pytest.param("/api/simulate/fleet-from-distribution", _FLEET_FORM_WITHOUT_A_SEED, "seed", 201, id="fleet"),
        pytest.param("/api/scenarios/preview-yaml", {"n_homes": 2}, "location_preset", 200, id="builder"),
    ],
)
def test_a_recognised_field_sent_as_null_reads_as_not_sent(
    client: FlaskClient,
    job_manager: NonCallableMagicMock,
    path: str,
    without: Mapping[str, Any],
    field: str,
    status: int,
) -> None:
    """The presence rule: each form reader answers a body whose *field* is null as it answers the body without it, queueing the same job or giving the same scenario."""
    answers = []
    for body in ({**without, field: None}, without):
        resp = client.post(path, json=body)
        answers.append((resp.status_code, resp.get_json(), list(job_manager.method_calls)))
        job_manager.reset_mock()

    null_answer, absent_answer = answers
    assert null_answer == absent_answer
    assert null_answer[0] == status
