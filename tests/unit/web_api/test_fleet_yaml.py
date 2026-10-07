# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the fleet page's scenario-file endpoints: POST /api/fleet/export-yaml, POST /api/fleet/import-yaml and GET /api/fleet/presets/<name>."""

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import yaml

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.config import DispatchStrategyConfig, load_fleet_config, parse_seg_rate
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig


#: A fleet page form with every value away from the form converter's defaults and every overlay set.
_FLEET_FORM_BODY: dict = {
    "name": "Export Round Trip",
    "n_homes": 4,
    "seed": 7,
    "location": "london",
    "start": "2024-07-01",
    "end": "2024-07-03",
    "pv": {
        "capacity_kw": {
            "type": "weighted_discrete",
            "values": [{"value": 3.0, "weight": 1}, {"value": 5.0, "weight": 2}],
        }
    },
    "battery": {
        "capacity_kwh": {
            "type": "shuffled_pool",
            "entries": [{"value": 0, "count": 2}, {"value": 5.0, "count": 2}],
        }
    },
    "load": {
        "annual_consumption_kwh": {"type": "normal", "mean": 3400, "std": 800, "min": 2000, "max": 6000}
    },
    "tariff": {"type": "economy_7", "peak_rate": 0.3, "off_peak_rate": 0.1},
    "seg": {"rate_pence_per_kwh": 5.5},
    "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 21]]},
}


class TestExportFleetYAML:
    """POST /api/fleet/export-yaml writes the fleet scenario the fleet page's form describes."""

    def test_export_loads_back_through_load_fleet_config_as_the_fleet_simulate_runs(
        self, client: FlaskClient, mock_job_manager: MagicMock, tmp_path: Path
    ) -> None:
        """The exported file, read as `finance run` reads it, is the fleet POST /api/simulate/fleet-from-distribution runs for the same form: its homes, name and dates.

        load_fleet_config does not read seg: yet (task 185), so the SEG rate is threaded onto
        its homes as cli/finance.py threads it, as tests/unit/test_scenario_writer.py does.
        """
        export = client.post("/api/fleet/export-yaml", json=_FLEET_FORM_BODY)
        assert export.status_code == 200, export.get_data(as_text=True)
        assert "text/yaml" in export.content_type
        assert export.headers["Content-Disposition"] == "attachment; filename=fleet-config.yaml"
        text = export.get_data(as_text=True)
        path = tmp_path / "fleet.yaml"
        path.write_text(text, encoding="utf-8")

        fleet = load_fleet_config(path)
        document = yaml.safe_load(text)
        seg_tariff = SEGTariff(name="", rate_pence_per_kwh=parse_seg_rate(document["seg"]))
        loaded = [dataclasses.replace(home, seg_tariff=seg_tariff) for home in fleet.homes]

        simulate = client.post("/api/simulate/fleet-from-distribution", json=_FLEET_FORM_BODY)
        assert simulate.status_code == 201, simulate.get_data(as_text=True)
        submitted = mock_job_manager.submit_fleet_job.call_args.kwargs
        homes = submitted["configs"]
        batteries = [home.battery_config for home in homes if home.battery_config is not None]
        assert 0 < len(batteries) < len(homes)
        assert all(
            battery.dispatch_strategy == DispatchStrategyConfig("tou_optimized", peak_hours=[(16, 21)])
            for battery in batteries
        )
        assert all(
            home.tariff_config == TariffConfig.economy_7(off_peak_rate=0.1, peak_rate=0.3)
            and home.seg_tariff == SEGTariff(name="", rate_pence_per_kwh=5.5)
            for home in homes
        )

        assert loaded == homes
        assert fleet.name == submitted["name"]
        timezone = homes[0].location.timezone
        period = document["period"]
        assert (
            pd.Timestamp(period["start_date"], tz=timezone),
            pd.Timestamp(period["end_date"], tz=timezone),
        ) == (submitted["start_date"], submitted["end_date"])

    def test_export_names_a_nameless_fleet_as_simulate_runs_it(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """A form without a name is exported under the name its simulation runs as."""
        body = {key: value for key, value in _FLEET_FORM_BODY.items() if key != "name"}

        export = client.post("/api/fleet/export-yaml", json=body)
        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)

        assert (export.status_code, simulate.status_code) == (200, 201)
        assert (
            yaml.safe_load(export.get_data(as_text=True))["name"]
            == mock_job_manager.submit_fleet_job.call_args.kwargs["name"]
        )

    @pytest.mark.parametrize(
        "patch",
        [
            pytest.param({"tariff": {"type": "flat_rate"}}, id="tariff-the-loaders-refuse"),
            pytest.param({"dispatch_strategy": ""}, id="empty-string-dispatch"),
            pytest.param({"days": float("inf")}, id="days-infinity"),
            pytest.param(
                {
                    "battery": {
                        **_FLEET_FORM_BODY["battery"],
                        "dispatch_strategy": {"strategy_type": "self_consumption"},
                    }
                },
                id="battery-dispatch-strategy",
            ),
        ],
    )
    def test_export_refuses_what_simulate_refuses_with_the_same_answer(
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict
    ) -> None:
        """A form the simulate endpoint refuses gets the same 400 and error from the export, so no YAML is written for a fleet that cannot run; no job is queued.

        The empty-string dispatch follows the nested blocks' presence rule: only null reads as absent.
        """
        body = {**_FLEET_FORM_BODY, **patch}

        export = client.post("/api/fleet/export-yaml", json=body)
        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)

        assert export.status_code == 400
        assert (export.status_code, export.get_json()) == (simulate.status_code, simulate.get_json())
        mock_job_manager.submit_fleet_job.assert_not_called()


