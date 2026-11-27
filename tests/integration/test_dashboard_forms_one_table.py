# SPDX-License-Identifier: AGPL-3.0-or-later
"""The S18 integration gate: docs/prds/dashboard-limits-and-distribution-table.md §5 row G1.

Both fleet pages, the fleet page and the scenario builder, edit, post, import and bound every
distribution from one table, fleet_distribution.DISTRIBUTION_TYPES, and one limits value,
web/fleet_components.page_limits(), through the Flask test client of the real dashboard app.
Each check is stated across pages, and every expected value comes from those two or from the
refusing reader, never a literal copy.
"""

import json
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
from solar_challenge.number_fields import Interval
from solar_challenge.scenario_blocks import parse_tariff_config
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.fleet_components import FLEET_COMPONENTS, ComponentLimits, page_limits
from solar_challenge.web.form_choices import flat_rate_choice
from tests._alpine_component_arguments import component_arguments
from tests._builder_form import builder_page_starting_form
from tests._fleet_form import fleet_page_starting_form, start_of, start_wire
from tests._html_page import element_attributes, script_text_by_id
from tests._html_select_options import options_of_each
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


#: Where the builder validates its form, answering {valid, errors}.
_VALIDATE_PATH = "/api/scenarios/validate"


def _downloaded_yaml(response: TestResponse) -> str:
    """The scenario YAML text *response* downloads."""
    return response.get_data(as_text=True)


def _previewed_yaml(response: TestResponse) -> str:
    """The scenario YAML text of *response*'s {yaml} answer."""
    text: str = response.get_json()["yaml"]
    return text


@dataclass(frozen=True)
class _FleetPage:
    """A page that edits a fleet: its name, its path, the form it starts at, where it exports that form as scenario YAML and how its answer holds the text, and where it imports one."""

    name: str
    path: str
    starting_form: Callable[[], dict[str, Any]]
    export_path: str
    exported_yaml: Callable[[TestResponse], str]
    import_path: str

    def export(self, client: FlaskClient, form: Mapping[str, Any]) -> str:
        """The scenario YAML text this page exports for *form*, which it accepts."""
        response = client.post(self.export_path, json=form)
        assert response.status_code == 200, response.get_data(as_text=True)
        return self.exported_yaml(response)

    def import_yaml(self, client: FlaskClient, text: str) -> TestResponse:
        """This page's answer to importing the scenario YAML *text*."""
        return client.post(self.import_path, data=text, content_type="text/yaml")


_FLEET_PAGE = _FleetPage(
    name="fleet",
    path="/simulate/fleet",
    starting_form=fleet_page_starting_form,
    export_path="/api/fleet/export-yaml",
    exported_yaml=_downloaded_yaml,
    import_path="/api/fleet/import-yaml",
)
_BUILDER = _FleetPage(
    name="builder",
    path="/scenarios/builder",
    starting_form=partial(builder_page_starting_form, _BUILDER_SCENARIO_NAME),
    export_path="/api/scenarios/preview-yaml",
    exported_yaml=_previewed_yaml,
    import_path="/api/scenarios/import-yaml",
)

#: Both pages, each as a parameter named after it.
_PAGES = [pytest.param(page, id=page.name) for page in (_FLEET_PAGE, _BUILDER)]

#: Each component with each type its distribution editor offers: Fixed Value, then its editor types.
_EDITED = [
    pytest.param(component, editor_type, id=f"{component.key}-{editor_type.name}")
    for component in FLEET_COMPONENTS.values()
    for editor_type in (component.scalar_form, *component.editor_types)
]


def _with_component(form: Mapping[str, Any], component: ComponentLimits, spec: Any) -> dict[str, Any]:
    """*form* with *component*'s block posting *spec* for its field."""
    return {**form, component.key: {component.grammar_key: spec}}


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
    assert getattr(fleets[_FLEET_PAGE.name], component.key).draws[component.grammar_key] == start_of(
        component, editor_type
    )
    validated = client.post(_VALIDATE_PATH, json=forms[_BUILDER])
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


