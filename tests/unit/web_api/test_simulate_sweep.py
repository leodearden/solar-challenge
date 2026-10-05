# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for POST /api/simulate/sweep, which submits one home job per sweep point.

This module's client submits to a recording double that numbers job ids in submission
order and takes the real submit_home_job's parameters.
"""

from collections.abc import Callable
from inspect import signature

import pytest

pytest.importorskip("flask")
from flask import Flask
from flask.testing import FlaskClient

from solar_challenge.home import HomeConfig


class _RecordingJobManager:
    """Stands in for the app's JobManager: records each home config a request submits and simulates nothing."""

    def __init__(self) -> None:
        self.submitted_homes: list[HomeConfig] = []

    def submit_home_job(
        self,
        config: HomeConfig,
        start_date: object,
        end_date: object,
        db_path: str,
        data_dir: str,
        name: str | None = None,
    ) -> tuple[str, str]:
        """Record the home config and return a fresh (job_id, run_id) pair."""
        self.submitted_homes.append(config)
        n = len(self.submitted_homes)
        return f"job-{n}", f"run-{n}"


@pytest.fixture
def recording_job_manager(app: Flask) -> _RecordingJobManager:
    """Install a recording double as the app's job manager and return it."""
    job_manager = _RecordingJobManager()
    app.extensions["job_manager"] = job_manager
    return job_manager


@pytest.fixture
def client(app: Flask, recording_job_manager: _RecordingJobManager) -> FlaskClient:
    """Create a Flask test client whose requests submit jobs to the recording double, not the package's MagicMock."""
    return app.test_client()


def _call_shape(method: Callable[..., object]) -> list[tuple[str, object, object]]:
    """The parameter names, kinds and defaults that decide which calls a method accepts."""
    return [(p.name, p.kind, p.default) for p in signature(method).parameters.values()]


class TestRecordingJobManager:
    """The recording double stays in step with the real JobManager it stands in for."""

    def test_submit_home_job_takes_the_parameters_the_real_one_takes(self, app: Flask) -> None:
        """A change to the real submit_home_job's parameters fails here, instead of passing silently behind the double."""
        real_job_manager = app.extensions["job_manager"]
        double = _RecordingJobManager()

        assert _call_shape(double.submit_home_job) == _call_shape(real_job_manager.submit_home_job)


class TestSimulateSweep:
    """Tests for POST /api/simulate/sweep."""

    def test_valid_linear_sweep_returns_201(self, client: FlaskClient) -> None:
        """A linear sweep from a base config returns 201 with the parameter, values evenly spaced from min to max, and each point's job id in point order."""
        resp = client.post(
            "/api/simulate/sweep",
            json={
                "parameter": "pv_capacity_kw",
                "min": 2.0,
                "max": 8.0,
                "steps": 4,
                "mode": "linear",
                "base_config": {"battery_kwh": 5.0, "location": "bristol", "days": 7},
            },
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["parameter"] == "pv_capacity_kw"
        assert data["values"] == [2.0, 4.0, 6.0, 8.0]
        assert data["job_ids"] == ["job-1", "job-2", "job-3", "job-4"]

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
        self,
        client: FlaskClient,
        recording_job_manager: _RecordingJobManager,
        base_config: object,
        type_name: str,
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
        assert recording_job_manager.submitted_homes == []

    def test_sweep_default_parameter_name(self, client: FlaskClient) -> None:
        """Default parameter name is pv_capacity_kw."""
        resp = client.post(
            "/api/simulate/sweep",
            json={"min": 1.0, "max": 5.0, "steps": 2},
        )
        assert resp.status_code == 201
        assert resp.get_json()["parameter"] == "pv_capacity_kw"

    def test_empty_object_body_submits_the_default_sweep(
        self, client: FlaskClient, recording_job_manager: _RecordingJobManager
    ) -> None:
        """Every field is optional: {} sweeps PV capacity linearly from 1 to 10 kW in 5 steps, one home job per step."""
        resp = client.post("/api/simulate/sweep", json={})
        assert resp.status_code == 201
        default_pv_kw = [1.0, 3.25, 5.5, 7.75, 10.0]
        assert (resp.get_json()["parameter"], resp.get_json()["values"]) == ("pv_capacity_kw", default_pv_kw)
        assert [home.pv_config.capacity_kw for home in recording_job_manager.submitted_homes] == default_pv_kw