class TestImportFleetYAML:
    """POST /api/fleet/import-yaml answers the fleet form a fleet scenario's YAML describes, and the settings of it the form does not load."""

    def test_an_exported_fleet_imports_back_as_its_form(self, client: FlaskClient) -> None:
        """The page's export imports in full, and the form the import answers exports the same scenario."""
        body = {key: value for key, value in _FLEET_FORM_BODY.items() if key != "location"}
        exported = client.post("/api/fleet/export-yaml", json=body)
        assert exported.status_code == 200, exported.get_data(as_text=True)
        text = exported.get_data(as_text=True)

        imported = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert imported.status_code == 200, imported.get_data(as_text=True)
        answer = imported.get_json()
        assert answer["not_loaded"] == []
        re_exported = client.post("/api/fleet/export-yaml", json=answer["form"])
        assert re_exported.status_code == 200, re_exported.get_data(as_text=True)
        assert yaml.safe_load(re_exported.get_data(as_text=True)) == yaml.safe_load(text)

    def test_a_scenario_file_imports_naming_what_was_not_loaded(self, client: FlaskClient) -> None:
        """A scenario file loads what the form holds and names the settings the form has no control for."""
        text = (
            "fleet_distribution:\n"
            "  n_homes: 25\n"
            "  random_order: bristol_legacy\n"
            "  pv:\n"
            "    capacity_kw: {type: uniform, min: 3.0, max: 6.0}\n"
            "  load:\n"
            "    annual_consumption_kwh: {type: uniform, min: 2500, max: 4500}\n"
        )

        resp = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        answer = resp.get_json()
        assert answer["form"]["n_homes"] == 25
        assert answer["not_loaded"] == ["fleet_distribution.random_order"]

    @pytest.mark.parametrize(
        ("text", "reason"),
        [
            pytest.param("", "Empty request body", id="empty-body"),
            pytest.param("[[[not valid yaml", "Invalid YAML", id="malformed-yaml"),
            pytest.param(
                "home:\n  pv:\n    capacity_kw: 4.0\n", "fleet_distribution", id="home-scenario"
            ),
            pytest.param(
                "n_homes: 25\nseed: 7\n", "fleet_distribution", id="bare-fleet-distribution"
            ),
        ],
    )
    def test_a_body_that_is_no_fleet_scenario_is_refused(
        self, client: FlaskClient, text: str, reason: str
    ) -> None:
        """An empty body, malformed YAML, and a scenario without a fleet_distribution block get a 400 saying why.

        The loaders read a fleet only from a fleet_distribution: or homes: file, so a bare
        fleet_distribution block is not one.
        """
        resp = client.post("/api/fleet/import-yaml", data=text, content_type="text/yaml")

        assert resp.status_code == 400
        assert reason in resp.get_json()["error"]


#: The built-in scenarios the fleet page's Load Preset offers: the scenarios/ directory's files.
_BUILTIN_SCENARIO_STEMS = sorted(
    path.stem
    for path in (Path(__file__).resolve().parents[3] / "scenarios").iterdir()
    if path.suffix in (".yaml", ".yml") and path.is_file()
)


class TestFleetPresetEndpoint:
    """GET /api/fleet/presets/<name> answers for a built-in scenario file what the import answers for its YAML."""

    def test_a_fleet_preset_answers_its_form_and_what_was_not_loaded(
        self, client: FlaskClient
    ) -> None:
        """bristol-phase1 loads its PV pool and SEG rate, and names its random order, which the form has no control for."""
        resp = client.get("/api/fleet/presets/bristol-phase1")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        answer = resp.get_json()
        assert answer["form"]["pv"]["capacity_kw"] == {
            "type": "shuffled_pool",
            "entries": [
                {"value": 3.0, "count": 20},
                {"value": 4.0, "count": 40},
                {"value": 5.0, "count": 30},
                {"value": 6.0, "count": 10},
            ],
        }
        assert answer["form"]["seg"] == {"rate_pence_per_kwh": 4.1}
        assert "fleet_distribution.random_order" in answer["not_loaded"]

    def test_an_unknown_preset_is_not_found(self, client: FlaskClient) -> None:
        """A name no built-in scenario file has is a 404 naming it."""
        resp = client.get("/api/fleet/presets/no-such-preset")

        assert resp.status_code == 404
        assert resp.get_json() == {"error": "Preset 'no-such-preset' not found"}

    def test_a_home_scenario_preset_is_refused_naming_fleet_distribution(
        self, client: FlaskClient
    ) -> None:
        """bristol-arbitrage is a home: scenario, which the fleet page cannot load."""
        resp = client.get("/api/fleet/presets/bristol-arbitrage")

        assert resp.status_code == 400
        assert "fleet_distribution" in resp.get_json()["error"]

    @pytest.mark.parametrize("name", _BUILTIN_SCENARIO_STEMS)
    def test_every_builtin_scenario_loads_or_is_refused_with_a_reason(
        self, client: FlaskClient, name: str
    ) -> None:
        """Every preset the fleet page offers loads as a form, or is refused with an error the page shows; none fails the server."""
        answer_keys = {200: {"form", "not_loaded"}, 400: {"error"}}

        resp = client.get(f"/api/fleet/presets/{name}")

        assert resp.status_code in answer_keys, resp.get_data(as_text=True)
        assert set(resp.get_json()) == answer_keys[resp.status_code]
