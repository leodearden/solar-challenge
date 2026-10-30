# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the fleet distribution endpoints: POST /api/fleet/preview-distribution and POST /api/simulate/fleet-from-distribution."""

from collections.abc import Callable
from unittest.mock import NonCallableMagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.config import (
    generate_homes_from_distribution,
    parse_fleet_distribution_config,
)
from solar_challenge.dispatch import GridChargeConfig, PeakShavingStrategyConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.home import HomeConfig
from solar_challenge.web.fleet_config import (
    MAX_FLEET_HOMES,
    MAX_FLEET_SEED,
    form_to_fleet_distribution_config,
    sample_distribution,
)
from solar_challenge.web.request_boundary import resolve_location
from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS
from tests._falsy_json_values import FALSY_NON_NULL_VALUES
from tests._fleet_form import FLEET_FORM_BLOCKS
from tests._home_payload import VALID_HOME_PAYLOAD
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES


UNUSABLE_SHUFFLED_POOL_ENTRIES = [
    pytest.param(
        [{"value": 4.0, "count": float("inf")}],
        "entries[0].count must be a finite number, got inf",
        id="infinity",
    ),
    pytest.param(
        [{"value": 4.0, "count": 2.5}],
        "entries[0].count must be a whole number, got 2.5",
        id="fraction",
    ),
    pytest.param(
        [{"value": 4.0, "count": 1e300}],
        f"entries[0].count must be between 0 and {MAX_FLEET_HOMES}, got 1e+300",
        id="huge-float",
    ),
    pytest.param(
        [{"value": 4.0, "count": MAX_FLEET_HOMES}, {"value": 5.0, "count": 1}],
        f"entries counts must total at most {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
        id="pool-total-one-above-the-fleet-limit",
    ),
]

#: Each fleet form block a fleet cannot do without, with the distribution the 400 for its absence names.
REQUIRED_BLOCK_DISTRIBUTIONS = {"pv": "pv.capacity_kw", "load": "load.annual_consumption_kwh"}

#: The fleet form's other blocks, which a fleet can do without.
OPTIONAL_BLOCKS = tuple(key for key in FLEET_FORM_BLOCKS if key not in REQUIRED_BLOCK_DISTRIBUTIONS)


