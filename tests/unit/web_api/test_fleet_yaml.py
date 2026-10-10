# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the fleet page's scenario-file endpoints, POST /api/fleet/export-yaml, POST /api/fleet/import-yaml and GET /api/fleet/presets/<name>, and for its Load Preset menu, which offers the presets GET /api/fleet/presets/<name> loads."""

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
from tests._html_page import element_attributes


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

    def test_export_writes_a_blocks_other_settings_and_loads_back_as_the_fleet_simulate_runs(
        self, client: FlaskClient, mock_job_manager: MagicMock, tmp_path: Path
    ) -> None:
        """A block's settings other than its distribution, a pv.tilt distribution and battery.grid_charging, are exported in config.py's grammar, and the file loads back as the fleet the simulate endpoint runs.

        The form sets no seg, which load_fleet_config does not read yet (task 185).
        """
        tilt = {"type": "uniform", "min": 10.0, "max": 20.0}
        grid_charging = {"target_soc_fraction": 0.5}
        without_seg = {key: value for key, value in _FLEET_FORM_BODY.items() if key != "seg"}
        body = {
            **without_seg,
            "pv": {**without_seg["pv"], "tilt": tilt},
            "battery": {**without_seg["battery"], "grid_charging": grid_charging},
        }

        export = client.post("/api/fleet/export-yaml", json=body)
        assert export.status_code == 200, export.get_data(as_text=True)
        text = export.get_data(as_text=True)
        fleet_distribution = yaml.safe_load(text)["fleet_distribution"]
        assert fleet_distribution["pv"].get("tilt") == tilt
        assert fleet_distribution["battery"].get("grid_charging") == grid_charging
        path = tmp_path / "fleet.yaml"
        path.write_text(text, encoding="utf-8")

        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert simulate.status_code == 201, simulate.get_data(as_text=True)
        homes = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert load_fleet_config(path).homes == homes

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
        ("patch", "reason"),
        [
            pytest.param(
                {"tariff": {"type": "flat_rate"}},
                "flat_rate tariff requires 'rate_per_kwh' field",
                id="tariff-the-loaders-refuse",
            ),
            pytest.param(
                {"dispatch_strategy": ""},
                "dispatch_strategy must be a mapping",
                id="empty-string-dispatch",
            ),
            pytest.param(
                {"days": float("inf"), "start": None, "end": None},
                "days must be an integer",
                id="days-infinity",
            ),
            pytest.param(
                {"days": 7, "start": "2024-07-01", "end": "2024-07-03"},
                "days must not be sent with start or end",
                id="days-with-start-and-end",
            ),
            pytest.param(
                {
                    "battery": {
                        **_FLEET_FORM_BODY["battery"],
                        "dispatch_strategy": {"strategy_type": "self_consumption"},
                    }
                },
                "battery.dispatch_strategy must be absent or null",
                id="battery-dispatch-strategy",
            ),
            pytest.param(
                {"battery": {**_FLEET_FORM_BODY["battery"], "enabled": False}},
                "Unrecognised keys in fleet_distribution.battery: 'enabled'",
                id="battery-enabled-false",
            ),
        ],
    )
    def test_export_refuses_what_simulate_refuses_with_the_same_answer(
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict, reason: str
    ) -> None:
        """A form the simulate endpoint refuses, for the reason each case names, gets the same 400 and error from the export, so no YAML is written for a fleet that cannot run; no job is queued.

        The empty-string dispatch follows the nested blocks' presence rule: only null reads as absent.
        """
        body = {**_FLEET_FORM_BODY, **patch}

        export = client.post("/api/fleet/export-yaml", json=body)
        simulate = client.post("/api/simulate/fleet-from-distribution", json=body)

        assert export.status_code == 400
        assert export.get_json()["error"].startswith(reason)
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
        ("settings", "message"),
        [
            pytest.param(
                {"n_homes": float("inf")},
                "fleet_distribution.n_homes must be a finite number, got inf",
                id="infinite-fleet-size",
            ),
            pytest.param(
                {"seed": 1.5},
                "fleet_distribution.seed must be a whole number, got 1.5",
                id="fractional-seed",
            ),
        ],
    )
    def test_a_fleet_size_or_seed_that_is_not_a_whole_number_is_refused_naming_the_scenarios_setting(
        self, client: FlaskClient, settings: dict, message: str
    ) -> None:
        """A scenario file whose n_homes or seed is not a whole number gets a 400 the fleet page shows, naming the scenario's setting and the value as written."""
        fleet = {
            "n_homes": 25,
            "pv": {"capacity_kw": {"type": "uniform", "min": 3.0, "max": 6.0}},
            "load": {"annual_consumption_kwh": {"type": "uniform", "min": 2500, "max": 4500}},
            **settings,
        }

        resp = client.post(
            "/api/fleet/import-yaml",
            data=yaml.safe_dump({"fleet_distribution": fleet}),
            content_type="text/yaml",
        )

        assert resp.status_code == 400
        assert resp.get_json() == {"error": message}

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


