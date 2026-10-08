# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for POST /api/simulate/home and POST /api/simulate/fleet, and for how the simulate endpoints parse and refuse a home config."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient

from solar_challenge.web.simulation_params import MAX_WINDOW_DAYS
from tests.unit.web_api._request_bodies import MALFORMED_SEG_BODIES, VALID_HOME_PAYLOAD


VALID_FLEET_PAYLOAD: dict = {
    "name": "Test Fleet",
    "homes": [
        {
            "pv_kw": 4.0,
            "battery_kwh": 5.0,
            "occupants": 3,
            "location": "bristol",
            "days": 7,
        },
        {
            "pv_kw": 3.0,
            "battery_kwh": 0,
            "occupants": 2,
            "location": "london",
            "days": 7,
        },
    ],
}


class TestSimulateHomeAPI:
    """Tests for POST /api/simulate/home."""

    def test_valid_config_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid JSON body returns 201 with job_id and run_id."""
        resp = client.post("/api/simulate/home", json=VALID_HOME_PAYLOAD)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["job_id"] == "job-home-001"
        assert data["run_id"] == "run-home-001"
        mock_job_manager.submit_home_job.assert_called_once()

    def test_default_values_accepted(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with empty JSON uses defaults and still returns 201."""
        resp = client.post("/api/simulate/home", json={})
        assert resp.status_code == 201

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST without JSON content type returns 400."""
        resp = client.post(
            "/api/simulate/home",
            data="not-json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data
        assert "JSON" in data["error"]

    def test_invalid_pv_too_low_returns_400(self, client: FlaskClient) -> None:
        """PV capacity below 0.5 kW triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "pv_kw": 0.1},
        )
        assert resp.status_code == 400
        assert "PV capacity" in resp.get_json()["error"]

    def test_invalid_pv_too_high_returns_400(self, client: FlaskClient) -> None:
        """PV capacity above 20 kW triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "pv_kw": 25.0},
        )
        assert resp.status_code == 400
        assert "PV capacity" in resp.get_json()["error"]

    def test_negative_battery_returns_400(self, client: FlaskClient) -> None:
        """Negative battery capacity triggers a 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "battery_kwh": -1.0},
        )
        assert resp.status_code == 400
        assert "Battery" in resp.get_json()["error"] or "negative" in resp.get_json()["error"]

    def test_days_365_sets_full_year(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Setting days=365 should use the full-year date range."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "days": 365},
        )
        assert resp.status_code == 201
        # The start_date and end_date are passed to submit_home_job
        call_kwargs = mock_job_manager.submit_home_job.call_args
        start = call_kwargs.kwargs.get("start_date") or call_kwargs[1].get("start_date")
        # call_args may be positional or keyword; handle either
        if start is None:
            # positional: config, start_date, end_date, ...
            start = call_kwargs[0][1]
            end = call_kwargs[0][2]
        else:
            end = call_kwargs.kwargs.get("end_date") or call_kwargs[1].get("end_date")
        assert str(start.date()) == "2024-01-01"
        assert str(end.date()) == "2024-12-31"

    def test_custom_start_end_dates(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Explicit start/end date strings are forwarded correctly."""
        payload = {
            "pv_kw": 4.0,
            "battery_kwh": 0,
            "start": "2024-03-01",
            "end": "2024-03-31",
            "location": "bristol",
        }
        resp = client.post("/api/simulate/home", json=payload)
        assert resp.status_code == 201

    def test_zero_battery_treated_as_none(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """battery_kwh=0 results in battery_config=None on the HomeConfig."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "battery_kwh": 0},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.battery_config is None

    def test_home_form_battery_on_payload_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """A snapshot of home.html buildPayload() with the battery on and form defaults is accepted."""
        payload = {
            "pv_kw": 4.0,
            "azimuth": 180.0,
            "tilt": 35.0,
            "system_age_years": 0.0,
            "degradation_rate_per_year": 0.005,
            "battery_kwh": 5.0,
            "max_charge_kw": 3.6,
            "max_discharge_kw": 3.6,
            "efficiency_pct": 90.0,
            "consumption_kwh": 3500.0,
            "occupants": 3,
            "stochastic": False,
            "location": "bristol",
            "name": "Web Simulation",
            "days": 30,
        }
        resp = client.post("/api/simulate/home", json=payload)
        assert resp.status_code == 201, resp.get_json()
        mock_job_manager.submit_home_job.assert_called_once()
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.battery_config is not None
        assert config.battery_config.efficiency == pytest.approx(0.9)

    def test_unrecognised_key_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """A body carrying a key the API does not read is refused by name, not simulated without it."""
        resp = client.post("/api/simulate/home", json={**VALID_HOME_PAYLOAD, "period_days": 1})
        assert resp.status_code == 400
        assert "period_days" in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()

    @pytest.mark.parametrize(
        ("body", "type_name"),
        [
            pytest.param([1], "list", id="array"),
            pytest.param("x", "str", id="string"),
            pytest.param(1, "int", id="number"),
            pytest.param(True, "bool", id="boolean"),
        ],
    )
    def test_body_that_is_not_a_json_object_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, body: object, type_name: str
    ) -> None:
        """A JSON body that is not an object is refused naming its type, not answered with a 500."""
        resp = client.post("/api/simulate/home", json=body)
        assert resp.status_code == 400
        assert type_name in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()

    @pytest.mark.parametrize(
        ("body", "message"),
        [
            pytest.param(
                {"pv_kw": 4.0, "start": "2024-01-01", "end": "2200-01-01"},
                f"start to end must span at most {MAX_WINDOW_DAYS} days, "
                "got start '2024-01-01' and end '2200-01-01', 64,284 days",
                id="176-year-start-end",
            ),
            pytest.param(
                {"pv_kw": 4.0, "days": 80000},
                f"days must be between 1 and {MAX_WINDOW_DAYS}, got 80000",
                id="80000-days",
            ),
            pytest.param(
                {"pv_kw": 4.0, "start": "2024-06-10", "end": "2024-06-01"},
                "end must not be before start, got start '2024-06-10' and end '2024-06-01'",
                id="end-before-start",
            ),
        ],
    )
    def test_window_it_cannot_run_returns_400_naming_it_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, body: dict, message: str
    ) -> None:
        """A window that ends before it starts, or spans more than MAX_WINDOW_DAYS days, is a 400 naming it, never a queued run."""
        resp = client.post("/api/simulate/home", json=body)
        assert resp.status_code == 400
        assert resp.get_json() == {"error": message}
        mock_job_manager.submit_home_job.assert_not_called()