class TestPreviewDistribution:
    """Tests for POST /api/fleet/preview-distribution."""

    def test_normal_distribution_returns_samples(self, client: FlaskClient) -> None:
        """Normal distribution preview returns expected number of samples."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "normal",
                "params": {"mean": 4.0, "std": 1.0},
                "n_samples": 50,
            },
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert len(data["samples"]) == 50

    def test_uniform_distribution_returns_samples(self, client: FlaskClient) -> None:
        """Uniform distribution preview returns samples within range."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={
                "type": "uniform",
                "params": {"min": 2.0, "max": 8.0},
                "n_samples": 20,
            },
        )
        assert resp.status_code == 200
        samples = resp.get_json()["samples"]
        assert len(samples) == 20
        assert all(2.0 <= s <= 8.0 for s in samples)

    def test_unknown_distribution_returns_400(self, client: FlaskClient) -> None:
        """A type the distribution editor does not offer is a 400 naming type and the type sent."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "banana", "params": {}},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "type must be one of normal, uniform, weighted_discrete, shuffled_pool, "
            "got 'banana'"
        }

    def test_params_without_what_the_type_is_drawn_from_return_400_naming_the_field(
        self, client: FlaskClient
    ) -> None:
        """Params without a parameter the type is drawn from, a normal's mean, are a 400 naming its field under params, not samples drawn with an invented default."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "normal", "params": {}},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "params.mean must be given: the preview draws a normal distribution from "
            "its mean and std"
        }

    def test_default_n_samples(self, client: FlaskClient) -> None:
        """Default n_samples is 100."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "normal", "params": {"mean": 3.0, "std": 0.5}},
        )
        assert resp.status_code == 200
        assert len(resp.get_json()["samples"]) == 100

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            pytest.param(
                {"type": "normal", "params": "x"},
                "params must be a mapping, got str",
                id="normal-str-params",
            ),
            pytest.param(
                {"type": "weighted_discrete", "params": {"values": ["x"]}},
                "values[0] must be a mapping, got str",
                id="weighted-discrete-str-row",
            ),
            pytest.param(
                {"type": "shuffled_pool", "params": {"entries": [1]}},
                "entries[0] must be a mapping, got int",
                id="shuffled-pool-int-row",
            ),
        ],
    )
    def test_malformed_params_return_400_naming_the_field(
        self, client: FlaskClient, body: dict, message: str
    ) -> None:
        """Params that are not an object, or a distribution row that is not an object, is a 400 naming it and the type sent."""
        resp = client.post("/api/fleet/preview-distribution", json=body)
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]

    @pytest.mark.parametrize(
        ("n_samples", "message"),
        [
            pytest.param("x", "n_samples must be a finite number, got 'x'", id="str"),
            pytest.param(None, "n_samples must be a finite number, got None", id="null"),
            pytest.param(
                float("inf"), "n_samples must be a finite number, got inf", id="infinity"
            ),
            pytest.param(2.5, "n_samples must be a whole number, got 2.5", id="fraction"),
            pytest.param(
                MAX_FLEET_HOMES + 1,
                f"n_samples must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="one-above-the-fleet-limit",
            ),
        ],
    )
    def test_n_samples_that_is_not_a_whole_number_in_range_returns_400_naming_it(
        self, client: FlaskClient, n_samples: object, message: str
    ) -> None:
        """An n_samples that is not a whole number, or one above the dashboard's fleet limit, is a 400 naming n_samples and the value sent; a fraction is refused, not truncated."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "normal", "params": {"mean": 4.0, "std": 1.0}, "n_samples": n_samples},
        )
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]

    @pytest.mark.parametrize(("entries", "message"), UNUSABLE_SHUFFLED_POOL_ENTRIES)
    def test_shuffled_pool_count_it_cannot_use_returns_400_naming_it(
        self, client: FlaskClient, entries: list, message: str
    ) -> None:
        """A shuffled_pool count that is not a whole number, a fraction included, or one above the dashboard's fleet limit, is a 400 naming the row's count and the value sent; so is a count that takes the pool's total above that limit, naming the total."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "shuffled_pool", "params": {"entries": entries}},
        )
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]

    @pytest.mark.parametrize("value", UNUSABLE_NUMBERS)
    @pytest.mark.parametrize(
        ("dist_type", "params", "field"),
        [
            pytest.param(
                "normal", lambda v: {"mean": v, "std": 1.0}, "params.mean", id="normal-mean"
            ),
            pytest.param(
                "uniform", lambda v: {"min": 2.0, "max": v}, "params.max", id="uniform-max"
            ),
            pytest.param(
                "weighted_discrete",
                lambda v: {"values": [{"value": 3.0, "weight": v}]},
                "params.values[0].weight",
                id="weighted-discrete-weight",
            ),
        ],
    )
    def test_params_number_that_is_not_finite_returns_400_naming_it(
        self,
        client: FlaskClient,
        dist_type: str,
        params: Callable[[object], dict],
        field: str,
        value: object,
    ) -> None:
        """A params number that is not a finite number, a boolean included, is a 400 naming its field under params and the value sent."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": dist_type, "params": params(value), "n_samples": 3},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": f"{field} must be a finite number, got {value!r}"}

    def test_finite_params_whose_draws_are_not_finite_return_400_carrying_sample_distributions_refusal(
        self, client: FlaskClient
    ) -> None:
        """Finite params that draw a sample a float cannot hold are a 400 carrying sample_distribution's refusal, not a 200 whose samples JSON cannot write."""
        body = {"type": "uniform", "params": {"min": -1.7e308, "max": 1.7e308}, "n_samples": 100}
        with pytest.raises(ValueError) as refusal:
            sample_distribution(body["type"], body["params"], body["n_samples"])
        resp = client.post("/api/fleet/preview-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(refusal.value)}


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

    def test_invalid_n_homes_returns_400(self, client: FlaskClient) -> None:
        """n_homes < 1 returns 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={"n_homes": 0},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            pytest.param(
                {"n_homes": float("inf")},
                "n_homes must be a finite number, got inf",
                id="n_homes-infinity",
            ),
            pytest.param(
                {"seed": float("inf")}, "seed must be a finite number, got inf", id="seed-infinity"
            ),
            pytest.param(
                {"n_homes": 2.5},
                "n_homes must be a whole number, got 2.5",
                id="n_homes-fraction",
            ),
            pytest.param({"seed": 1.5}, "seed must be a whole number, got 1.5", id="seed-fraction"),
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
    def test_n_homes_seed_or_days_it_cannot_use_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict, message: str
    ) -> None:
        """An n_homes, seed or days that is not a whole number, a seed beyond MAX_FLEET_SEED, or a fleet above the dashboard's fleet limit, is a 400 naming it and the value sent; no fleet is queued."""
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
            pytest.param(None, id="null"),
        ],
    )
    def test_location_it_cannot_resolve_returns_400_carrying_the_refusal_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, location: object
    ) -> None:
        """A location resolve_location refuses, a value that is not a string included, is a 400 whose error is its refusal, never a fleet at Bristol or a 500; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "location": location},
        )
        assert resp.status_code == 400
        mock_job_manager.submit_fleet_job.assert_not_called()
        with pytest.raises(ValueError) as refusal:
            resolve_location(location)
        assert resp.get_json() == {"error": str(refusal.value)}

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
                        "values": [
                            {"value": 0, "weight": 1},
                            {"value": 5.0, "weight": 1},
                        ],
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
        [pytest.param("x", "str", id="str"), *FALSY_NON_NULL_VALUES],
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
        """Any of the six blocks, the pv/battery/load distributions and the tariff/dispatch_strategy/seg overlays, sent as a non-object, a falsy one other than null included, is a 400 naming the block and the type sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: value},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": f"{key} must be a mapping, got {type_name}"}
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
            pytest.param("", id="empty-string"),
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
    def test_battery_dispatch_strategy_returns_400_naming_the_fleets_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, fleet_dispatch: dict
    ) -> None:
        """A battery block's own dispatch_strategy is a 400 naming it and the fleet's dispatch_strategy, which every battery takes, whether or not the fleet's is set; no fleet is queued."""
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
            "error": "battery.dispatch_strategy must be absent or null: every battery takes the "
            f"fleet's dispatch_strategy, got {strategy!r}"
        }
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_null_battery_dispatch_strategy_leaves_every_battery_the_fleets(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A null battery dispatch_strategy reads as absent: every queued battery takes the fleet's dispatch_strategy."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "battery": {"capacity_kwh": 5.0, "dispatch_strategy": None},
                "dispatch_strategy": {"strategy_type": "peak_shaving", "import_limit_kw": 4.5},
            },
        )
        assert resp.status_code == 201, resp.get_data(as_text=True)
        configs = mock_job_manager.submit_fleet_job.call_args.kwargs["configs"]
        fleet_dispatch = PeakShavingStrategyConfig(import_limit_kw=4.5)
        assert [config.battery_config.dispatch_strategy for config in configs] == [fleet_dispatch] * 2

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
        """A null block a fleet cannot do without reads as absent: the body with it gets the 400 the body without it gets, naming the missing distribution, and no fleet is queued."""
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
        assert distribution in null_block.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_empty_battery_block_returns_400_carrying_the_grammars_refusal_naming_its_capacity(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """An empty battery block is a present block, not an absent one: a battery without its capacity distribution, it reaches config.py's grammar and is a 400 whose error is the grammar's refusal, naming battery.capacity_kwh; no fleet is queued."""
        body = {**self._VALID_BODY, "battery": {}}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_to_fleet_distribution_config(body))
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert "battery.capacity_kwh" in resp.get_json()["error"]
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
        """A distribution sent without a parameter or its rows reaches config.py's grammar without them, not with an invented default, and is a 400 whose error is the grammar's refusal naming each missing key; no fleet is queued."""
        body = {**self._VALID_BODY, **patch}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_to_fleet_distribution_config(body))
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        for key in missing:
            assert repr(key) in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_row_without_its_weight_returns_400_naming_it_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A weighted_discrete row without its weight is a 400 naming the row and the row sent, not a row of weight 1; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "pv": {"capacity_kw": {"type": "weighted_discrete", "values": [{"value": 4.0}]}},
            },
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "pv.capacity_kw.values[0] must be a mapping with 'value' and 'weight', "
            "got {'value': 4.0}"
        }
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_distribution_type_the_editor_does_not_offer_returns_400_naming_its_type_field(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A block setting's distribution of a type the fleet page's editor does not offer, a fixed pv.tilt, is a 400 naming its type field and the type sent, not the grammar's refusal of the spec cut down to its type; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "pv": {"capacity_kw": 4.0, "tilt": {"type": "fixed", "value": 30.0}},
            },
        )
        assert resp.status_code == 400
        assert resp.get_json() == {
            "error": "pv.tilt.type must be one of normal, uniform, weighted_discrete, "
            "shuffled_pool, got 'fixed'"
        }
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "pv",
        [
            pytest.param({"type": "normal", "mean": 4.0, "std": 1.0}, id="normal"),
            pytest.param(
                {"type": "weighted_discrete", "values": [{"value": 4.0, "weight": 1}]},
                id="weighted-discrete",
            ),
        ],
    )
    def test_pv_block_that_is_itself_a_distribution_returns_400_naming_pv_type_and_pv_capacity_kw(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, pv: dict
    ) -> None:
        """A pv block sent as its distribution, instead of holding it in pv.capacity_kw, is a 400 carrying form_to_fleet_distribution_config's refusal, which names pv.type and pv.capacity_kw; no fleet is queued."""
        body = {**self._VALID_BODY, "pv": pv}
        with pytest.raises(ValueError) as conversion_refusal:
            form_to_fleet_distribution_config(body)
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(conversion_refusal.value)}
        assert "pv.type" in resp.get_json()["error"]
        assert "pv.capacity_kw" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("block", "message"),
        [
            pytest.param(
                {"pv": {"capacity_kw": {"type": "weighted_discrete", "values": ["x"]}}},
                "values[0] must be a mapping, got str",
                id="pv-weighted-discrete-str-row",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "weighted_discrete", "values": "ab"}}},
                "values must be a list, got str",
                id="pv-weighted-discrete-str-values",
            ),
            pytest.param(
                {"pv": {"capacity_kw": {"type": "shuffled_pool", "entries": [1]}}},
                "entries[0] must be a mapping, got int",
                id="pv-shuffled-pool-int-row",
            ),
            pytest.param(
                {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "weighted_discrete",
                            "values": [3500],
                        }
                    }
                },
                "values[0] must be a mapping, got int",
                id="load-weighted-discrete-int-row",
            ),
        ],
    )
    def test_malformed_distribution_rows_return_400_naming_the_field(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, block: dict, message: str
    ) -> None:
        """A weighted_discrete/shuffled_pool row that is not an object, or a row list that is not an array, is a 400 naming it and the type sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, **block},
        )
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(("entries", "message"), UNUSABLE_SHUFFLED_POOL_ENTRIES)
    def test_shuffled_pool_count_it_cannot_use_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, entries: list, message: str
    ) -> None:
        """A shuffled_pool count that is not a whole number, a fraction included, or one above the dashboard's fleet limit, is a 400 naming the row's count and the value sent; so is a count that takes the pool's total above that limit, naming the total. No fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "pv": {"capacity_kw": {"type": "shuffled_pool", "entries": entries}},
            },
        )
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        "count",
        [pytest.param(1, id="short of n_homes"), pytest.param(3, id="beyond n_homes")],
    )
    def test_shuffled_pool_not_sized_to_n_homes_returns_400_carrying_the_grammars_refusal(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, count: int
    ) -> None:
        """A shuffled_pool whose count is not the body's 2 homes reaches config.py's grammar and is a 400 whose error is the grammar's refusal, naming pv.capacity_kw; no fleet is queued."""
        body = {
            **self._VALID_BODY,
            "pv": {"capacity_kw": {"type": "shuffled_pool", "entries": [{"value": 4.0, "count": count}]}},
        }
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(form_to_fleet_distribution_config(body))
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
                parse_fleet_distribution_config(form_to_fleet_distribution_config(body)),
                resolve_location(body["location"]),
            )
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(refusal.value)}
        assert "load.household_occupants" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("patch", "message"),
        [
            pytest.param(
                {"battery": {"capacity_kwh": {"type": "weighted_discrete", "values": ["x"]}}},
                "battery.capacity_kwh.values[0] must be a mapping, got str",
                id="battery-weighted-discrete-str-row",
            ),
            pytest.param(
                {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "shuffled_pool",
                            "entries": [{"value": 3500.0, "count": -1}],
                        }
                    }
                },
                f"load.annual_consumption_kwh.entries[0].count must be between 0 and "
                f"{MAX_FLEET_HOMES}, got -1",
                id="load-shuffled-pool-negative-count",
            ),
        ],
    )
    def test_row_or_count_it_cannot_use_returns_400_naming_its_distribution(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict, message: str
    ) -> None:
        """A malformed distribution row or count is a 400 naming its field under the distribution it belongs to; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, **patch},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": message}
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
                "pv.capacity_kw.mean",
                id="pv-normal-mean",
            ),
            pytest.param(
                lambda v: {
                    "load": {
                        "annual_consumption_kwh": {
                            "type": "weighted_discrete",
                            "values": [{"value": 3500.0, "weight": v}],
                        }
                    }
                },
                "load.annual_consumption_kwh.values[0].weight",
                id="load-weighted-discrete-weight",
            ),
        ],
    )
    def test_distribution_number_that_is_not_finite_returns_400_naming_it(
        self,
        client: FlaskClient,
        mock_job_manager: NonCallableMagicMock,
        patch: Callable[[object], dict],
        field: str,
        value: object,
    ) -> None:
        """A distribution number that is not a finite number, a boolean included, is a 400 naming its field and the value sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, **patch(value)},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": f"{field} must be a finite number, got {value!r}"}
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_block_setting_too_large_for_a_float_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A block setting too large for a float is a 400 naming it and the value sent, not a 500; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "pv": {**self._VALID_BODY["pv"], "tilt": 10**400}},
        )
        assert resp.status_code == 400
        assert resp.get_json() == {"error": f"pv.tilt must be a finite number, got {10**400!r}"}
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
        """A block setting sent as a distribution, pv.tilt, is sampled for every queued home, and the battery block's grid_charging reaches every queued battery."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={
                **self._VALID_BODY,
                "pv": {
                    **self._VALID_BODY["pv"],
                    "tilt": {"type": "uniform", "min": 10.0, "max": 20.0},
                },
                "battery": {"capacity_kwh": 5.0, "grid_charging": {"target_soc_fraction": 0.5}},
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
        ],
    )
    def test_a_mapping_block_setting_the_grammar_refuses_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock, patch: dict, named: str
    ) -> None:
        """A block setting sent as a mapping that config.py's grammar refuses reaches the grammar unchanged, and is a 400 whose error is the grammar's own refusal, naming the setting; no fleet is queued."""
        body = {**self._VALID_BODY, **patch}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(
                {key: body[key] for key in ("n_homes", "seed", "pv", "battery", "load") if key in body}
            )
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
        """The fleet form has no toggle for a block: a pv/battery/load block's enabled, true, false, 0 or null, reaches config.py's grammar, which has no such key, and is a 400 whose error is the grammar's refusal naming it; no fleet is queued. A fleet without batteries leaves its battery block out or sends it null."""
        body = {**self._VALID_BODY, block: {**settings, "enabled": value}}
        with pytest.raises(ConfigurationError) as grammar_refusal:
            parse_fleet_distribution_config(
                {key: body[key] for key in ("n_homes", "seed", "pv", "battery", "load") if key in body}
            )
        resp = client.post("/api/simulate/fleet-from-distribution", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": str(grammar_refusal.value)}
        assert "'enabled'" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_a_battery_blocks_enabled_sent_as_the_string_false_returns_400_and_queues_nothing(
        self, client: FlaskClient, mock_job_manager: NonCallableMagicMock
    ) -> None:
        """A battery block's enabled sent as the string "false" toggles nothing: it is a 400 naming battery.enabled, and no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "battery": {"capacity_kwh": 5.0, "enabled": "false"}},
        )
        assert resp.status_code == 400
        assert "battery.enabled" in resp.get_json()["error"]
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
