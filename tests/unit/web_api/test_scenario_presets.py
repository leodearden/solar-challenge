# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the scenario builder's scenario-file endpoints: POST /api/scenarios/import-yaml, GET /api/scenarios/presets and /api/scenarios/presets/<name>, and POST /api/scenarios/save."""

import json
import logging
import sqlite3
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.errors import ConfigurationError
from solar_challenge.web.builder_form import builder_form_errors, builder_form_from_yaml, scenario_from_builder_form
from solar_challenge.web.request_boundary import read_string, require_encodable_text
from solar_challenge.web.text_options import read_one_of
from tests._builder_form import accepted_builder_form
from tests._config_preset_rows import insert_saved_fleet_preset, saved_preset_names
from tests._deeply_nested_json import JSON_NESTED_TOO_DEEPLY_TO_DECODE
from tests._repository_paths import SCENARIOS_DIR
from tests._web_app import database_of, point_store_config_at_a_missing_directory

#: The stem of each committed scenario file, the built-in presets the builder may offer.
_BUILTIN_SCENARIO_STEMS = sorted(path.stem for path in SCENARIOS_DIR.glob("*.yaml"))


def _former_format_refusal(name: str) -> dict[str, str]:
    """The answer to the lookup of the saved preset *name*, stored in the builder's former form format."""
    return {"error": f"Saved preset {name!r} was saved in the builder's former form format and must be saved again"}


def _saved_form(client: FlaskClient, name: str) -> Any:
    """The form the ?source=saved lookup of *name* answers; the calling test fails unless it answers 200."""
    response = client.get(f"/api/scenarios/presets/{name}?source=saved")
    assert response.status_code == 200, response.get_json()
    return response.get_json()["form"]


def _save(client: FlaskClient, name: str, config: Any) -> Any:
    """POST /api/scenarios/save of *config* under *name*; the calling test fails unless it answers 201."""
    response = client.post("/api/scenarios/save", json={"name": name, "config": config})
    assert response.status_code == 201, response.get_json()
    return response.get_json()


class TestScenarioImportYaml:
    """POST /api/scenarios/import-yaml reads a scenario file's text as the builder's form."""

    def test_an_economy_7_scenario_answers_400_naming_its_tariff_type(self, client: FlaskClient) -> None:
        yaml_text = (SCENARIOS_DIR / "bristol-phase1-flex.yaml").read_text(encoding="utf-8")

        response = client.post("/api/scenarios/import-yaml", data=yaml_text, content_type="text/yaml")

        assert response.status_code == 400
        assert set(response.get_json()) == {"error"}
        assert "tariff.type" in response.get_json()["error"]

    def test_a_scenario_the_builder_loads_answers_its_form_and_what_it_does_not_load(self, client: FlaskClient) -> None:
        yaml_text = (SCENARIOS_DIR / "bristol-phase1.yaml").read_text(encoding="utf-8")
        imported = builder_form_from_yaml(yaml_text)

        response = client.post("/api/scenarios/import-yaml", data=yaml_text, content_type="text/yaml")

        assert (response.status_code, response.get_json()) == (
            200,
            {"form": dict(imported.form), "not_loaded": list(imported.not_loaded)},
        )

    def test_an_empty_body_answers_400(self, client: FlaskClient) -> None:
        response = client.post("/api/scenarios/import-yaml", data="", content_type="text/yaml")

        assert (response.status_code, response.get_json()) == (400, {"error": "Empty request body"})


