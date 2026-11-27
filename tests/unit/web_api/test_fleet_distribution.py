# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the fleet distribution endpoints: POST /api/fleet/preview-distribution and POST /api/simulate/fleet-from-distribution."""

import re
from collections.abc import Callable
from typing import Any
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.dispatch import GridChargeConfig, PeakShavingStrategyConfig, SelfConsumptionStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.fleet_distribution import (
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.home import HomeConfig
from solar_challenge.location import Location
from solar_challenge.scenario_blocks import parse_location_block
from solar_challenge.web.fleet_components import (
    FLEET_COMPONENTS,
    MAX_FLEET_HOMES,
    MAX_FLEET_SEED,
    MAX_WINDOW_DAYS,
    fleet_component_values,
    page_limits,
)
from solar_challenge.web.fleet_scenario import parse_fleet_form
from solar_challenge.web.request_boundary import read_location, require_encodable_text
from tests._default_pv_pool_fleet import DEFAULT_PV_POOL_FLEET_FORM, DEFAULT_PV_POOL_FLEET_HOMES
from tests._error_records import error_records
from tests._falsy_json_values import FALSY_SENT_VALUES
from tests._non_mapping_block_refusals import non_mapping_block_refusal
from tests._fleet_form import (
    FLEET_FORM_BLOCKS,
    FLEET_FORM_COMPONENT_BLOCKS,
    form_fleet_blocks,
    start_spec,
    valid_distribution_form,
)
from tests._home_payload import VALID_HOME_PAYLOAD
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES


#: Shuffled pools, as their values and counts lists, that fleet_distribution.py's grammar refuses for the 2-home fleet TestFleetFromDistribution posts: a count that is not a whole number of at least 0, or counts that do not total n_homes.
POOLS_THE_GRAMMAR_REFUSES = [
    pytest.param({"values": [4.0], "counts": [float("inf")]}, id="infinity"),
    pytest.param({"values": [4.0], "counts": [2.5]}, id="fraction"),
    pytest.param({"values": [4.0], "counts": [True]}, id="boolean"),
    pytest.param({"values": [4.0, 5.0], "counts": [-1, 3]}, id="negative"),
    pytest.param({"values": [4.0], "counts": [1e300]}, id="huge-float"),
    pytest.param(
        {"values": [4.0, 5.0], "counts": [MAX_FLEET_HOMES, 1]},
        id="pool-total-one-above-the-fleet-limit",
    ),
]


def grammar_refusal(body: dict) -> str:
    """The str() of fleet_distribution.py's grammar's refusal of the fleet form *body*'s fleet blocks, read as sent at the form's own paths."""
    with pytest.raises(ConfigurationError) as refusal:
        parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
    return str(refusal.value)


#: Each fleet form block a fleet cannot do without, with what the 400 for its absence names:
#: the grammar's refusal of a fleet without pv. An absent load is the grammar's absent load
#: block, every home at LoadConfig's default consumption.
REQUIRED_BLOCK_DISTRIBUTIONS = {"pv": "'pv'"}

#: The fleet form's other blocks, which a fleet can do without.
OPTIONAL_BLOCKS = tuple(key for key in FLEET_FORM_BLOCKS if key not in REQUIRED_BLOCK_DISTRIBUTIONS)


def fleet_page_starting_form() -> dict[str, Any]:
    """The fleet form the fleet page starts at: page_limits()'s fleet size, seed and days, and each component's editor at the type its card shows."""
    limits = page_limits()
    return {
        "n_homes": limits.fleet_size_default,
        "seed": limits.seed_default,
        "days": limits.default_days,
        **{
            component.key: {component.grammar_key: start_spec(component, component.start.shown)}
            for component in FLEET_COMPONENTS.values()
        },
    }


def run_refusal(form: dict[str, Any]) -> str:
    """The str() of parse_fleet_form's refusal of the fleet *form*, Run's reader; the calling test fails if it reads it."""
    with pytest.raises(ConfigurationError) as refusal:
        parse_fleet_form(form)
    return str(refusal.value)


#: PV specs Run refuses for a 6-home fleet: a normal whose clamp is inverted, a weighted
#: discrete with a negative weight, and a shuffled pool whose counts total 3 homes.
PV_SPECS_RUN_REFUSES = [
    pytest.param({"type": "normal", "mean": 4, "std": 1, "min": 9, "max": 2}, id="P8-inverted-clamp"),
    pytest.param({"type": "weighted_discrete", "values": [4, 5], "weights": [-1, 3]}, id="P9-negative-weight"),
    pytest.param({"type": "shuffled_pool", "values": [3, 4], "counts": [2, 1]}, id="P10-pool-short-of-n-homes"),
]


class TestPreviewDistribution:
    """POST /api/fleet/preview-distribution answers the homes Run builds from the same fleet form, or Run's refusal."""

    def test_the_starting_form_answers_each_components_value_of_each_of_runs_homes(
        self, client: FlaskClient
    ) -> None:
        """P1: the page's starting form answers 200 with its 100 homes and fleet_component_values of parse_fleet_form's homes."""
        form = fleet_page_starting_form()
        homes = parse_fleet_form(form).homes
        resp = client.post("/api/fleet/preview-distribution", json=form)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        body = resp.get_json()
        values = body["values"]
        assert len(set(values["pv"])) > 1
        assert 0.0 in values["battery"]
        assert body["homes"] == page_limits().fleet_size_default == len(homes)
        assert values["pv"] == [home.pv_config.capacity_kw for home in homes]
        assert values == fleet_component_values(homes)

    def test_a_form_without_a_battery_block_answers_the_batterys_absent_value_for_every_home(
        self, client: FlaskClient
    ) -> None:
        """A fleet without batteries reads 0 kWh, the battery editor's spelling of none, for each home."""
        form = valid_distribution_form()
        del form["battery"]
        resp = client.post("/api/fleet/preview-distribution", json=form)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["values"]["battery"] == [0.0] * form["n_homes"]

    def test_a_form_without_a_load_block_answers_null_for_each_homes_unscaled_load(
        self, client: FlaskClient
    ) -> None:
        """A fleet without a load block leaves each home's load unscaled, which reads null."""
        form = valid_distribution_form()
        del form["load"]
        resp = client.post("/api/fleet/preview-distribution", json=form)
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json()["values"]["load"] == [None] * form["n_homes"]

    @pytest.mark.parametrize("spec", PV_SPECS_RUN_REFUSES)
    def test_a_pv_spec_run_refuses_answers_runs_400(self, client: FlaskClient, spec: dict[str, Any]) -> None:
        """P2: a PV spec Run refuses is the preview's 400 carrying parse_fleet_form's refusal, as Run answers it."""
        body = {**valid_distribution_form(), "n_homes": 6, "pv": {"capacity_kw": spec}}
        expected = run_refusal(body)
        assert "pv.capacity_kw" in expected
        preview = client.post("/api/fleet/preview-distribution", json=body)
        assert (preview.status_code, preview.get_json()) == (400, {"error": expected})
        run = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert (run.status_code, run.get_json()) == (preview.status_code, preview.get_json())

    def test_a_drawn_value_outside_its_components_range_answers_runs_400(self, client: FlaskClient) -> None:
        """A normal far above PV's value_range draws PV no home may hold: the 400 carries refuse_homes_outside_ranges' refusal, as parse_fleet_form raises it."""
        pv_range = FLEET_COMPONENTS["pv"].value_range
        body = {
            **valid_distribution_form(),
            "pv": {"capacity_kw": {"type": "normal", "mean": pv_range.high * 10, "std": 1}},
        }
        expected = run_refusal(body)
        assert expected.startswith(f"pv.capacity_kw must be {pv_range} for every home, got ")
        resp = client.post("/api/fleet/preview-distribution", json=body)
        assert (resp.status_code, resp.get_json()) == (400, {"error": expected})

    @pytest.mark.parametrize(
        ("data", "content_type"),
        [
            pytest.param("not json", "text/plain", id="text-body"),
            pytest.param(None, "application/json", id="empty-json-body"),
        ],
    )
    def test_no_json_body_returns_400(self, client: FlaskClient, data: str | None, content_type: str) -> None:
        """A body that does not read as a JSON object, plain text or an empty JSON body, returns 400."""
        resp = client.post("/api/fleet/preview-distribution", data=data, content_type=content_type)
        assert resp.status_code == 400

    def test_a_preview_queues_nothing(self, client: FlaskClient, mock_job_manager: NonCallableMagicMock) -> None:
        """A 200 preview calls nothing on the job manager."""
        resp = client.post("/api/fleet/preview-distribution", json=valid_distribution_form())
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert mock_job_manager.method_calls == []


class TestFleetFromDistribution:
    """Tests for POST /api/simulate/fleet-from-distribution."""

    _VALID_BODY: dict = {
        "n_homes": 2,
        "seed": 1,
        "location": "bristol",
        "days": 1,
        "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
        "load": {"annual_consumption_kwh": 3500.0},
    }

    def test_valid_distribution_config_returns_201(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Valid 3-home distribution POST returns 201 with job_id/run_id and the run's results_url.

        Asserts:
        - status_code == 201
        - body is job_id and run_id from the mock, and as results_url the path of the run's results page, /results/<run_id>
        - submit_fleet_job called exactly once
        - the configs argument is a list of exactly 3 HomeConfig instances
        - the 3 homes have distinct PV capacities (they were sampled, not copied)
        """
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                "n_homes": 3,
                "seed": 42,
                "location": "bristol",
                "days": 1,
                "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
                "battery": {
                    "capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0},
                },
                "load": {"annual_consumption_kwh": 3500.0},
            },
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        assert resp.get_json() == {
            "job_id": "job-fleet-001",
            "run_id": "run-fleet-001",
            "results_url": "/results/run-fleet-001",
        }

        mock_job_manager.submit_fleet_job.assert_called_once()
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) == 3
        assert all(isinstance(c, HomeConfig) for c in configs)
        # Homes were sampled from distributions — not all identical
        pv_caps = {round(c.pv_config.capacity_kw, 3) for c in configs}
        assert len(pv_caps) > 1, f"Expected distinct PV capacities but got {pv_caps}"

    def test_a_fixed_value_outside_its_components_range_returns_400_naming_it_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """P3: a PV fixed at 50 kW, which no home may hold, is a 400 naming pv.capacity_kw, its range, the value and the home."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "pv": {"capacity_kw": 50}},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 1"
        }
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_drawn_value_outside_its_components_range_returns_400_naming_the_home_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """P15: a normal around 50 kW draws PV no home may hold, a 400 naming pv.capacity_kw, its range and the home."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "pv": {"capacity_kw": {"type": "normal", "mean": 50, "std": 1}}},
        )
        assert resp.status_code == 400
        assert re.fullmatch(
            r"pv\.capacity_kw must be between 0\.5 and 20 for every home, got \d+\.\d+ for home \d+",
            resp.get_json()["error"],
        ), resp.get_json()
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_the_export_of_a_fixed_value_outside_its_components_range_returns_400_naming_it(
        self, client: FlaskClient
    ) -> None:
        resp = client.post("/api/fleet/export-yaml", json={**self._VALID_BODY, "pv": {"capacity_kw": 50}})
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "pv.capacity_kw must be between 0.5 and 20 for every home, got 50.0 for home 1"
        }

    def test_a_fleet_of_2000_homes_returns_201_queueing_every_home(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """L5, P11: the fleet size is the server's to bound, 1 to MAX_FLEET_HOMES, so a fleet larger than the page's slider is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "n_homes": 2000, "pv": {"capacity_kw": 4.0}},
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        assert len(mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]) == 2000

    def test_a_fleet_above_max_fleet_homes_returns_400_naming_n_homes_its_range_and_the_value(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "n_homes": MAX_FLEET_HOMES + 1},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": "n_homes must be between 1 and 10000, got 10001"}
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("data", "content_type"),
        [
            pytest.param("not json", "text/plain", id="text-body"),
            pytest.param(None, "application/json", id="empty-json-body"),
        ],
    )
    def test_no_json_body_returns_400(
        self, client: FlaskClient, data: str | None, content_type: str
    ) -> None:
        """A body that does not read as a JSON object, plain text or an empty JSON body, returns 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution", data=data, content_type=content_type
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        "patch",
        [
            pytest.param({"n_homes": 0}, id="n_homes-zero"),
            pytest.param({"n_homes": 2.5}, id="n_homes-fraction"),
            pytest.param({"n_homes": True}, id="n_homes-boolean"),
            pytest.param({"n_homes": float("inf")}, id="n_homes-infinity"),
            pytest.param({"seed": 1.5}, id="seed-fraction"),
            pytest.param({"seed": True}, id="seed-boolean"),
            pytest.param({"seed": float("inf")}, id="seed-infinity"),
        ],
    )
    def test_n_homes_or_seed_the_grammar_refuses_returns_400_carrying_its_refusal(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict
    ) -> None:
        """An n_homes or seed that is not a whole number, or no homes, reaches fleet_distribution.py's grammar as sent, and is a 400 whose error is the grammar's refusal, naming it; no fleet is queued."""
        body = {**self._VALID_BODY, **patch}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert next(iter(patch)) in refusal
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            pytest.param(
                {"seed": MAX_FLEET_SEED + 2},
                f"seed must be between {-MAX_FLEET_SEED} and {MAX_FLEET_SEED}, got {MAX_FLEET_SEED + 2}",
                id="seed-beyond-max-fleet-seed",
            ),
            pytest.param(
                {"n_homes": MAX_FLEET_HOMES + 1},
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="n_homes-one-above-the-fleet-limit",
            ),
            pytest.param(
                {"days": float("inf")}, "days must be a finite number, got inf", id="days-infinity"
            ),
            pytest.param({"days": 2.5}, "days must be a whole number, got 2.5", id="days-fraction"),
        ],
    )
    def test_a_fleet_beyond_the_dashboards_bounds_or_days_it_cannot_use_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict, message: str
    ) -> None:
        """A seed beyond MAX_FLEET_SEED or a fleet above the dashboard's fleet limit, which the grammar accepts, or days that is not a whole number, is a 400 naming it and the value sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, **patch},
        )
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("window", "message"),
        [
            pytest.param(
                {"start": "2024-06-10", "end": "2024-06-01"},
                "end must not be before start, got start '2024-06-10' and end '2024-06-01'",
                id="end-before-start",
            ),
            pytest.param(
                {"start": "2024-01-01", "end": "2025-01-01"},
                f"start to end must span at most {MAX_WINDOW_DAYS} days, "
                "got start '2024-01-01' and end '2025-01-01', 367 days",
                id="one-day-past-the-longest-window",
            ),
        ],
    )
    def test_window_it_cannot_run_returns_400_naming_start_and_end_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, window: dict, message: str
    ) -> None:
        """A fleet window that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is a 400 naming start and end; no fleet is queued."""
        body = {key: value for key, value in self._VALID_BODY.items() if key != "days"}
        resp = client.post("/api/simulate/fleet-from-distribution", json={**body, **window})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == message
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_days_sent_with_start_and_end_returns_400_naming_them_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A fleet window set by both days and start/end is a 400 naming days, start and end as sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "start": "2024-03-01", "end": "2024-03-31"},
        )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == (
            "days must not be sent with start or end, "
            "got days 1 with start '2024-03-01' and end '2024-03-31'"
        )
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "location",
        [
            pytest.param("Paris", id="unknown-place"),
            pytest.param("95,0", id="latitude-out-of-range"),
            pytest.param(5, id="number"),
            pytest.param({"latitude": 50}, id="block-without-longitude"),
        ],
    )
    def test_location_it_cannot_resolve_returns_400_carrying_the_refusal_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, location: object
    ) -> None:
        """A location read_location refuses, a value that is neither a string nor a JSON object included, is a 400 whose error is its refusal, never a fleet at Bristol or a 500; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "location": location},
        )
        assert resp.status_code == 400
        mock_job_manager.submit_fleet_job.assert_not_called()
        with pytest.raises(ConfigurationError) as refusal:
            read_location(location)
        assert resp.get_json() == {"error": str(refusal.value)}

    def test_a_location_block_queues_every_home_at_the_location_it_reads_as(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A location: block of latitude and longitude is a 201 that queues every home at the location parse_location_block reads from it."""
        block = {"latitude": 55.95, "longitude": -3.19}
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "location": block},
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert [config.location for config in configs] == [parse_location_block(block)] * 2

    def test_a_name_holding_a_lone_surrogate_returns_400_naming_name_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A JSON string can escape a lone surrogate, which the run store cannot bind, so such a name is refused as request_boundary.require_encodable_text refuses it, before any fleet is queued."""
        with pytest.raises(ValueError) as refusal:
            require_encodable_text(chr(0xD800), "name")

        resp = client.post(
            "/api/simulate/fleet-from-distribution", json={**self._VALID_BODY, "name": chr(0xD800)}
        )

        assert (resp.status_code, resp.get_json()) == (400, {"error": str(refusal.value)})
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            pytest.param("heat_pump", "ASHP", id="heat-pump-the-fleet-has-no-overlay-for"),
            pytest.param(
                "tarif", {"type": "flat_rate", "rate_per_kwh": 0.3}, id="misspelt-tariff"
            ),
        ],
    )
    def test_unrecognised_key_returns_400_naming_it_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, key: str, value: object
    ) -> None:
        """A top-level key the fleet form does not have is refused by name, not dropped from a fleet run without it; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: value},
        )
        assert resp.status_code == 400
        assert f"Unrecognised fleet form keys: {key!r};" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("unsent", [pytest.param(None, id="null"), pytest.param("", id="empty-string")])
    def test_an_unrecognised_key_sent_as_null_or_empty_text_returns_400_naming_it_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, unsent: object
    ) -> None:
        """The presence rule applies to recognised keys only: an unrecognised key is refused by name whatever it holds."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution", json={**self._VALID_BODY, "tarif": unsent}
        )
        assert resp.status_code == 400
        assert "Unrecognised fleet form keys: 'tarif';" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("field", ["seed", "n_homes", "location"])
    def test_a_field_sent_as_null_or_empty_text_queues_the_fleet_a_form_without_it_queues(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, field: str
    ) -> None:
        """A seed, n_homes or location sent as null or "" reads as not sent: each queues the fleet the form without it queues, its default seed, size or Bristol."""
        without = {key: value for key, value in self._VALID_BODY.items() if key != field}
        answers = [
            client.post("/api/simulate/fleet-from-distribution", json=body).status_code
            for body in ({**without, field: None}, {**without, field: ""}, without)
        ]

        assert answers == [201, 201, 201]
        null, empty, left_out = (call.kwargs for call in mock_job_manager.submit_fleet_job.call_args_list)
        assert null == empty == left_out

    def test_a_form_that_sends_no_location_queues_every_home_at_bristol(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A fleet form whose location is not sent is a fleet at Bristol."""
        without = {key: value for key, value in self._VALID_BODY.items() if key != "location"}
        resp = client.post("/api/simulate/fleet-from-distribution", json=without)
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert [config.location for config in configs] == [Location.bristol()] * self._VALID_BODY["n_homes"]

    def test_fleet_wide_tariff_dispatch_seg_applied_to_all_homes(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Fleet-wide overlay: tariff/dispatch/SEG are applied to every generated HomeConfig.

        Uses a mix of battery/battery-less homes (weighted_discrete with 0 and 5 kWh)
        to verify that:
        - Every home carries the tariff_config and seg_tariff.
        - Homes WITH a battery carry battery_config.dispatch_strategy.
        - Homes WITHOUT a battery remain battery-less (no fabricated battery).
        """
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                "n_homes": 4,
                "seed": 42,
                "location": "bristol",
                "days": 1,
                "pv": {"capacity_kw": {"type": "normal", "mean": 4.0, "std": 1.0}},
                "load": {"annual_consumption_kwh": 3500.0},
                "battery": {
                    "capacity_kwh": {
                        "type": "weighted_discrete",
                        "values": [0, 5.0],
                        "weights": [1, 1],
                    },
                },
                "tariff": {"type": "flat_rate", "rate_per_kwh": 0.30},
                "dispatch_strategy": {
                    "strategy_type": "tou_optimized",
                    "peak_hours": [[16, 21]],
                },
                "seg": {"rate_pence_per_kwh": 5.5},
            },
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        mock_job_manager.submit_fleet_job.assert_called_once()
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) == 4
        assert all(isinstance(c, HomeConfig) for c in configs)

        # Assert both branches are actually present in this deterministic sample
        # (seed=42, n=4, weight=[0:1, 5.0:1] → ~2/4 each).  If the sampler ever
        # degenerates the error message explains why the branch test is vacuous.
        homes_with_battery = [c for c in configs if c.battery_config is not None]
        homes_without_battery = [c for c in configs if c.battery_config is None]
        assert len(homes_with_battery) >= 1, (
            "No home with battery in sampled fleet — distribution may have degenerated; "
            "battery-gated dispatch branch was not exercised"
        )
        assert len(homes_without_battery) >= 1, (
            "No battery-less home in sampled fleet — distribution may have degenerated; "
            "'no fabricated battery' branch was not exercised"
        )

        for cfg in configs:
            # Every home must have the tariff applied
            assert cfg.tariff_config is not None, "tariff_config missing on a home"
            # Every home must have the SEG tariff applied
            assert cfg.seg_tariff is not None, "seg_tariff missing on a home"
            assert cfg.seg_tariff.rate_pence_per_kwh == pytest.approx(5.5)
            # Battery gate: dispatch only where battery exists; never fabricated
            if cfg.battery_config is not None:
                assert cfg.battery_config.dispatch_strategy is not None, (
                    "dispatch_strategy missing on battery home"
                )
                assert cfg.battery_config.dispatch_strategy.strategy_type == "tou_optimized"
            else:
                # battery_config is None — no dispatch, no fabricated battery
                assert cfg.battery_config is None

    def test_fleet_wide_invalid_tariff_returns_400(self, client: FlaskClient) -> None:
        """Missing required tariff field returns HTTP 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            # flat_rate without rate_per_kwh — must fail validation
            json={**self._VALID_BODY, "tariff": {"type": "flat_rate"}},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("value", "type_name"),
        [pytest.param("x", "str", id="str"), *FALSY_SENT_VALUES],
    )
    @pytest.mark.parametrize("key", FLEET_FORM_BLOCKS)
    def test_non_mapping_block_returns_400_naming_it(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        key: str,
        value: object,
        type_name: str,
    ) -> None:
        """Any of the six blocks, the pv/battery/load distributions and the tariff/dispatch_strategy/seg overlays, sent as a non-object, a falsy one other than null or "" included, is a 400 naming the block and the type sent; no fleet is queued. A component block's refusal is the grammar's."""
        body = {**self._VALID_BODY, key: value}
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        expected = (
            grammar_refusal(body)
            if key in FLEET_FORM_COMPONENT_BLOCKS
            else non_mapping_block_refusal(key, type_name)
        )
        assert resp.get_json() == {"error": expected}
        assert key in expected and type_name in expected
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "battery_kwh",
        [
            pytest.param(0, id="home-without-battery"),
            pytest.param(5.0, id="home-with-battery"),
        ],
    )
    @pytest.mark.parametrize(
        "dispatch_strategy",
        [
            pytest.param(False, id="false"),
            pytest.param({}, id="empty-object"),
        ],
    )
    def test_empty_or_falsy_dispatch_strategy_gets_the_answer_simulate_home_gives(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        dispatch_strategy: object,
        battery_kwh: float,
    ) -> None:
        """An empty or falsy dispatch_strategy gets the same 400 here as at /api/simulate/home for a home with or without a battery, and neither queues a job."""
        home = client.post(
            "/api/simulate/home",
            json={
                **VALID_HOME_PAYLOAD,
                "battery_kwh": battery_kwh,
                "dispatch_strategy": dispatch_strategy,
            },
        )
        fleet = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "dispatch_strategy": dispatch_strategy},
        )
        assert fleet.status_code == 400
        assert (home.status_code, home.get_json()) == (fleet.status_code, fleet.get_json())
        mock_job_manager.submit_home_job.assert_not_called()
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "fleet_dispatch",
        [
            pytest.param({}, id="alone"),
            pytest.param(
                {"dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5}},
                id="beside-the-fleets-dispatch-strategy",
            ),
        ],
    )
    def test_battery_dispatch_strategy_returns_400_naming_it_and_the_one_strategy_rule_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, fleet_dispatch: dict
    ) -> None:
        """A battery block's own dispatch_strategy is a 400 naming it and the rule that the form gives every battery one dispatch strategy, whether or not the fleet's is set; no fleet is queued."""
        strategy = {"strategy_type": "self_consumption"}
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "battery": {"capacity_kwh": 5.0, "dispatch_strategy": strategy},
                **fleet_dispatch,
            },
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "battery.dispatch_strategy must be absent or null: a dashboard form gives every "
            f"battery one dispatch strategy, its own or the default, got {strategy!r}"
        }
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("fleet_dispatch", "battery_dispatch"),
        [
            pytest.param(
                {"dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5}},
                PeakShavingStrategyConfig(import_limit_kw=4.5),
                id="the-fleets",
            ),
            pytest.param({}, SelfConsumptionStrategyConfig(), id="self-consumption-when-the-fleet-sets-none"),
        ],
    )
    def test_null_battery_dispatch_strategy_leaves_every_battery_the_fleets(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        fleet_dispatch: dict,
        battery_dispatch: object,
    ) -> None:
        """A null battery dispatch_strategy reads as absent: every queued battery takes the fleet's dispatch_strategy, or BatteryConfig's self-consumption when the fleet sets none."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "battery": {"capacity_kwh": 5.0, "dispatch_strategy": None},
                **fleet_dispatch,
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert [config.battery_config.dispatch_strategy for config in configs] == [battery_dispatch] * 2

    @pytest.mark.parametrize("key", OPTIONAL_BLOCKS)
    def test_null_optional_block_reads_as_absent_queueing_the_fleet_without_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, key: str
    ) -> None:
        """A null block a fleet can do without reads as absent: the body with it gets the 201 the body without it gets, queueing the same fleet."""
        without_block = {k: v for k, v in self._VALID_BODY.items() if k != key}

        null_block = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: None},
        )
        absent_block = client.post("/api/simulate/fleet-from-distribution", json=without_block)

        assert (null_block.status_code, null_block.get_json()) == (
            absent_block.status_code,
            absent_block.get_json(),
        )
        assert null_block.status_code == 201
        submissions = mock_job_manager.submit_fleet_job.call_args_list
        assert len(submissions) == 2
        assert submissions[0] == submissions[1]

    @pytest.mark.parametrize(("key", "distribution"), REQUIRED_BLOCK_DISTRIBUTIONS.items())
    def test_null_required_block_reads_as_absent_returning_400_naming_its_distribution(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, key: str, distribution: str
    ) -> None:
        """A null block a fleet cannot do without reads as absent: the body with it gets the 400 the body without it gets, the grammar's refusal naming the missing block, and no fleet is queued."""
        without_block = {k: v for k, v in self._VALID_BODY.items() if k != key}

        null_block = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: None},
        )
        absent_block = client.post("/api/simulate/fleet-from-distribution", json=without_block)

        assert (null_block.status_code, null_block.get_json()) == (
            absent_block.status_code,
            absent_block.get_json(),
        )
        assert null_block.status_code == 400
        assert null_block.get_json() == {"error": grammar_refusal(without_block)}
        assert distribution in null_block.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_empty_battery_block_returns_400_carrying_the_grammars_refusal_naming_its_capacity(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """An empty battery block is a present block, not an absent one: a battery without its capacity distribution, it reaches fleet_distribution.py's grammar and is a 400 whose error is the grammar's refusal, naming battery's capacity_kwh; no fleet is queued."""
        body = {**self._VALID_BODY, "battery": {}}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert resp.get_json()["error"].startswith("battery") and "'capacity_kwh'" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("patch", "missing"),
        [
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "uniform"}}},
                ("min", "max"),
                id="battery-uniform-without-its-range",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "normal"}}},
                ("mean", "std"),
                id="pv-normal-without-its-parameters",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "uniform", "min": 2.0}}},
                ("max",),
                id="pv-uniform-without-its-max",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": {"type": "normal", "mean": 20.0}}},
                ("std",),
                id="pv-tilt-normal-without-its-std",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": {"type": "weighted_discrete"}}},
                ("weights",),
                id="load-weighted-discrete-without-its-rows",
            ),
        ],
    )
    def test_distribution_without_a_parameter_or_its_rows_returns_400_carrying_the_grammars_refusal_naming_it_and_queues_nothing(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        patch: dict,
        missing: tuple[str, ...],
    ) -> None:
        """A distribution sent without a parameter or its rows reaches fleet_distribution.py's grammar without them, not with an invented default, and is a 400 whose error is the grammar's refusal naming each missing key; no fleet is queued."""
        body = {**self._VALID_BODY, **patch}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        for key in missing:
            assert repr(key) in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_distribution_key_its_type_does_not_read_returns_400_carrying_the_grammars_refusal_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A normal whose mean is misspelt mena reaches fleet_distribution.py's grammar with it, and is a 400 whose error is the grammar's refusal naming mena, not its refusal of a normal without a mean; no fleet is queued."""
        body = {**self._VALID_BODY, "pv": {"capacity_kw": {"type": "normal", "mena": 4.0, "std": 1.0}}}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert "mena" in refusal
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_block_settings_fixed_distribution_queues_every_home_with_its_value(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A pv.tilt sent as fleet_distribution.py's fixed distribution, a type the fleet page's editor does not offer, reaches the grammar as sent, and every queued home's PV has its tilt."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "pv": {"capacity_kw": 4.0, "tilt": {"type": "fixed", "value": 30}}},
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert [config.pv_config.tilt for config in configs] == [30.0] * self._VALID_BODY["n_homes"]

    @pytest.mark.parametrize(
        "pv",
        [
            pytest.param({"type": "normal", "mean": 4.0, "std": 1.0}, id="normal"),
            pytest.param({"type": "weighted_discrete", "values": [4.0], "weights": [1]}, id="weighted-discrete"),
        ],
    )
    def test_pv_block_that_is_itself_a_distribution_returns_400_carrying_the_grammars_refusal_naming_pv(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, pv: dict
    ) -> None:
        """A pv block sent as its distribution, instead of holding it in pv.capacity_kw, is a 400 carrying the grammar's refusal of the keys the pv block has no row for, naming pv; no fleet is queued."""
        body = {**self._VALID_BODY, "pv": pv}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert refusal.startswith("pv: unrecognised keys")
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_E2_a_normal_without_its_parameters_returns_400_naming_its_mean_and_std_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """Nothing is invented for a parameter the page leaves out: the grammar names pv.capacity_kw's 'mean' and 'std'."""
        body = {**self._VALID_BODY, "pv": {"capacity_kw": {"type": "normal"}}}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert all(each in refusal for each in ("pv.capacity_kw", "'mean'", "'std'"))
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "spec",
        [
            pytest.param({"type": "weighted_discrete", "values": [4.0, 5.0], "weights": [1]}, id="weighted-discrete"),
            pytest.param({"type": "shuffled_pool", "values": [4.0], "counts": [1, 1]}, id="shuffled-pool"),
        ],
    )
    def test_parallel_lists_of_unequal_length_return_400_carrying_the_grammars_refusal_naming_pv_capacity_kw(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, spec: dict
    ) -> None:
        body = {**self._VALID_BODY, "pv": {"capacity_kw": spec}}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert "pv.capacity_kw" in refusal
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("pool", POOLS_THE_GRAMMAR_REFUSES)
    def test_shuffled_pool_count_the_grammar_refuses_returns_400_carrying_its_refusal(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, pool: dict
    ) -> None:
        """A shuffled_pool count that is not a whole number of at least 0, a fraction included, or counts that do not total the fleet's homes, reach fleet_distribution.py's grammar as sent, and are a 400 whose error is the grammar's refusal, naming pv.capacity_kw; no fleet is queued."""
        body = {
            **self._VALID_BODY,
            "pv": {"capacity_kw": {"type": "shuffled_pool", **pool}},
        }
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert "pv.capacity_kw" in refusal
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "count",
        [pytest.param(1, id="short of n_homes"), pytest.param(3, id="beyond n_homes")],
    )
    def test_shuffled_pool_not_sized_to_n_homes_returns_400_carrying_the_grammars_refusal(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, count: int
    ) -> None:
        """A shuffled_pool whose count is not the body's 2 homes reaches fleet_distribution.py's grammar and is a 400 whose error is the grammar's refusal, naming pv.capacity_kw; no fleet is queued."""
        body = {
            **self._VALID_BODY,
            "pv": {"capacity_kw": {"type": "shuffled_pool", "values": [4.0], "counts": [count]}},
        }
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert "pv.capacity_kw" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_distribution_whose_draws_overflow_a_float_returns_400_carrying_the_samplers_refusal_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A household_occupants uniform whose every draw overflows a float is a 400 whose error is the fleet sampler's refusal, naming load.household_occupants; no fleet is queued."""
        body = {
            **self._VALID_BODY,
            "load": {
                "annual_consumption_kwh": 3500.0,
                "household_occupants": {"type": "uniform", "min": -1.7e308, "max": 1.7e308},
            },
        }
        with pytest.raises(ConfigurationError) as refusal:
            generate_homes_from_distribution(
                parse_fleet_distribution_config(form_fleet_blocks(body), block_path=""),
                read_location(body["location"]),
            )
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(refusal.value)}
        assert "load.household_occupants" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("patch", "field"),
        [
            pytest.param(
                lambda v: {"battery": {"capacity_kwh": v}},
                "battery.capacity_kwh",
                id="battery-fixed",
            ),
            pytest.param(
                lambda v: {"pv": {"capacity_kw": {"type": "normal", "mean": v, "std": 1.0}}},
                "pv.capacity_kw",
                id="pv-normal-mean",
            ),
            pytest.param(
                lambda v: {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "weighted_discrete",
                            "values": [3500.0],
                            "weights": [v],
                        }
                    }
                },
                "load.annual_consumption_kwh",
                id="load-weighted-discrete-weight",
            ),
        ],
    )
    def test_distribution_number_that_is_not_finite_returns_400_carrying_the_grammars_refusal(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        patch: Callable[[object], dict],
        field: str,
        value: object,
    ) -> None:
        """A distribution number that is not a finite number, a boolean included, reaches fleet_distribution.py's grammar as sent, and is a 400 whose error is the grammar's refusal, naming its distribution; no fleet is queued."""
        body = {**self._VALID_BODY, **patch(value)}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert field in refusal
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_block_setting_too_large_for_a_float_returns_400_carrying_the_grammars_refusal(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A block setting too large for a float reaches fleet_distribution.py's grammar as sent, and is a 400 whose error is the grammar's refusal naming pv.tilt, not a 500; no fleet is queued."""
        body = {**self._VALID_BODY, "pv": {**self._VALID_BODY["pv"], "tilt": 10**400}}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert refusal.startswith("pv.tilt")
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_boolean_block_setting_reaches_the_queued_homes_as_given(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A boolean block setting, load.use_stochastic, reaches every queued home as the boolean sent, not as a number."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "load": {"annual_consumption_kwh": 3500.0, "use_stochastic": False},
            },
        )
        assert resp.status_code == 201, (
            f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        )
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert all(config.load_config.use_stochastic is False for config in configs)

    def test_a_block_settings_distribution_and_grid_charging_reach_the_queued_homes(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A block setting sent as a distribution, pv.tilt, is sampled for every queued home, and the battery block's grid_charging reaches every queued battery, which dispatches tou_optimized by the fleet's tariff."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "pv": {
                    **self._VALID_BODY["pv"],
                    "tilt": {"type": "uniform", "min": 10.0, "max": 20.0},
                },
                "battery": {"capacity_kwh": 5.0, "grid_charging": {"target_soc_fraction": 0.5}},
                "dispatch_strategy": {"strategy_type": "tou_optimized", "peak_hours": [[16, 19]]},
                "tariff": {"type": "economy_7"},
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        assert len(configs) == 2
        tilts = [config.pv_config.tilt for config in configs]
        assert all(10.0 <= tilt <= 20.0 for tilt in tilts), tilts
        grid_charging = GridChargeConfig(target_soc_fraction=0.5)
        assert [config.battery_config.grid_charging for config in configs] == [grid_charging] * 2

    @pytest.mark.parametrize(
        ("patch", "named"),
        [
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "tilt": {"mean": 20.0}}},
                "pv.tilt",
                id="pv-tilt-mapping-without-a-type",
            ),
            pytest.param(
                {"battery": {"capacity_kwh": 5.0, "grid_charging": {"target_soc": 0.5}}},
                "battery.grid_charging",
                id="battery-grid-charging-unknown-key",
            ),
            pytest.param(
                {"pv": {"capacity_kw": 4.0, "orientation": {"azimuth": 180.0}}},
                "'orientation'",
                id="pv-mapping-setting-the-grammar-has-no-key-for",
            ),
            pytest.param(
                {"load": {"annual_consumption_kwh": 3500.0, "use_stochastic": {}}},
                "load.use_stochastic",
                id="load-use-stochastic-empty-mapping",
            ),
        ],
    )
    def test_a_mapping_block_setting_the_grammar_refuses_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict, named: str
    ) -> None:
        """A block setting sent as a mapping that fleet_distribution.py's grammar refuses reaches the grammar unchanged, and is a 400 whose error is the grammar's own refusal, naming the setting; no fleet is queued."""
        body = {**self._VALID_BODY, **patch}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert named in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "value",
        [
            pytest.param(True, id="true"),
            pytest.param(False, id="false"),
            pytest.param(0, id="zero"),
            pytest.param(None, id="null"),
        ],
    )
    @pytest.mark.parametrize(
        ("block", "settings"),
        [
            pytest.param("pv", {"capacity_kw": 4.0}, id="pv"),
            pytest.param("battery", {"capacity_kwh": 5.0}, id="battery"),
            pytest.param("load", {"annual_consumption_kwh": 3500.0}, id="load"),
        ],
    )
    def test_a_component_blocks_enabled_returns_400_carrying_the_grammars_refusal_and_queues_nothing(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        block: str,
        settings: dict,
        value: object,
    ) -> None:
        """The fleet form has no toggle for a block: a pv/battery/load block's enabled, true, false, 0 or null, reaches fleet_distribution.py's grammar, which has no such key, and is a 400 whose error is the grammar's refusal naming it; no fleet is queued. A fleet without batteries leaves its battery block out or sends it null."""
        body = {**self._VALID_BODY, block: {**settings, "enabled": value}}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_fleet_blocks(body), block_path="")
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert "'enabled'" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_battery_blocks_enabled_sent_as_the_string_false_returns_400_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A battery block's enabled sent as the string "false" toggles nothing: it reaches fleet_distribution.py's grammar as sent, and is a 400 whose error is the grammar's refusal naming enabled under battery; no fleet is queued."""
        body = {**self._VALID_BODY, "battery": {"capacity_kwh": 5.0, "enabled": "false"}}
        refusal = grammar_refusal(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": refusal}
        assert refusal.startswith("battery: unrecognised keys 'enabled'")
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize("seg", MALFORMED_SEG_BODIES)
    def test_malformed_fleet_seg_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, seg: object
    ) -> None:
        """A malformed fleet-wide seg is a 400 naming seg, never a 500; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "seg": seg},
        )
        assert resp.status_code == 400
        assert "seg" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()


def test_the_fleet_pages_default_pv_pool_with_200_homes_is_answered_400_naming_the_pool(
    client: FlaskClient, mock_job_manager: NonCallableMagicMock, caplog: pytest.LogCaptureFixture
) -> None:
    """Row R4: the pool holds 100 values for 200 homes, a refusal, not a defect."""
    response = client.post("/api/simulate/fleet-from-distribution", json=DEFAULT_PV_POOL_FLEET_FORM)

    assert response.status_code == 400
    error = response.get_json()["error"]
    assert "pv.capacity_kw" in error and str(DEFAULT_PV_POOL_FLEET_HOMES) in error, error
    assert error_records(caplog) == []
    assert mock_job_manager.method_calls == []
