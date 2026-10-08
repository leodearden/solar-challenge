# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests of the /simulate/home and /simulate/fleet pages, which web/routes.py serves: the forms that start a home and a fleet simulation.

The optional-settings tests identify a control by its Alpine binding, the form state the page's script builds its
request from: heat pump, tariff, dispatch, PV age and SEG on /simulate/home, and the fleet-wide tariff, dispatch and
SEG on /simulate/fleet.
"""

import re
from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.seg import SEG_PRESETS
from tests._html_page import (
    counts_of,
    doctype,
    element_count,
    element_ids,
    headings,
    texts,
)
from tests._web_app import build_test_app


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create a Flask test client."""
    return app.test_client()


def _options_per_seg_preset_key(page: str) -> dict[str, int]:
    """How many options of *page* offer each SEG preset by its key, the value the server resolves a preset from.

    Fails when SEG_PRESETS is empty: the empty result would equal the empty expectation, whatever the page offers.
    """
    assert SEG_PRESETS, "SEG_PRESETS is empty, so there is no preset option to look for"
    return {key: element_count(page, "option", {"value": key}) for key in SEG_PRESETS}


class TestSimulateHomeRoute:
    """Tests for the GET /simulate/home route."""

    def test_simulate_home_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/home returns HTTP 200."""
        response = client.get("/simulate/home")
        assert response.status_code == 200

    def test_simulate_home_page_contains_form(self, client: FlaskClient) -> None:
        """GET /simulate/home renders the PV capacity, battery capacity and annual consumption inputs, and one submit button."""
        response = client.get("/simulate/home")
        page = response.get_data(as_text=True)
        assert {"pv_kw", "battery_kwh", "consumption_kwh"} <= element_ids(page)
        assert element_count(page, "button", {"type": "submit"}) == 1

    def test_simulate_home_page_contains_tabs(self, client: FlaskClient) -> None:
        """GET /simulate/home renders one tab list and, per tab, one panel shown while it is active."""
        response = client.get("/simulate/home")
        page = response.get_data(as_text=True)
        assert element_count(page, "nav", {"role": "tablist"}) == 1
        tab_ids = ("pv", "battery", "load", "heat_pump", "tariff", "location", "period")
        panels_per_tab = {
            tab_id: element_count(
                page, "div", {"role": "tabpanel", "x-show": f"activeTab === '{tab_id}'"}
            )
            for tab_id in tab_ids
        }
        assert panels_per_tab == dict.fromkeys(tab_ids, 1)


class TestSimulateHomePageRendering:
    """Tests for the /simulate/home page rendering quality."""

    def test_simulate_home_no_raw_js_in_body(self, client: FlaskClient) -> None:
        """Test /simulate/home does not expose raw JavaScript in the page body.

        JavaScript should be contained within <script> tags, not visible
        as text content in the rendered HTML body.
        """
        response = client.get("/simulate/home")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # The page uses Alpine.js. Check that raw JS function bodies are not
        # leaked outside of <script> tags. We do this by checking that certain
        # JS-only patterns don't appear outside <script> blocks.

        # Remove all script blocks first, then check remaining HTML body
        # Remove all script tag contents
        body_without_scripts = re.sub(
            r"<script[^>]*>.*?</script>",
            "",
            html,
            flags=re.DOTALL,
        )

        # These are JS-specific patterns that should NOT appear in visible body text
        assert "function()" not in body_without_scripts, (
            "Raw 'function()' found outside <script> tags"
        )
        assert "async () =>" not in body_without_scripts, (
            "Raw arrow function found outside <script> tags"
        )
        assert "addEventListener" not in body_without_scripts, (
            "Raw 'addEventListener' found outside <script> tags"
        )

    def test_simulate_home_has_proper_html_structure(self, client: FlaskClient) -> None:
        """Test /simulate/home has proper HTML document structure."""
        response = client.get("/simulate/home")
        assert response.status_code == 200
        html = response.data.decode("utf-8")

        # Should have a proper HTML document
        assert doctype(html) == "html"
        assert element_count(html, "head") == 1
        assert element_count(html, "body") == 1


class TestHomeFormRender:
    """Smoke test: GET /simulate/home renders the heat pump, tariff, dispatch, PV-age and SEG controls."""

    def test_home_form_shows_heat_pump_tariff_and_dispatch(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/home renders one select each for the heat pump type, the tariff type and the dispatch strategy."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "formData.heat_pump_type"}) == 1
        assert element_count(page, "select", {"x-model": "formData.tariff_type"}) == 1
        assert element_count(page, "select", {"x-model": "formData.dispatch_strategy_type"}) == 1

    def test_home_form_shows_pv_age_inputs(self, client: FlaskClient) -> None:
        """GET /simulate/home renders one number input each for the PV system's age and its yearly degradation rate."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert element_count(page, "input", {"type": "number", "x-model.number": "formData.system_age_years"}) == 1
        assert element_count(page, "input", {"type": "number", "x-model.number": "formData.degradation_rate_per_year"}) == 1

    def test_home_form_shows_seg_section(self, client: FlaskClient) -> None:
        """GET /simulate/home renders the SEG preset select, one option per SEG preset key, and the custom rate number input."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "formData.seg_preset"}) == 1
        assert _options_per_seg_preset_key(page) == dict.fromkeys(SEG_PRESETS, 1)
        assert element_count(page, "input", {"type": "number", "x-model.number": "formData.seg_rate_pence_per_kwh"}) == 1


class TestFleetConfigRoute:
    """Tests for the GET /simulate/fleet route."""

    def test_fleet_page_returns_200(self, client: FlaskClient) -> None:
        """Test GET /simulate/fleet returns HTTP 200."""
        response = client.get("/simulate/fleet")
        assert response.status_code == 200

    def test_fleet_page_contains_distribution_editors(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders three distribution editors, one per card, and the n_homes input."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "dist.type"}) == 3
        assert "n_homes" in element_ids(page)

    def test_fleet_page_contains_pv_battery_load_sections(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders one heading per distribution card: PV Capacity, Battery Capacity and Annual Consumption."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        subjects = ("PV Capacity", "Battery Capacity", "Annual Consumption")
        assert counts_of(headings(page), subjects) == dict.fromkeys(subjects, 1)

    def test_fleet_page_contains_action_buttons(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders the Import YAML and Export YAML controls and one button that runs the fleet simulation."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        page_texts = texts(page)
        assert page_texts.count("Import YAML") == 1
        assert element_count(page, "input", {"type": "file", "@change": "importYaml($event)"}) == 1
        assert page_texts.count("Export YAML") == 1
        assert element_count(page, "button", {"@click": "exportYaml()"}) == 1
        assert element_count(page, "button", {"@click": "submitFleet()"}) == 1

    def test_fleet_page_has_correct_page_identifier(self, client: FlaskClient) -> None:
        """GET /simulate/fleet renders the sidebar with the simulate-fleet page identifier, so the Simulate group's links show on this page."""
        response = client.get("/simulate/fleet")
        page = response.get_data(as_text=True)
        simulate_links_condition = (
            "(openGroup === 'simulate' || 'simulate-fleet'.startsWith('simulate')) && sidebarOpen"
        )
        assert element_count(page, "div", {"x-show": simulate_links_condition}) == 1


class TestFleetFormRender:
    """Smoke test: GET /simulate/fleet renders the tariff/dispatch/SEG overlay section."""

    def test_fleet_form_shows_tariff_dispatch_seg_section(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/fleet renders the fleet-wide tariff, dispatch and SEG controls.

        One select each for the tariff type, the dispatch strategy and the SEG preset, one option per
        SEG preset key, and the custom SEG rate number input.
        """
        resp = client.get("/simulate/fleet")
        assert resp.status_code == 200
        page = resp.get_data(as_text=True)
        assert element_count(page, "select", {"x-model": "tariffType"}) == 1
        assert element_count(page, "select", {"x-model": "dispatchStrategyType"}) == 1
        assert element_count(page, "select", {"x-model": "segPreset"}) == 1
        assert _options_per_seg_preset_key(page) == dict.fromkeys(SEG_PRESETS, 1)
        assert element_count(page, "input", {"type": "number", "x-model.number": "segRatePencePerKwh"}) == 1