#: The name of each built-in scenario, once: the stems of the .yaml and .yml files in scenarios/, in name order.
_BUILTIN_SCENARIO_STEMS = sorted(
    {
        path.stem
        for path in (Path(__file__).resolve().parents[3] / "scenarios").iterdir()
        if path.suffix in (".yaml", ".yml") and path.is_file()
    }
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

    @pytest.mark.parametrize(
        ("name", "fixed_blocks", "named_not_loaded"),
        [
            pytest.param(
                "bristol-fin-calibration",
                {
                    "pv": {"capacity_kw": 5.5},
                    "battery": {"capacity_kwh": 5.0},
                    "load": {"annual_consumption_kwh": 3400.0},
                },
                ("fleet_distribution.pv.azimuth", "fleet_distribution.pv.tilt", "finance"),
                id="bristol-fin-calibration",
            ),
            pytest.param(
                "bristol-phase1-flex",
                {"battery": {"capacity_kwh": 5.0}},
                (
                    "fleet_distribution.battery.max_charge_kw",
                    "fleet_distribution.battery.max_discharge_kw",
                    "fleet_distribution.battery.grid_charging",
                    "fleet_distribution.load.use_stochastic",
                    "fleet_distribution.dispatch_strategy",
                ),
                id="bristol-phase1-flex",
            ),
        ],
    )
    def test_a_fleet_preset_with_a_fixed_capacity_loads_it_as_its_number(
        self,
        client: FlaskClient,
        name: str,
        fixed_blocks: dict,
        named_not_loaded: tuple[str, ...],
    ) -> None:
        """A built-in fleet whose homes all take one capacity loads it as the number the fleet page's Fixed Value holds, and names the settings the form has no control for."""
        resp = client.get(f"/api/fleet/presets/{name}")

        assert resp.status_code == 200, resp.get_data(as_text=True)
        answer = resp.get_json()
        assert {block: answer["form"][block] for block in fixed_blocks} == fixed_blocks
        assert [path for path in named_not_loaded if path not in answer["not_loaded"]] == []

    @pytest.mark.parametrize("name", _BUILTIN_SCENARIO_STEMS)
    def test_every_builtin_scenario_loads_or_is_refused_with_a_reason(
        self, client: FlaskClient, name: str
    ) -> None:
        """Every built-in scenario file loads as a form, or is refused with an error the page shows; none fails the server."""
        answer_keys = {200: {"form", "not_loaded"}, 400: {"error"}}

        resp = client.get(f"/api/fleet/presets/{name}")

        assert resp.status_code in answer_keys, resp.get_data(as_text=True)
        assert set(resp.get_json()) == answer_keys[resp.status_code]


class TestFleetPagePresetMenu:
    """The Load Preset menu of GET /simulate/fleet offers the built-in scenario files GET /api/fleet/presets/<name> loads."""

    def test_the_menu_offers_in_name_order_exactly_the_builtin_scenarios_that_load(
        self, client: FlaskClient
    ) -> None:
        """The menu offers each built-in scenario file the preset endpoint answers 200 for, in name order, and none it refuses."""
        loadable = [
            name
            for name in _BUILTIN_SCENARIO_STEMS
            if client.get(f"/api/fleet/presets/{name}").status_code == 200
        ]
        page = client.get("/simulate/fleet").get_data(as_text=True)
        offered = [
            attributes["value"]
            for attributes in element_attributes(page, "option")
            if attributes.get("value") in _BUILTIN_SCENARIO_STEMS
        ]

        assert loadable, "no built-in scenario file loads, so the menu's choice goes untested"
        assert offered == loadable
