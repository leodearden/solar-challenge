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

from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    DistributionSpec,
    DistributionType,
    parse_fleet_distribution_config,
    write_distribution_spec,
)
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits
from tests._builder_form import builder_page_starting_form
from tests._fleet_form import fleet_page_starting_form, start_wire
from tests._repository_paths import SCENARIOS_DIR
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


def _bristol_phase1_yaml(**fleet_blocks: Mapping[str, Any]) -> str:
    """scenarios/bristol-phase1.yaml, which both pages load, with *fleet_blocks* in place of those of its fleet_distribution block."""
    document = yaml.safe_load((SCENARIOS_DIR / "bristol-phase1.yaml").read_text(encoding="utf-8"))
    document["fleet_distribution"] = {**document["fleet_distribution"], **fleet_blocks}
    return yaml.safe_dump(document, sort_keys=False)


def _grammar_reading(text: str, component: ComponentLimits) -> DistributionSpec:
    """The spec the scenario grammar reads for *component*'s field in the fleet_distribution block of the scenario YAML *text*."""
    fleet = parse_fleet_distribution_config(yaml.safe_load(text)["fleet_distribution"])
    spec: DistributionSpec = getattr(fleet, component.key).draws[component.grammar_key]
    return spec


@pytest.mark.parametrize(
    ("component", "spec"),
    [
        pytest.param(FLEET_COMPONENTS["pv"], {"type": "fixed", "value": 4}, id="pv-fixed"),
        pytest.param(
            FLEET_COMPONENTS["load"], {"type": "normal", "mean": 3400, "std": 800}, id="load-normal-without-clamps"
        ),
    ],
)
def test_both_pages_load_a_spec_their_editors_hold_as_its_canonical_spec(
    client: FlaskClient, component: ComponentLimits, spec: Mapping[str, Any]
) -> None:
    """E3: a spec an editor holds loads on both pages as the grammar's reading of it, written as the grammar writes it."""
    text = _bristol_phase1_yaml(**{component.key: {component.grammar_key: spec}})
    expected = {component.grammar_key: write_distribution_spec(_grammar_reading(text, component))}

    responses = {page.name: page.import_yaml(client, text) for page in (_FLEET_PAGE, _BUILDER)}

    assert {name: response.status_code for name, response in responses.items()} == dict.fromkeys(responses, 200)
    assert {name: response.get_json()["form"][component.key] for name, response in responses.items()} == dict.fromkeys(
        responses, expected
    )


def test_both_pages_refuse_a_spec_no_editor_holds_with_the_editors_own_refusal(client: FlaskClient) -> None:
    """E3: a battery capacity proportional to the PV's, which the battery editor does not hold, is refused on both pages with the editor's refusal."""
    battery = FLEET_COMPONENTS["battery"]
    proportional = {"type": "proportional_to", "source": "pv.capacity_kw", "multiplier": 2.0}
    text = _bristol_phase1_yaml(battery={battery.grammar_key: proportional})
    with pytest.raises(ConfigurationError) as refusal:
        battery.editor_spec(_grammar_reading(text, battery), f"fleet_distribution.{battery.key}.{battery.grammar_key}")

    responses = {page.name: page.import_yaml(client, text) for page in (_FLEET_PAGE, _BUILDER)}

    assert {name: (response.status_code, response.get_json()) for name, response in responses.items()} == dict.fromkeys(
        responses, (400, {"error": str(refusal.value)})
    )
