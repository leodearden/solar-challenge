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
        """GET /simulate/fleet returns 200 with the fleet-wide overlay section rendered.

        Checks stable form-wiring markers:
        - The tariff type selector is present (name="tariff_type").
        - The dispatch strategy selector is present (name="dispatch_strategy_type").
        - The SEG preset dropdown and custom rate input are present.
        - All six UK supplier SEG preset keys appear as option text (parity with
          test_home_form_shows_seg_section).

        Heading-prose strings are intentionally NOT asserted — form-field name
        attributes and preset-key option text are the meaningful contract checks
        without pinning cosmetic copy.
        """
        resp = client.get("/simulate/fleet")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Tariff section — wiring contract
        assert 'name="tariff_type"' in html, "tariff_type select missing"

        # Dispatch strategy section — wiring contract
        assert 'name="dispatch_strategy_type"' in html, "dispatch_strategy_type select missing"

        # SEG section — wiring contract
        assert 'name="seg_preset"' in html, "seg_preset select missing"
        assert 'name="seg_rate_pence_per_kwh"' in html, "seg_rate_pence_per_kwh input missing"

        # All six UK supplier preset keys (parity with test_home_form_shows_seg_section)
        for preset_key in ("Octopus", "British Gas", "EDF", "E.ON", "Scottish Power", "OVO"):
            assert preset_key in html, f"SEG preset '{preset_key}' missing from fleet form HTML"
