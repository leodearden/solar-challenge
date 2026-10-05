"""Tests for the API blueprint endpoints with mocked JobManager.

Tests all endpoints in solar_challenge.web.api without running real
simulations.  The JobManager is mocked so that submit/status/event
calls return canned responses instantly.
"""

import dataclasses
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest
pytest.importorskip("flask")
import pandas as pd
import yaml
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.config import DispatchStrategyConfig, load_fleet_config, parse_seg_rate
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig
from solar_challenge.web.api import api_bp
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES
from tests._web_app import build_test_app
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES, VALID_HOME_PAYLOAD


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(tmp_path: Path) -> Flask:
    """Create a test Flask application with a temporary database."""
    return build_test_app(tmp_path)


@pytest.fixture
def mock_job_manager(app: Flask) -> MagicMock:
    """Replace the real JobManager on the app with a MagicMock.

    The mock is pre-configured with sensible return values so that
    tests can focus on request/response behaviour.
    """
    jm = MagicMock()
    jm.submit_home_job.return_value = ("job-home-001", "run-home-001")
    jm.submit_fleet_job.return_value = ("job-fleet-001", "run-fleet-001")
    jm.get_job_status.return_value = {
        "job_id": "job-home-001",
        "run_id": "run-home-001",
        "status": "running",
        "progress_pct": 42.0,
        "current_step": "Simulating",
        "message": "Running home simulation...",
    }
    jm.get_events.return_value = iter([
        {
            "event": "complete",
            "data": {"status": "completed", "run_id": "run-home-001"},
        }
    ])
    app.extensions["job_manager"] = jm
    return jm


@pytest.fixture
def client(app: Flask, mock_job_manager: MagicMock) -> FlaskClient:
    """Create a Flask test client with the mocked JobManager."""
    return app.test_client()


# ===================================================================
# UI render smoke test
# ===================================================================


class TestHomeFormRender:
    """Smoke test: GET /simulate/home renders the new tabs and controls."""

    def test_home_form_shows_heat_pump_tariff_and_dispatch(
        self, client: FlaskClient
    ) -> None:
        """GET /simulate/home returns 200 with Heat Pump, Tariff tabs and dispatch control."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Heat Pump" in html
        assert "Tariff" in html
        assert "Dispatch Strategy" in html

    def test_home_form_shows_pv_age_inputs(self, client: FlaskClient) -> None:
        """GET /simulate/home returns HTML containing the two PV-age number inputs."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert 'name="system_age_years"' in html
        assert 'name="degradation_rate_per_year"' in html

    def test_home_form_shows_seg_section(self, client: FlaskClient) -> None:
        """GET /simulate/home renders the SEG sub-section with all six preset options."""
        resp = client.get("/simulate/home")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Preset dropdown field must be present
        assert 'name="seg_preset"' in html
        # Explicit-rate input field must be present
        assert 'name="seg_rate_pence_per_kwh"' in html
        # All six UK supplier preset keys must appear as selectable option values
        for preset_key in ("Octopus", "British Gas", "EDF", "E.ON", "Scottish Power", "OVO"):
            assert preset_key in html, f"SEG preset '{preset_key}' missing from form HTML"


# ===================================================================
# GET /simulate/fleet — render smoke test
# ===================================================================


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