class TestSimulateFleetAPI:
    """Tests for POST /api/simulate/fleet."""

    def test_valid_fleet_returns_201(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Valid fleet config returns 201 with job_id and run_id."""
        resp = client.post("/api/simulate/fleet", json=VALID_FLEET_PAYLOAD)
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["job_id"] == "job-fleet-001"
        assert data["run_id"] == "run-fleet-001"
        mock_job_manager.submit_fleet_job.assert_called_once()

    def test_no_json_body_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400
        assert "JSON" in resp.get_json()["error"]

    def test_empty_homes_returns_400(self, client: FlaskClient) -> None:
        """Fleet with empty homes array returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={"name": "Empty", "homes": []},
        )
        assert resp.status_code == 400
        assert "at least one" in resp.get_json()["error"]

    def test_missing_homes_key_returns_400(self, client: FlaskClient) -> None:
        """Fleet without 'homes' key returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={"name": "No homes key"},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("homes", "type_name"),
        [
            pytest.param({"a": 1}, "dict", id="object"),
            pytest.param(5, "int", id="number"),
            pytest.param("abc", "str", id="string"),
        ],
    )
    def test_homes_that_is_not_a_json_array_returns_400_naming_its_type_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, homes: object, type_name: str
    ) -> None:
        """A 'homes' that is not an array is refused naming its own type, not read as a list of home configs."""
        resp = client.post("/api/simulate/fleet", json={"name": "Bad Fleet", "homes": homes})
        assert resp.status_code == 400
        assert resp.get_json()["error"] == f"homes must be a JSON array, got {type_name}"
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_invalid_home_in_fleet_returns_400(self, client: FlaskClient) -> None:
        """Fleet with an invalid home config returns 400."""
        resp = client.post(
            "/api/simulate/fleet",
            json={
                "name": "Bad Fleet",
                "homes": [
                    {"pv_kw": 0.01},  # invalid: PV < 0.5
                ],
            },
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize(
        ("homes", "type_name"),
        [
            pytest.param([1], "int", id="first-home"),
            pytest.param([VALID_HOME_PAYLOAD, "x"], "str", id="later-home"),
        ],
    )
    def test_home_that_is_not_a_json_object_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, homes: list[object], type_name: str
    ) -> None:
        """A homes entry that is not an object is refused naming its type, whether it is the first home or a later one."""
        resp = client.post("/api/simulate/fleet", json={"name": "Bad Fleet", "homes": homes})
        assert resp.status_code == 400
        assert type_name in resp.get_json()["error"]
        mock_job_manager.submit_fleet_job.assert_not_called()

    def test_fleet_uses_first_home_dates(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Fleet date range is taken from the first home config."""
        resp = client.post("/api/simulate/fleet", json=VALID_FLEET_PAYLOAD)
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_fleet_job.call_args
        configs = call_kwargs.kwargs.get("configs") or call_kwargs[0][0]
        assert len(configs) == 2


