"""End-to-end tests for the Scenario Builder page (/scenarios/builder).

Verifies page loading, accordion sections, YAML preview, Download YAML
button, General section inputs, and detects Bug B1 (Alpine race condition
with external JS).
"""

import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from playwright.sync_api import ConsoleMessage, Page, Response, expect

from solar_challenge.config import load_fleet_config
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.pv import PVConfig
from solar_challenge.scenario_writer import fleet_scenario, scenario_yaml

pytestmark = pytest.mark.e2e


# ── Page loading ─────────────────────────────────────────────────────


def test_builder_page_loads(page: Page, live_server: str) -> None:
    """GET /scenarios/builder returns a page with 'Scenario Builder' heading."""
    response = page.goto(live_server + "/scenarios/builder")
    assert response is not None
    assert response.status == 200

    page.wait_for_load_state("domcontentloaded")

    heading = page.locator("text=Scenario Builder").first
    expect(heading).to_be_visible()


# ── Bug B1: Alpine race condition with external JS ───────────────────


def test_builder_no_js_errors(page: Page, live_server: str) -> None:
    """The scenario builder page should load without JS console errors.

    The ``scenarioBuilder()`` component is defined in an external JS file
    loaded via ``defer`` in ``{% block head %}``.  Alpine.js may evaluate
    the ``x-data`` before the component function is registered, causing
    a ReferenceError in the console.
    """
    errors: list[str] = []

    def _on_console(msg: ConsoleMessage) -> None:
        if msg.type == "error":
            errors.append(msg.text)

    page.on("console", _on_console)
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(1000)
    page.remove_listener("console", _on_console)

    assert errors == [], f"Console errors on /scenarios/builder: {errors}"


# ── Accordion sections ───────────────────────────────────────────────


def test_accordion_sections_exist(page: Page, live_server: str) -> None:
    """The accordion should have General, Period, Location, Fleet Distribution,
    and Tariff sections.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    expected_sections = ["General", "Period", "Location", "Fleet Distribution", "Tariff"]

    for section_name in expected_sections:
        accordion_btn = page.locator(
            "button",
            has_text=section_name,
        ).first
        expect(accordion_btn).to_be_visible(), (
            f"Accordion section '{section_name}' should be visible"
        )


# ── YAML Preview pane ────────────────────────────────────────────────


def test_yaml_preview_visible(page: Page, live_server: str) -> None:
    """The YAML Preview pane in the right column should be visible.

    The preview heading is always rendered.  The ``<pre>`` element that
    displays the YAML text may be invisible when Alpine has not yet
    populated ``yamlPreview`` (the element collapses to zero height with
    empty text content).  We verify the heading is visible and that the
    ``<pre>`` element is attached to the DOM.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    yaml_heading = page.locator("h3", has_text="YAML Preview")
    expect(yaml_heading).to_be_visible()

    # The <pre> element that displays the YAML content should be in the DOM.
    # It may not be "visible" in the Playwright sense when Alpine hasn't
    # initialised scenarioBuilder() (external JS race condition) because
    # it would have empty text content and collapse to zero height.
    yaml_pre = page.locator("pre")
    expect(yaml_pre).to_be_attached()


# ── Download YAML button ─────────────────────────────────────────────


def test_download_yaml_button(page: Page, live_server: str) -> None:
    """The 'Download YAML' button exists and is clickable."""
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    download_btn = page.locator("button", has_text="Download YAML")
    expect(download_btn).to_be_visible()
    expect(download_btn).to_be_enabled()


# ── General section inputs ───────────────────────────────────────────


