# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the home preset endpoints: GET /api/presets, POST /api/presets and GET /api/presets/<name>."""

import json
import sqlite3
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient
from werkzeug.test import TestResponse


def _write_saved_home_preset(app: Flask, name: str, config: dict[str, object]) -> None:
    """Write the saved home preset *name* holding *config* into the app's database.

    It writes the row as POST /api/presets saved one before it refused a built-in
    preset's name; no public seam can write such a row any more.
    """
    with closing(sqlite3.connect(app.config["DATABASE"])) as conn:
        with conn:
            conn.execute(
                "INSERT INTO config_presets (id, name, type, config_json, created_at) VALUES (?, ?, 'home', ?, ?)",
                (str(uuid.uuid4()), name, json.dumps(config), datetime.now(timezone.utc).isoformat()),
            )


def _save_home_presets_one_of_them_under_a_builtin_name(app: Flask, client: FlaskClient) -> None:
    """Save a home preset named 'Small Urban', as a release from before the refusal could, and one named 'Mine'.

    The 'Small Urban' row's values are unlike the built-in one's, so applying the wrong preset shows.
    """
    _write_saved_home_preset(app, "Small Urban", {"pv_kw": 9.5, "battery_kwh": 7.0, "consumption_kwh": 6000})
    assert client.post("/api/presets", json={"name": "Mine", "pv_kw": 2.5}).status_code == 201


def _answers_to_saves_sent_together(app: Flask, *saves: tuple[str, dict[str, object]]) -> list[TestResponse]:
    """Send each (path, JSON body) save from its own thread, and return the answers in order.

    Another connection holds the database's write lock while the saves are sent and lets go
    half a second later, so every save is in flight before any of them can write.
    """
    with closing(sqlite3.connect(app.config["DATABASE"], isolation_level=None)) as other_writer:
        other_writer.execute("BEGIN IMMEDIATE")
        with ThreadPoolExecutor(max_workers=len(saves)) as pool:
            sent = [pool.submit(app.test_client().post, path, json=body) for path, body in saves]
            time.sleep(0.5)
            other_writer.execute("ROLLBACK")
            return [answer.result(timeout=30) for answer in sent]


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

    def test_a_saved_home_preset_under_a_builtin_presets_name_is_not_listed(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Each name is listed once: a saved home preset under a built-in preset's name is left out, and the built-in one is listed."""
        _save_home_presets_one_of_them_under_a_builtin_name(app, client)

        presets = client.get("/api/presets").get_json()

        assert [p["name"] for p in presets] == ["Small Urban", "Medium Suburban", "Large with Battery", "Mine"]
        assert {p["name"]: p for p in presets}["Small Urban"] == {
            "name": "Small Urban",
            "pv_kw": 3.0,
            "battery_kwh": 0,
            "consumption_kwh": 2900,
            "source": "builtin",
        }


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

    @pytest.mark.parametrize(
        ("rival_save", "statuses"),
        [
            pytest.param(("/api/presets", {"name": "Raced", "pv_kw": 2.0}), [201, 201], id="home-save"),
            pytest.param(
                ("/api/scenarios/save", {"name": "Raced", "config": {"n_homes": 9}}), [201, 409], id="fleet-save"
            ),
        ],
    )
    def test_saves_racing_for_a_new_name_answer_as_they_would_one_after_the_other(
        self, app: Flask, rival_save: tuple[str, dict[str, object]], statuses: list[int]
    ) -> None:
        """Two saves racing for a new name are never a 500: two home saves both answer 201, and a home and a fleet save answer 201 and 409."""
        answers = _answers_to_saves_sent_together(app, ("/api/presets", {"name": "Raced", "pv_kw": 1.0}), rival_save)
        assert sorted(answer.status_code for answer in answers) == statuses


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

    def test_each_listed_name_answers_the_entry_the_list_holds_under_it(self, app: Flask, client: FlaskClient) -> None:
        """The lookup agrees with the list the home page applies presets from, even for a built-in preset's name a saved home preset also holds."""
        _save_home_presets_one_of_them_under_a_builtin_name(app, client)

        for entry in client.get("/api/presets").get_json():
            resp = client.get(f"/api/presets/{entry['name']}")
            assert (resp.status_code, resp.get_json()) == (200, entry)

    def test_a_name_only_a_saved_fleet_preset_holds_answers_404(self, app: Flask, client: FlaskClient) -> None:
        """The lookup answers home presets only, as the list holds them: a saved fleet preset's name is not found."""
        _save_home_presets_one_of_them_under_a_builtin_name(app, client)
        assert client.post("/api/scenarios/save", json={"name": "Fleet only", "config": {"n_homes": 9}}).status_code == 201

        resp = client.get("/api/presets/Fleet only")

        assert (resp.status_code, resp.get_json()) == (404, {"error": "Preset 'Fleet only' not found"})
        assert "Fleet only" not in [p["name"] for p in client.get("/api/presets").get_json()]