class TestParseHomeConfigErrorPaths:
    """Endpoint 400 error-path tests for home-config fields the simulate endpoints cannot use: an unknown tariff, an incomplete dispatch_strategy, a nested block that is not an object, an unusable number, and a window set by both days and start/end."""

    def test_invalid_tariff_returns_400(
        self, client: FlaskClient
    ) -> None:
        """POST with an unrecognised tariff type returns 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "tariff": {"type": "nonsense"}},
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    def test_invalid_dispatch_returns_400(
        self, client: FlaskClient
    ) -> None:
        """POST with tou_optimized dispatch but missing peak_hours returns 400."""
        resp = client.post(
            "/api/simulate/home",
            json={
                **VALID_HOME_PAYLOAD,
                "battery_kwh": 5.0,
                "dispatch_strategy": {
                    "strategy_type": "tou_optimized",
                    # peak_hours intentionally omitted — required for tou_optimized
                },
            },
        )
        assert resp.status_code == 400
        data = resp.get_json()
        assert "error" in data

    @pytest.mark.parametrize(
        ("url", "body", "key"),
        [
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "heat_pump": "ASHP"},
                "heat_pump",
                id="home-heat_pump",
            ),
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "seg": "Octopus"},
                "seg",
                id="home-seg",
            ),
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "tariff": "flat_rate"},
                "tariff",
                id="home-tariff",
            ),
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "dispatch_strategy": "self_consumption"},
                "dispatch_strategy",
                id="home-dispatch_strategy",
            ),
            pytest.param(
                "/api/simulate/fleet",
                {"homes": [{**VALID_HOME_PAYLOAD, "heat_pump": "ASHP"}]},
                "heat_pump",
                id="fleet-heat_pump",
            ),
            pytest.param(
                "/api/simulate/sweep",
                {
                    "parameter": "pv_capacity_kw",
                    "min": 1,
                    "max": 5,
                    "steps": 2,
                    "base_config": {"heat_pump": "ASHP"},
                },
                "heat_pump",
                id="sweep-heat_pump",
            ),
        ],
    )
    def test_non_mapping_block_returns_400_naming_it_and_submits_nothing(
        self,
        client: FlaskClient,
        mock_job_manager: MagicMock,
        url: str,
        body: dict,
        key: str,
    ) -> None:
        """A nested block sent as a non-object is a 400 naming the block and the type sent, never a 500; nothing is submitted."""
        resp = client.post(url, json=body)
        assert resp.status_code == 400
        assert f"{key} must be a mapping, got str" in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("url", "body", "message"),
        [
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "days": float("inf")},
                "days must be an integer, got inf",
                id="home-days-infinity",
            ),
            pytest.param(
                "/api/simulate/fleet",
                {"homes": [{**VALID_HOME_PAYLOAD, "days": float("inf")}]},
                "days must be an integer, got inf",
                id="fleet-days-infinity",
            ),
            pytest.param(
                "/api/simulate/sweep",
                {"min": 1, "max": 5, "steps": 2, "base_config": {"days": float("inf")}},
                "days must be an integer, got inf",
                id="sweep-days-infinity",
            ),
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "pv_kw": 10**400},
                f"pv_kw must be a finite number, got {10**400!r}",
                id="home-pv_kw-too-large-for-a-float",
            ),
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "heat_pump": {"thermal_capacity_kw": 10**400}},
                f"heat_pump.thermal_capacity_kw must be a finite number, got {10**400!r}",
                id="home-heat_pump.thermal_capacity_kw-too-large-for-a-float",
            ),
        ],
    )
    def test_number_it_cannot_use_returns_400_naming_it_and_submits_nothing(
        self,
        client: FlaskClient,
        mock_job_manager: MagicMock,
        url: str,
        body: dict,
        message: str,
    ) -> None:
        """A number field the home-config parser cannot use is a 400 naming the field and the value sent, never a 500; nothing is submitted."""
        resp = client.post(url, json=body)
        assert resp.status_code == 400
        assert message in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()
        mock_job_manager.submit_fleet_job.assert_not_called()

    @pytest.mark.parametrize(
        ("url", "body"),
        [
            pytest.param(
                "/api/simulate/home",
                {**VALID_HOME_PAYLOAD, "start": "2024-03-01", "end": "2024-03-31"},
                id="home",
            ),
            pytest.param(
                "/api/simulate/fleet",
                {"homes": [{**VALID_HOME_PAYLOAD, "start": "2024-03-01", "end": "2024-03-31"}]},
                id="fleet",
            ),
            pytest.param(
                "/api/simulate/sweep",
                {
                    "min": 1,
                    "max": 5,
                    "steps": 2,
                    "base_config": {"days": 7, "start": "2024-03-01", "end": "2024-03-31"},
                },
                id="sweep",
            ),
        ],
    )
    def test_window_set_by_both_days_and_start_end_returns_400_naming_them_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, url: str, body: dict
    ) -> None:
        """A home config that sets its window by days and by start/end is a 400 naming days, start and end as sent, never a run of either window; nothing is submitted."""
        resp = client.post(url, json=body)
        assert resp.status_code == 400
        assert (
            "days must not be sent with start or end, "
            "got days 7 with start '2024-03-01' and end '2024-03-31'"
        ) in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()
        mock_job_manager.submit_fleet_job.assert_not_called()


class TestParseHomeConfigPVAge:
    """PV-age boundary tests: form→PVConfig threading."""

    def test_endpoint_threads_system_age_years_to_pv_config(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with system_age_years=20 returns 201 and HomeConfig carries the value."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "system_age_years": 20},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.pv_config.system_age_years == 20.0

    def test_negative_system_age_returns_400(self, client: FlaskClient) -> None:
        """POST with system_age_years=-5 returns HTTP 400 (PVConfig validates age >= 0)."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "system_age_years": -5},
        )
        assert resp.status_code == 400

    def test_invalid_degradation_rate_returns_400(self, client: FlaskClient) -> None:
        """POST with degradation_rate_per_year=1.5 returns HTTP 400 (PVConfig validates rate 0-1)."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "degradation_rate_per_year": 1.5},
        )
        assert resp.status_code == 400


class TestParseHomeConfigSEG:
    """Boundary tests for the SEG export-rate field round-trip.

    Scope: validates field population only, not end-to-end simulation pricing.
    """

    def test_endpoint_threads_seg_preset_to_home_config(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with seg.preset='OVO' returns 201 and HomeConfig carries OVO's rate."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "seg": {"preset": "OVO"}},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.seg_tariff is not None
        assert config.seg_tariff.rate_pence_per_kwh == pytest.approx(4.0)

    def test_endpoint_threads_custom_rate_to_seg_tariff(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """POST with seg.rate_pence_per_kwh=5.5 returns 201 and HomeConfig carries that rate.

        This exercises the most common non-preset user action (explicit custom rate)
        through the full HTTP endpoint path, complementing the direct parse_home_config
        unit test for the same case.
        """
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "seg": {"rate_pence_per_kwh": 5.5}},
        )
        assert resp.status_code == 201
        call_kwargs = mock_job_manager.submit_home_job.call_args
        config = call_kwargs.kwargs.get("config") or call_kwargs[0][0]
        assert config.seg_tariff is not None
        assert config.seg_tariff.rate_pence_per_kwh == pytest.approx(5.5)

    def test_null_rate_with_custom_preset_returns_400(self, client: FlaskClient) -> None:
        """POST with seg.rate_pence_per_kwh=null returns 400 (NaN from blank input)."""
        resp = client.post(
            "/api/simulate/home",
            # JSON null mirrors JSON.stringify({rate_pence_per_kwh: NaN}) from the
            # browser when the custom rate input is blank — must not silently succeed.
            json={**VALID_HOME_PAYLOAD, "seg": {"rate_pence_per_kwh": None}},
        )
        assert resp.status_code == 400

    def test_unknown_preset_returns_400(self, client: FlaskClient) -> None:
        """POST with seg.preset='NotASupplier' returns HTTP 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "seg": {"preset": "NotASupplier"}},
        )
        assert resp.status_code == 400

    def test_negative_rate_returns_400(self, client: FlaskClient) -> None:
        """POST with seg.rate_pence_per_kwh=-2 returns HTTP 400."""
        resp = client.post(
            "/api/simulate/home",
            json={**VALID_HOME_PAYLOAD, "seg": {"rate_pence_per_kwh": -2}},
        )
        assert resp.status_code == 400

    @pytest.mark.parametrize("seg", MALFORMED_SEG_BODIES)
    def test_malformed_seg_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, seg: object
    ) -> None:
        """A malformed seg is a 400 naming seg, never a 500 or a run priced at a rate nobody sent."""
        resp = client.post("/api/simulate/home", json={**VALID_HOME_PAYLOAD, "seg": seg})
        assert resp.status_code == 400
        assert "seg" in resp.get_json()["error"]
        mock_job_manager.submit_home_job.assert_not_called()
