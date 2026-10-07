# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for the fleet distribution endpoints: POST /api/fleet/preview-distribution and POST /api/simulate/fleet-from-distribution."""

from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.config import (
    ConfigurationError,
    DispatchStrategyConfig,
    GridChargeConfig,
    parse_fleet_distribution_config,
)
from solar_challenge.home import HomeConfig
from solar_challenge.web.fleet_config import MAX_FLEET_HOMES
from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS
from tests._unusable_numbers import UNUSABLE_NUMBERS
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES, VALID_HOME_PAYLOAD


UNUSABLE_SHUFFLED_POOL_ENTRIES = [
    pytest.param(
        [{"value": 4.0, "count": float("inf")}],
        "entries[0].count must be an integer, got inf",
        id="infinity",
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
        """Unknown distribution type returns 400."""
        resp = client.post(
            "/api/fleet/preview-distribution",
            json={"type": "banana", "params": {}},
        )
        assert resp.status_code == 400
        assert "Unknown" in resp.get_json()["error"]

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
            pytest.param("x", "n_samples must be an integer, got 'x'", id="str"),
            pytest.param(None, "n_samples must be an integer, got None", id="null"),
            pytest.param(float("inf"), "n_samples must be an integer, got inf", id="infinity"),
            pytest.param(
                MAX_FLEET_HOMES + 1,
                f"n_samples must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="one-above-the-fleet-limit",
            ),
        ],
    )
    def test_n_samples_that_is_not_an_integer_in_range_returns_400_naming_it(
        self, client: FlaskClient, n_samples: object, message: str
    ) -> None:
        """An n_samples that int() cannot read, or one above the dashboard's fleet limit, is a 400 naming n_samples and the value sent."""
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
        """A shuffled_pool count that int() cannot read, or one above the dashboard's fleet limit, is a 400 naming the row's count and the value sent; so is a count that takes the pool's total above that limit, naming the total."""
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
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid 3-home distribution POST returns 201 with job_id/run_id.

        Asserts:
        - status_code == 201
        - body contains job_id and run_id from the mock
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
                    "enabled": True,
                    "capacity_kwh": {"type": "uniform", "min": 3.0, "max": 10.0},
                },
                "load": {"annual_consumption_kwh": 3500.0},
            },
        )
        assert resp.status_code == 201, f"Expected 201, got {resp.status_code}: {resp.get_data(as_text=True)}"
        body = resp.get_json()
        assert body["job_id"] == "job-fleet-001"
        assert body["run_id"] == "run-fleet-001"

        mock_job_manager.submit_fleet_job.assert_called_once()
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs.args[0]
        assert len(configs) == 3
        assert all(isinstance(c, HomeConfig) for c in configs)
        # Homes were sampled from distributions — not all identical
        pv_caps = {round(c.pv_config.capacity_kw, 3) for c in configs}
        assert len(pv_caps) > 1, f"Expected distinct PV capacities but got {pv_caps}"

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON returns 400."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            data="not json",
            content_type="text/plain",
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
                "n_homes must be an integer, got inf",
                id="n_homes-infinity",
            ),
            pytest.param(
                {"seed": float("inf")}, "seed must be an integer, got inf", id="seed-infinity"
            ),
            pytest.param(
                {"n_homes": MAX_FLEET_HOMES + 1},
                f"n_homes must be between 1 and {MAX_FLEET_HOMES}, got {MAX_FLEET_HOMES + 1}",
                id="n_homes-one-above-the-fleet-limit",
            ),
            pytest.param(
                {"days": float("inf")}, "days must be an integer, got inf", id="days-infinity"
            ),
        ],
    )
    def test_n_homes_seed_or_days_it_cannot_use_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict, message: str
    ) -> None:
        """An n_homes, seed or days that int() cannot read, or a fleet above the dashboard's fleet limit, is a 400 naming the field and the value sent; no fleet is queued."""
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
        self, client: FlaskClient, mock_job_manager: MagicMock, window: dict, message: str
    ) -> None:
        """A fleet window that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is a 400 naming start and end; no fleet is queued."""
        body = {key: value for key, value in self._VALID_BODY.items() if key != "days"}
        resp = client.post("/api/simulate/fleet-from-distribution", json={**body, **window})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == message
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_fleet_wide_tariff_dispatch_seg_applied_to_all_homes(
        self, client: FlaskClient, mock_job_manager: MagicMock
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
                    "enabled": True,
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

    @pytest.mark.parametrize("key", ["pv", "battery", "load"])
    def test_non_mapping_component_block_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: MagicMock, key: str
    ) -> None:
        """A pv/battery/load block sent as a non-object is a 400 naming the block and the type sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: "x"},
        )
        assert resp.status_code == 400
        assert f"{key} must be a mapping, got str" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("key", "value"),
        [
            ("tariff", "flat_rate"),
            ("dispatch_strategy", "self_consumption"),
            ("seg", "Octopus"),
        ],
    )
    def test_non_mapping_overlay_block_returns_400_naming_it(
        self, client: FlaskClient, mock_job_manager: MagicMock, key: str, value: str
    ) -> None:
        """A tariff/dispatch_strategy/seg block sent as a non-object is a 400 naming the block and the type sent; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: value},
        )
        assert resp.status_code == 400
        assert f"{key} must be a mapping, got str" in resp.get_json()["error"]
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
        mock_job_manager: MagicMock,
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
        self, client: FlaskClient, mock_job_manager: MagicMock, fleet_dispatch: dict
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
        self, client: FlaskClient, mock_job_manager: MagicMock
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
        fleet_dispatch = DispatchStrategyConfig("peak_shaving", import_limit_kw=4.5)
        assert [config.battery_config.dispatch_strategy for config in configs] == [fleet_dispatch] * 2

    @pytest.mark.parametrize(
        ("key", "distribution"),
        [("pv", "pv.capacity_kw"), ("load", "load.annual_consumption_kwh")],
    )
    def test_null_pv_or_load_component_block_returns_400(
        self, client: FlaskClient, mock_job_manager: MagicMock, key: str, distribution: str
    ) -> None:
        """A null pv/load block reads as absent, and the endpoint refuses the missing distribution with a 400 naming it; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, key: None},
        )
        assert resp.status_code == 400
        assert distribution in resp.get_json()["error"]
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
        self, client: FlaskClient, mock_job_manager: MagicMock, block: dict, message: str
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
        self, client: FlaskClient, mock_job_manager: MagicMock, entries: list, message: str
    ) -> None:
        """A shuffled_pool count that int() cannot read, or one above the dashboard's fleet limit, is a 400 naming the row's count and the value sent; so is a count that takes the pool's total above that limit, naming the total. No fleet is queued."""
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
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict, message: str
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
        mock_job_manager: MagicMock,
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
        self, client: FlaskClient, mock_job_manager: MagicMock
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
        self, client: FlaskClient, mock_job_manager: MagicMock
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
        self, client: FlaskClient, mock_job_manager: MagicMock
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
        self, client: FlaskClient, mock_job_manager: MagicMock, patch: dict, named: str
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

    @pytest.mark.parametrize("seg", MALFORMED_SEG_BODIES)
    def test_malformed_fleet_seg_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, seg: object
    ) -> None:
        """A malformed fleet-wide seg is a 400 naming seg, never a 500; no fleet is queued."""
        resp = client.post(
            "/api/simulate/fleet-from-distribution",
            json={**self._VALID_BODY, "seg": seg},
        )
        assert resp.status_code == 400
        assert "seg" in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()