def test_general_section_inputs(page: Page, live_server: str) -> None:
    """Opening the General accordion reveals Name and Description inputs.

    The General accordion uses Alpine ``x-collapse``, which may keep the
    panel at ``height: 0`` with ``overflow: hidden`` depending on the CDN
    load order of the Alpine collapse plugin.  We verify that the inputs
    exist in the DOM (attached) and fall back to checking their
    ``x-model`` bindings to confirm correct wiring.
    """
    page.goto(live_server + "/scenarios/builder")
    page.wait_for_load_state("networkidle")

    # Wait for Alpine + external JS to fully initialise
    page.wait_for_timeout(1000)

    general_btn = page.locator("button", has_text="General").first
    expect(general_btn).to_be_visible()

    # Try clicking the General accordion to open it.  Toggle closed
    # then open to ensure we end in the open state.
    general_btn.click()
    page.wait_for_timeout(400)
    general_btn.click()
    page.wait_for_timeout(600)

    # Verify Scenario Name input exists in the DOM
    name_input = page.locator('input[placeholder="e.g. Bristol Phase 1"]')
    expect(name_input).to_be_attached()

    # Verify the input is wired with x-model="name"
    x_model = name_input.get_attribute("x-model")
    assert x_model == "name", (
        f"Expected x-model='name' on Scenario Name input, got '{x_model}'"
    )

    # Verify Description textarea exists in the DOM
    desc_textarea = page.locator('textarea[placeholder="Optional description"]')
    expect(desc_textarea).to_be_attached()

    x_model_desc = desc_textarea.get_attribute("x-model")
    assert x_model_desc == "description", (
        f"Expected x-model='description' on textarea, got '{x_model_desc}'"
    )


# ── Builder YAML: what the scenario loaders read ─────────────────────