@pytest.mark.parametrize("component", [pytest.param(each, id=each.key) for each in FLEET_COMPONENTS.values()])
def test_both_pages_refuse_a_drawn_value_outside_its_components_range_with_one_message(
    client: FlaskClient, component: ComponentLimits
) -> None:
    """L2: a normal drawn far above a component's value_range is refused on both pages with one message, which names the range."""
    high = component.value_range.high
    far_above = {"type": "normal", "mean": 2 * high, "std": high / 100}

    exported = client.post(
        _FLEET_PAGE.export_path, json=_with_component(_FLEET_PAGE.starting_form(), component, far_above)
    )
    validated = client.post(_VALIDATE_PATH, json=_with_component(_BUILDER.starting_form(), component, far_above))

    assert exported.status_code == 400, exported.get_data(as_text=True)
    error = exported.get_json()["error"]
    assert validated.get_json()["errors"] == [error]
    assert error.startswith(f"{component.key}.{component.grammar_key} must be {component.value_range} for every home")


@pytest.mark.parametrize(("component", "editor_type"), _EDITED)
@pytest.mark.parametrize("page", _PAGES)
def test_an_export_imported_on_its_own_page_loads_every_setting_and_exports_the_same_scenario(
    client: FlaskClient, page: _FleetPage, component: ComponentLimits, editor_type: DistributionType
) -> None:
    """A page's export of a component's start spec of a type imports on that page with every setting and the spec posted, and exports the same scenario again."""
    wire = start_wire(component, editor_type)
    text = page.export(client, _with_component(page.starting_form(), component, wire))

    imported = page.import_yaml(client, text)

    assert imported.status_code == 200, imported.get_data(as_text=True)
    loaded = imported.get_json()
    assert loaded["not_loaded"] == []
    assert loaded["form"][component.key] == {component.grammar_key: wire}
    assert yaml.safe_load(page.export(client, loaded["form"])) == yaml.safe_load(text)


@pytest.mark.parametrize(
    ("exporting", "importing"),
    [
        pytest.param(_FLEET_PAGE, _BUILDER, id="fleet-to-builder"),
        pytest.param(_BUILDER, _FLEET_PAGE, id="builder-to-fleet"),
    ],
)
def test_each_pages_export_loads_on_the_other_page_with_the_same_component_blocks(
    client: FlaskClient, exporting: _FleetPage, importing: _FleetPage
) -> None:
    """A scenario one page exports from its starting form loads on the other with the same component blocks."""
    form = exporting.starting_form()

    imported = importing.import_yaml(client, exporting.export(client, form))

    assert imported.status_code == 200, imported.get_data(as_text=True)
    loaded = imported.get_json()["form"]
    assert {key: loaded[key] for key in FLEET_COMPONENTS} == {key: form[key] for key in FLEET_COMPONENTS}


#: The dashboard's form pages, each of which writes #page-limits.
_FORM_PAGE_PATHS = ("/simulate/home", _FLEET_PAGE.path, _BUILDER.path, "/scenarios/sweep")

#: What the dashboard's forms accept and start at, which every page check below expects.
_LIMITS = page_limits()


def _page(client: FlaskClient, path: str) -> str:
    """The HTML the dashboard renders at *path*."""
    response = client.get(path)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_data(as_text=True)


def test_every_form_page_writes_the_one_page_limits_value_into_its_page_limits_element(client: FlaskClient) -> None:
    """L1: the home, fleet, builder and sweep pages each write page_limits().as_json() as their #page-limits."""
    written = {path: json.loads(script_text_by_id(_page(client, path), "page-limits")) for path in _FORM_PAGE_PATHS}

    assert written == dict.fromkeys(_FORM_PAGE_PATHS, _LIMITS.as_json())