class TestScenarioPresetLookup:
    """GET /api/scenarios/presets/<name>?source=builtin|saved answers the preset as the builder's form."""

    def test_a_builtin_preset_answers_its_form_and_what_it_does_not_load(self, client: FlaskClient) -> None:
        imported = builder_form_from_yaml((SCENARIOS_DIR / "bristol-phase1.yaml").read_text(encoding="utf-8"))

        response = client.get("/api/scenarios/presets/bristol-phase1?source=builtin")

        assert (response.status_code, response.get_json()) == (
            200,
            {"form": dict(imported.form), "not_loaded": list(imported.not_loaded)},
        )

    def test_a_builtin_preset_the_builder_refuses_answers_400_naming_the_setting(self, client: FlaskClient) -> None:
        response = client.get("/api/scenarios/presets/bristol-phase1-flex?source=builtin")

        assert response.status_code == 400
        assert "tariff.type" in response.get_json()["error"]

    @pytest.mark.parametrize("query", ["", "?source=", "?source=file"], ids=["missing", "empty", "unknown"])
    def test_a_missing_or_unknown_source_answers_400_naming_source_and_its_two_choices(
        self, client: FlaskClient, query: str
    ) -> None:
        sent = query.partition("=")[2] if query else None
        with pytest.raises(ConfigurationError) as refusal:
            read_one_of(sent, ("builtin", "saved"), "source")

        response = client.get(f"/api/scenarios/presets/bristol-phase1{query}")

        assert (response.status_code, response.get_json()) == (400, {"error": str(refusal.value)})
        assert "'builtin'" in str(refusal.value) and "'saved'" in str(refusal.value)

    @pytest.mark.parametrize("source", ["builtin", "saved"])
    def test_a_name_no_preset_of_the_source_holds_answers_404(self, client: FlaskClient, source: str) -> None:
        response = client.get(f"/api/scenarios/presets/nonexistent-preset-xyz?source={source}")

        assert (response.status_code, response.get_json()) == (404, {"error": "Preset 'nonexistent-preset-xyz' not found"})

    def test_a_saved_preset_named_after_a_builtin_one_is_served_by_each_source_as_its_own(self, client: FlaskClient) -> None:
        """Task 359: a built-in no longer shadows a saved preset of the same name."""
        _save(client, "bristol-phase1", accepted_builder_form())

        builtin = client.get("/api/scenarios/presets/bristol-phase1?source=builtin").get_json()["form"]
        saved = _saved_form(client, "bristol-phase1")

        assert (builtin["name"], saved["name"]) == ("Bristol Phase 1", "One home")

    def test_a_name_only_a_saved_home_preset_holds_is_not_a_scenario_preset(self, client: FlaskClient) -> None:
        """The lookup serves saved fleet presets only, as the list holds them: a saved home preset's name is not found."""
        assert client.post("/api/presets", json={"name": "Home only", "pv_kw": 3.0}).status_code == 201

        resp = client.get("/api/scenarios/presets/Home only?source=saved")

        assert (resp.status_code, resp.get_json()) == (404, {"error": "Preset 'Home only' not found"})
        assert "Home only" not in [p["name"] for p in client.get("/api/scenarios/presets").get_json()["presets"]]

    @pytest.mark.parametrize(
        "config",
        [
            pytest.param({"n_homes": 10, "pv": {"capacity_kw": 4}}, id="the-builders-form"),
            pytest.param({"pv_distribution_type": "fixed", "pv_capacity_kw": 4}, id="the-flat-form-before-it"),
        ],
    )
    def test_a_preset_saved_in_the_builders_former_form_format_answers_400_naming_it(
        self, app: Flask, client: FlaskClient, config: dict[str, Any]
    ) -> None:
        """B3: neither former format holds a fleet_distribution block, so the preset must be saved again."""
        insert_saved_fleet_preset(database_of(app), "Old", json.dumps(config))

        resp = client.get("/api/scenarios/presets/Old?source=saved")

        assert (resp.status_code, resp.get_json()) == (400, _former_format_refusal("Old"))

    @pytest.mark.parametrize("config_json", ["", None], ids=["empty-text", "sql-null"])
    def test_a_saved_fleet_preset_whose_config_is_stored_as_empty_text_or_null_is_one_in_the_former_format(
        self, app: Flask, client: FlaskClient, config_json: str | None
    ) -> None:
        """A config stored as empty text or NULL is read as {}, which holds no fleet_distribution block."""
        insert_saved_fleet_preset(database_of(app), "Empty", config_json)

        resp = client.get("/api/scenarios/presets/Empty?source=saved")

        assert (resp.status_code, resp.get_json()) == (400, _former_format_refusal("Empty"))

    def test_a_saved_preset_the_database_cannot_read_answers_500_naming_it_and_logs_an_error_naming_it(
        self, app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A database fault in the lookup of a saved preset is a 500 naming the preset and the fault, not "not found", logged once at ERROR with the database's error in its traceback."""
        _save(client, "Mine", accepted_builder_form())
        database_of(app).path.write_bytes(b"not a database")

        with caplog.at_level(logging.WARNING):
            resp = client.get("/api/scenarios/presets/Mine?source=saved")

        message = "Saved preset 'Mine' could not be read: file is not a database"
        assert (resp.status_code, resp.get_json()) == (500, {"error": message})
        records = [r for r in caplog.records if "'Mine'" in r.getMessage()]
        assert [(r.levelno, r.getMessage()) for r in records] == [(logging.ERROR, message)]
        assert records[0].exc_info is not None
        assert isinstance(records[0].exc_info[1].__cause__, sqlite3.DatabaseError)

    def test_a_saved_fleet_preset_whose_config_is_not_json_answers_500_naming_it(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A saved fleet preset the list holds, but whose config is not JSON, is a 500 naming it, not "not found"."""
        insert_saved_fleet_preset(database_of(app), "Broken", "{not json")
        assert "Broken" in [p["name"] for p in client.get("/api/scenarios/presets").get_json()["presets"]]

        resp = client.get("/api/scenarios/presets/Broken?source=saved")

        assert (resp.status_code, resp.get_json()) == (
            500,
            {"error": "Saved preset 'Broken' could not be read: its config is not JSON"},
        )

    def test_a_saved_fleet_preset_whose_config_is_nested_too_deeply_to_decode_answers_500_naming_it_caused_by_the_recursion(
        self, app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A saved fleet preset whose config json.loads gives up on as nested too deeply is a 500 naming it and that fault, logged once at ERROR with the RecursionError as the cause."""
        insert_saved_fleet_preset(database_of(app), "Deep", JSON_NESTED_TOO_DEEPLY_TO_DECODE)

        with caplog.at_level(logging.WARNING):
            resp = client.get("/api/scenarios/presets/Deep?source=saved")

        message = "Saved preset 'Deep' could not be read: its config is nested too deeply to decode as JSON"
        assert (resp.status_code, resp.get_json()) == (500, {"error": message})
        records = [r for r in caplog.records if "'Deep'" in r.getMessage()]
        assert [(r.levelno, r.getMessage()) for r in records] == [(logging.ERROR, message)]
        assert records[0].exc_info is not None
        assert isinstance(records[0].exc_info[1].__cause__, RecursionError)

    @pytest.mark.parametrize("config_json", ["[1]", "3", '"text"', "null"], ids=["array", "number", "string", "json-null"])
    def test_a_saved_fleet_preset_whose_config_is_json_but_not_an_object_answers_500_naming_it(
        self, app: Flask, client: FlaskClient, config_json: str
    ) -> None:
        insert_saved_fleet_preset(database_of(app), "Not an object", config_json)

        resp = client.get("/api/scenarios/presets/Not an object?source=saved")

        assert (resp.status_code, resp.get_json()) == (
            500,
            {"error": "Saved preset 'Not an object' could not be read: its config is not a JSON object"},
        )


class TestScenarioPresetMenu:
    """GET /api/scenarios/presets lists the built-ins the builder loads, then the saved fleet presets."""

    def test_the_menu_lists_in_name_order_exactly_the_builtins_the_builder_loads_then_the_saved_presets(
        self, client: FlaskClient
    ) -> None:
        loadable = [
            name
            for name in _BUILTIN_SCENARIO_STEMS
            if client.get(f"/api/scenarios/presets/{name}?source=builtin").status_code == 200
        ]
        _save(client, "Mine", accepted_builder_form())

        listed = client.get("/api/scenarios/presets").get_json()["presets"]

        assert loadable, "no built-in scenario file loads, so the menu's choice goes untested"
        assert loadable != _BUILTIN_SCENARIO_STEMS, "every built-in loads, so the menu's filter goes untested"
        assert [(p["name"], p["source"]) for p in listed] == [
            *((name, "builtin") for name in loadable),
            ("Mine", "saved"),
        ]

    def test_saved_scenario_presets_are_listed_and_found_in_the_apps_database_after_its_store_config_names_a_missing_directory(
        self, app: Flask, client: FlaskClient, tmp_path: Path
    ) -> None:
        """The scenario preset list and lookup read the Database create_app built, whatever the app's store config names afterwards."""
        _save(client, "Fleet", accepted_builder_form())
        point_store_config_at_a_missing_directory(app, tmp_path / "missing")

        listed = client.get("/api/scenarios/presets").get_json()["presets"]
        assert [preset["name"] for preset in listed if preset["source"] == "saved"] == ["Fleet"]
        assert _saved_form(client, "Fleet")["name"] == "One home"

    def test_the_builtin_scenario_files_are_listed_alone_and_a_warning_logged_when_the_database_cannot_be_read(
        self, app: Flask, client: FlaskClient, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A database that cannot be read leaves the list answering, with the built-in scenario files alone, and the presets module logs the database's error once, as a warning."""
        builtin_names = [
            p["name"] for p in client.get("/api/scenarios/presets").get_json()["presets"] if p["source"] == "builtin"
        ]
        assert builtin_names, "the list holds no built-in preset, so it cannot show them listed alone"
        _save(client, "Mine", accepted_builder_form())
        database_of(app).path.write_bytes(b"not a database")

        with caplog.at_level(logging.WARNING):
            resp = client.get("/api/scenarios/presets")

        assert resp.status_code == 200
        assert [(p["name"], p["source"]) for p in resp.get_json()["presets"]] == [
            (name, "builtin") for name in builtin_names
        ]
        records = [r for r in caplog.records if r.name == "solar_challenge.web.presets"]
        assert [r.levelno for r in records] == [logging.WARNING]
        assert records[0].exc_info is not None
        assert isinstance(records[0].exc_info[1], sqlite3.DatabaseError)


class TestScenarioSave:
    """POST /api/scenarios/save validates the builder form and stores the scenario document it describes."""

    def test_a_saved_form_reloads_as_a_form_describing_the_same_scenario(self, client: FlaskClient) -> None:
        """B2 saved: the lookup answers nothing not loaded, and a form that describes the scenario saved."""
        form = {**accepted_builder_form(), "location_preset": "bristol", "seed": 3, "load": {"annual_consumption_kwh": 3500.0}}

        answer = _save(client, "Saved", form)

        assert answer["name"] == "Saved"
        lookup = client.get("/api/scenarios/presets/Saved?source=saved").get_json()
        assert lookup["not_loaded"] == []
        assert scenario_from_builder_form(lookup["form"]) == scenario_from_builder_form(form)

    def test_a_form_the_builder_refuses_answers_400_with_its_errors_and_saves_nothing(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """B4: the save's reasons are builder_form_errors' list, the one Validate shows."""
        form = {**accepted_builder_form(), "n_homes": 0}
        errors = builder_form_errors(form)
        assert errors, "premise: the builder refuses the form"

        response = client.post("/api/scenarios/save", json={"name": "Refused", "config": form})

        assert (response.status_code, response.get_json()) == (400, {"errors": errors})
        assert saved_preset_names(database_of(app)) == []

    @pytest.mark.parametrize(
        "body",
        [
            pytest.param({"config": accepted_builder_form()}, id="no-name"),
            pytest.param({"name": "   ", "config": accepted_builder_form()}, id="blank-name"),
        ],
    )
    def test_save_preset_without_a_name_returns_400_and_saves_nothing(
        self, app: Flask, client: FlaskClient, body: dict[str, Any]
    ) -> None:
        response = client.post("/api/scenarios/save", json=body)

        assert (response.status_code, response.get_json()) == (400, {"error": "Scenario name is required"})
        assert saved_preset_names(database_of(app)) == []

    @pytest.mark.parametrize("name", [pytest.param(5, id="integer"), pytest.param(None, id="null")])
    def test_save_of_a_name_that_is_not_a_json_string_returns_400_naming_name_and_saves_nothing(
        self, app: Flask, client: FlaskClient, name: object
    ) -> None:
        with pytest.raises(ConfigurationError) as refusal:
            read_string(name, "name")

        response = client.post("/api/scenarios/save", json={"name": name, "config": accepted_builder_form()})

        assert (response.status_code, response.get_json()) == (400, {"error": str(refusal.value)})
        assert saved_preset_names(database_of(app)) == []

    @pytest.mark.parametrize(
        ("config", "type_name"),
        [
            pytest.param([1, 2], "list", id="array"),
            pytest.param([], "list", id="empty-array"),
            pytest.param("", "str", id="empty-string"),
            pytest.param(0, "int", id="zero"),
            pytest.param(None, "NoneType", id="null"),
        ],
    )
    def test_save_of_a_config_that_is_not_a_json_object_returns_400_and_saves_nothing(
        self, app: Flask, client: FlaskClient, config: object, type_name: str
    ) -> None:
        """A sent config, falsy or not, must be a JSON object: it is never the cue to save the rest of the body as the preset."""
        response = client.post("/api/scenarios/save", json={"name": "s", "config": config})

        assert (response.status_code, response.get_json()) == (
            400,
            {"error": f"config must be a JSON object, got {type_name}"},
        )
        assert saved_preset_names(database_of(app)) == []

    @pytest.mark.parametrize(
        ("body", "config"),
        [
            pytest.param({"name": "Flat", "n_homes": 3}, {"n_homes": 3}, id="a-body-that-sends-no-config"),
            pytest.param({"name": "Empty", "config": {}}, {}, id="an-empty-config-object"),
        ],
    )
    def test_the_config_judged_is_the_one_sent_or_else_the_bodys_flat_form(
        self, app: Flask, client: FlaskClient, body: dict[str, Any], config: dict[str, Any]
    ) -> None:
        """Every key of a body sending no config but name and type is its config; a sent config is the config even when empty. Each is judged by builder_form_errors."""
        response = client.post("/api/scenarios/save", json=body)

        assert (response.status_code, response.get_json()) == (400, {"errors": builder_form_errors(config)})
        assert saved_preset_names(database_of(app)) == []

    def test_save_of_a_name_holding_a_lone_surrogate_returns_400_naming_name_and_saves_nothing(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """A JSON string can escape a lone surrogate, which sqlite3 cannot bind, so such a name is refused as request_boundary.require_encodable_text refuses it, before any database access."""
        name = chr(0xD800)
        with pytest.raises(ValueError) as refusal:
            require_encodable_text(name, "name")

        response = client.post("/api/scenarios/save", json={"name": name, "config": accepted_builder_form()})

        assert (response.status_code, response.get_json()) == (400, {"error": str(refusal.value)})
        assert saved_preset_names(database_of(app)) == []

    def test_save_under_a_name_a_saved_home_preset_holds_returns_409_and_changes_nothing(
        self, client: FlaskClient
    ) -> None:
        """Saved presets share one namespace: a scenario save under a home preset's name is a 409 naming that preset, which keeps its config."""
        assert client.post("/api/presets", json={"name": "Taken", "pv_kw": 3.0}).status_code == 201

        response = client.post("/api/scenarios/save", json={"name": "Taken", "config": accepted_builder_form()})

        assert response.status_code == 409
        assert response.get_json() == {"error": "A saved home preset is already named 'Taken'"}
        home_preset = client.get("/api/presets/Taken").get_json()
        assert (home_preset["source"], home_preset["pv_kw"]) == ("saved", 3.0)
        assert "Taken" not in [p["name"] for p in client.get("/api/scenarios/presets").get_json()["presets"]]

    def test_saving_a_scenario_again_replaces_its_config_and_keeps_its_id(self, client: FlaskClient) -> None:
        """A second save under a saved scenario's name updates that preset in place."""
        first = _save(client, "again", accepted_builder_form())
        second = _save(client, "again", {**accepted_builder_form(), "n_homes": 2})

        assert second["id"] == first["id"]
        assert _saved_form(client, "again")["n_homes"] == 2