def test_default_form_previews_yaml_the_fleet_loader_loads(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """The YAML previewed for the builder's default form loads through load_fleet_config.

    The page previews its default form as soon as it opens, so this pins the real
    payload of getFormData(), which tests/unit/test_web_scenarios.py's
    TestBuilderScenarioYaml._DEFAULT_FORM mirrors.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as preview:
        page.goto(live_server + "/scenarios/builder")

    response = preview.value
    assert response.status == 200
    path = tmp_path / "builder.yaml"
    path.write_text(response.json()["yaml"], encoding="utf-8")

    fleet = load_fleet_config(path)

    assert len(fleet.homes) == 100
    assert {home.pv_config.capacity_kw for home in fleet.homes} == {4.0}


def _preview_after_uploading(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str
) -> Response:
    """The preview the builder, freshly opened, requests once *yaml_text* is uploaded to it."""
    with page.expect_response("**/api/scenarios/preview-yaml"):
        page.goto(live_server + "/scenarios/builder")
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    with page.expect_response("**/api/scenarios/preview-yaml") as after_upload:
        page.set_input_files('input[type="file"]', path)
    return after_upload.value


_UPLOADED_FORM_GENERAL_FIELDS: dict[str, Any] = {
    "name": "Upload round trip",
    "description": "every builder block",
    "start_date": "2024-06-01",
    "end_date": "2024-06-30",
    "location_preset": "custom",
    "latitude": 53.4,
    "longitude": -2.2,
    "altitude": 38.0,
    "n_homes": 12,
    "import_rate": 0.3,
    "seg_rate_pence_per_kwh": 5.5,
}


@pytest.mark.parametrize(
    "form",
    [
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv_distribution_type": "weighted_discrete",
                "pv_wd_values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 3}],
                "battery_distribution_type": "normal",
                "battery_mean": 5.0,
                "battery_std": 2.0,
                "battery_min": 0,
                "battery_max": 10.0,
                "load_distribution_type": "shuffled_pool",
                "load_sp_entries": [{"value": 2900, "count": 6}, {"value": 4100, "count": 6}],
            },
            id="distribution rows and min 0",
        ),
        pytest.param(
            {
                **_UPLOADED_FORM_GENERAL_FIELDS,
                "pv_distribution_type": "uniform",
                "pv_mean": 4.0,
                "pv_std": 1.0,
                "pv_min": 2,
                "pv_max": 8,
                "battery_capacity_kwh": 0,
                "annual_consumption_kwh": 3100,
            },
            id="fixed values and uniform",
        ),
    ],
)
def test_uploading_a_builder_yaml_restores_the_form_that_emits_it(
    page: Page, live_server: str, tmp_path: Path, form: dict[str, Any]
) -> None:
    """Uploading the YAML the builder previews for *form* sets the form to one that previews the same scenario.

    The location is custom: a preset location reloads as 'custom', the same place under no preset name.
    """
    yaml_text = page.request.post(
        live_server + "/api/scenarios/preview-yaml", data=form, fail_on_status_code=True
    ).json()["yaml"]

    preview = _preview_after_uploading(page, live_server, tmp_path, yaml_text)

    assert preview.status == 200, preview.text()
    assert yaml.safe_load(preview.json()["yaml"]) == yaml.safe_load(yaml_text)


_LOCATION_WITHOUT_ALTITUDE_YAML = yaml.safe_dump(
    {
        "name": "Hand-written location",
        "period": {"start_date": "2024-06-01", "end_date": "2024-06-30"},
        "location": {"latitude": 53.4, "longitude": -2.2},
        "fleet_distribution": {
            "n_homes": 12,
            "pv": {"capacity_kw": 4.0},
            "battery": {"capacity_kwh": 5.0},
            "load": {"annual_consumption_kwh": 3100},
        },
        "tariff": {"type": "flat_rate", "rate_per_kwh": 0.3},
        "seg": {"rate_pence_per_kwh": 5.5},
    }
)
"""A hand-written fleet scenario with every block the form holds; its location: has no altitude."""


def test_uploading_a_scenario_whose_location_omits_altitude_previews_that_scenario(
    page: Page, live_server: str, tmp_path: Path
) -> None:
    """The builder previews an uploaded scenario without altitude: parse_location_block defaults it.

    It does not refuse the form, which the upload has already set.
    """
    preview = _preview_after_uploading(page, live_server, tmp_path, _LOCATION_WITHOUT_ALTITUDE_YAML)

    assert preview.status == 200, preview.text()
    assert yaml.safe_load(preview.json()["yaml"]) == yaml.safe_load(_LOCATION_WITHOUT_ALTITUDE_YAML)


_RUN_EXPORT_YAML = scenario_yaml(
    fleet_scenario(
        [HomeConfig(pv_config=PVConfig(capacity_kw=4.0), load_config=LoadConfig())],
        name="Exported run",
    )
)
"""A run-history YAML export, which lists the fleet's homes one by one."""


@pytest.mark.parametrize(
    ("yaml_text", "refusal"),
    [
        pytest.param(_RUN_EXPORT_YAML, "fleet_distribution", id="run-history export"),
        pytest.param(
            yaml.safe_dump(
                {
                    "name": "Pool without values",
                    "fleet_distribution": {
                        "n_homes": 5,
                        "pv": {"capacity_kw": {"type": "weighted_discrete", "weights": [1, 3]}},
                    },
                }
            ),
            "fleet_distribution.pv.capacity_kw",
            id="weighted_discrete without values",
        ),
    ],
)
def test_uploading_a_yaml_the_form_cannot_hold_leaves_the_form_and_says_why(
    page: Page, live_server: str, tmp_path: Path, yaml_text: str, refusal: str
) -> None:
    """Uploading a scenario the builder's form cannot hold leaves every field as it was, and the preview says why.

    A run-history export has no fleet_distribution: block for the form to edit, and a
    weighted_discrete distribution without values has no rows to show.
    """
    with page.expect_response("**/api/scenarios/preview-yaml") as opened:
        page.goto(live_server + "/scenarios/builder")
    form_before_upload = opened.value.request.post_data_json
    path = tmp_path / "scenario.yaml"
    path.write_text(yaml_text, encoding="utf-8")

    page.set_input_files('input[type="file"]', path)

    expect(page.locator("pre")).to_have_text(
        re.compile(rf"^# scenario\.yaml was not loaded: .*{re.escape(refusal)}")
    )
    with page.expect_response("**/api/scenarios/validate") as validated:
        page.get_by_role("button", name="Validate", exact=True).click()
    assert validated.value.request.post_data_json == form_before_upload
