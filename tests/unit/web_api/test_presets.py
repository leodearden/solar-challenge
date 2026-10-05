# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the home preset endpoints: GET /api/presets, POST /api/presets and GET /api/presets/<name>."""

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient


class TestListPresets:
    """Tests for GET /api/presets."""

    def test_list_presets_returns_200(self, client: FlaskClient) -> None:
        """GET /api/presets returns 200 with a JSON array."""
        resp = client.get("/api/presets")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)

    def test_builtin_presets_present(self, client: FlaskClient) -> None:
        """Built-in presets are included in the response."""
        resp = client.get("/api/presets")
        data = resp.get_json()
        names = [p["name"] for p in data]
        assert "Small Urban" in names
        assert "Medium Suburban" in names
        assert "Large with Battery" in names

    def test_builtin_presets_tagged(self, client: FlaskClient) -> None:
        """Built-in presets have source='builtin'."""
        resp = client.get("/api/presets")
        data = resp.get_json()
        for preset in data:
            if preset["name"] in ("Small Urban", "Medium Suburban", "Large with Battery"):
                assert preset["source"] == "builtin"


class TestSavePreset:
    """Tests for POST /api/presets."""

    def test_save_preset_returns_201(self, client: FlaskClient) -> None:
        """Valid preset save returns 201 with name and id."""
        resp = client.post(
            "/api/presets",
            json={"name": "My Custom Preset", "pv_kw": 5.0, "battery_kwh": 10.0},
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["name"] == "My Custom Preset"
        assert "id" in data

    def test_saved_preset_appears_in_list(self, client: FlaskClient) -> None:
        """Saved preset appears in GET /api/presets listing."""
        client.post(
            "/api/presets",
            json={"name": "Listed Preset", "pv_kw": 3.5},
        )
        resp = client.get("/api/presets")
        names = [p["name"] for p in resp.get_json()]
        assert "Listed Preset" in names

    def test_save_no_json_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/presets",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_save_empty_name_returns_400(self, client: FlaskClient) -> None:
        """POST with empty preset name returns 400."""
        resp = client.post(
            "/api/presets",
            json={"name": "", "pv_kw": 4.0},
        )
        assert resp.status_code == 400
        assert "name" in resp.get_json()["error"].lower()

    def test_save_whitespace_name_returns_400(self, client: FlaskClient) -> None:
        """POST with whitespace-only preset name returns 400."""
        resp = client.post(
            "/api/presets",
            json={"name": "   ", "pv_kw": 4.0},
        )
        assert resp.status_code == 400


class TestGetPreset:
    """Tests for GET /api/presets/<name>."""

    def test_get_builtin_preset(self, client: FlaskClient) -> None:
        """Fetch a built-in preset by name."""
        resp = client.get("/api/presets/Small Urban")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Small Urban"
        assert data["source"] == "builtin"

    def test_get_saved_preset(self, client: FlaskClient) -> None:
        """Fetch a saved preset by name."""
        client.post(
            "/api/presets",
            json={"name": "Saved One", "pv_kw": 6.0},
        )
        resp = client.get("/api/presets/Saved One")
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["name"] == "Saved One"
        assert data["source"] == "saved"

    def test_get_nonexistent_preset_returns_404(self, client: FlaskClient) -> None:
        """Unknown preset name returns 404."""
        resp = client.get("/api/presets/Does Not Exist")
        assert resp.status_code == 404
        assert "error" in resp.get_json()
