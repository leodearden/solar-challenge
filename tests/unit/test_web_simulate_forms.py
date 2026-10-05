# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smoke tests that the simulate forms render their optional-settings controls: heat pump, tariff, dispatch,
PV age and SEG on /simulate/home, and the fleet-wide tariff, dispatch and SEG on /simulate/fleet.

A control is identified by its Alpine binding, the form state the page's script builds its request from.
"""

from pathlib import Path

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.seg import SEG_PRESETS
from tests._html_page import element_count
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
    """How many options of *page* offer each SEG preset by its key, the value the server resolves a preset from."""
    return {key: element_count(page, "option", {"value": key}) for key in SEG_PRESETS}


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
