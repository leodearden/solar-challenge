# SPDX-License-Identifier: AGPL-3.0-or-later
"""The S18 integration gate: docs/prds/dashboard-limits-and-distribution-table.md §5 row G1.

Both fleet pages, the fleet page and the scenario builder, edit, post, import and bound every
distribution from one table, fleet_distribution.DISTRIBUTION_TYPES, and one limits value,
web/fleet_components.page_limits(), through the Flask test client of the real dashboard app.
Each check is stated across pages, and every expected value comes from those two or from the
refusing reader, never a literal copy.
"""

from collections.abc import Callable, Mapping
from contextlib import ExitStack
from dataclasses import dataclass
from functools import partial
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")
import yaml
from flask.testing import FlaskClient
from werkzeug.test import TestResponse

from solar_challenge.fleet_distribution import DistributionType, parse_fleet_distribution_config
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits
from tests._builder_form import builder_page_starting_form
from tests._fleet_form import fleet_page_starting_form, start_wire
from tests._web_app import app_builder

#: The scenario name a user types on the builder before Validate or Save.
_BUILDER_SCENARIO_NAME = "One table"


@pytest.fixture
def client(tmp_path: Path, closes_at_teardown: ExitStack) -> FlaskClient:
    """A client of the real dashboard app, which answers a defect as a production app does rather than raising it into the client."""
    app = app_builder(closes_at_teardown)(tmp_path / "dashboard")
    app.config["PROPAGATE_EXCEPTIONS"] = False
    return app.test_client()


def _export_on_the_fleet_page(client: FlaskClient, form: Mapping[str, Any]) -> str:
    """The YAML text POST /api/fleet/export-yaml downloads for the fleet page's *form*."""
    response = client.post("/api/fleet/export-yaml", json=form)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_data(as_text=True)


def _preview_on_the_builder(client: FlaskClient, form: Mapping[str, Any]) -> str:
    """The YAML text POST /api/scenarios/preview-yaml answers for the builder's *form*."""
    response = client.post("/api/scenarios/preview-yaml", json=form)
    assert response.status_code == 200, response.get_data(as_text=True)
    text: str = response.get_json()["yaml"]
    return text


@dataclass(frozen=True)
class _FleetPage:
    """A page that edits a fleet: its name, its path, the form it starts at, how it exports that form as scenario YAML, and where it imports one."""

    name: str
    path: str
    starting_form: Callable[[], dict[str, Any]]
    export: Callable[[FlaskClient, Mapping[str, Any]], str]
    import_path: str

    def import_yaml(self, client: FlaskClient, text: str) -> TestResponse:
        """This page's answer to importing the scenario YAML *text*."""
        return client.post(self.import_path, data=text, content_type="text/yaml")


_FLEET_PAGE = _FleetPage(
    name="fleet",
    path="/simulate/fleet",
    starting_form=fleet_page_starting_form,
    export=_export_on_the_fleet_page,
    import_path="/api/fleet/import-yaml",
)
_BUILDER = _FleetPage(
    name="builder",
    path="/scenarios/builder",
    starting_form=partial(builder_page_starting_form, _BUILDER_SCENARIO_NAME),
    export=_preview_on_the_builder,
    import_path="/api/scenarios/import-yaml",
)

#: Each component with each type its distribution editor offers: Fixed Value, then its editor types.
_EDITED = [
    pytest.param(component, editor_type, id=f"{component.key}-{editor_type.name}")
    for component in FLEET_COMPONENTS.values()
    for editor_type in (component.scalar_form, *component.editor_types)
]


def _with_component(form: Mapping[str, Any], component: ComponentLimits, spec: Any) -> dict[str, Any]:
    """*form* with *component*'s block posting *spec* for its field."""
    return {**form, component.key: {component.grammar_key: spec}}


def _start_of(component: ComponentLimits, editor_type: DistributionType) -> object:
    """The spec *component*'s editor starts at for *editor_type*: its start's Fixed Value for the scalar form, else its start spec of that type."""
    if editor_type.is_scalar_form:
        return component.start.fixed
    return component.start.specs[component.editor_types.index(editor_type)]


@pytest.mark.parametrize(("component", "editor_type"), _EDITED)
def test_the_start_spec_of_each_type_posted_by_either_page_reads_as_one_fleet(
    client: FlaskClient, component: ComponentLimits, editor_type: DistributionType
) -> None:
    """E1: each page posting a component's start spec of a type exports one fleet, which draws that spec, and the builder validates it."""
    wire = start_wire(component, editor_type)
    forms = {page: _with_component(page.starting_form(), component, wire) for page in (_FLEET_PAGE, _BUILDER)}

    fleets = {
        page.name: parse_fleet_distribution_config(yaml.safe_load(page.export(client, form))["fleet_distribution"])
        for page, form in forms.items()
    }

    assert fleets[_FLEET_PAGE.name] == fleets[_BUILDER.name]
    assert getattr(fleets[_FLEET_PAGE.name], component.key).draws[component.grammar_key] == _start_of(
        component, editor_type
    )
    validated = client.post("/api/scenarios/validate", json=forms[_BUILDER])
    assert validated.get_json() == {"valid": True, "errors": []}