@pytest.mark.parametrize(
    ("path", "input_id", "limit"),
    [
        pytest.param(_FLEET_PAGE.path, "n_homes", _LIMITS.fleet_size, id="fleet-n_homes"),
        pytest.param(_BUILDER.path, "builder_n_homes", _LIMITS.fleet_size, id="builder-n_homes"),
        pytest.param(_BUILDER.path, "builder_seed", _LIMITS.seed, id="builder-seed"),
        pytest.param("/simulate/home", "pv_kw", _LIMITS.components["pv"].value_range, id="home-pv_kw"),
        pytest.param(
            "/simulate/home", "consumption_kwh", _LIMITS.components["load"].value_range, id="home-consumption_kwh"
        ),
        pytest.param("/scenarios/sweep", "sweep_base_days", _LIMITS.window_days, id="sweep-base_days"),
    ],
)
def test_every_input_a_page_limit_bounds_spans_that_limit(
    client: FlaskClient, path: str, input_id: str, limit: Interval
) -> None:
    """L1: the one input carrying *input_id* on *path* has the page limit's ends as its min and max."""
    (attributes,) = [each for each in element_attributes(_page(client, path), "input") if each.get("id") == input_id]

    assert (attributes.get("min"), attributes.get("max")) == (str(limit.low), str(limit.high))


def test_both_fleet_pages_offer_each_component_fixed_value_then_its_editor_types_titled_by_the_table(
    client: FlaskClient,
) -> None:
    """Each card's Distribution Type, on both fleet pages, offers Fixed Value then its component's editor types, each by its name and title in DISTRIBUTION_TYPES."""
    offered = {
        page.name: options_of_each(_page(client, page.path), {"x-model": "dist.type"}) for page in (_FLEET_PAGE, _BUILDER)
    }

    assert offered == dict.fromkeys(
        offered,
        [
            [("", component.scalar_form.title), *((each.name, each.title) for each in component.editor_types)]
            for component in FLEET_COMPONENTS.values()
        ],
    )


def test_both_fleet_pages_bound_each_fixed_value_by_its_components_value_range(client: FlaskClient) -> None:
    """L1: each card's Fixed Value input, on both fleet pages and in card order, spans its component's value_range."""
    bounds = {
        page.name: [
            (attributes.get("min"), attributes.get("max"))
            for attributes in element_attributes(_page(client, page.path), "input")
            if attributes.get("x-model.number") == "dist.fixed"
        ]
        for page in (_FLEET_PAGE, _BUILDER)
    }

    assert bounds == dict.fromkeys(
        bounds,
        [(str(component.value_range.low), str(component.value_range.high)) for component in FLEET_COMPONENTS.values()],
    )


def test_the_fleet_page_and_the_builder_start_their_flat_rate_at_flat_rate_start(client: FlaskClient) -> None:
    """V3: the flat-rate tariff the fleet page's script posts at its starts, and the builder's starting import rate, export one tariff at flat_rate_start."""
    flat_rate_type = flat_rate_choice("fleet page").type
    tariff_choices = component_arguments(_page(client, _FLEET_PAGE.path), "fleetSimulator")[0]
    (flat_rate,) = [choice for choice in tariff_choices if choice["type"] == flat_rate_type]
    posted_tariff = {"type": flat_rate_type, **{setting["key"]: setting["start"] for setting in flat_rate["settings"]}}

    documents = {
        _FLEET_PAGE.name: _FLEET_PAGE.export(client, {**_FLEET_PAGE.starting_form(), "tariff": posted_tariff}),
        _BUILDER.name: _BUILDER.export(client, _BUILDER.starting_form()),
    }

    assert {name: parse_tariff_config(yaml.safe_load(text)["tariff"]) for name, text in documents.items()} == dict.fromkeys(
        documents, TariffConfig.flat_rate(_LIMITS.flat_rate_start)
    )
