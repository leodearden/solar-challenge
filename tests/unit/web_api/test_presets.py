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

    @pytest.mark.parametrize(
        ("preset_type", "error"),
        [
            pytest.param(
                "fleet",
                "type must be 'home', got 'fleet'; POST /api/scenarios/save saves fleet presets",
                id="fleet",
            ),
            pytest.param(
                "banana",
                "type must be 'home', got 'banana'; POST /api/scenarios/save saves fleet presets",
                id="unknown",
            ),
            pytest.param(
                5,
                "type must be 'home', got 5; POST /api/scenarios/save saves fleet presets",
                id="integer",
            ),
            pytest.param(
                [1],
                "type must be 'home', got [1]; POST /api/scenarios/save saves fleet presets",
                id="array",
            ),
            pytest.param(
                None,
                "type must be 'home', got None; POST /api/scenarios/save saves fleet presets",
                id="null",
            ),
        ],
    )
    def test_save_type_other_than_home_returns_400_naming_it_and_saves_nothing(
        self, client: FlaskClient, preset_type: object, error: str
    ) -> None:
        """POST /api/presets saves home presets only: any other type, null included, is a 400 naming type and the value sent, and nothing is saved."""
        resp = client.post("/api/presets", json={"name": "Typed", "type": preset_type, "pv_kw": 3.0})
        assert resp.status_code == 400
        assert resp.get_json() == {"error": error}
        assert client.get("/api/presets/Typed").status_code == 404

    def test_save_type_home_saves_a_home_preset(self, client: FlaskClient) -> None:
        """A type of 'home', the one type POST /api/presets saves, is accepted."""
        resp = client.post("/api/presets", json={"name": "Typed home", "type": "home", "pv_kw": 3.0})
        assert resp.status_code == 201
        assert "Typed home" in [
            p["name"] for p in client.get("/api/presets").get_json() if p["source"] == "saved"
        ]

    def test_save_under_a_name_a_saved_fleet_preset_holds_returns_409_and_changes_nothing(
        self, client: FlaskClient
    ) -> None:
        """Saved presets share one namespace: a home save under a fleet preset's name is a 409 naming that preset, which keeps its config."""
        assert client.post("/api/scenarios/save", json={"name": "Taken", "config": {"n_homes": 9}}).status_code == 201

        resp = client.post("/api/presets", json={"name": "Taken", "pv_kw": 3.0})

        assert resp.status_code == 409
        assert resp.get_json() == {"error": "A saved fleet preset is already named 'Taken'"}
        assert client.get("/api/scenarios/presets/Taken").get_json()["config"] == {"n_homes": 9}
        assert "Taken" not in [p["name"] for p in client.get("/api/presets").get_json()]

    def test_saving_a_name_again_replaces_its_config_and_keeps_its_id(self, client: FlaskClient) -> None:
        """A second save under a saved home preset's name updates that preset in place."""
        first = client.post("/api/presets", json={"name": "Again", "pv_kw": 1.0})
        second = client.post("/api/presets", json={"name": "Again", "pv_kw": 2.0})
        assert (first.status_code, second.status_code) == (201, 201)
        assert second.get_json()["id"] == first.get_json()["id"]
        assert client.get("/api/presets/Again").get_json()["pv_kw"] == 2.0


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
