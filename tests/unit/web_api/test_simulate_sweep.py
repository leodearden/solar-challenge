# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for POST /api/simulate/sweep, which submits one home job per sweep point."""

from unittest.mock import MagicMock

import pytest

pytest.importorskip("flask")
from flask.testing import FlaskClient


class TestSimulateSweep:
    """Tests for POST /api/simulate/sweep."""

    def test_valid_linear_sweep_returns_201(self, client: FlaskClient) -> None:
        """Linear sweep with valid params returns 201 with job_ids."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 1.0,
                "max": 10.0,
                "steps": 5,
                "mode": "linear",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["parameter"] == "pv_capacity_kw"
        assert len(data["values"]) == 5
        assert "job_ids" in data
        assert len(data["job_ids"]) == 5
        # First and last values should match min/max
        assert data["values"][0] == pytest.approx(1.0, abs=0.01)
        assert data["values"][-1] == pytest.approx(10.0, abs=0.01)

    def test_valid_geometric_sweep_returns_201(self, client: FlaskClient) -> None:
        """Geometric sweep with valid params returns 201 with job_ids."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "battery_capacity_kwh",
                "min": 1.0,
                "max": 16.0,
                "steps": 3,
                "mode": "geometric",
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert len(data["values"]) == 3
        assert "job_ids" in data
        assert data["values"][0] == pytest.approx(1.0, abs=0.01)
        assert data["values"][-1] == pytest.approx(16.0, abs=0.01)

    def test_no_json_returns_400(self, client: FlaskClient) -> None:
        """POST with no JSON body returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            data="not json",
            content_type="text/plain",
        )
        assert resp.status_code == 400

    def test_steps_less_than_2_returns_400(self, client: FlaskClient) -> None:
        """Steps < 2 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 10.0, "steps": 1},
        )
        assert resp.status_code == 400
        assert "Steps" in resp.get_json()["error"]

    def test_min_gte_max_returns_400(self, client: FlaskClient) -> None:
        """min >= max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 10.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Min" in resp.get_json()["error"]

    def test_min_equals_max_returns_400(self, client: FlaskClient) -> None:
        """min == max returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 5.0, "max": 5.0, "steps": 3},
        )
        assert resp.status_code == 400

    def test_geometric_negative_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min <= 0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": -1.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400
        assert "positive" in resp.get_json()["error"]

    def test_geometric_zero_min_returns_400(self, client: FlaskClient) -> None:
        """Geometric sweep with min=0 returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 0.0, "max": 10.0, "steps": 3, "mode": "geometric"},
        )
        assert resp.status_code == 400

    def test_invalid_numeric_param_returns_400(self, client: FlaskClient) -> None:
        """Non-numeric min/max/steps returns 400."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": "abc", "max": 10.0, "steps": 3},
        )
        assert resp.status_code == 400
        assert "Invalid numeric" in resp.get_json()["error"]

    @pytest.mark.parametrize(
        ("base_config", "type_name"),
        [
            pytest.param("abc", "str", id="string"),
            pytest.param("", "str", id="empty-string"),
            pytest.param(5, "int", id="number"),
            pytest.param([1], "list", id="array"),
            pytest.param([], "list", id="empty-array"),
            pytest.param(True, "bool", id="boolean"),
            pytest.param(None, "NoneType", id="null"),
            pytest.param([["battery_kwh", 5.0]], "list", id="array-of-key-value-pairs"),
        ],
    )
    def test_base_config_that_is_not_a_json_object_returns_400_and_submits_nothing(
        self, client: FlaskClient, mock_job_manager: MagicMock, base_config: object, type_name: str
    ) -> None:
        """A base_config that is not a JSON object is refused naming base_config and its type, and no sweep point is submitted."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2, "base_config": base_config},
        )
        assert resp.status_code == 400
        error = resp.get_json()["error"]
        assert "base_config" in error
        assert type_name in error
        mock_job_manager.submit_home_job.assert_not_called()

    def test_sweep_default_parameter_name(self, client: FlaskClient) -> None:
        """Default parameter name is pv_capacity_kw."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2},
        )
        assert resp.status_code == 201
        assert resp.get_json()["parameter"] == "pv_capacity_kw"

    def test_empty_object_body_submits_the_default_sweep(
        self, client: FlaskClient, mock_job_manager: MagicMock
    ) -> None:
        """Every field is optional: {} sweeps PV capacity linearly from 1 to 10 kW in 5 steps, one home job per step."""
        resp = client.post("/api/simulate/sweep", json={})
        assert resp.status_code == 201
        default_pv_kw = [1.0, 3.25, 5.5, 7.75, 10.0]
        assert (resp.get_json()["parameter"], resp.get_json()["values"]) == ("pv_capacity_kw", default_pv_kw)
        submitted_homes = [call.kwargs["config"] for call in mock_job_manager.submit_home_job.call_args_list]
        assert [home.pv_config.capacity_kw for home in submitted_homes] == default_pv_kw
